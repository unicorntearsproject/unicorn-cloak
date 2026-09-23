"""
The single merged Control Panel window -- replaces the separate
EditorWindow/SettingsWindow top-level windows (2026-09-17, owner's
request: "single window for editing/settings"; the docs used to call
this a "two-window architecture" -- Render Window plus one Control
Panel -- but Editor and Settings had organically drifted into two
separate windows without ever reconfirming that split. This merges them
back into one, with a real information architecture instead of one long
scrolling column: a canvas (toggle between the live Render Window preview
and an interactive drag-to-position editor) with a level meter always
below it, a tabbed body (Sprites / Behavior / Audio / Application, each
made of resizable+collapsible sections), and a persistent bottom bar
(audio source controls, Save/Save As/Load/Export/Check for Issues/Guide/
Ghost/Quit) that's never scrolled out of view.

Still never captured by OBS -- only the Render Window is.

Dirty-tracking is scoped to the avatar *rig* only (position edits, added
sprites, etc.) -- every Settings-style field (audio thresholds, motion,
OBS, hotkeys...) already writes straight into `Config` and autosaves
immediately, so there is no unsaved-changes risk for those to warn about.
"Unsaved changes" always means "the avatar hasn't been saved to its file
since the last edit."
"""
from __future__ import annotations

import copy
import dataclasses
import json
import math
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QShortcut,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyleOptionGraphicsItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import motion, theme
from .avatar_io import load_avatar_with_upgrade
from .config import Config, save_state
from .help_window import HelpWindow
from .persistence import DEFAULT_EXTENSION, save_avatar
from .render import BACKGROUND_COLORS
from .rig import NUM_COSTUMES, AvatarRig, Sprite, duplicate_sprite, with_costume_layer
from .rig_lint import find_rig_issues
from .snapshot import export_costume_snapshot
from .spritesheet import slice_frame
from .widgets import (
    CollapsibleSection,
    LevelMeter,
    PreviewView,
    ScrollSafeDoubleSpinBox,
    ScrollSafeSpinBox,
    elide_path_middle,
)

SELECTED_ID = Qt.ItemDataRole.UserRole
AUTOSAVE_INTERVAL_MS = 30_000

# Expression hotkeys are Shift+<digit>, fixed (not user-remappable, unlike
# costume_keys) -- owner's request, 2026-09-17: "yea hotkey it up please...
# shift+<number>". Same 1-9,0 numbering convention as
# config.HotkeysConfig.costume_keys' own default, purely for the on-screen
# label; render.py/render matching uses Qt.Key constants directly, not
# this string form.
EXPRESSION_HOTKEY_LABELS = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0")

_BACKGROUND_LABELS = {
    "transparent": "Transparent (see-through to OBS -- normal setup)",
    "black": "Black",
    "white": "White",
    "green": "Green (chroma key)",
    "image": "Image (choose a file below)",
    "video": "Video, looping (choose a file below)",
}


def _is_input_widget_focused() -> bool:
    """True while the focused widget is something the user is typing or
    picking into -- costume/expression hotkeys must not steal a digit or
    Shift+digit keypress from these (owner's request, 2026-09-19: "only
    if no input field is focused of course"), since both hotkey sets now
    also fire while the Control Panel has focus, which is full of exactly
    these widgets (State Assignment's editable combos, the costume/
    expression sprite pickers, the costume key-capture boxes themselves)."""
    widget = QApplication.focusWidget()
    return isinstance(widget, (QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QKeySequenceEdit))


def _eye_icon(visible: bool) -> QIcon:
    """A tiny hand-drawn open/closed eye -- no icon set is bundled with
    this app, so this is a plain, dependency-free stand-in, colored to
    read against the dark theme's list background."""
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(theme.PINK_WHITE) if visible else QColor(theme.GREY_500)
    pen = QPen(color)
    pen.setWidth(2)
    painter.setPen(pen)
    if visible:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(2, 5, 14, 8)
        painter.setBrush(color)
        painter.drawEllipse(7, 7, 4, 4)
    else:
        painter.drawLine(3, 9, 15, 9)
    painter.end()
    return QIcon(pixmap)


def _lock_icon(locked: bool) -> QIcon:
    """A tiny hand-drawn padlock, same dependency-free-stand-in approach
    as _eye_icon above -- shackle swung open to one side when unlocked,
    not just a color change, so the two states still read apart in
    grayscale."""
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(theme.MAGENTA_500) if locked else QColor(theme.GREY_500)
    pen = QPen(color)
    pen.setWidth(2)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if locked:
        painter.drawArc(5, 2, 8, 9, 0, 180 * 16)
    else:
        painter.drawArc(2, 2, 8, 9, 30 * 16, 180 * 16)
    painter.setBrush(color)
    painter.drawRoundedRect(4, 8, 10, 8, 2, 2)
    painter.end()
    return QIcon(pixmap)


class _LayerNameLabel(QLabel):
    """A sprite-list row's name text -- plain QLabel plus "clicking it
    selects this sprite", since setItemWidget() replaces the row's own
    click-to-select area with whatever widget is placed there."""

    def __init__(self, text: str, sprite_id: int, panel: "ControlPanelWindow") -> None:
        super().__init__(text)
        self._sprite_id = sprite_id
        self._panel = panel

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._panel.select_sprite_in_list(self._sprite_id)
        super().mousePressEvent(event)


# Corner/rotate handle geometry for EditableSpriteItem, below -- fixed in
# local (unscaled) pixels rather than compensated for the edit canvas's own
# zoom, since GridCanvasView has no zoom feature of its own to compensate
# for (confirmed 2026-09-17: it's a plain 1:1 QGraphicsView).
_HANDLE_HALF = 10.0
_ROTATE_HANDLE_DISTANCE = 28.0


class EditableSpriteItem(QGraphicsPixmapItem):
    def __init__(self, sprite: Sprite, pixmap: QPixmap, panel: "ControlPanelWindow", parent=None) -> None:
        super().__init__(pixmap, parent)
        self.sprite = sprite
        self._panel = panel
        self._active_handle: str | None = None
        # See mousePressEvent/mouseMoveEvent below -- bug audit
        # 2026-09-23, #20 ("no-op undo entries").
        self._undo_pending_for_press = False
        self.setOffset(-pixmap.width() / 2 + sprite.offset[0], -pixmap.height() / 2 + sprite.offset[1])
        self.setZValue(sprite.z_index)
        self.setFlag(QGraphicsItem.ItemStacksBehindParent, sprite.z_index < 0)
        if sprite.clipped:
            self.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
            self.setShapeMode(QGraphicsPixmapItem.ShapeMode.MaskShape)
        self.setTransformationMode(Qt.SmoothTransformation)
        # Kept in sync afterward by _on_sprite_lock_toggled -- sprite.
        # locked can change any time after construction, from either the
        # Layer List's padlock or Lock Position (see that method).
        self.setFlag(QGraphicsItem.ItemIsMovable, not sprite.locked)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setPos(*sprite.position)
        # Edit canvas is a static preview (no *reactive* drag-rotation or
        # squash/stretch -- see render.py's own comment on those) -- the
        # two *authored* transform properties (rotation_deg, scale_x/y)
        # still need to show here, same combination render.py itself uses.
        self.setTransform(QTransform().rotate(sprite.rotation_deg).scale(sprite.scale_x, sprite.scale_y))

    def _pixmap_rect(self) -> QRectF:
        # NOT super().boundingRect() -- QGraphicsPixmapItem pads that by
        # half a unit on every side (confirmed empirically, 2026-09-17:
        # offset (-50,-50) + a 100x100 pixmap boundingRect()s as
        # (-50.5,-50.5,101,101), not (-50,-50,100,100)). Handle placement
        # and the corner-scale math in _drag_handle both need the exact,
        # unpadded pixmap edges.
        size = self.pixmap().size()
        offset = self.offset()
        return QRectF(offset.x(), offset.y(), size.width(), size.height())

    def boundingRect(self) -> QRectF:  # noqa: N802 (Qt override)
        rect = self._pixmap_rect()
        if self.isSelected():
            # Extended on every side, not just upward -- corner handles
            # are centered exactly ON the pixmap's own corners (see
            # _handle_rects), so half of each one -- the outer half,
            # the natural place to actually click one -- sticks out past
            # the pixmap's own edges on all four sides, not just the top
            # (top additionally needs room for the rotate handle, further
            # out still). Qt clips both paint() and hit-testing to
            # whatever this reports, so a boundingRect that only grew
            # upward left the other three handles half-invisible on
            # move (paint sticking out past the region Qt knows to
            # invalidate/erase, leaving trail artifacts behind a drag)
            # and half-unclickable (owner's report, 2026-09-19: "click on
            # the resize or rotate handles [and] the guides disappear and
            # nothing happens" -- a click landing in that outer half fell
            # through to the empty canvas instead, deselecting the
            # sprite). See shape() below for the other half of this fix.
            rect = rect.adjusted(
                -_HANDLE_HALF, -(_ROTATE_HANDLE_DISTANCE + _HANDLE_HALF), _HANDLE_HALF, _HANDLE_HALF
            )
        return rect

    def shape(self) -> QPainterPath:  # noqa: N802 (Qt override)
        path = super().shape()
        if self.isSelected():
            # QGraphicsPixmapItem.shape() (unlike boundingRect()) traces
            # the pixmap's actual opaque pixels by default -- lets a click
            # on a fully-transparent part of a sprite fall through to
            # whatever's stacked underneath it, instead of selecting this
            # one. But a handle drawn past the pixmap's edge (see
            # boundingRect()'s own comment) almost always lands over a
            # transparent pixel near that edge, which would make it
            # unclickable via the inherited mask-based shape() alone even
            # once boundingRect() is big enough to receive the event in
            # the first place. Only the handle areas get an explicit
            # rectangular carve-out here -- the rest of the sprite keeps
            # its normal click-through-transparency behavior.
            for hrect in self._handle_rects().values():
                path.addRect(hrect)
        return path

    def _handle_rects(self) -> dict[str, QRectF]:
        if self.sprite.locked:
            # Single choke point for "this sprite can't be transformed" --
            # an empty dict here also makes _handle_at() (hit-testing),
            # paint()'s own handle-drawing loop, and shape()'s handle
            # carve-out all correctly no-op, with nothing else to guard.
            return {}
        rect = self._pixmap_rect()
        centers = {
            "tl": rect.topLeft(), "tr": rect.topRight(),
            "bl": rect.bottomLeft(), "br": rect.bottomRight(),
            "rotate": QPointF(rect.center().x(), rect.top() - _ROTATE_HANDLE_DISTANCE),
        }
        return {
            name: QRectF(pt.x() - _HANDLE_HALF, pt.y() - _HANDLE_HALF, _HANDLE_HALF * 2, _HANDLE_HALF * 2)
            for name, pt in centers.items()
        }

    def _handle_at(self, local_pos: QPointF) -> str | None:
        if not self.isSelected():
            return None
        for name, rect in self._handle_rects().items():
            if rect.contains(local_pos):
                return name
        return None

    def paint(self, painter, option, widget=None) -> None:  # noqa: N802 (Qt override)
        # Qt's own dashed selection rectangle doesn't communicate "drag a
        # corner to scale, drag above to rotate" -- suppressed here
        # (standard Qt pattern: paint with a copy of `option` that has
        # State_Selected cleared) and replaced with the handles below,
        # which are this sprite's only selection indicator now.
        plain_option = QStyleOptionGraphicsItem(option)
        plain_option.state &= ~QStyle.StateFlag.State_Selected
        super().paint(painter, plain_option, widget)
        if not self.isSelected():
            return
        # Muted gray, not magenta, while locked -- still shows this
        # sprite is selected, but reads as "can't transform" rather than
        # implying the normal drag/scale/rotate affordance that (per
        # _handle_rects) isn't there anymore.
        accent = QColor(theme.GREY_500) if self.sprite.locked else QColor(theme.MAGENTA_500)
        pen = QPen(accent)
        pen.setWidth(2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = self._pixmap_rect()
        painter.drawRect(rect)
        handles = self._handle_rects()
        if not handles:
            return
        top_center = QPointF(rect.center().x(), rect.top())
        painter.drawLine(top_center, handles["rotate"].center())
        # A dark box outline around each handle first, then the colored
        # marker on top -- owner's request, 2026-09-19, alongside a
        # bigger click target (_HANDLE_HALF): makes the now-larger
        # handles read clearly against any part of the art underneath,
        # not just whichever happens to contrast with plain magenta.
        outline_pen = QPen(QColor(theme.INK_900))
        outline_pen.setWidth(1)
        outline_pen.setCosmetic(True)
        painter.setPen(outline_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for hrect in handles.values():
            painter.drawRect(hrect.adjusted(-2, -2, 2, 2))
        painter.setPen(pen)
        painter.setBrush(accent)
        for name, hrect in handles.items():
            if name == "rotate":
                painter.drawEllipse(hrect)
            else:
                painter.drawRect(hrect)

    def hoverMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        handle = self._handle_at(event.pos())
        if handle == "rotate":
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif handle is not None:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Deferred, not pushed here -- bug audit 2026-09-23, #20 ("no-op
        # undo entries"): every press used to push a snapshot
        # unconditionally, including a plain click-to-select with no
        # drag at all, so Undo often appeared to do nothing (it was
        # undoing a click, not an edit). Pushed instead on the first
        # actual mouseMoveEvent of this gesture, if one ever comes --
        # still captures the correct pre-edit state, since nothing has
        # moved/rotated/scaled yet at that point.
        self._undo_pending_for_press = True
        handle = self._handle_at(event.pos())
        if handle is not None:
            self._active_handle = handle
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._undo_pending_for_press:
            self._panel.push_undo_snapshot()
            self._undo_pending_for_press = False
        if self._active_handle is not None:
            self._drag_handle(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._active_handle = None
        # A plain click never reached mouseMoveEvent at all -- nothing
        # to push for it now either.
        self._undo_pending_for_press = False
        super().mouseReleaseEvent(event)

    def _drag_handle(self, scene_pos: QPointF) -> None:
        # scene_pos, not event.pos() -- .pos() maps through this item's
        # CURRENT transform(), which includes the very scale being
        # computed this frame. Feeding an already-scaled position back
        # into "divide by the original corner" computes the new scale
        # as (true_scale / current_scale) instead of true_scale outright
        # -- wrong whenever current_scale != 1, and since current_scale
        # is exactly what gets set from that wrong result, the error
        # compounds every single mouseMoveEvent, diverging into the
        # wild, rapid size jumps the owner reported (2026-09-19) from
        # only a small handle movement. Mapping scene_pos into the
        # *parent's* local space instead (mapFromScene walks up however
        # many ancestor transforms there are, correctly, even for a
        # nested child sprite -- see rig.py's parent/child contract)
        # and subtracting self.pos() gives this item's offset in the
        # coordinate space its own transform() operates ON, before that
        # transform is applied -- anchored to the sprite's fixed,
        # original geometry every time, regardless of whatever scale or
        # rotation was already in effect.
        parent = self.parentItem()
        parent_local_pos = parent.mapFromScene(scene_pos) if parent is not None else scene_pos
        offset = parent_local_pos - self.pos()

        if self._active_handle == "rotate":
            # 0 deg = straight up from the origin (this item's pivot,
            # i.e. Position -- see rig.Sprite's Position/Offset comment);
            # verified empirically against QTransform.rotate's own sign
            # convention (positive = clockwise in Qt's y-down coordinate
            # system) rather than assumed. Uses the pre-rotation offset
            # directly (not un-rotated further) -- solving for the
            # rotation that would put the handle under the cursor is
            # exactly atan2 of the vector from the origin to the cursor,
            # in the frame rotation_deg itself is defined against.
            angle = math.degrees(math.atan2(offset.x(), -offset.y()))
            self.sprite.rotation_deg = angle
            self._apply_authored_transform()
            self._panel.on_sprite_rotated(self.sprite)
            return

        # Un-rotate (never un-scale, see above) to isolate the distance
        # from origin scale_x/y are actually defined relative to -- the
        # corner points below are themselves in that same pre-rotation,
        # pre-scale pixmap space.
        pre_scale_pos = QTransform().rotate(-self.sprite.rotation_deg).map(offset)
        corner = {
            "tl": self._pixmap_rect().topLeft(), "tr": self._pixmap_rect().topRight(),
            "bl": self._pixmap_rect().bottomLeft(), "br": self._pixmap_rect().bottomRight(),
        }[self._active_handle]
        if abs(corner.x()) < 1e-6 or abs(corner.y()) < 1e-6:
            return  # a zero-size pixmap dimension has no meaningful corner to scale from
        new_scale_x = pre_scale_pos.x() / corner.x()
        new_scale_y = pre_scale_pos.y() / corner.y()
        if self._panel.scale_lock.isChecked():
            # Same lock the Scale spinboxes already honor (see
            # _on_scale_x/y_changed) -- reused here rather than a second,
            # separate lock concept for the same idea.
            ratio = (abs(new_scale_x) + abs(new_scale_y)) / 2
            new_scale_x = math.copysign(ratio, new_scale_x)
            new_scale_y = math.copysign(ratio, new_scale_y)
        # Dragging a corner across the origin would otherwise flip the
        # sprite (a negative scale) -- the Scale spinboxes only ever go
        # positive (0.01-100.0), so clamp here too rather than showing a
        # canvas-only capability the numeric field can't represent.
        self.sprite.scale_x = max(0.01, abs(new_scale_x))
        self.sprite.scale_y = max(0.01, abs(new_scale_y))
        self._apply_authored_transform()
        self._panel.on_sprite_scaled(self.sprite)

    def _apply_authored_transform(self) -> None:
        self.prepareGeometryChange()
        self.setTransform(QTransform().rotate(self.sprite.rotation_deg).scale(self.sprite.scale_x, self.sprite.scale_y))

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            pos = self.pos()
            self.sprite.position = (pos.x(), pos.y())
            self._panel.on_sprite_moved(self.sprite)
        elif change == QGraphicsItem.ItemSelectedHasChanged:
            # boundingRect() grows to fit the rotate handle once selected
            # (see its own comment) -- Qt must be told explicitly, or it
            # keeps using the smaller, stale rect from before selection.
            self.prepareGeometryChange()
        return super().itemChange(change, value)


_VIEWPORT_ZOOM_STEP = 1.15
# Asymmetric on purpose (owner's report, 2026-09-19: "we can zoom out
# really really far but not in very far at all... need it vice versa"):
# refit_to_content's fit-to-content baseline (_viewport_zoom == 1.0)
# already shows the whole avatar with padding, so there's rarely a
# reason to zoom out much further -- 0.1x of that made an already-small
# view shrink to a sliver. Precise per-sprite positioning, the actual
# goal, needs the opposite: room to zoom in *much* closer than 10x.
_MIN_VIEWPORT_ZOOM = 0.5
_MAX_VIEWPORT_ZOOM = 50.0


class GridCanvasView(QGraphicsView):
    """The edit canvas, plus an optional grid overlay -- replaces the
    earlier single-crosshair "origin guides" (owner's request,
    2026-09-17: "origin guide change to 'grid', add grid lines @ 100px
    intervals"). Drawn in drawForeground() so it survives scene.clear()
    with no recreate-it-every-time bookkeeping, and can never be
    accidentally selected or dragged like a real item could. The origin
    axes (through scene (0, 0), where a root-level sprite's own Position
    of (0, 0) sits) are still drawn, brighter than the rest of the grid,
    so that reference point stays easy to find at a glance.

    Scroll-to-zoom (owner's request, 2026-09-19: viewport zoom for this
    editor screen specifically, "keep it simple for now") is purely a
    "look closer while editing" aid on top of whatever refit_to_content
    already fit to the viewport -- it never touches AvatarRig.zoom (the
    authored, whole-avatar Render Window scale -- see the Zoom field on
    the Behavior tab) or anything persisted, and resets on the next
    refit (a resize, a reload, or re-entering Edit mode), same as
    refit_to_content's own fit-to-content transform already does. Live
    Preview (PreviewView) has no equivalent, deliberately -- it must
    always show the avatar at its real Render Window size, so scrolling
    there is left alone.

    Ctrl+drag pans the viewport (owner's request, same day, once zoom
    made panning around while zoomed in actually useful) -- see
    mousePressEvent."""

    show_grid = False
    grid_spacing_px = 100

    def __init__(self, scene, parent=None) -> None:
        super().__init__(scene, parent)
        # Zoom centered on the cursor, not the viewport center -- the
        # natural feel for scroll-to-zoom.
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._viewport_zoom = 1.0
        # Scrollbars off, same as PreviewView's own reasoning -- and load-
        # bearing here, not just cosmetic: zooming in past the fit-to-
        # content baseline makes the content bigger than the viewport,
        # which (with Qt's default ScrollBarAsNeeded) makes a scrollbar
        # appear -- that shrinks the *viewport's* own geometry to make
        # room for it, which fires this widget's resizeEvent, which calls
        # refit_to_content(), instantly resetting the very zoom that just
        # triggered it. Owner's report, 2026-09-19: "the character jumps
        # forward real quick and snaps back... a horizontal scroll bar
        # appears" -- exactly this feedback loop, and exactly why zooming
        # out (content only ever shrinks, no scrollbar, no loop) "worked
        # fine" while zooming in didn't. Never *visible* again below, but
        # still driven programmatically by Ctrl+drag panning (see
        # mousePressEvent) -- QGraphicsView's scrollbars keep working as
        # the view's actual horizontal/vertical offset even at
        # ScrollBarAlwaysOff, which is exactly what makes that safe to
        # use for panning without reintroducing this same feedback loop.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._panning = False
        self._pan_last_pos = QPointF()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Ctrl+drag pans the viewport (owner's request, 2026-09-19) --
        # checked on the mouse event's own modifiers, not tracked via
        # separate key press/release handlers, so it works regardless of
        # whatever widget currently has keyboard focus. Takes priority
        # over the normal click-to-select/drag-to-move-a-sprite behavior
        # below it (event.accept() + early return, never reaching
        # super()) -- Ctrl held is an explicit, unambiguous request to
        # pan, even if the press happens to land on a sprite.
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.button() == Qt.MouseButton.LeftButton:
            self._panning = True
            self._pan_last_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._panning:
            delta = event.position() - self._pan_last_pos
            self._pan_last_pos = event.position()
            self.horizontalScrollBar().setValue(round(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(round(self.verticalScrollBar().value() - delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._panning:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt override)
        delta_y = event.angleDelta().y()
        if delta_y == 0:
            # A horizontal-only wheel/trackpad scroll has nothing to do
            # with zoom -- bug audit 2026-09-23, #20 ("wheel
            # direction"): this used to fall into the "zoom out" branch
            # below (a bare `if y() > 0 else zoom-out` treats *anything*
            # that isn't scroll-up as scroll-down, including a purely
            # horizontal delta), so a horizontal trackpad swipe zoomed
            # out instead of doing nothing. Swallowed, not propagated
            # (still accept()ed), same as this event always was before.
            event.accept()
            return
        factor = _VIEWPORT_ZOOM_STEP if delta_y > 0 else 1 / _VIEWPORT_ZOOM_STEP
        new_zoom = self._viewport_zoom * factor
        if _MIN_VIEWPORT_ZOOM <= new_zoom <= _MAX_VIEWPORT_ZOOM:
            self._viewport_zoom = new_zoom
            self.scale(factor, factor)
        event.accept()

    def drawForeground(self, painter, rect) -> None:  # noqa: N802 (Qt override)
        super().drawForeground(painter, rect)
        if not self.show_grid:
            return
        spacing = max(1, self.grid_spacing_px)
        line_color = QColor(theme.INK_500)
        line_color.setAlpha(140)
        pen = QPen(line_color)
        pen.setCosmetic(True)
        painter.setPen(pen)
        left = math.floor(rect.left() / spacing) * spacing
        top = math.floor(rect.top() / spacing) * spacing
        x = left
        while x <= rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += spacing
        y = top
        while y <= rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += spacing

        axis_color = QColor(theme.MAGENTA_500)
        axis_color.setAlpha(180)
        axis_pen = QPen(axis_color)
        axis_pen.setStyle(Qt.PenStyle.DashLine)
        axis_pen.setCosmetic(True)
        painter.setPen(axis_pen)
        painter.drawLine(QPointF(rect.left(), 0), QPointF(rect.right(), 0))
        painter.drawLine(QPointF(0, rect.top()), QPointF(0, rect.bottom()))

    def refit_to_content(self) -> None:
        bounds = self.scene().itemsBoundingRect()
        if bounds.isEmpty():
            return
        padded = bounds.adjusted(-60, -60, 60, 60)
        self.fitInView(padded, Qt.AspectRatioMode.KeepAspectRatio)
        # fitInView sets its own transform outright, unrelated to
        # whatever scroll-zoom had accumulated -- reset the baseline so
        # the min/max clamp in wheelEvent stays relative to *this* fit,
        # not a stale one from before a resize/reload/mode switch.
        self._viewport_zoom = 1.0

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self.refit_to_content()


class ControlPanelWindow(QWidget):
    def __init__(
        self,
        rig: AvatarRig,
        config: Config,
        render_window,
        state_path=None,
        audio_manager=None,
        obs_link_manager=None,
        asset_watcher=None,
        autosave_interval_ms: int = AUTOSAVE_INTERVAL_MS,
    ) -> None:
        super().__init__()
        self.rig = rig
        self.config = config
        self.render_window = render_window
        self._state_path = state_path
        self.audio_manager = audio_manager
        self.obs_link_manager = obs_link_manager
        # For note_own_write() -- see _on_save/_on_save_as and
        # hot_reload.py's own docstring (bug audit 2026-09-23, #3).
        # Optional the same way audio_manager/obs_link_manager are: every
        # test builds a panel without a real one.
        self.asset_watcher = asset_watcher

        # --- sprite-editing state (was EditorWindow) ---
        self._items: dict[int, EditableSpriteItem] = {}
        # Layer List row lock buttons, keyed by sprite id -- lets
        # _on_sprite_lock_toggled update a specific row's icon/checked
        # state directly (same safe pattern _on_visibility_toggled
        # already uses for the eye icon) when the toggle came from the
        # *other* control (Lock Position), without rebuilding the whole
        # list mid-signal from a button that list rebuild would delete.
        self._lock_row_buttons: dict[int, QToolButton] = {}
        self._rebuilding_scene = False
        self._selected_id: int | None = None
        self._updating_form = False
        self._undo_pending_for_selection = False
        self._zoom_undo_pending = True
        self._undo_stack: list[list[Sprite]] = []
        self._redo_stack: list[list[Sprite]] = []
        self._help_window: HelpWindow | None = None

        # --- unsaved-avatar-changes tracking (new 2026-09-17) ---
        self._dirty = False
        self._current_avatar_path: str = config.avatar_path

        # --- field-widget bookkeeping (was SettingsWindow) ---
        self._reset_buttons: dict = {}
        self._lock_buttons: dict = {}
        self._expression_buttons: dict[tuple[str, str], QPushButton] = {}
        # Costume/Expression hotkey editors, owner's request, 2026-09-17
        # -- see _rebuild_costume_and_expression_editors's own docstring.
        # Indexed 0..NUM_COSTUMES-1 like rig.AvatarRig.costume_assignments/
        # expression_hotkeys, initialized before any tab is built since
        # _rebuild_scene() (called at the end of __init__) rebuilds these
        # too and must find real lists/layouts here, not missing keys.
        # Each swap/force row is its own QListWidgetItem, immediately
        # before that slot's "+ Add" item -- not one item per slot holding
        # a variable-length inner layout (a QListWidgetItem's size hint
        # doesn't reliably refresh when its embedded widget gains a child
        # after the fact, confirmed empirically, 2026-09-17). _costume_rows
        # is the row *widgets* (what the rest of this app already reads,
        # e.g. row.hide_combo); _costume_row_items is the parallel list of
        # their QListWidgetItems, same order, needed only to remove the
        # right item from the list.
        self._costume_rows: dict[int, list[QWidget]] = {slot: [] for slot in range(NUM_COSTUMES)}
        self._costume_row_items: dict[int, list[QListWidgetItem]] = {slot: [] for slot in range(NUM_COSTUMES)}
        self._costume_add_button_items: dict[int, QListWidgetItem] = {}
        self._expression_hotkey_rows: dict[int, list[QWidget]] = {slot: [] for slot in range(NUM_COSTUMES)}
        self._expression_row_items: dict[int, list[QListWidgetItem]] = {slot: [] for slot in range(NUM_COSTUMES)}
        self._expression_add_button_items: dict[int, QListWidgetItem] = {}
        self._sections: dict[str, CollapsibleSection] = {}
        self._tab_splitters: list[QSplitter] = []
        self._obs_connected = False
        self._obs_muted = False
        # Every per-selected-sprite property widget, across all tabs --
        # appended to as each tab is built, then used uniformly by
        # _set_property_form_enabled (was previously one single
        # QFormLayout's rowCount(); now spans several forms across
        # Sprites and Behavior tabs).
        self._per_sprite_widgets: list[QWidget] = []

        self.setWindowTitle("Unicorn Cloak — Control Panel")
        self.setObjectName("ControlPanelWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Small minimum, not the default width -- "resizable to smaller
        # sizes, scaling the avatar appropriately" (owner's request). The
        # *default* width is what makes the canvas prominent, not a
        # floor that would prevent shrinking the window later.
        self.setMinimumWidth(700)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Side by side, like the original separate Editor/Settings
        # windows -- canvas+level meter on the left, everything else
        # (tabs, bottom bar) on the right. A real QSplitter, not a fixed
        # stretch ratio, so the split itself is resizable too.
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)

        left = self._build_canvas_area()
        self.splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 8, 8, 8)
        self._build_tabs(right_layout)
        self._build_bottom_bar(right_layout)
        self.splitter.addWidget(right)

        # The canvas is the primary feature (owner's request, 2026-09-17:
        # "the preview/editor should be the primary feature and avatar as
        # close to real size as possible") -- it gets the majority share,
        # both as a stretch-on-resize factor and (since stretch factors
        # alone don't control the *initial* split -- QSplitter falls back
        # to each pane's own sizeHint() before any resize happens, and
        # the tabs side easily wins that on sizeHint() alone) as an
        # explicit initial size below, once the window's real width is
        # known.
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        root.addWidget(self.splitter)

        self.scene.selectionChanged.connect(self._on_scene_selection_changed)

        self._apply_persisted_ui_state()
        self._apply_persisted_geometry()
        # NOT called here: QSplitter.setSizes() only sticks reliably once
        # the window has actually been shown at least once (verified
        # empirically, 2026-09-17 -- calling it pre-show gets silently
        # renegotiated against a not-yet-laid-out placeholder geometry,
        # discarding the requested ratio). See showEvent() below.
        self._splitter_sizes_applied = False

        self._rebuild_scene()
        self._rebuild_list()
        self._set_property_form_enabled(False)
        self._update_undo_redo_buttons()
        self._update_dirty_indicator()

        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._save_config)
        self._autosave_timer.start(autosave_interval_ms)

    # =====================================================================
    # Construction: canvas area
    # =====================================================================

    def _build_canvas_area(self) -> QWidget:
        canvas_container = QWidget()
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(8, 8, 8, 8)

        # Stored on self -- _build_bottom_bar (built later, after this
        # method returns) adds the Undo/Redo buttons to the *end* of
        # this same row once they exist (owner's request, 2026-09-19),
        # rather than duplicating a second pair of buttons here before
        # self.undo/self.redo's own real button objects are even built.
        self.mode_row = mode_row = QHBoxLayout()
        # Two side-by-side mode buttons, not one button whose label swaps
        # (owner's request, 2026-09-19: "side by side, active one
        # highlighted") -- a QButtonGroup gives the usual radio-style
        # exclusivity, and QPushButton:checked (theme.py) already renders
        # the active one highlighted for free.
        mode_tooltip = (
            "Live Preview mirrors the real Render Window -- reacts to your\n"
            "actual mic and blinking, read-only. Edit Sprites is the\n"
            "interactive canvas -- drag sprites to position them, driven by\n"
            "the Preview state controls below instead of live audio.\n"
            "Neither view is captured by OBS; only the Render Window is."
        )
        self.live_preview_btn = QPushButton("Live Preview")
        self.live_preview_btn.setCheckable(True)
        self.live_preview_btn.setChecked(True)
        self.live_preview_btn.setToolTip(mode_tooltip)
        self.edit_sprites_btn = QPushButton("Edit Sprites")
        self.edit_sprites_btn.setCheckable(True)
        self.edit_sprites_btn.setToolTip(mode_tooltip)
        self._canvas_mode_group = QButtonGroup(self)
        self._canvas_mode_group.setExclusive(True)
        self._canvas_mode_group.addButton(self.live_preview_btn)
        self._canvas_mode_group.addButton(self.edit_sprites_btn)
        self.edit_sprites_btn.toggled.connect(self._on_canvas_mode_toggled)
        mode_row.addWidget(self.live_preview_btn)
        mode_row.addWidget(self.edit_sprites_btn)

        # Guide/Ghost, right of Edit Sprites and left of Reset Size/
        # Reset Rotation -- owner's request, 2026-09-20 (they'd landed at
        # the row's far end, after Undo/Redo, the day before). Toggle
        # buttons, not checkboxes with paragraph-long labels (owner's
        # request, 2026-09-17) -- the detail lives in the tooltip
        # instead. Hidden outside Edit mode (see _on_canvas_mode_toggled)
        # since both only ever affect the Edit canvas.
        self.guide_btn = QPushButton("Guide")
        self.guide_btn.setCheckable(True)
        self.guide_btn.setToolTip(
            "Shows a grid on the Edit canvas (spacing set on the\n"
            "Application tab), plus the origin axes through (0, 0) -- where\n"
            "a root-level sprite's own Position of (0, 0) sits. Off by\n"
            "default."
        )
        self.guide_btn.toggled.connect(self._on_guide_toggled)
        mode_row.addWidget(self.guide_btn)

        self.ghost_btn = QPushButton("Ghost")
        self.ghost_btn.setCheckable(True)
        self.ghost_btn.setToolTip(
            "Shows hidden layers and sprites not visible in the current\n"
            "Preview state at 40% opacity on the Edit canvas, so you can\n"
            "see where they are. Never affects the Render Window/OBS,\n"
            "which always renders them at true 0%. Off by default."
        )
        self.ghost_btn.toggled.connect(self._on_ghost_toggled)
        mode_row.addWidget(self.ghost_btn)

        # Owner's request, 2026-09-19: two buttons next to Edit Sprites to
        # reset the selected sprite's Scale/Rotation back to native --
        # hidden outside Edit mode (nothing to reset in Live Preview,
        # which isn't even showing the authored-transform canvas), and
        # disabled with the rest of the per-sprite property form when
        # nothing is selected (see _set_property_form_enabled).
        self.reset_size_btn = QPushButton("Reset Size")
        self.reset_size_btn.setToolTip("Reset the selected sprite's Scale X/Y back to 1.0 (native size).")
        self.reset_size_btn.clicked.connect(self._on_reset_size_clicked)
        self.reset_rotation_btn = QPushButton("Reset Rotation")
        self.reset_rotation_btn.setToolTip("Reset the selected sprite's Rotation back to 0° (unrotated).")
        self.reset_rotation_btn.clicked.connect(self._on_reset_rotation_clicked)
        mode_row.addWidget(self.reset_size_btn)
        mode_row.addWidget(self.reset_rotation_btn)
        self._per_sprite_widgets.extend((self.reset_size_btn, self.reset_rotation_btn))

        # The trailing stretch is added once, in _build_bottom_bar, after
        # Undo/Redo are appended below -- owner's request, 2026-09-19:
        # keep this whole row as one contiguous group rather than a
        # stretch splitting it into two clusters (which is what happened
        # when Undo/Redo were first added here, pushed off to the far
        # right on their own).
        canvas_layout.addLayout(mode_row)

        # --- Edit-mode preview-state controls (only meaningful in Edit
        # mode -- hidden while Live Preview is active) ---
        self.preview_controls = self._build_preview_controls()
        canvas_layout.addWidget(self.preview_controls)

        self.canvas_stack = QStackedWidget()

        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(QColor(theme.INK_850))
        self.edit_view = GridCanvasView(self.scene, self)
        self.edit_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.edit_view.setToolTip("Drag a sprite to move it. Click to select.")
        self.canvas_stack.addWidget(self.edit_view)

        self.live_view = PreviewView(self.render_window.scene)
        self.canvas_stack.addWidget(self.live_view)

        canvas_layout.addWidget(self.canvas_stack, stretch=1)

        self.level_meter = LevelMeter(self.config, self.render_window)
        self.level_meter.setToolTip(
            "Live level against the Audio tab's thresholds -- solid marks\n"
            "are the \"open\" thresholds, dashed marks are \"close\". Always\n"
            "shown below the avatar, in both Live Preview and Edit modes."
        )
        canvas_layout.addWidget(self.level_meter)

        return canvas_container

    def _build_preview_controls(self) -> QWidget:
        box = QWidget()
        form = QFormLayout(box)
        form.setContentsMargins(0, 0, 0, 0)

        self.preview_talk_level = 0
        self.preview_blink_level = 1
        self.preview_manual_overrides: dict[str, str] = {}

        row1 = QHBoxLayout()
        self.preview_talk_combo = QComboBox()
        self.preview_talk_combo.addItem("Quiet", 0)
        self.preview_talk_combo.addItem("Mild", 1)
        self.preview_talk_combo.addItem("Wide", 2)
        self.preview_talk_combo.setToolTip(
            "Forces the Edit canvas to preview sprites as if the mic were\n"
            "at this talk level -- lets you check which mouth (etc.)\n"
            "actually shows at each level without talking. Never affects\n"
            "the Render Window."
        )
        self.preview_talk_combo.currentIndexChanged.connect(self._on_preview_talk_level_changed)
        row1.addWidget(QLabel("Talk level"))
        row1.addWidget(self.preview_talk_combo)

        self.preview_blink_combo = QComboBox()
        self.preview_blink_combo.addItem("Eyes open", 1)
        self.preview_blink_combo.addItem("Mid-blink", 2)
        self.preview_blink_combo.setToolTip(
            "Forces the Edit canvas to preview sprites as if the avatar\n"
            "were in this blink state. Never affects the Render Window."
        )
        self.preview_blink_combo.currentIndexChanged.connect(self._on_preview_blink_level_changed)
        row1.addWidget(QLabel("Blink state"))
        row1.addWidget(self.preview_blink_combo)
        row1.addStretch(1)
        form.addRow(row1)

        row2 = QHBoxLayout()
        self.preview_talk_variant = QSpinBox()
        self.preview_talk_variant.setRange(0, 9)
        self.preview_talk_variant.setToolTip(
            "Which variant to preview among sprites sharing the same Talk\n"
            "level -- only matters if more than one sprite shares it."
        )
        self.preview_talk_variant.valueChanged.connect(self._on_preview_variant_changed)
        row2.addWidget(QLabel("Force talk variant"))
        row2.addWidget(self.preview_talk_variant)

        self.preview_blink_variant = QSpinBox()
        self.preview_blink_variant.setRange(0, 9)
        self.preview_blink_variant.setToolTip(
            "Which variant to preview among sprites sharing the same Blink\n"
            "state (e.g. squint vs. wide-open eyes, both \"eyes open\")."
        )
        self.preview_blink_variant.valueChanged.connect(self._on_preview_variant_changed)
        row2.addWidget(QLabel("Force blink variant"))
        row2.addWidget(self.preview_blink_variant)

        self.preview_expression_combo = QComboBox()
        self.preview_expression_combo.setToolTip(
            "Forces the Edit canvas to preview a manually-driven expression\n"
            "as if it were live-activated. Never affects the Render Window,\n"
            "which uses the Expressions section instead."
        )
        self.preview_expression_combo.currentIndexChanged.connect(self._on_preview_expression_changed)
        self._refresh_preview_expression_combo()
        row2.addWidget(QLabel("Force expression"))
        row2.addWidget(self.preview_expression_combo)
        row2.addStretch(1)
        form.addRow(row2)

        return box

    # =====================================================================
    # Construction: tabs
    # =====================================================================

    def _register_section(self, section: CollapsibleSection) -> CollapsibleSection:
        self._sections[section.title] = section
        return section

    def _tab_splitter(self, sections: list[CollapsibleSection]) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Vertical)
        self._tab_splitters.append(splitter)
        for section in sections:
            self._register_section(section)
            splitter.addWidget(section)
        for section in sections:
            section.collapsed_changed.connect(
                lambda collapsed, sec=section, sp=splitter: self._on_section_collapsed_changed(sp, sec, collapsed)
            )
        return splitter

    def _add_tab_splitter(self, outer: QVBoxLayout, sections: list[CollapsibleSection]) -> None:
        splitter = self._tab_splitter(sections)
        outer.addWidget(splitter)
        # Initial value only -- _apply_persisted_ui_state()'s own
        # set_collapsed() calls (right after every tab is built) already
        # fire collapsed_changed for each section, which recomputes this
        # for real against whatever the persisted state actually is. See
        # _update_splitter_top_alignment for what this is and why it must
        # stay conditional, not permanent.
        self._update_splitter_top_alignment(splitter)

    def _update_splitter_top_alignment(self, splitter: QSplitter) -> None:
        # Root cause, 2026-09-17, owner's report ("the behavior tab
        # started all collapsed & centered"): once every section in a
        # splitter is collapsed, QSplitter's own effective maximumHeight
        # shrinks to the sum of its (now Maximum-policy) children's
        # sizeHints -- a plain QVBoxLayout, with no alignment set,
        # centers a child that can't grow to fill the space it's given
        # rather than pegging it to the top.
        #
        # This must be conditional, not a permanent AlignTop set once at
        # construction (what the first version of this fix did) --
        # confirmed empirically, 2026-09-17, owner's report on the new
        # single-section Costume/Expression Hotkeys tabs ("sooo much room
        # and clipping them"): Qt's setAlignment() on a layout item
        # overrides that item's own size policy entirely, permanently
        # capping it to its sizeHint and aligning within the leftover
        # space -- it is *not* the "no-op once the widget can already
        # fill the space" behavior the original comment assumed, that
        # assumption was simply wrong.
        #
        # The condition below used to be just "all collapsed" -- correct
        # back when every *expanded* section requested QWIDGETSIZE_MAX
        # and so could always grow into extra room. Since
        # _resync_tab_splitter_sizes started capping non-growable
        # sections to their own content height (2026-09-19, see
        # CollapsibleSection.wants_extra_space's own comment), an
        # expanded-but-capped section can no longer fill leftover space
        # either -- and the same centering this comment already describes
        # showed up again, this time with State Assignment/Expressions
        # both expanded and Layer List merely collapsed, not everything.
        # The real condition was never really about collapsed/expanded at
        # all -- it's about whether *anything* currently visible in this
        # splitter can actually grow to absorb extra space.
        nothing_can_grow = not any(
            not splitter.widget(i).is_collapsed() and splitter.widget(i).wants_extra_space
            for i in range(splitter.count())
        )
        outer = splitter.parentWidget().layout()
        outer.setAlignment(splitter, Qt.AlignmentFlag.AlignTop if nothing_can_grow else Qt.AlignmentFlag(0))

    def _on_section_collapsed_changed(
        self, splitter: QSplitter, section: CollapsibleSection, collapsed: bool
    ) -> None:
        # _make_room_if_needed first, not last -- it can itself collapse a
        # *different* section in this splitter to make room, which the
        # resync/realign below needs to already know about.
        if not collapsed:
            self._make_room_if_needed(splitter, section)
        self._resync_tab_splitter_sizes(splitter)
        self._update_splitter_top_alignment(splitter)
        # A second pass, deferred to the next event-loop tick, is also
        # needed -- found 2026-09-19 chasing an unrelated bug (a growable
        # section, e.g. Layer List, staying stuck at its pre-toggle height
        # after a same-splitter collapse/expand sequence, surviving even a
        # plain processEvents() in the caller). setAlignment() above did
        # take effect (confirmed by inspecting the item's actual alignment
        # afterward), but the QSplitter's own negotiated geometry against
        # its parent layout still didn't reflect it until something forced
        # a *fresh* layout pass outside this call's own stack -- an
        # otherwise-redundant extra call to this same method, but only
        # once deferred via QTimer.singleShot(0, ...), reliably fixed it;
        # neither an inline re-call nor reordering these three calls did.
        # Re-fetches the section/splitter fresh rather than closing over
        # them, in case either no longer exists by the time this runs.
        def _resync_again() -> None:
            if section.parent() is splitter:
                self._resync_tab_splitter_sizes(splitter)
                self._update_splitter_top_alignment(splitter)

        QTimer.singleShot(0, _resync_again)

    def _resync_tab_splitter_sizes(self, splitter: QSplitter) -> None:
        # QSplitter caches each pane's last-negotiated pixel size across
        # calls, even after a child's sizePolicy/sizeHint changes --
        # verified empirically, 2026-09-17: collapsing every section
        # after having previously expanded them left the collapsed
        # headers floating well below the top of the tab instead of
        # pegged to it (owner's report: "when all items collapse they
        # jump to vertical center"), because the splitter still thought
        # each pane needed its old, larger allotment. Forcing a fresh
        # setSizes() call -- each collapsed pane's actual sizeHint, and a
        # deliberately oversized number for every expanded one so it
        # still competes normally for whatever's left -- makes Qt
        # recompute proportions from scratch instead of reusing the
        # stale ones.
        sizes = []
        for i in range(splitter.count()):
            pane = splitter.widget(i)
            if isinstance(pane, CollapsibleSection) and pane.is_collapsed():
                pane.setMaximumHeight(16_777_215)
                sizes.append(pane.sizeHint().height())
            elif isinstance(pane, CollapsibleSection) and not pane.wants_extra_space:
                # Cap to the section's own real content height instead of
                # requesting QWIDGETSIZE_MAX like every expanded section
                # used to (owner's report, 2026-09-19: a gap between two
                # small expanded sections, e.g. State Assignment and
                # Expressions, "disappears when layers is also open").
                # setSizes() alone doesn't stop QSplitter from stretching
                # a pane past what's requested when there's leftover
                # space and nothing else claims it -- only an actual
                # setMaximumHeight() does. Growable sections (see
                # CollapsibleSection.wants_extra_space) keep the old
                # QWIDGETSIZE_MAX behavior below, so they're still what
                # absorbs genuine leftover splitter space.
                content_height = pane.sizeHint().height()
                pane.setMaximumHeight(content_height)
                sizes.append(content_height)
            else:
                if isinstance(pane, CollapsibleSection):
                    pane.setMaximumHeight(16_777_215)
                sizes.append(16_777_215)  # QWIDGETSIZE_MAX -- "everything left over"
        splitter.setSizes(sizes)

    def _make_room_if_needed(self, splitter: QSplitter, just_expanded: CollapsibleSection) -> None:
        # Owner's request, 2026-09-17: "when expanding all, if that makes
        # the column longer than the window it changes the window
        # size... instead it should collapse something else and not
        # change the window size." Nothing absorbs overflow in these
        # per-tab splitters (no scroll area), so an expanded section's
        # full minimumSizeHint bumps the whole Control Panel window's own
        # effective minimum size, which Qt then grows the real window to
        # satisfy. Pre-empt that here: if every section's current
        # minimum no longer fits the space this tab actually has,
        # collapse another section in the same splitter to make room
        # instead -- repeating in the rare case one collapse isn't
        # enough. Gives up rather than loop forever once nothing is left
        # that can be collapsed.
        #
        # "The space this tab actually has" is deliberately NOT
        # splitter.height() -- a real bug, found from the owner's
        # follow-up report ("now you can only have one section open at a
        # time"): once _add_tab_splitter's AlignTop takes effect (see its
        # own comment), the splitter's *own* height shrinks to fit its
        # content whenever nothing in it is expanded, so measuring
        # against it right as the first section expands from an
        # all-collapsed state reads a stale, much-too-small number and
        # triggers a collapse that was never actually needed. The tab
        # *page*'s own height, by contrast, is assigned directly by
        # QTabWidget and does not change just because the splitter inside
        # it is smaller than that -- a stable measure of the real budget,
        # confirmed empirically by reproducing the two-sections-expanded
        # case and comparing both numbers side by side.
        page = splitter.parentWidget()
        page_layout = page.layout()
        margins = page_layout.contentsMargins()
        available = page.height() - margins.top() - margins.bottom()
        handles = splitter.handleWidth() * max(0, splitter.count() - 1)
        panes = [splitter.widget(i) for i in range(splitter.count())]
        while True:
            demand = sum(p.minimumSizeHint().height() for p in panes) + handles
            if demand <= available:
                return
            candidate = next(
                (
                    p for p in panes
                    if p is not just_expanded
                    and isinstance(p, CollapsibleSection)
                    and not p.is_collapsed()
                ),
                None,
            )
            if candidate is None:
                return
            candidate.set_collapsed(True)

    def _build_tabs(self, root: QVBoxLayout) -> None:
        self.tabs = QTabWidget()
        # Behavior right after Sprites -- owner's request, 2026-09-19,
        # since its Position & Hierarchy section is what most sprite
        # edits actually land on, and it now carries a header naming the
        # sprite currently selected (see _build_behavior_tab).
        self.tabs.addTab(self._build_sprites_tab(), "Sprites")
        self.tabs.addTab(self._build_behavior_tab(), "Behavior")
        self.tabs.addTab(self._build_costumes_tab(), "Costume Hotkeys")
        self.tabs.addTab(self._build_expressions_tab(), "Expression Hotkeys")
        self.tabs.addTab(self._build_audio_tab(), "Audio")
        self.tabs.addTab(self._build_application_tab(), "Application")
        root.addWidget(self.tabs, stretch=3)

    def _build_sprites_tab(self) -> QWidget:
        layer_section = CollapsibleSection("Layer List", wants_extra_space=True)
        self.sprite_list = QListWidget()
        self.sprite_list.setToolTip(
            "Every sprite in this avatar, listed front-to-back -- top of\n"
            "the list is drawn in front of (on top of) everything below it.\n"
            "Indentation shows parent/child grouping. Click to select."
        )
        self.sprite_list.currentItemChanged.connect(self._on_list_selection_changed)
        # Owner's request, 2026-09-17: "expand the layers section so it
        # can display 10 lines... it's super cramped @ around 2.75 right
        # now." Without an explicit minimum, this list only ever got
        # whatever leftover space State Assignment/Expressions didn't
        # need, on this same tab's shared splitter. Row height measured
        # empirically (sizeHintForRow, real rig, real theme) at 23px --
        # 10 rows plus a little frame padding.
        self.sprite_list.setMinimumHeight(23 * 10 + 20)
        layer_section.body_layout.addWidget(self.sprite_list)

        layer_order_row = QHBoxLayout()
        move_up_btn = QPushButton("Move Up")
        move_down_btn = QPushButton("Move Down")
        move_up_btn.setToolTip(
            "Move the selected sprite one step toward the front, swapping\n"
            "places with the sprite currently in front of it (siblings only)."
        )
        move_down_btn.setToolTip(
            "Move the selected sprite one step toward the back, swapping\n"
            "places with the sprite currently behind it (siblings only)."
        )
        move_up_btn.clicked.connect(self._on_move_up)
        move_down_btn.clicked.connect(self._on_move_down)
        layer_order_row.addWidget(move_up_btn)
        layer_order_row.addWidget(move_down_btn)
        layer_section.body_layout.addLayout(layer_order_row)

        struct_row = QHBoxLayout()
        add_btn = QPushButton("Add…")
        replace_btn = QPushButton("Replace…")
        duplicate_btn = QPushButton("Duplicate")
        delete_btn = QPushButton("Delete")
        add_btn.setToolTip("Add a new sprite layer from an image file.")
        replace_btn.setToolTip(
            "Swap the selected sprite's image for a different file.\n"
            "Position, motion, and visibility settings are kept as-is."
        )
        duplicate_btn.setToolTip("Duplicate the selected sprite, slightly offset from the original.")
        delete_btn.setToolTip(
            "Delete the selected sprite. Any children are kept and moved\n"
            "to the root level, not deleted along with it."
        )
        add_btn.clicked.connect(self._on_add)
        replace_btn.clicked.connect(self._on_replace)
        duplicate_btn.clicked.connect(self._on_duplicate)
        delete_btn.clicked.connect(self._on_delete)
        for b in (add_btn, replace_btn, duplicate_btn, delete_btn):
            struct_row.addWidget(b)
        layer_section.body_layout.addLayout(struct_row)

        # State Assignment and Expressions live here, not on the Behavior
        # tab -- owner's request, 2026-09-17: both are about *what a
        # sprite is* (which group/state it belongs to, and testing that
        # tagging live), which belongs next to the sprite list that
        # defines it, not next to the avatar-wide Motion tuning knobs.
        state_section = CollapsibleSection("State Assignment")
        self.state_form = QFormLayout()
        self.group_name = QComboBox()
        self.group_name.setEditable(True)
        self.state_name = QComboBox()
        self.state_name.setEditable(True)
        self.manual_driven = QCheckBox("Manually driven")
        self.talk_state = QComboBox()
        for value, label in motion.TALK_STATE_LABELS.items():
            self.talk_state.addItem(label, value)
        self.blink_state = QComboBox()
        for value, label in motion.BLINK_STATE_LABELS.items():
            self.blink_state.addItem(label, value)
        # Last row, not on the Behavior tab's Animation section where it
        # used to live -- owner's request, 2026-09-20: Variant is which
        # *slot* within a shared Talk/Blink state this sprite alternates
        # in, so it belongs with the rest of that state assignment, not
        # grouped with Frames/Anim speed (spritesheet playback, an
        # unrelated concept it only happened to share a section with).
        self.variant = QSpinBox()
        self.variant.setRange(0, 9)

        self.group_name.setToolTip(
            "The named slot this sprite belongs to -- e.g. \"Mouth\" or\n"
            "\"Eyes\". Purely organizational: it doesn't change what shows\n"
            "on its own, but it's what \"Check for Issues\" uses to reason\n"
            "about a set of sprites together instead of them only\n"
            "coincidentally sharing numbers and positions. Leave blank for\n"
            "anything that isn't part of a named group (hair, body, etc.)."
        )
        self.state_name.setToolTip(
            "Which state within Group name this sprite represents -- e.g.\n"
            "\"Closed\", \"Open wide\", \"Laughing\". Options are scoped to\n"
            "whatever's already used in the same Group name above."
        )
        self.manual_driven.setToolTip(
            "When checked, Talk state/Blink state below are ignored\n"
            "entirely -- this sprite shows only when its Group name's live\n"
            "override is forced to this exact State name (via the\n"
            "Expressions section below, on the real Render Window, or the\n"
            "canvas's own Preview state for canvas-only testing). For a\n"
            "named expression like \"Laughing\" that isn't tied to mic\n"
            "volume or blinking at all."
        )
        self.talk_state.setToolTip(
            "What talk level makes this sprite visible. \"Always visible\"\n"
            "is for anything that isn't part of a mouth (hair, body,\n"
            "shades, etc.) -- for an actual mouth shape, pick the one\n"
            "exclusive level it belongs to (Quiet/Mild/Wide) so only one\n"
            "mouth ever shows at a time. Ignored entirely when Manually\n"
            "driven is checked."
        )
        self.blink_state.setToolTip(
            "What blink state makes this sprite visible. \"Always visible\"\n"
            "is for anything that isn't an eye shape. Ignored entirely\n"
            "when Manually driven is checked."
        )
        self.variant.setToolTip(
            "Alternation slot for sprites that share the same Talk state\n"
            "(e.g. two \"mild\" mouths) or Blink state (e.g. two \"eyes\n"
            "open\" shapes) -- they take turns showing, cycling 0, 1, 2...\n"
            "at the Behavior tab's \"Mouth/Eye alternate rate\". A state\n"
            "with only one sprite in it ignores this."
        )
        self.state_form.addRow("Group name", self.group_name)
        self.state_form.addRow("State name", self.state_name)
        self.state_form.addRow(self.manual_driven)
        self.state_form.addRow("Talk state", self.talk_state)
        self.state_form.addRow("Blink state", self.blink_state)
        self.state_form.addRow("Variant", self.variant)
        for widget in (self.group_name, self.state_name, self.talk_state, self.blink_state, self.variant):
            label = self.state_form.labelForField(widget)
            if label is not None:
                label.setToolTip(widget.toolTip())
        state_section.body_layout.addLayout(self.state_form)
        # See position_section's own comment below (Zoom vs. property_form)
        # for why this matters: without it, whenever this section is given
        # more splitter room than state_form actually needs, Qt spreads
        # that leftover space into the layout instead of leaving it below.
        state_section.body_layout.addStretch(1)

        self.talk_state.currentIndexChanged.connect(self._on_property_changed)
        self.blink_state.currentIndexChanged.connect(self._on_property_changed)
        self.variant.valueChanged.connect(self._on_property_changed)
        self.manual_driven.toggled.connect(self._on_manual_driven_toggled)
        # editTextChanged, not currentIndexChanged: verified empirically
        # that for an editable QComboBox, picking an existing item fires
        # both, but typing a brand-new value that isn't in the list fires
        # only editTextChanged.
        self.group_name.editTextChanged.connect(self._on_group_name_changed)
        self.state_name.editTextChanged.connect(self._on_property_changed)

        self._per_sprite_widgets.extend(
            (self.group_name, self.state_name, self.manual_driven, self.talk_state, self.blink_state, self.variant)
        )

        expressions_section = CollapsibleSection("Expressions")
        self._expressions_layout = QVBoxLayout()
        self._expressions_placeholder = QLabel(
            "No manually-driven expressions yet -- tag a sprite above\n"
            "(Group name / State name / Manually driven) to get a toggle\n"
            "here."
        )
        self._expressions_placeholder.setToolTip(self._expressions_placeholder.text())
        self._refresh_expressions_section()
        expressions_section.body_layout.addLayout(self._expressions_layout)
        # Without this, the section's own QVBoxLayout has nothing to
        # absorb extra vertical space once expanded -- with only a
        # handful of toggle buttons (or the placeholder label), Qt
        # centers that lone child in the leftover space instead of
        # pinning it to the top (owner's report, 2026-09-19: "when
        # expanded rows are centered"). A trailing stretch gives that
        # extra space somewhere else to go.
        expressions_section.body_layout.addStretch(1)

        tab = QWidget()
        outer = QVBoxLayout(tab)
        self._add_tab_splitter(outer, [layer_section, state_section, expressions_section])
        return tab

    def _build_behavior_tab(self) -> QWidget:
        motion_section = CollapsibleSection("Motion")
        motion_form = QFormLayout()
        self._add_double(
            motion_form, "Bounce strength", 0.0, 2000.0, 10.0, 0,
            self.config.motion, "bounce_strength",
            "How high the avatar hops on a speech bounce.",
        )
        self._add_double(
            # Minimum 100.0, not 0.0 -- bug audit 2026-09-23, #13:
            # gravity 0 never decays a bounce's velocity at all, so the
            # avatar's first speak-bounce just drifts permanently
            # off-screen instead of settling. motion.bounce_step floors
            # it the same way independently, at the same value (a
            # hand-edited settings.json bypasses this range entirely --
            # see that constant's own comment for why 100.0 specifically,
            # not a token nonzero minimum), but there's no reason to let
            # the UI itself offer a value that's silently broken.
            motion_form, "Gravity", 100.0, 5000.0, 10.0, 0,
            self.config.motion, "gravity",
            "How fast a bounce falls back down. Higher = snappier and\n"
            "shorter hops, lower = slower and floatier.",
        )
        self._add_double(
            motion_form, "Bounce retrigger (ms)", 20.0, 2000.0, 10.0, 0,
            self.config.motion, "bounce_retrigger_ms",
            "Minimum time between bounces during continuous speech, so the\n"
            "avatar keeps bobbing the whole time you're talking instead of\n"
            "bouncing once and going still. The bounce also has to have\n"
            "actually settled first, so this is a floor, not a guarantee.",
        )
        self._add_double(
            motion_form, "Blink speed", 0.1, 5.0, 0.1, 1,
            self.config.motion, "blink_speed",
            "Blink frequency multiplier. Higher = blinks more often.",
        )
        self._add_int(
            motion_form, "Blink chance (1-in-N)", 10, 2000,
            self.config.motion, "blink_chance",
            "Odds of a blink each time one becomes eligible: 1 in N.\n"
            "Lower N = blinks more often.",
        )
        self._add_double(
            motion_form, "Mouth wobble freq", 0.0, 3.0, 0.05, 2,
            self.config.motion, "mouth_wobble_freq",
            "How fast the mouth wiggles while it's open (any shape other\n"
            "than closed). 0 disables the wiggle.",
        )
        self._add_double(
            motion_form, "Mouth wobble amount", 0.0, 30.0, 0.5, 1,
            self.config.motion, "mouth_wobble_amp",
            "How far the mouth wiggles while it's open, in pixels.",
        )
        self._add_double(
            motion_form, "Mouth alternate rate (Hz)", 0.0, 20.0, 0.5, 1,
            self.config.motion, "mouth_variant_hz",
            "How many times per second a mouth shape with more than one\n"
            "image (e.g. two \"mild\" mouths) swaps between them while that\n"
            "shape is showing -- gives continuous talking some flutter\n"
            "instead of freezing on one static image. A shape with only\n"
            "one image ignores this (set each mouth's Variant, below in\n"
            "Animation, to group them).",
        )
        self._add_double(
            motion_form, "Eye alternate rate (Hz)", 0.0, 2.0, 0.05, 2,
            self.config.motion, "eye_variant_hz",
            "How often an \"eyes open\" shape with more than one image\n"
            "(e.g. wide-open and squint) swaps between them while not\n"
            "blinking -- deliberately slow, an occasional expression\n"
            "change rather than a flutter. A shape with only one image\n"
            "ignores this (set each eye shape's Variant, below in\n"
            "Animation, to group them).",
        )
        motion_section.body_layout.addLayout(motion_form)
        motion_section.body_layout.addStretch(1)

        # Position & Hierarchy and Animation live here, not on the
        # Sprites tab -- owner's request, 2026-09-17: both are per-sprite
        # *behavior* tuning (where it sits, how it animates), same
        # category as Motion above, not sprite identity/structure like
        # the Layer List. Collapsed by default (also the owner's
        # request) since Motion is the one most people tune first.
        position_section = CollapsibleSection("Position & Hierarchy", collapsed=True)

        # Zoom, moved here from the Application tab's Display group,
        # owner's request, 2026-09-17: "i think we should move zoom to
        # the position panel." It's a whole-avatar scale, not per-sprite
        # like everything else below -- its own QFormLayout, deliberately
        # left out of self.property_form/self._per_sprite_widgets, so it
        # doesn't get reloaded or disabled as sprites are selected.
        #
        # setContentsMargins(0, ...) -- same fix _build_preview_controls
        # already uses for its own form box, so two forms stacked in one
        # section don't each carry their own default margins on top of
        # each other.
        #
        # The real cause of the owner's 2026-09-19 report ("since zoom
        # was added it has a big gap under it") turned out to be a
        # different, bigger thing than that margin doubling, confirmed
        # from a follow-up screenshot after the margin fix alone didn't
        # help: with two stacked layouts here (zoom_form, self.property_
        # form below) and nothing telling Qt where to put leftover space,
        # this section -- once it's the only or dominant thing expanded
        # in the Behavior tab's splitter, so it's handed far more height
        # than either form actually needs -- spread that surplus space
        # *into* the layout (a visible gap between the two forms) instead
        # of leaving it below both. The fix is the addStretch(1) after
        # self.property_form, below -- same technique already used for
        # the Sprites tab's Expressions section (see its own comment) and
        # now applied to every section here for the same reason.
        zoom_form = QFormLayout()
        zoom_form.setContentsMargins(0, 0, 0, 0)
        self.zoom = ScrollSafeDoubleSpinBox()
        self.zoom.setRange(0.1, 5.0)
        self.zoom.setSingleStep(0.05)
        self.zoom.setDecimals(2)
        self.zoom.setValue(self.rig.zoom)
        zoom_tooltip = (
            "Scales the whole avatar bigger/smaller within the Render\n"
            "Window, around its own center -- doesn't change the window's\n"
            "own size, and applies no matter which sprite (if any) is\n"
            "selected below. 1.0 = normal size. Saved with the avatar, not\n"
            "the app -- different avatars can each have their own zoom."
        )
        self.zoom.setToolTip(zoom_tooltip)
        self.zoom.valueChanged.connect(self._on_zoom_changed)
        self.zoom.editingFinished.connect(self._on_zoom_editing_finished)
        self._add_row_with_reset_and_lock(
            zoom_form, "Zoom (whole avatar)", self.zoom,
            self._default_for(self.rig, "zoom"), zoom_tooltip,
        )
        position_section.body_layout.addLayout(zoom_form)

        self.property_form = QFormLayout()
        self.property_form.setContentsMargins(0, 0, 0, 0)
        # Range widened from an earlier +/-4000, decimals from the
        # QDoubleSpinBox default (2) to 4 -- bug audit 2026-09-23, #7:
        # _on_property_changed (below) writes back *every* transform
        # field on *any* property edit, whichever widget's signal
        # actually fired, reading each spinbox's current .value(). A
        # canvas drag writes unrounded, unbounded floats straight to
        # sprite.position -- at 2 decimals and a +/-4000 range, the next
        # unrelated edit (e.g. Talk state) silently rounded (12.3456 ->
        # 12.35) or clamped (a drag past 4000 -> 4000) that value the
        # moment _load_property_form reflected it back into these boxes.
        # 4 decimals and a much larger range don't eliminate the
        # possibility entirely (still a bounded, rounded float), but
        # cover anything this canvas could plausibly produce.
        self.pos_x = self._spin(-1_000_000, 1_000_000, decimals=4)
        self.pos_y = self._spin(-1_000_000, 1_000_000, decimals=4)
        self.offset_x = self._spin(-1_000_000, 1_000_000, decimals=4)
        self.offset_y = self._spin(-1_000_000, 1_000_000, decimals=4)
        self.z_index = QSpinBox()
        self.z_index.setRange(-1000, 1000)
        self.parent_combo = QComboBox()
        # Seeded with a placeholder immediately -- unlike the spinboxes
        # above (which show *some* value, e.g. 0.00, even before a
        # sprite is ever selected), a QComboBox nobody has ever called
        # addItem() on shows as a genuinely empty, item-less dropdown --
        # owner's report, 2026-09-19: "it does not populate in the
        # parent row." _populate_parent_combo (see _load_property_form)
        # replaces this with the real list, including this same "None
        # (root)" first entry, the moment a sprite is actually selected.
        self.parent_combo.addItem("None (root)", None)

        _pos_tip = "relative to this sprite's parent (or the avatar's center, for a root-level sprite)."
        self.pos_x.setToolTip(f"Horizontal position, {_pos_tip}")
        self.pos_y.setToolTip(f"Vertical position, {_pos_tip}")
        _offset_tip = (
            "Shifts where the image is drawn without moving this sprite's\n"
            "pivot point -- mainly matters for rotation and stretch."
        )
        self.offset_x.setToolTip(_offset_tip)
        self.offset_y.setToolTip(_offset_tip)
        self.z_index.setToolTip(
            "Stacking order relative to this sprite's siblings only\n"
            "(same parent) -- higher draws in front. Negative draws behind\n"
            "this sprite's own parent (e.g. a hair-back layer)."
        )
        self.parent_combo.setToolTip(
            "Attach this sprite to another as its parent -- it will inherit\n"
            "the parent's position, rotation, and stretch. A sprite with its\n"
            "own drag speed set can lag behind a moving parent (e.g. hair\n"
            "trailing a head) -- drag speed isn't editable in this panel yet,\n"
            "only via the .save file."
        )
        self.property_form.addRow("Position X", self.pos_x)
        self.property_form.addRow("Position Y", self.pos_y)
        self.property_form.addRow("Offset X", self.offset_x)
        self.property_form.addRow("Offset Y", self.offset_y)
        self.property_form.addRow("Z-index", self.z_index)
        self.property_form.addRow("Parent", self.parent_combo)

        # Rotation, owner's request, 2026-09-17: "in the editor, drag the
        # active sprite around and scale/rotate it" -- a plain numeric
        # field here, same as Position/Offset above; the drag-to-rotate
        # handle on the edit canvas (see EditableSpriteItem) writes into
        # this same sprite.rotation_deg and keeps this spinbox in sync via
        # on_sprite_rotated, the same pattern on_sprite_moved already uses
        # for drag-to-move.
        self.rotation = self._spin(-360.0, 360.0, decimals=4)  # decimals: see pos_x's own comment, bug audit #7
        self.rotation.setToolTip(
            "Permanently rotates this sprite, e.g. for an accessory drawn\n"
            "at the wrong angle, or a limb that should hang at a fixed\n"
            "tilt. 0 is the image's own native orientation. Independent of\n"
            "the reactive drag-based rotation on the Behavior tab's Motion\n"
            "section, which adds on top of this."
        )
        self.property_form.addRow("Rotation (deg)", self.rotation)

        # Scale, owner's request, 2026-09-17: "add scale features to the
        # positioning section... w/a lock toggle (on by default) that
        # scales x & y maintaining proportions." A toggle QPushButton,
        # not a checkbox -- matches Guide/Ghost's own established
        # convention in this app. Linking is handled in
        # _on_scale_x/y_changed and EditableSpriteItem._drag_handle, not
        # here; this row just lays the three widgets out. Briefly
        # retired 2026-09-19 when this exact button's own toggle was
        # repurposed into per-sprite Lock Position (below) -- restored as
        # its own separate control the same day: a session-wide editing
        # preference (do the two axes track each other), independent of
        # whether the sprite is fully locked or not.
        self.scale_x = self._spin(0.01, 100.0, decimals=4)  # decimals: see pos_x's own comment, bug audit #7
        self.scale_y = self._spin(0.01, 100.0, decimals=4)
        self.scale_lock = QPushButton("🔗 Lock proportions")
        self.scale_lock.setCheckable(True)
        self.scale_lock.setChecked(True)
        self.scale_x.setToolTip(
            "Permanently resizes this sprite horizontally, e.g. for a\n"
            "prop drawn at the wrong scale relative to everything else\n"
            "it's layered with. 1.0 is the image's own native size.\n"
            "Independent of the reactive squash/stretch on the Behavior\n"
            "tab's Motion section, which multiplies on top of this."
        )
        self.scale_y.setToolTip(
            self.scale_x.toolTip().replace("horizontally", "vertically")
        )
        self.scale_lock.setToolTip(
            "While on (default), editing Scale X or Scale Y -- or\n"
            "dragging a corner handle on the Edit canvas -- updates/\n"
            "scales the other to match, so the sprite always scales\n"
            "proportionally. Turn off to stretch width and height\n"
            "independently. Independent of \"Lock Position\" below, which\n"
            "blocks Scale entirely rather than just linking its axes."
        )
        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("X"))
        scale_row.addWidget(self.scale_x)
        scale_row.addWidget(QLabel("Y"))
        scale_row.addWidget(self.scale_y)
        scale_row.addWidget(self.scale_lock)
        self.property_form.addRow("Scale", scale_row)

        # Lock Position (owner's request, 2026-09-19) -- a per-sprite,
        # saved-with-the-avatar lock on Position/Scale/Rotation entirely
        # (see Sprite.locked's own comment), distinct from Lock
        # proportions above (which only links Scale X/Y, and is a
        # session preference, not saved per sprite). Fires the exact
        # same code as the padlock icon next to this sprite in the
        # Sprites tab's Layer List (see _on_sprite_lock_toggled) and
        # stays in sync with it regardless of which one was clicked.
        self.lock_position_btn = QPushButton("🔒 Lock Position")
        self.lock_position_btn.setCheckable(True)
        self.lock_position_btn.setToolTip(
            "Prevents this sprite's Position, Rotation, and Scale from\n"
            "being changed -- by dragging on the Edit canvas (moving it,\n"
            "or its resize/rotate handles) or these fields directly.\n"
            "Everything else (Offset, Z-index, Parent, Frames/Anim speed,\n"
            "State Assignment including Variant...) stays editable. Same\n"
            "lock as the padlock icon next to this sprite in the Layer\n"
            "List -- either one toggles both."
        )
        self.lock_position_btn.toggled.connect(self._on_lock_position_btn_toggled)
        self.property_form.addRow(self.lock_position_btn)
        position_section.body_layout.addLayout(self.property_form)
        position_section.body_layout.addStretch(1)

        animation_section = CollapsibleSection("Animation", collapsed=True)
        self.animation_form = QFormLayout()
        self.frames = QSpinBox()
        self.frames.setRange(1, 60)
        self.anim_speed = self._spin(0.0, 60.0)
        self.frames.setToolTip(
            "Number of equal-width frames in this sprite's image, for a\n"
            "simple looping animation. 1 = a plain static image."
        )
        self.anim_speed.setToolTip(
            "Animation speed in frames per second. Only matters if Frames is greater than 1."
        )
        self.animation_form.addRow("Frames", self.frames)
        self.animation_form.addRow("Anim speed (fps)", self.anim_speed)
        animation_section.body_layout.addLayout(self.animation_form)
        animation_section.body_layout.addStretch(1)

        property_fields = (
            self.pos_x, self.pos_y, self.offset_x, self.offset_y, self.z_index, self.parent_combo,
            self.rotation, self.scale_x, self.scale_y, self.scale_lock, self.lock_position_btn,
            self.frames, self.anim_speed,
        )
        for form, fields in (
            (self.property_form, (self.pos_x, self.pos_y, self.offset_x, self.offset_y, self.z_index, self.parent_combo, self.rotation)),
            (self.animation_form, (self.frames, self.anim_speed)),
        ):
            for field_widget in fields:
                label = form.labelForField(field_widget)
                if label is not None:
                    label.setToolTip(field_widget.toolTip())
        for box in (
            self.pos_x, self.pos_y, self.offset_x, self.offset_y, self.z_index,
            self.rotation, self.anim_speed,
        ):
            box.valueChanged.connect(self._on_property_changed)
        # Scale X/Y get their own handlers, not the generic loop above --
        # each one may also need to update the *other* spinbox's value
        # when proportions are locked, which _on_property_changed alone
        # doesn't do.
        self.scale_x.valueChanged.connect(self._on_scale_x_changed)
        self.scale_y.valueChanged.connect(self._on_scale_y_changed)
        self.frames.valueChanged.connect(self._on_frames_changed)
        self.parent_combo.currentIndexChanged.connect(self._on_parent_changed)

        self._per_sprite_widgets.extend(property_fields)
        # Position/Rotation/Scale specifically -- disabled independently
        # of the rest of property_fields above when the selected sprite
        # is locked (see _update_locked_transform_fields_enabled), so
        # this list needs to be its own thing, not reused from
        # property_fields (which also has Offset/Z-index/Parent, which
        # stay editable even when locked).
        self._lockable_transform_widgets = (
            self.pos_x, self.pos_y, self.rotation, self.scale_x, self.scale_y,
        )

        tab = QWidget()
        outer = QVBoxLayout(tab)
        # Owner's request, 2026-09-19, alongside moving this tab to 2nd
        # position (right after Sprites): something naming which layer
        # Position & Hierarchy/Animation below are actually editing --
        # those sections only ever act on self._selected_id, but nothing
        # on this tab itself said so, easy to lose track of after
        # switching sprites on the Sprites tab and back. Upgraded to a
        # combo the next day (still owner's request) so it also *drives*
        # selection for quick switching, not just displaying it -- kept
        # in sync both ways through the single _select() choke point
        # (see _sync_behavior_layer_combo) and its own currentIndexChanged
        # (see _on_behavior_layer_combo_changed), guarding against the
        # obvious feedback loop with blockSignals the same way sprite_
        # list already does in _select.
        self.behavior_layer_combo = QComboBox()
        self.behavior_layer_combo.setToolTip(
            "Quick-switch which layer's Position & Hierarchy/Animation\n"
            "you're editing below -- the same selection as the Sprites\n"
            "tab's Layer List and the Edit canvas, just reachable from\n"
            "here too. Locked layers are shown dimmed."
        )
        self.behavior_layer_combo.currentIndexChanged.connect(self._on_behavior_layer_combo_changed)
        # QComboBox is already Fixed-height by default -- unlike the
        # QLabel this replaced, which needed an explicit QSizePolicy.
        # Fixed to stop it silently absorbing leftover vertical space and
        # pushing the splitter below it down the page (see git history
        # for that bug, caught by test_a_tab_that_starts_fully_collapsed_
        # from_persisted_config_stays_pegged_to_top).
        outer.addWidget(self.behavior_layer_combo)
        self._add_tab_splitter(outer, [motion_section, position_section, animation_section])
        return tab

    def _populate_behavior_layer_combo(self) -> None:
        self.behavior_layer_combo.blockSignals(True)
        self.behavior_layer_combo.clear()
        self.behavior_layer_combo.addItem("(no layer selected)", None)
        for sprite, _depth in self.rig.sprites_in_stacking_order():
            name = sprite.path.rsplit("/", 1)[-1]
            self.behavior_layer_combo.addItem(name, sprite.id)
        self._refresh_behavior_layer_combo_styles()
        self._sync_behavior_layer_combo(self.rig.by_id(self._selected_id) if self._selected_id is not None else None)
        self.behavior_layer_combo.blockSignals(False)

    def _refresh_behavior_layer_combo_styles(self) -> None:
        # Owner's request, 2026-09-20: "show locked layers as slightly
        # greyed out" -- GREY_500 is this theme's existing disabled/
        # placeholder color (theme.py), reused here rather than
        # inventing a new one. Re-applied whenever lock state changes
        # (see _on_sprite_lock_toggled), not just on a full repopulate.
        dim = QColor(theme.GREY_500)
        for i in range(self.behavior_layer_combo.count()):
            sprite_id = self.behavior_layer_combo.itemData(i)
            sprite = self.rig.by_id(sprite_id) if sprite_id is not None else None
            self.behavior_layer_combo.setItemData(
                i, dim if sprite is not None and sprite.locked else None, Qt.ItemDataRole.ForegroundRole
            )

    def _sync_behavior_layer_combo(self, sprite: Sprite | None) -> None:
        # The read half of the two-way sync -- called from _select()
        # (the single choke point every selection change already goes
        # through, whether from the Sprites tab's Layer List or clicking
        # a sprite directly on the Edit canvas), so this combo always
        # reflects "whatever's actually selected" without needing to
        # duplicate that logic. blockSignals guards against the obvious
        # feedback loop back into _on_behavior_layer_combo_changed.
        target_id = sprite.id if sprite is not None else None
        self.behavior_layer_combo.blockSignals(True)
        index = self.behavior_layer_combo.findData(target_id)
        self.behavior_layer_combo.setCurrentIndex(max(index, 0))
        self.behavior_layer_combo.blockSignals(False)

    def _on_behavior_layer_combo_changed(self, index: int) -> None:
        # The write half -- picking a layer here drives selection exactly
        # like clicking it in the Layer List or on the canvas would,
        # through the same _select() choke point (which then calls
        # _sync_behavior_layer_combo right back, a no-op here since
        # they already agree).
        sprite_id = self.behavior_layer_combo.itemData(index)
        self._select(sprite_id)

    def _build_audio_tab(self) -> QWidget:
        envelope_section = CollapsibleSection("Envelope")
        envelope_form = QFormLayout()
        self._add_double(
            envelope_form, "Sensitivity", 0.05, 20.0, 0.05, 2,
            self.config.audio, "gain",
            "Multiplies the raw mic/file volume before anything below\n"
            "sees it -- an in-app control independent of your OS's mic\n"
            "volume or a mic's own physical gain knob, for when those\n"
            "don't line up with what this app is actually measuring.\n"
            "1.0 = no change. Raise it if the level meter barely moves;\n"
            "lower it if it's pinned at the top even when you're quiet.",
        )
        self.noise_gate_field = self._add_double(
            envelope_form, "Noise gate", 0.0, 0.5, 0.001, 4,
            self.config.audio, "noise_gate",
            "RMS volume below this is treated as silence -- filters out\n"
            "mic hiss and room noise so it never registers as speech.",
        )
        self.mild_open = self._add_double(
            envelope_form, "Mild: open above", 0.0, 1.0, 0.001, 4,
            self.config.audio, "mild_open",
            "Volume must rise above this to open the mouth to \"mild\".",
        )
        self.mild_close = self._add_double(
            envelope_form, "Mild: close below", 0.0, 1.0, 0.001, 4,
            self.config.audio, "mild_close",
            "Volume must fall below this to close the mouth again.\n"
            "Kept lower than \"open above\" on purpose (hysteresis) so it\n"
            "doesn't flicker open/closed right at one boundary value.",
        )
        self.wide_open = self._add_double(
            envelope_form, "Wide: open above", 0.0, 1.0, 0.001, 4,
            self.config.audio, "wide_open",
            "Volume must rise above this for the \"wide\" (loud) mouth shape.",
        )
        self.wide_close = self._add_double(
            envelope_form, "Wide: close below", 0.0, 1.0, 0.001, 4,
            self.config.audio, "wide_close",
            "Volume must fall below this to drop back from \"wide\" to \"mild\".\n"
            "Same hysteresis idea as \"Mild: close below\".",
        )
        self._add_double(
            envelope_form, "Attack (ms)", 0.0, 500.0, 1.0, 0,
            self.config.audio, "attack_ms",
            "How fast the mouth reacts when you start talking. Lower = snappier.",
        )
        self._add_double(
            envelope_form, "Hold (ms)", 0.0, 1000.0, 5.0, 0,
            self.config.audio, "hold_ms",
            "How long the mouth stays open after volume drops, before it\n"
            "starts closing. This is what keeps continuous speech from\n"
            "flickering shut in the gaps between syllables.",
        )
        self._add_double(
            envelope_form, "Release (ms)", 0.0, 2000.0, 5.0, 0,
            self.config.audio, "release_ms",
            "How fast the mouth closes once the hold period ends.",
        )
        envelope_section.body_layout.addLayout(envelope_form)

        # Quick-win enhancement E5 (bug audit addendum 2026-09-23):
        # samples 3s of ambient noise and sets Noise gate to 1.5x the
        # loudest sample measured -- a quick starting point, not a
        # replacement for watching the level meter while talking.
        calibrate_row = QHBoxLayout()
        self._calibrate_gate_btn = QPushButton("Calibrate noise gate (3s of quiet)")
        self._calibrate_gate_btn.setToolTip(
            "Stay quiet for 3 seconds while this samples the current\n"
            "source's own ambient noise floor, then sets Noise gate to\n"
            "about 1.5x the loudest ambient sample measured. A quick\n"
            "starting point -- fine-tune by ear afterward if needed."
        )
        self._calibrate_gate_btn.clicked.connect(self._on_calibrate_noise_gate_clicked)
        calibrate_row.addWidget(self._calibrate_gate_btn)
        calibrate_row.addStretch(1)
        envelope_section.body_layout.addLayout(calibrate_row)
        if self.audio_manager is not None:
            self.audio_manager.calibration_started.connect(self._on_calibration_started)
            self.audio_manager.calibration_finished.connect(self._on_calibration_finished)

        # Warning, not a live clamp -- owner's request, 2026-09-23 (bug
        # audit finding #20, "no threshold ordering checks"): nothing
        # enforces mild_close <= mild_open <= wide_open or
        # wide_close <= wide_open. A crossed pair doesn't crash -- it
        # just makes a band unreachable or makes it flap -- so this
        # surfaces the problem instead of silently fighting the values
        # the owner just typed. Hidden whenever the ordering holds.
        self._threshold_warning_label = QLabel()
        self._threshold_warning_label.setWordWrap(True)
        self._threshold_warning_label.setStyleSheet(
            f"color: {theme.DANGER}; font-weight: 600; background: transparent;"
        )
        self._threshold_warning_label.setVisible(False)
        envelope_section.body_layout.addWidget(self._threshold_warning_label)
        envelope_section.body_layout.addStretch(1)

        for box in (self.mild_open, self.mild_close, self.wide_open, self.wide_close):
            box.valueChanged.connect(self._refresh_threshold_warning)
        self._refresh_threshold_warning()

        obs_section = CollapsibleSection("OBS mute awareness")
        obs_form = QFormLayout()
        self.obs_enabled = QCheckBox("Force mouth closed while muted in OBS")
        self.obs_enabled.setChecked(self.config.obs.enabled)
        self.obs_enabled.setToolTip(
            "Reads the mute state of the OBS input named below, live, over\n"
            "obs-websocket -- closes the mouth entirely while it's muted,\n"
            "regardless of what the mic/file is actually saying. Off until\n"
            "you fill in the fields below and turn it on -- otherwise this\n"
            "would just retry a connection with nothing configured yet."
        )
        self.obs_enabled.toggled.connect(self._on_obs_enabled_toggled)
        obs_form.addRow(self.obs_enabled)

        self.obs_host = QLineEdit(self.config.obs.host)
        self.obs_host.setToolTip("Where OBS's obs-websocket server is listening. \"localhost\" if it's this machine.")
        self.obs_host.editingFinished.connect(self._on_obs_connection_field_changed)
        obs_form.addRow("Host", self.obs_host)
        self._set_label_tooltip(obs_form, self.obs_host, self.obs_host.toolTip())

        self.obs_port = ScrollSafeSpinBox()
        self.obs_port.setRange(1, 65535)
        self.obs_port.setValue(self.config.obs.port)
        obs_port_tooltip = "obs-websocket's port -- 4455 is OBS's own default."
        self.obs_port.setToolTip(obs_port_tooltip)
        # editingFinished, not valueChanged -- bug audit 2026-09-23,
        # #19: valueChanged fires on every single step/keystroke, and
        # _on_obs_connection_field_changed calls ObsLinkManager.restart()
        # every time it runs, which stop()s the watcher and joins its
        # thread for up to 2s *on the Qt thread* -- typing "4456" froze
        # the UI four times over. The other three OBS fields already use
        # editingFinished for exactly this reason; Port just missed it.
        self.obs_port.editingFinished.connect(self._on_obs_connection_field_changed)
        self._add_row_with_reset_and_lock(
            obs_form, "Port", self.obs_port,
            self._default_for(self.config.obs, "port"), obs_port_tooltip,
        )

        self.obs_password = QLineEdit(self.config.obs.password)
        self.obs_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.obs_password.setToolTip(
            "OBS Settings -> WebSocket Server Settings -> Show Connect Info\n"
            "has this. Stored in this app's own settings.json, same as\n"
            "everything else here -- never read from OBS's own config."
        )
        self.obs_password.editingFinished.connect(self._on_obs_connection_field_changed)
        obs_form.addRow("Password", self.obs_password)
        self._set_label_tooltip(obs_form, self.obs_password, self.obs_password.toolTip())

        self.obs_input_name = QLineEdit(self.config.obs.input_name)
        self.obs_input_name.setToolTip(
            "Must match an OBS input's name exactly (case-sensitive) --\n"
            "e.g. \"Mic/Aux\". Check OBS's own Sources/Mixer list."
        )
        self.obs_input_name.editingFinished.connect(self._on_obs_connection_field_changed)
        obs_form.addRow("Input name", self.obs_input_name)
        self._set_label_tooltip(obs_form, self.obs_input_name, self.obs_input_name.toolTip())

        self.obs_status_label = QLabel(self._obs_status_text(connected=False))
        self.obs_status_label.setToolTip("Live connection/mute status -- updates automatically, nothing to click.")
        obs_form.addRow(self.obs_status_label)

        if self.obs_link_manager is not None:
            self.obs_link_manager.connection_changed.connect(
                self._on_obs_connection_changed, Qt.ConnectionType.QueuedConnection
            )
            self.obs_link_manager.mute_changed.connect(
                self._on_obs_mute_changed, Qt.ConnectionType.QueuedConnection
            )
        obs_section.body_layout.addLayout(obs_form)
        obs_section.body_layout.addStretch(1)

        tab = QWidget()
        outer = QVBoxLayout(tab)
        self._add_tab_splitter(outer, [envelope_section, obs_section])
        return tab

    def _build_application_tab(self) -> QWidget:
        # One section, not two -- Zoom moved out to Behavior's Position &
        # Hierarchy (see there) and Grid spacing is a single row, so
        # "Display" and "Canvas" as separate collapsible headers left
        # each holding almost nothing (owner's report, 2026-09-19: "few
        # options, only need one content area").
        display_section = CollapsibleSection("Display & Canvas")
        display_form = QFormLayout()
        display_form.setContentsMargins(0, 0, 0, 0)
        self.background = QComboBox()
        for mode in BACKGROUND_COLORS:
            self.background.addItem(_BACKGROUND_LABELS.get(mode, mode), mode)
        # Image/video, owner's request, 2026-09-17 -- not in BACKGROUND_COLORS
        # (that dict is solid-brush colors only, see render.py), added as
        # their own combo entries here instead.
        self.background.addItem(_BACKGROUND_LABELS["image"], "image")
        self.background.addItem(_BACKGROUND_LABELS["video"], "video")
        self.background.setToolTip(
            "What's behind the avatar. Transparent lets whatever is beneath\n"
            "this source in your OBS scene show through -- that's the normal\n"
            "setup. Pick a solid color instead if you're using OBS's Chroma\n"
            "Key filter on this source, or just want a plain backdrop while\n"
            "previewing outside OBS. Image/Video show a file of your own\n"
            "choosing (Browse… appears below once selected) -- video loops\n"
            "continuously and is always silent, regardless of its own audio\n"
            "track."
        )
        index = self.background.findData(self.config.window.background)
        self.background.setCurrentIndex(max(index, 0))
        self.background.currentIndexChanged.connect(self._on_background_changed)
        display_form.addRow("Background", self.background)
        self._set_label_tooltip(display_form, self.background, self.background.toolTip())

        self._background_browse_btn = QPushButton("Browse…")
        self._background_browse_btn.setToolTip(
            "Choose the image or video file to show behind the avatar."
        )
        self._background_browse_btn.clicked.connect(self._on_browse_background_file)
        display_form.addRow("", self._background_browse_btn)

        self.background_file_label = QLabel()
        display_form.addRow(self.background_file_label)
        self._update_background_controls_visible()
        display_section.body_layout.addLayout(display_form)

        canvas_form = QFormLayout()
        canvas_form.setContentsMargins(0, 0, 0, 0)
        self.grid_spacing = ScrollSafeSpinBox()
        self.grid_spacing.setRange(10, 1000)
        grid_tooltip = (
            "Pixel spacing of the Edit canvas's grid overlay (toggled with\n"
            "the Guide button below). Purely a drawing aid -- never affects\n"
            "the avatar itself."
        )
        self.grid_spacing.setValue(self.config.control_panel.grid_spacing_px)
        self.grid_spacing.setToolTip(grid_tooltip)
        self.grid_spacing.valueChanged.connect(self._on_grid_spacing_changed)
        self._add_row_with_reset_and_lock(
            canvas_form, "Grid spacing (px)", self.grid_spacing,
            self._default_for(self.config.control_panel, "grid_spacing_px"), grid_tooltip,
        )
        display_section.body_layout.addLayout(canvas_form)
        # See position_section's own comment (Behavior tab) for the real
        # cause and why addStretch(1), not the margin fix above alone,
        # is what actually closes the gap: confirmed from a follow-up
        # screenshot showing the exact same "big gap between two stacked
        # forms" symptom here too, once this became this tab's only
        # section and so gets handed all its leftover splitter height.
        display_section.body_layout.addStretch(1)

        tab = QWidget()
        outer = QVBoxLayout(tab)
        self._add_tab_splitter(outer, [display_section])
        return tab

    def _build_costumes_tab(self) -> QWidget:
        # Its own tab, immediately right of Sprites -- owner's request,
        # 2026-09-17, after seeing this squeezed into one collapsed
        # Application-tab section: "let's put costumes & expressions each
        # in their own tabs immediately to the right of the sprites tab."
        #
        # A QListWidget, not a QScrollArea over a plain QVBoxLayout (tried
        # first) -- the QScrollArea version showed real, hard-to-pin-down
        # rendering corruption in the owner's own real, themed app
        # (patches of the wrong background color, misaligned/overlapping
        # rows) that a from-scratch isolated repro of a themed QScrollArea
        # alone did *not* reproduce, meaning it was something about this
        # exact nested combination, not a generic Qt gotcha with a known
        # one-line fix to reach for with confidence. Same technique the
        # Sprites tab's own Layer List already uses -- proven correct in
        # this exact app/theme/tab context.
        #
        # One QListWidgetItem *per swap row*, not one item per slot
        # containing a variable-length inner layout (tried second): a
        # QListWidgetItem's size hint does not reliably refresh when a
        # child is added to its embedded widget after the fact --
        # confirmed empirically (stale sizeHint even after
        # updateGeometry()/layout().activate()), not assumed. A header
        # item, an item per existing row, and a trailing "+ Add" item are
        # each a stable, never-resized item instead -- adding/removing a
        # row means adding/removing a whole list item (a plain, native
        # QListWidget operation), never resizing one in place.
        section = CollapsibleSection("Costumes — press the number to switch", wants_extra_space=True)
        self.costume_list = QListWidget()
        self.costume_list.setToolTip("One row per costume slot -- see the Hotkeys Help tab for the full explanation.")
        section.body_layout.addWidget(self.costume_list)

        self._hotkey_edits: list[QKeySequenceEdit] = []
        for slot, key_text in enumerate(self.config.hotkeys.costume_keys[:NUM_COSTUMES]):
            header = QWidget()
            header_row = QHBoxLayout(header)
            header_row.addWidget(QLabel(f"Costume {slot + 1}"))
            edit = QKeySequenceEdit()
            edit.setMaximumSequenceLength(1)
            edit.setKeySequence(QKeySequence(key_text))
            edit.setToolTip(
                "Press a key to switch to this costume slot -- works while\n"
                "either the Render Window or this Control Panel has\n"
                "keyboard focus (skipped here while a text/combo/key-capture\n"
                "field is itself focused, so it never steals your typing).\n"
                "Escape can't be bound here -- it always quits the app, no\n"
                "matter what. Avoid reusing the same key on two slots --\n"
                "only the first matching slot fires. Modifiers (Ctrl/Alt/\n"
                "Shift) aren't distinguished from the plain key."
            )
            edit.keySequenceChanged.connect(self._hotkey_setter(slot, edit))
            self._hotkey_edits.append(edit)
            header_row.addWidget(edit, stretch=1)
            self._add_list_item_widget(self.costume_list, header)

            add_btn = QPushButton("+ Add swap")
            add_btn.setToolTip(
                "Pick two sprites: the top one starts hidden and this\n"
                "costume shows it; the bottom one starts shown and this\n"
                "costume hides it. Add more than one pair to swap several\n"
                "sprites at once (e.g. both halves of a hoodie for a vest)."
            )
            add_btn.clicked.connect(lambda _checked=False, s=slot: self._add_costume_row(s))
            self._costume_add_button_items[slot] = self._add_list_item_widget(self.costume_list, add_btn)

        tab = QWidget()
        outer = QVBoxLayout(tab)
        self._add_tab_splitter(outer, [section])
        return tab

    def _build_expressions_tab(self) -> QWidget:
        section = CollapsibleSection("Expressions — Shift + number toggles on/off", wants_extra_space=True)
        self.expression_hotkey_list = QListWidget()
        self.expression_hotkey_list.setToolTip("One row per hotkey slot -- see the Hotkeys Help tab for the full explanation.")
        section.body_layout.addWidget(self.expression_hotkey_list)

        for slot in range(NUM_COSTUMES):
            header = QLabel(f"Shift+{EXPRESSION_HOTKEY_LABELS[slot]}")
            self._add_list_item_widget(self.expression_hotkey_list, header)

            add_btn = QPushButton("+ Add expression")
            add_btn.setToolTip(
                "Pick an Expression (tag a sprite Manually driven with a\n"
                "Group/State on the Behavior tab first if none exist yet).\n"
                "Add more than one to force several groups at once (e.g. a\n"
                "mouth shape and an eye shape together for one combined\n"
                "expression)."
            )
            add_btn.clicked.connect(lambda _checked=False, s=slot: self._add_expression_hotkey_row(s))
            self._expression_add_button_items[slot] = self._add_list_item_widget(self.expression_hotkey_list, add_btn)

        tab = QWidget()
        outer = QVBoxLayout(tab)
        self._add_tab_splitter(outer, [section])
        return tab

    # =====================================================================
    # Construction: persistent bottom bar
    # =====================================================================

    def _build_bottom_bar(self, root: QVBoxLayout) -> None:
        # Owner's request, 2026-09-17: audio source controls live in the
        # always-visible global area too, on their own bar, with the
        # chosen file's path shown (middle-elided) just below it.
        self.source_row = QHBoxLayout()
        self.audio_source = QComboBox()
        self.audio_source.addItem("Microphone", "microphone")
        self.audio_source.addItem("Desktop audio (what's playing)", "desktop")
        self.audio_source.addItem("File (play a recording instead)", "file")
        self.audio_source.setToolTip(
            "What drives the mouth: a live microphone (normal setup),\n"
            "desktop audio (whatever's actually playing out your\n"
            "speakers -- a game, a video, music), or a local audio/video\n"
            "file played back through this app instead -- for driving\n"
            "the avatar from a pre-recorded isolated track while a\n"
            "*different* recording is what actually gets captured (e.g.\n"
            "a combined track played separately through an OBS Media\n"
            "Source). See the Help window for the full workflow."
        )
        index = self.audio_source.findData(self.config.audio.source)
        self.audio_source.setCurrentIndex(max(index, 0))
        self.audio_source.currentIndexChanged.connect(self._on_audio_source_changed)
        self.source_row.addWidget(self.audio_source, stretch=1)

        # Left of Play, not right -- owner's request, 2026-09-20 (it
        # first landed to Play's right the day before). FilePlayback
        # (audio.py) is a one-shot ffmpeg pipe decode with no seek
        # support -- there's no such thing as "resume from where it
        # was," only "start over from 0:00" -- so this restarts playback
        # via the exact same AudioManager.play_file() a Play click uses,
        # which already stops whatever's currently playing first.
        #
        # Same-day reversal, still 2026-09-20: only does that while a
        # file is actually mid-playback. It used to also fire while
        # stopped -- restarting playback the owner hadn't asked for --
        # but a stopped file is already sitting at 0:00 for the next
        # Play (play_file() always decodes from the start), so there was
        # never really anything to "rewind" in that state; a no-op is
        # the correct rewind, not an unexpected auto-play.
        self._rewind_file_btn = QPushButton("Rewind")
        self._rewind_file_btn.setToolTip(
            "While playing, restarts the chosen file from the beginning --\n"
            "playback can't seek mid-file, so this is the only way back to\n"
            "0:00 short of Stop then Play again. Does nothing while\n"
            "stopped, since a stopped file already starts over from 0:00\n"
            "on the next Play."
        )
        self._rewind_file_btn.clicked.connect(self._on_rewind_file_clicked)
        self.source_row.addWidget(self._rewind_file_btn)

        self.play_file_btn = QPushButton("Play")
        self.play_file_btn.setToolTip(
            "Start or stop playing the chosen file to drive the mouth.\n"
            "Silent by design -- it never plays out loud, only extracts\n"
            "the volume envelope from it in real time."
        )
        self.play_file_btn.clicked.connect(self._on_play_file_clicked)
        self.source_row.addWidget(self.play_file_btn)

        self._browse_file_btn = QPushButton("Browse…")
        self._browse_file_btn.setToolTip(
            "Choose an audio or video file. Its audio track drives the\n"
            "mouth once you click Play -- this app never plays its sound\n"
            "out loud, only extracts its volume, so play the actual\n"
            "recording you want captured separately (e.g. in OBS)."
        )
        self._browse_file_btn.clicked.connect(self._on_browse_audio_file)
        self.source_row.addWidget(self._browse_file_btn)

        self.record_loop_btn = QPushButton("Record 10s & loop")
        self.record_loop_btn.setToolTip(
            "Captures 10 seconds of whatever's currently driving the\n"
            "mouth (mic or file), then loops it continuously so you can\n"
            "tune the Audio tab's thresholds without talking the whole\n"
            "time. Click again (or switch Source) to stop the loop and go\n"
            "back to whatever was active before."
        )
        self.record_loop_btn.clicked.connect(self._on_record_loop_clicked)
        self.source_row.addWidget(self.record_loop_btn)
        root.addLayout(self.source_row)

        # Own row, not source_row -- owner's request, 2026-09-23, for
        # Desktop Audio (added alongside this dropdown). source_row is
        # already the app's single biggest driver of this pane's minimum
        # width (measured 2026-09-17, the reason the button row was ever
        # split across two rows in the first place -- see actions_row_1/
        # actions_row_2 below); adding this here instead of squeezing it
        # into source_row is exactly that same lesson applied again
        # (confirmed: cramming it into source_row broke the splitter-
        # ratio tests by pushing the pane's minimum width past what they
        # assume).
        self.device_row = QHBoxLayout()
        self.device_row.addWidget(QLabel("Device:"))
        # Backs both Microphone and Desktop Audio, which share the exact
        # same audio.Microphone capture path and the exact same device
        # list (this owner's PipeWire/JACK setup doesn't distinguish
        # "real mic" from "sink with a monitor tap" by name -- both just
        # show up as capture-capable devices, see config.py's
        # desktop_device comment), so one dropdown covers both; only
        # *which* config field it writes to changes, handled by
        # AudioManager.set_device via the currently selected source.
        # "System default" (data=None) reproduces the zero-config
        # behavior this app always had before this dropdown existed --
        # audio.resolve_input_device(None) picks the first usable
        # device, same as an empty hint always has.
        self.audio_device = QComboBox()
        self.audio_device.setToolTip(
            "Which capture device feeds the mouth. \"System default\"\n"
            "picks automatically (this app's original zero-config\n"
            "behavior). Remembered separately for Microphone and Desktop\n"
            "Audio -- switching between them keeps each one's own choice.\n"
            "Grayed out on File, which doesn't use a capture device at all."
        )
        self.audio_device.currentIndexChanged.connect(self._on_audio_device_changed)
        self.device_row.addWidget(self.audio_device, stretch=1)

        self._audio_device_refresh_btn = QPushButton("Refresh")
        self._audio_device_refresh_btn.setToolTip(
            "Re-scan for capture devices -- e.g. after plugging in\n"
            "headphones or a new mic, which this app has no way to\n"
            "detect on its own."
        )
        self._audio_device_refresh_btn.clicked.connect(self._on_refresh_audio_devices_clicked)
        self.device_row.addWidget(self._audio_device_refresh_btn)
        root.addLayout(self.device_row)
        self._populate_audio_devices()

        # "Now capturing: <device>" -- quick-win enhancement E2 (bug audit
        # addendum 2026-09-23). The Device dropdown above shows what's
        # *asked for*; this shows what Microphone/Desktop Audio actually
        # opened, from AudioManager.device_resolved -- would have made
        # D1-D3 (switching source silently kept the old device, or a
        # missing device silently fell back to the mic) obvious at a
        # glance instead of needing an audit to catch. Empty/hidden while
        # nothing is actually capturing (File source, or before the first
        # device resolves).
        self._now_capturing_label = QLabel("")
        self._now_capturing_label.setToolTip(
            "Which device is actually open right now, not just what the\n"
            "Device dropdown above asks for -- if this doesn't match what\n"
            "you expected, double-check that dropdown's selection."
        )
        self._now_capturing_label.setVisible(False)
        root.addWidget(self._now_capturing_label)

        self.audio_file_label = QLabel(self._elided_file_label())
        self.audio_file_label.setToolTip(self.config.audio.file_path or "No file chosen yet -- click Browse….")
        self.audio_file_label.setVisible(bool(self.config.audio.file_path))
        root.addWidget(self.audio_file_label)

        self._recording_countdown_timer = QTimer(self)
        self._recording_countdown_timer.timeout.connect(self._on_recording_tick)
        self._recording_deadline: float = 0.0
        if self.audio_manager is not None:
            self.audio_manager.file_playback_stopped.connect(
                self._on_file_playback_stopped, Qt.ConnectionType.QueuedConnection
            )
            self.audio_manager.recording_started.connect(self._on_recording_started)
            self.audio_manager.recording_finished.connect(self._on_recording_finished)
            # QueuedConnection: fires from Microphone's own background
            # thread -- same reasoning as every other audio_manager
            # connection here (see AudioManager's own docstring).
            self.audio_manager.device_resolved.connect(
                self._on_device_resolved, Qt.ConnectionType.QueuedConnection
            )
        self._update_source_controls_enabled()
        self._update_play_button_text()
        self._update_record_loop_button_text()

        # Split across two rows, not one -- an 11-button single row was
        # the single biggest driver of this pane's minimum width
        # (measured, 2026-09-17: 1021px), which is exactly what forced
        # the canvas down to a sliver regardless of the splitter's
        # requested ratio. Two rows roughly halves that. Down to 7
        # buttons across both rows as of 2026-09-19 (Undo/Redo/Guide/
        # Ghost moved up into the mode row above), but still split the
        # same way rather than second-guessing a measured decision.
        actions_row_1 = QHBoxLayout()
        actions_row_2 = QHBoxLayout()

        self._undo_btn = QPushButton("Undo")
        self._redo_btn = QPushButton("Redo")
        self._undo_btn.setToolTip("Undo the last change (Ctrl+Z).")
        self._redo_btn.setToolTip("Redo the last undone change (Ctrl+Shift+Z).")
        self._undo_btn.clicked.connect(self.undo)
        self._redo_btn.clicked.connect(self.redo)
        # In the Live Preview/Edit Sprites row, not here -- owner's
        # request, 2026-09-19 -- and only visible in Edit mode (see
        # _on_canvas_mode_toggled), since Live Preview has nothing
        # editable to undo/redo from. self.mode_row was built earlier, in
        # _build_canvas_area, specifically so these buttons (which need
        # self.undo/self.redo to already exist) could still land there.
        self.mode_row.addWidget(self._undo_btn)
        self.mode_row.addWidget(self._redo_btn)
        # The trailing stretch, added last so it comes after every button
        # in this row (Guide/Ghost are built earlier, in _build_canvas_
        # area) -- owner's request, 2026-09-19: keep the whole row as one
        # contiguous left-aligned group, not split into two clusters by a
        # stretch in the middle.
        self.mode_row.addStretch(1)
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, activated=self.redo)

        # Expression hotkeys, owner's request, 2026-09-17: "shift+<number>"
        # -- fixed, not user-remappable (unlike costume_keys), scoped to
        # this window (fires while the Control Panel has focus, not the
        # Render Window) since that's already where Expressions are
        # configured and toggled today. Guarded against a focused text/
        # combo/key-capture field inside _trigger_expression_hotkey.
        for slot, label in enumerate(EXPRESSION_HOTKEY_LABELS):
            QShortcut(
                QKeySequence(f"Shift+{label}"), self,
                activated=lambda s=slot: self._trigger_expression_hotkey(s),
            )

        # Costume hotkeys, added here 2026-09-19 -- previously these only
        # worked while the Render Window had focus, while Expression
        # hotkeys (above) only worked here, so testing both together
        # always left one set looking broken depending on which window
        # was focused (owner's report: "costumes/expressions hotkeys
        # don't seem to be working properly"). render.py's own
        # keyPressEvent handling is untouched -- this is purely additive,
        # a second place the same keys now also work. Unlike Expression
        # hotkeys these are remappable, so each slot's QShortcut is kept
        # around in self._costume_shortcuts and updated live by
        # _hotkey_setter on a rebind, the same way render.py's own
        # keyPressEvent resolves config.hotkeys.costume_keys fresh.
        self._costume_shortcuts: list[QShortcut] = [
            QShortcut(
                QKeySequence(key_text), self,
                activated=lambda s=slot: self._trigger_costume_hotkey(s),
            )
            for slot, key_text in enumerate(self.config.hotkeys.costume_keys[:NUM_COSTUMES])
        ]

        help_btn = QPushButton("Help")
        help_btn.setToolTip("Open the full reference: hotkeys, sprite fields, file format, workflow.")
        help_btn.clicked.connect(self._on_help)
        actions_row_1.addWidget(help_btn)

        save_btn = QPushButton("Save")
        save_btn.setToolTip("Save the avatar to the file it was last saved to/loaded from.")
        save_btn.clicked.connect(self._on_save)
        actions_row_1.addWidget(save_btn)

        save_as_btn = QPushButton("Save As…")
        save_as_btn.setToolTip("Save the avatar to a new file, choosing the location.")
        save_as_btn.clicked.connect(self._on_save_as)
        actions_row_1.addWidget(save_as_btn)

        load_btn = QPushButton("Load…")
        load_btn.setToolTip(
            "Load a different avatar from a file, replacing everything\n"
            "currently loaded (position, undo history, and all)."
        )
        load_btn.clicked.connect(self._on_load)
        actions_row_1.addWidget(load_btn)
        actions_row_1.addStretch(1)

        export_snapshot_btn = QPushButton("Export Snapshot…")
        export_snapshot_btn.setToolTip(
            "Renders the currently active costume at rest (mouth closed,\n"
            "eyes open, no motion) to a PNG at whatever resolution you\n"
            "choose -- for thumbnails, channel art, etc."
        )
        export_snapshot_btn.clicked.connect(self._on_export_snapshot)
        actions_row_2.addWidget(export_snapshot_btn)

        check_issues_btn = QPushButton("Check for Issues…")
        check_issues_btn.setToolTip(
            "Scans Talk state/Blink state/Group name assignments for likely\n"
            "mistakes -- an incomplete trio (e.g. no sprite gated \"Only when\n"
            "quiet\"), two sprites that would fight instead of alternating,\n"
            "a Manually driven sprite that can never show, or inconsistent\n"
            "labeling. Heuristic, not a hard validator -- a clean result\n"
            "doesn't guarantee the rig is correct, just that nothing obvious\n"
            "looks wrong."
        )
        check_issues_btn.clicked.connect(self._on_check_for_issues)
        actions_row_2.addWidget(check_issues_btn)

        # Quick-win enhancement E12 (bug audit addendum 2026-09-23): a
        # manual "mouth closed" toggle, independent of OBS mute, for a
        # cough or an aside without touching OBS at all. Checkable, not a
        # momentary press-and-hold -- a stream aside can run longer than
        # a single click-and-release, and a toggle is simpler to reason
        # about mid-performance than "is it currently held."
        self._mute_mouth_btn = QPushButton("Mute mouth")
        self._mute_mouth_btn.setCheckable(True)
        self._mute_mouth_btn.setToolTip(
            "Forces the mouth closed, independent of OBS mute -- for a\n"
            "cough or an aside without touching OBS. Click again to let\n"
            "the mouth follow the mic/audio source again."
        )
        self._mute_mouth_btn.toggled.connect(self._on_mute_mouth_toggled)
        actions_row_2.addWidget(self._mute_mouth_btn)

        actions_row_2.addStretch(1)

        quit_btn = QPushButton("Quit")
        quit_btn.setToolTip(
            "Quit Unicorn Cloak entirely (same as Escape on the Render\n"
            "Window) -- always confirms, and warns first if the avatar has\n"
            "unsaved changes."
        )
        quit_btn.clicked.connect(self._on_quit_clicked)
        actions_row_2.addWidget(quit_btn)

        root.addLayout(actions_row_1)
        root.addLayout(actions_row_2)

    # =====================================================================
    # Field-builder helpers (Reset/Lock, tooltips)
    # =====================================================================

    @staticmethod
    def _spin(lo: float, hi: float, decimals: int = 2) -> QDoubleSpinBox:
        box = ScrollSafeDoubleSpinBox()
        box.setRange(lo, hi)
        box.setDecimals(decimals)
        return box

    def _add_double(
        self, form, label, lo, hi, step, decimals, target, field_name, tooltip: str
    ) -> QDoubleSpinBox:
        box = ScrollSafeDoubleSpinBox()
        box.setRange(lo, hi)
        box.setSingleStep(step)
        box.setDecimals(decimals)
        box.setValue(getattr(target, field_name))
        box.setToolTip(tooltip)
        box.valueChanged.connect(self._setter(target, field_name))
        self._add_row_with_reset_and_lock(
            form, label, box, self._default_for(target, field_name), tooltip
        )
        return box

    def _add_int(self, form, label, lo, hi, target, field_name, tooltip: str) -> None:
        box = ScrollSafeSpinBox()
        box.setRange(lo, hi)
        box.setValue(getattr(target, field_name))
        box.setToolTip(tooltip)
        box.valueChanged.connect(self._setter(target, field_name))
        self._add_row_with_reset_and_lock(
            form, label, box, self._default_for(target, field_name), tooltip
        )

    @staticmethod
    def _default_for(target, field_name: str):
        for f in dataclasses.fields(target):
            if f.name == field_name:
                return f.default
        raise ValueError(f"{target!r} has no field {field_name!r}")

    def _add_row_with_reset_and_lock(
        self, form: QFormLayout, label: str, box, default_value, tooltip: str
    ) -> None:
        row = QHBoxLayout()
        row.addWidget(box, stretch=1)

        reset_btn = QPushButton("Reset")
        reset_btn.setToolTip(f"Reset to the default value ({default_value}).")
        reset_btn.clicked.connect(lambda: box.setValue(default_value))
        row.addWidget(reset_btn)

        lock_btn = QPushButton("Lock")
        lock_btn.setMinimumWidth(lock_btn.fontMetrics().horizontalAdvance("Locked") + 24)
        lock_btn.setCheckable(True)
        lock_btn.setToolTip(
            "Lock this field so it can't change by accident -- scrolling,\n"
            "arrow keys, the spin buttons, and typing all do nothing while\n"
            "locked. Click again to unlock."
        )

        def on_lock_toggled(checked: bool) -> None:
            box.set_locked(checked)
            reset_btn.setEnabled(not checked)
            lock_btn.setText("Locked" if checked else "Lock")

        lock_btn.toggled.connect(on_lock_toggled)
        row.addWidget(lock_btn)

        form.addRow(label, row)
        self._set_label_tooltip(form, row, tooltip)
        self._reset_buttons[box] = reset_btn
        self._lock_buttons[box] = lock_btn

    @staticmethod
    def _set_label_tooltip(form: QFormLayout, field_widget, tooltip: str) -> None:
        label = form.labelForField(field_widget)
        if label is not None:
            label.setToolTip(tooltip)

    def _setter(self, target, field_name: str) -> Callable[[float], None]:
        def on_change(value: float) -> None:
            setattr(target, field_name, value)
            self._save_config()

        return on_change

    def _hotkey_setter(self, slot: int, edit: QKeySequenceEdit) -> Callable[[QKeySequence], None]:
        def on_change(sequence: QKeySequence) -> None:
            if sequence.count() == 1 and sequence[0].key() == Qt.Key.Key_Escape:
                edit.blockSignals(True)
                edit.setKeySequence(QKeySequence(self.config.hotkeys.costume_keys[slot]))
                edit.blockSignals(False)
                return
            keys = list(self.config.hotkeys.costume_keys)
            keys[slot] = sequence.toString()
            self.config.hotkeys.costume_keys = tuple(keys)
            # Keeps this slot's Control Panel QShortcut (see __init__)
            # in sync -- render.py needs no equivalent update since it
            # resolves costume_keys fresh on every keypress instead of
            # holding a QShortcut of its own.
            self._costume_shortcuts[slot].setKey(sequence)
            self._save_config()

        return on_change

    # =====================================================================
    # Undo/redo
    # =====================================================================

    def push_undo_snapshot(self) -> None:
        self._undo_stack.append(self._snapshot())
        self._redo_stack.clear()
        self._update_undo_redo_buttons()

    def _snapshot(self) -> tuple[list[Sprite], list[list[tuple[int, int]]], list[list[tuple[str, str]]], float]:
        # costume_assignments/expression_hotkeys ride along in the same
        # snapshot as the sprites, added 2026-09-17 -- otherwise undoing a
        # sprite edit that happens to also revert a sprite's
        # costume_layers (assign_costume_pair/remove_costume_pair mutate
        # it) would leave the *assignment list* stale, showing a costume/
        # Expression hotkey row that no longer matches what the sprites
        # actually do. deepcopy, not copy.copy -- these are lists of
        # lists of tuples; a shallow copy of the outer list would still
        # share (and let this snapshot silently mutate alongside) the
        # per-slot inner lists.
        #
        # zoom joined 2026-09-19 when it moved from WindowConfig to here
        # (see AvatarRig.zoom) -- same reasoning: it's rig state now, so
        # leaving it out of the snapshot would silently break Undo for it.
        return (
            [copy.copy(s) for s in self.rig.sprites],
            copy.deepcopy(self.rig.costume_assignments),
            copy.deepcopy(self.rig.expression_hotkeys),
            self.rig.zoom,
        )

    def _restore(
        self, snapshot: tuple[list[Sprite], list[list[tuple[int, int]]], list[list[tuple[str, str]]], float]
    ) -> None:
        sprites, costume_assignments, expression_hotkeys, zoom = snapshot
        self.rig.sprites = [copy.copy(s) for s in sprites]
        self.rig.costume_assignments = copy.deepcopy(costume_assignments)
        self.rig.expression_hotkeys = copy.deepcopy(expression_hotkeys)
        self.rig.zoom = zoom
        self._rebuild_scene()
        self._rebuild_list()
        self._select(None)
        self._mark_dirty()
        self._sync_zoom_controls()
        self.render_window.rebuild()

    def undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        self._restore(self._undo_stack.pop())
        self._update_undo_redo_buttons()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        self._restore(self._redo_stack.pop())
        self._update_undo_redo_buttons()

    def _update_undo_redo_buttons(self) -> None:
        self._undo_btn.setEnabled(bool(self._undo_stack))
        self._redo_btn.setEnabled(bool(self._redo_stack))

    # =====================================================================
    # Dirty-tracking / Save / Save As / Quit confirmation
    # =====================================================================

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._update_dirty_indicator()

    def _update_dirty_indicator(self) -> None:
        star = "*" if self._dirty else ""
        name = Path(self._current_avatar_path).name if self._current_avatar_path else "unsaved avatar"
        self.setWindowTitle(f"Unicorn Cloak — Control Panel — {name}{star}")

    def _save_config(self) -> None:
        self._capture_ui_state_into_config()
        if self._state_path is not None:
            save_state(self.config, self._state_path)
        else:
            save_state(self.config)

    def _on_save(self) -> None:
        if not self._current_avatar_path:
            self._on_save_as()
            return
        try:
            save_avatar(self.rig, self._current_avatar_path)
        except OSError as exc:
            # Bug audit 2026-09-23, #16: a failed save (unwritable
            # directory, a full disk) used to print a traceback to the
            # console and nothing else -- the only visible clue was that
            # the title's "*" never cleared, easy to miss entirely.
            QMessageBox.warning(
                self, "Save failed", f"Could not save {self._current_avatar_path!r}:\n{exc}"
            )
            return
        if self.asset_watcher is not None:
            self.asset_watcher.note_own_write(self._current_avatar_path)
        self.config.avatar_path = self._current_avatar_path
        self._dirty = False
        self._update_dirty_indicator()
        self._save_config()

    def _on_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save avatar as", "", f"Unicorn Cloak avatar (*{DEFAULT_EXTENSION})"
        )
        if not path:
            return
        if not path.endswith(DEFAULT_EXTENSION):
            path += DEFAULT_EXTENSION
        try:
            save_avatar(self.rig, path)
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", f"Could not save {path!r}:\n{exc}")
            return
        if self.asset_watcher is not None:
            self.asset_watcher.note_own_write(path)
            # Re-point the watch at the new path -- bug audit 2026-09-23,
            # #14: watch_avatar_file was only ever called once, at
            # startup, so Save As left the *old* file watched and the
            # newly current one entirely unwatched -- a change to the
            # old file would even trigger a reload that read
            # config.avatar_path, i.e. this new file, not the one that
            # actually changed.
            self.asset_watcher.watch_avatar_file(path)
        self._current_avatar_path = path
        self.config.avatar_path = path
        self._dirty = False
        self._update_dirty_indicator()
        self._save_config()

    def confirm_and_quit(self) -> bool:
        """The single gate both Escape (on the Render Window) and the
        Quit button route through -- always confirms, with an explicit
        extra warning (and a chance to save first) if the avatar has
        unsaved changes. Returns True if the app should actually quit."""
        if self._dirty:
            result = QMessageBox.warning(
                self,
                "Quit Unicorn Cloak?",
                "The avatar has unsaved changes that will be lost.\n\nQuit anyway?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if result == QMessageBox.StandardButton.Cancel:
                return False
            if result == QMessageBox.StandardButton.Save:
                self._on_save()
                if self._dirty:
                    # Save As was cancelled (no current path yet) -- don't
                    # quit out from under an avatar that still isn't saved.
                    return False
            return True
        result = QMessageBox.question(
            self,
            "Quit Unicorn Cloak?",
            "Quit Unicorn Cloak?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def _on_quit_clicked(self) -> None:
        # Routes through the Render Window's own closeEvent -- the single
        # confirm_and_quit() gate -- rather than calling confirm_and_quit()
        # here too. Bug found 2026-09-17, owner's report ("pops the quit
        # dialog twice"): this used to call confirm_and_quit() directly and
        # *then* QApplication.instance().quit(), but quit() itself sends a
        # QCloseEvent to every remaining top-level window (including the
        # Render Window) as part of normal Qt shutdown -- which hits
        # RenderWindow.closeEvent's own on_quit_requested() call, i.e. this
        # same confirm_and_quit(), a second time. Closing the Render Window
        # directly here means quit() (called from inside its closeEvent,
        # see render.py) only ever runs after that single confirmation.
        if self.render_window is not None:
            self.render_window.close()
        elif self.confirm_and_quit():
            QApplication.instance().quit()

    # =====================================================================
    # Window/UI state persistence
    # =====================================================================

    def _apply_persisted_ui_state(self) -> None:
        cp = self.config.control_panel
        self.guide_btn.setChecked(cp.show_origin_guides)
        self.ghost_btn.setChecked(cp.show_hidden_ghosted)
        if cp.canvas_mode == "edit":
            self.edit_sprites_btn.setChecked(True)
        else:
            self.live_preview_btn.setChecked(True)
        self._on_canvas_mode_toggled(self.edit_sprites_btn.isChecked())
        self.scale_lock.setChecked(cp.scale_lock_proportions)
        self.tabs.setCurrentIndex(min(cp.active_tab, self.tabs.count() - 1))
        self.tabs.currentChanged.connect(self._on_tab_changed)
        for title, section in self._sections.items():
            section.set_collapsed(title in cp.collapsed_sections)

    def _apply_persisted_geometry(self) -> None:
        cp = self.config.control_panel
        self.resize(cp.width, self._clamp_height_to_screen(cp.height))
        if cp.x is not None and cp.y is not None:
            self.move(cp.x, cp.y)

    def _apply_initial_splitter_sizes(self) -> None:
        # setStretchFactor alone only governs what happens on a *resize*
        # after the fact -- QSplitter's initial layout falls back to each
        # pane's own sizeHint(), and the tabs side (lots of wide spinbox+
        # Reset+Lock rows) wins that easily, squeezing the canvas down to
        # a sliver regardless of stretch factors (confirmed with a real
        # screenshot, 2026-09-17). Explicit sizes fix the *default* split;
        # the user can still drag it to whatever ratio they want after,
        # which persists via _capture_ui_state_into_config below.
        persisted = self.config.control_panel.splitter_sizes
        if persisted is not None:
            self.splitter.setSizes(list(persisted))
            return
        total = self.width()
        self.splitter.setSizes([int(total * 0.6), total - int(total * 0.6)])

    def _clamp_height_to_screen(self, height: int) -> int:
        screen = self.screen()
        if screen is None:
            return height
        available = screen.availableGeometry().height()
        return min(height, available)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        clamped = self._clamp_height_to_screen(self.height())
        if clamped < self.height():
            self.resize(self.width(), clamped)
        self.edit_view.refit_to_content()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        if not self._splitter_sizes_applied:
            self._splitter_sizes_applied = True
            self._apply_initial_splitter_sizes()
            # Same "doesn't stick pre-show" issue as the line above, one
            # level down: a tab whose sections start collapsed straight
            # from persisted config (not from a live toggle during this
            # session) got its _resync_tab_splitter_sizes() call during
            # __init__, before the window had ever been shown --
            # reproduced empirically, 2026-09-17, owner's report: "the
            # behavior tab started all collapsed & centered" on a fresh
            # launch, even though live toggling after that (once shown)
            # "behaved well". Redoing it here, once, after the window
            # actually exists on screen, is what makes it stick.
            for splitter in self._tab_splitters:
                self._resync_tab_splitter_sizes(splitter)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # The "neon cyber grid" backdrop, ported from the web design
        # system's own `body` rule (ai-animated-video's globals.css --
        # a violet glow near the top plus two hairline repeating grids,
        # magenta horizontal/cyan vertical, at 64px spacing) since Qt
        # stylesheets have no repeating-linear-gradient equivalent to
        # reach for instead. Owner's request 2026-09-17: "killin' me
        # w/the white background in the settings section... use the
        # neon cyber grid pattern style from ../ai-animated-video".
        #
        # super().paintEvent(event) here is what actually paints the QSS
        # `background-color: INK_900` rule for #ControlPanelWindow
        # (WA_StyledBackground makes Qt paint that automatically as part
        # of this call, before the rest of this method runs -- verified
        # empirically, not assumed, since overriding paintEvent could
        # otherwise easily suppress it) -- everything below draws on top
        # of that base fill, not instead of it.
        super().paintEvent(event)
        painter = QPainter(self)
        rect = self.rect()

        glow = QRadialGradient(rect.width() / 2, 0, rect.width() * 0.6)
        glow_color = QColor(theme.VIOLET_500)
        glow_color.setAlpha(36)
        glow.setColorAt(0.0, glow_color)
        glow_edge = QColor(theme.VIOLET_500)
        glow_edge.setAlpha(0)
        glow.setColorAt(1.0, glow_edge)
        painter.fillRect(rect, glow)

        spacing = 64
        magenta = QColor(theme.MAGENTA_500)
        magenta.setAlpha(46)
        cyan = QColor(theme.CYAN_500)
        cyan.setAlpha(36)

        pen = QPen(magenta)
        pen.setWidth(1)
        painter.setPen(pen)
        y = 0
        while y <= rect.height():
            painter.drawLine(0, y, rect.width(), y)
            y += spacing

        pen = QPen(cyan)
        pen.setWidth(1)
        painter.setPen(pen)
        x = 0
        while x <= rect.width():
            painter.drawLine(x, 0, x, rect.height())
            x += spacing

    def _on_tab_changed(self, index: int) -> None:
        self.config.control_panel.active_tab = index

    def _capture_ui_state_into_config(self) -> None:
        cp = self.config.control_panel
        cp.x = self.x()
        cp.y = self.y()
        cp.width = self.width()
        cp.height = self.height()
        cp.active_tab = self.tabs.currentIndex()
        cp.canvas_mode = "edit" if self.edit_sprites_btn.isChecked() else "live_preview"
        cp.show_origin_guides = self.guide_btn.isChecked()
        cp.show_hidden_ghosted = self.ghost_btn.isChecked()
        cp.scale_lock_proportions = self.scale_lock.isChecked()
        cp.grid_spacing_px = self.grid_spacing.value()
        cp.collapsed_sections = tuple(
            title for title, section in self._sections.items() if section.is_collapsed()
        )
        sizes = self.splitter.sizes()
        if len(sizes) == 2:
            cp.splitter_sizes = (sizes[0], sizes[1])

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Closing the Control Panel does NOT quit the app or ask for
        # confirmation -- owner's request: "Settings window can be closed,
        # leaving avatar live." Quitting the whole app is Escape/Quit
        # only, both gated by confirm_and_quit().
        self._save_config()
        super().closeEvent(event)

    # =====================================================================
    # Scene/list construction
    # =====================================================================

    def _rebuild_scene(self) -> None:
        self._items.clear()
        self._selected_id = None
        self.scene.blockSignals(True)
        self.scene.clear()
        self.scene.blockSignals(False)
        by_parent: dict[int | None, list[Sprite]] = {}
        for sprite in self.rig.sprites:
            by_parent.setdefault(sprite.parent_id, []).append(sprite)

        def build(sprite: Sprite, parent_item) -> None:
            pixmap = QPixmap()
            if sprite.image_data:
                pixmap.loadFromData(sprite.image_data)
            frame0 = slice_frame(pixmap, sprite.frames, 0)
            item = EditableSpriteItem(sprite, frame0, self, parent_item)
            if parent_item is None:
                self.scene.addItem(item)
            self._items[sprite.id] = item
            self._apply_preview_opacity(item)
            for child in by_parent.get(sprite.id, []):
                build(child, item)

        # Guards on_sprite_moved: EditableSpriteItem.__init__'s own
        # setPos() call fires Qt's itemChange (ItemPositionHasChanged)
        # exactly like a real drag would -- a real bug found via a real
        # test, 2026-09-17, once dirty-tracking existed to expose it:
        # every _rebuild_scene() call (on load, undo/redo, hot reload,
        # even the very first construction) was marking the avatar dirty
        # on its own, before any actual edit. Pre-existing in the code
        # this was ported from, just never observable before dirty-
        # tracking existed to notice it.
        self._rebuilding_scene = True
        try:
            for root_sprite in by_parent.get(None, []):
                build(root_sprite, None)
        finally:
            self._rebuilding_scene = False
        self.edit_view.refit_to_content()
        self._rebuild_costume_and_expression_editors()

    def _preview_variant_counts(self) -> tuple[int, int]:
        """How many *distinct* `variant` values are in play for the Edit
        canvas's manual talk/blink preview spinboxes -- not a raw
        eligible-sprite count. Same fix as render.py's
        _talk_variant_values_at/_blink_variant_values_at (bug audit
        2026-09-23, #4, which named this method as a third affected
        site): two sprites sharing a talk/blink band by coincidence,
        both left at the default variant=0 since neither was ever meant
        to alternate against the other, used to report a count of 2 --
        wrongly implying a second, distinct preview value exists to
        scrub to, when nothing in the rig actually has one."""
        talk_values: set[int] = set()
        blink_values: set[int] = set()
        for item in self._items.values():
            sprite = item.sprite
            if sprite.manual_driven or sprite.hidden or not sprite.costume_layers[self.rig.active_costume]:
                continue
            if sprite.talk_state != 0 and motion.axis_visible(sprite.talk_state, self.preview_talk_level):
                talk_values.add(sprite.variant)
            if sprite.blink_state != 0 and sprite.blink_state == self.preview_blink_level:
                blink_values.add(sprite.variant)
        return max(1, len(talk_values)), max(1, len(blink_values))

    def _apply_preview_opacity(self, item: EditableSpriteItem) -> None:
        talk_variant_count, blink_variant_count = self._preview_variant_counts()
        manual_active = (
            self.preview_manual_overrides.get(item.sprite.group_name) == item.sprite.state_name
        )
        alpha = motion.sprite_alpha(
            item.sprite.talk_state,
            item.sprite.blink_state,
            talk_level=self.preview_talk_level,
            blink_level=self.preview_blink_level,
            edit_mode=self.ghost_btn.isChecked(),
            talk_variant=item.sprite.variant,
            active_talk_variant=self.preview_talk_variant.value(),
            talk_variant_count=talk_variant_count,
            blink_variant=item.sprite.variant,
            active_blink_variant=self.preview_blink_variant.value(),
            blink_variant_count=blink_variant_count,
            hidden=item.sprite.hidden,
            manual_driven=item.sprite.manual_driven,
            manual_active=manual_active,
        )
        in_costume = item.sprite.costume_layers[self.rig.active_costume]
        item.setOpacity(alpha if in_costume else 0.2)

    def _refresh_preview_expression_combo(self) -> None:
        pairs = sorted({
            (s.group_name, s.state_name)
            for s in self.rig.sprites
            if s.manual_driven and s.group_name and s.state_name
        })
        current = self.preview_expression_combo.currentData()
        self.preview_expression_combo.blockSignals(True)
        self.preview_expression_combo.clear()
        self.preview_expression_combo.addItem("(none)", None)
        for group, state in pairs:
            self.preview_expression_combo.addItem(f"{group}: {state}", (group, state))
        index = self.preview_expression_combo.findData(current)
        self.preview_expression_combo.setCurrentIndex(max(index, 0))
        self.preview_expression_combo.blockSignals(False)

    def _rebuild_list(self) -> None:
        # Group headers + a lighter row background for members -- owner's
        # request, 2026-09-17: "when items are linked/grouped (like say
        # the mouths & eyes), show the group name and indent the members
        # w/a slightly lighter bg color". Group name (State Assignment)
        # is independent of parent/child hierarchy (`depth` below) --
        # e.g. three alternate mouth shapes are usually siblings, not
        # nested -- so this adds one more indent level and a header on
        # top of, not instead of, the existing hierarchy indentation.
        # Re-prints the header each time a *run* of the same group name
        # starts, which also naturally handles a group's sprites not
        # being contiguous in stacking order without any extra tracking.
        self.sprite_list.blockSignals(True)
        self.sprite_list.clear()
        self._lock_row_buttons.clear()
        current_group: str | None = None
        for sprite, depth in self.rig.sprites_in_stacking_order():
            group_name = sprite.group_name or None
            if group_name != current_group:
                current_group = group_name
                if group_name:
                    header_item = QListWidgetItem()
                    header_item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # not selectable
                    self.sprite_list.addItem(header_item)
                    header_row = self._build_group_header_row(group_name, depth)
                    header_item.setSizeHint(header_row.sizeHint())
                    self.sprite_list.setItemWidget(header_item, header_row)

            name = sprite.path.rsplit("/", 1)[-1]
            list_item = QListWidgetItem()
            list_item.setData(SELECTED_ID, sprite.id)
            self.sprite_list.addItem(list_item)
            indent = depth + 1 if group_name else depth
            row = self._build_layer_row(sprite, indent, name, grouped=bool(group_name))
            list_item.setSizeHint(row.sizeHint())
            self.sprite_list.setItemWidget(list_item, row)
        self.sprite_list.blockSignals(False)
        self._populate_behavior_layer_combo()

    def _build_group_header_row(self, group_name: str, depth: int) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(2, 4, 2, 2)
        label = QLabel("    " * depth + group_name)
        label.setStyleSheet(f"color: {theme.MAGENTA_500}; font-weight: 600; background: transparent;")
        label.setToolTip(
            f'Sprites tagged with Group name "{group_name}" (State Assignment,\n'
            "on this tab) -- purely organizational, shown here so a named\n"
            "set of alternates (e.g. mouth shapes, eye states) reads as one\n"
            "group instead of only coincidentally sitting near each other."
        )
        row_layout.addWidget(label)
        return row

    def _build_layer_row(self, sprite: Sprite, depth: int, name: str, grouped: bool = False) -> QWidget:
        row = QWidget()
        if grouped:
            # A plain QWidget paints no background of its own without
            # WA_StyledBackground -- see theme.py's own notes on this.
            row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            row.setStyleSheet(f"background-color: {theme.INK_700};")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(2, 0, 2, 0)
        row_layout.setSpacing(6)

        eye_btn = QToolButton()
        eye_btn.setCheckable(True)
        eye_btn.setChecked(not sprite.hidden)
        eye_btn.setAutoRaise(True)
        eye_btn.setIcon(_eye_icon(not sprite.hidden))
        eye_btn.setIconSize(QSize(16, 16))
        eye_btn.setToolTip(
            "Show/hide this layer everywhere (Render Window and here) --\n"
            "independent of costume, talk, or blink state. All layers\n"
            "start visible; click to hide one, e.g. when only one of two\n"
            "alternatives (glasses vs. bare eyes) should show at a time."
        )
        eye_btn.toggled.connect(
            lambda checked, sid=sprite.id, btn=eye_btn: self._on_visibility_toggled(sid, checked, btn)
        )
        row_layout.addWidget(eye_btn)

        lock_btn = QToolButton()
        lock_btn.setCheckable(True)
        lock_btn.setChecked(sprite.locked)
        lock_btn.setAutoRaise(True)
        lock_btn.setIcon(_lock_icon(sprite.locked))
        lock_btn.setIconSize(QSize(16, 16))
        lock_btn.setToolTip(
            "Lock this sprite's Position, Rotation, and Scale -- by\n"
            "dragging on the Edit canvas or the Position & Hierarchy\n"
            "tab's own fields. Everything else stays editable. Same lock\n"
            "as that tab's \"Lock Position\" button -- either toggles both."
        )
        lock_btn.toggled.connect(
            lambda checked, sid=sprite.id: self._on_sprite_lock_toggled(sid, checked)
        )
        self._lock_row_buttons[sprite.id] = lock_btn
        row_layout.addWidget(lock_btn)

        label = _LayerNameLabel("    " * depth + name, sprite.id, self)
        row_layout.addWidget(label, stretch=1)
        return row

    def select_sprite_in_list(self, sprite_id: int) -> None:
        for i in range(self.sprite_list.count()):
            item = self.sprite_list.item(i)
            if item.data(SELECTED_ID) == sprite_id:
                self.sprite_list.setCurrentItem(item)
                return

    def _on_visibility_toggled(self, sprite_id: int, checked: bool, button: QToolButton) -> None:
        sprite = self.rig.by_id(sprite_id)
        if sprite is None:
            return
        self.push_undo_snapshot()
        sprite.hidden = not checked
        self._mark_dirty()
        button.setIcon(_eye_icon(checked))
        item = self._items.get(sprite_id)
        if item is not None:
            self._apply_preview_opacity(item)

    def _on_sprite_lock_toggled(self, sprite_id: int, locked: bool) -> None:
        """Shared by both the Layer List's padlock icon (see
        _build_layer_row) and the Position & Hierarchy tab's "Lock
        Position" button (see _on_lock_position_btn_toggled) -- owner's
        request, 2026-09-19: "both... will both fire the same code and
        share state." Whichever one the user actually clicked has
        already updated its own checked state before this fires (Qt);
        this brings the *other* one (and the canvas item's own
        ItemIsMovable flag, and the property form's own field-disabling)
        into sync with it."""
        sprite = self.rig.by_id(sprite_id)
        if sprite is None:
            return
        self.push_undo_snapshot()
        sprite.locked = locked
        self._mark_dirty()

        row_btn = self._lock_row_buttons.get(sprite_id)
        if row_btn is not None:
            row_btn.blockSignals(True)
            row_btn.setChecked(locked)
            row_btn.blockSignals(False)
            row_btn.setIcon(_lock_icon(locked))

        canvas_item = self._items.get(sprite_id)
        if canvas_item is not None:
            canvas_item.setFlag(QGraphicsItem.ItemIsMovable, not locked)
            canvas_item.update()  # handles disappear/reappear immediately, not just on next repaint

        self._refresh_behavior_layer_combo_styles()

        if sprite_id == self._selected_id:
            self.lock_position_btn.blockSignals(True)
            self.lock_position_btn.setChecked(locked)
            self.lock_position_btn.blockSignals(False)
            self._update_locked_transform_fields_enabled(locked)

    def _on_lock_position_btn_toggled(self, checked: bool) -> None:
        if self._updating_form or self._selected_id is None:
            return
        self._on_sprite_lock_toggled(self._selected_id, checked)

    def _update_locked_transform_fields_enabled(self, locked: bool) -> None:
        for widget in self._lockable_transform_widgets:
            widget.setEnabled(not locked)

    # =====================================================================
    # Selection
    # =====================================================================

    def on_sprite_moved(self, sprite: Sprite) -> None:
        if self._rebuilding_scene:
            return  # setPos() during item construction, not a real drag
        self._mark_dirty()
        if sprite.id == self._selected_id:
            self._load_property_form(sprite)

    def on_sprite_scaled(self, sprite: Sprite) -> None:
        # Same shape as on_sprite_moved above -- EditableSpriteItem's
        # corner-handle drag (see _drag_handle) writes straight into
        # sprite.scale_x/y, this just keeps the Scale spinboxes and the
        # dirty flag in sync with that live drag.
        self._mark_dirty()
        if sprite.id == self._selected_id:
            self._load_property_form(sprite)

    def on_sprite_rotated(self, sprite: Sprite) -> None:
        self._mark_dirty()
        if sprite.id == self._selected_id:
            self._load_property_form(sprite)

    def _on_scene_selection_changed(self) -> None:
        selected = self.scene.selectedItems()
        if not selected:
            self._select(None)
            return
        item = selected[0]
        if isinstance(item, EditableSpriteItem):
            self._select(item.sprite.id)

    def _on_list_selection_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            self._select(None)
            return
        self._select(current.data(SELECTED_ID))

    def _select(self, sprite_id: int | None) -> None:
        self._selected_id = sprite_id
        self._undo_pending_for_selection = sprite_id is not None

        self.scene.blockSignals(True)
        for sid, item in self._items.items():
            item.setSelected(sid == sprite_id)
        self.scene.blockSignals(False)

        self.sprite_list.blockSignals(True)
        for i in range(self.sprite_list.count()):
            list_item = self.sprite_list.item(i)
            if list_item.data(SELECTED_ID) == sprite_id:
                self.sprite_list.setCurrentItem(list_item)
        self.sprite_list.blockSignals(False)

        sprite = self.rig.by_id(sprite_id) if sprite_id is not None else None
        self._sync_behavior_layer_combo(sprite)
        if sprite is None:
            self._set_property_form_enabled(False)
        else:
            self._set_property_form_enabled(True)
            self._load_property_form(sprite)
            self._auto_expand_assignment_sections(sprite)

    def _set_property_form_enabled(self, enabled: bool) -> None:
        for widget in self._per_sprite_widgets:
            widget.setEnabled(enabled)

    def _auto_expand_assignment_sections(self, sprite: Sprite) -> None:
        # Owner's request, 2026-09-17: "when clicking on a sprite, it
        # should auto-populate it's state/expression assignments if it
        # has any." The fields themselves were already being set either
        # way (see _load_property_form) -- that's easy to miss if the
        # relevant section happens to be collapsed, including by this
        # app's own auto-collapse-to-fit behavior (_make_room_if_needed)
        # from a moment ago. Only expands a section that actually has
        # something to show for *this* sprite -- clicking a plain,
        # untagged sprite (hair, body, etc.) leaves sections exactly as
        # they were, not forcing them open for nothing.
        if sprite.group_name:
            state_section = self._sections.get("State Assignment")
            if state_section is not None and state_section.is_collapsed():
                state_section.set_collapsed(False)
        if sprite.manual_driven and sprite.group_name and sprite.state_name:
            expressions_section = self._sections.get("Expressions")
            if expressions_section is not None and expressions_section.is_collapsed():
                expressions_section.set_collapsed(False)

    def _load_property_form(self, sprite: Sprite) -> None:
        self._updating_form = True
        self.pos_x.setValue(sprite.position[0])
        self.pos_y.setValue(sprite.position[1])
        self.offset_x.setValue(sprite.offset[0])
        self.offset_y.setValue(sprite.offset[1])
        self.z_index.setValue(sprite.z_index)
        self.rotation.setValue(sprite.rotation_deg)
        self.scale_x.setValue(sprite.scale_x)
        self.scale_y.setValue(sprite.scale_y)
        self._populate_group_name_combo(sprite)
        self._populate_state_name_combo(sprite.group_name, sprite.state_name)
        self.manual_driven.setChecked(sprite.manual_driven)
        self._update_manual_driven_enabled_state()
        self.talk_state.setCurrentIndex(max(self.talk_state.findData(sprite.talk_state), 0))
        self.blink_state.setCurrentIndex(max(self.blink_state.findData(sprite.blink_state), 0))
        self.variant.setValue(sprite.variant)
        self.frames.setValue(sprite.frames)
        self.anim_speed.setValue(sprite.anim_speed)
        self._populate_parent_combo(sprite)
        self.lock_position_btn.setChecked(sprite.locked)
        self._updating_form = False
        # Outside the _updating_form guard above -- this disables/enables
        # real widgets (not a value a signal handler would otherwise
        # react to), and _set_property_form_enabled(True) (called by
        # _select() right before this) would have just re-enabled these
        # same widgets, so it must run after that, not before.
        self._update_locked_transform_fields_enabled(sprite.locked)

    def _group_names_in_rig(self) -> list[str]:
        return sorted({s.group_name for s in self.rig.sprites if s.group_name})

    def _state_names_for_group(self, group_name: str) -> list[str]:
        return sorted({
            s.state_name for s in self.rig.sprites
            if s.group_name == group_name and s.state_name
        })

    def _populate_group_name_combo(self, sprite: Sprite) -> None:
        self.group_name.blockSignals(True)
        self.group_name.clear()
        self.group_name.addItems(self._group_names_in_rig())
        self.group_name.setCurrentText(sprite.group_name)
        self.group_name.blockSignals(False)

    def _populate_state_name_combo(self, group_name: str, current_text: str) -> None:
        self.state_name.blockSignals(True)
        self.state_name.clear()
        self.state_name.addItems(self._state_names_for_group(group_name))
        self.state_name.setCurrentText(current_text)
        self.state_name.blockSignals(False)

    def _update_manual_driven_enabled_state(self) -> None:
        manual = self.manual_driven.isChecked()
        self.talk_state.setEnabled(not manual)
        self.blink_state.setEnabled(not manual)

    def _populate_parent_combo(self, sprite: Sprite) -> None:
        self.parent_combo.blockSignals(True)
        self.parent_combo.clear()
        self.parent_combo.addItem("None (root)", None)
        blocked_ids = {sprite.id} | {s.id for s in self.rig.descendants_of(sprite.id)}
        for other in self.rig.sprites:
            if other.id in blocked_ids:
                continue
            name = other.path.rsplit("/", 1)[-1]
            self.parent_combo.addItem(f"{name} ({other.id})", other.id)
        index = self.parent_combo.findData(sprite.parent_id)
        self.parent_combo.setCurrentIndex(max(index, 0))
        self.parent_combo.blockSignals(False)

    def _on_property_changed(self, _value) -> None:
        if self._updating_form or self._selected_id is None:
            return
        sprite = self.rig.by_id(self._selected_id)
        item = self._items.get(self._selected_id)
        if sprite is None or item is None:
            return

        if self._undo_pending_for_selection:
            self.push_undo_snapshot()
            self._undo_pending_for_selection = False

        sprite.position = (self.pos_x.value(), self.pos_y.value())
        sprite.offset = (self.offset_x.value(), self.offset_y.value())
        sprite.z_index = int(self.z_index.value())
        sprite.rotation_deg = self.rotation.value()
        sprite.scale_x = self.scale_x.value()
        sprite.scale_y = self.scale_y.value()
        sprite.group_name = self.group_name.currentText().strip()
        sprite.state_name = self.state_name.currentText().strip()
        sprite.manual_driven = self.manual_driven.isChecked()
        sprite.talk_state = int(self.talk_state.currentData())
        sprite.blink_state = int(self.blink_state.currentData())
        sprite.variant = int(self.variant.value())
        sprite.anim_speed = self.anim_speed.value()
        self._mark_dirty()

        item.setPos(*sprite.position)
        item.setOffset(-item.pixmap().width() / 2 + sprite.offset[0], -item.pixmap().height() / 2 + sprite.offset[1])
        item.setZValue(sprite.z_index)
        item.setFlag(QGraphicsItem.ItemStacksBehindParent, sprite.z_index < 0)
        item.setTransform(QTransform().rotate(sprite.rotation_deg).scale(sprite.scale_x, sprite.scale_y))
        self._refresh_preview_expression_combo()
        self._refresh_expressions_section()
        self._apply_preview_opacity(item)
        self.render_window.sync_sprite_offset_and_z(sprite.id)

    def _on_manual_driven_toggled(self, _checked: bool) -> None:
        self._update_manual_driven_enabled_state()
        self._on_property_changed(None)

    def _on_scale_x_changed(self, value: float) -> None:
        if self._updating_form:
            return
        if self.scale_lock.isChecked() and abs(self.scale_y.value() - value) > 1e-9:
            self.scale_y.blockSignals(True)
            self.scale_y.setValue(value)
            self.scale_y.blockSignals(False)
        self._on_property_changed(None)

    def _on_scale_y_changed(self, value: float) -> None:
        if self._updating_form:
            return
        if self.scale_lock.isChecked() and abs(self.scale_x.value() - value) > 1e-9:
            self.scale_x.blockSignals(True)
            self.scale_x.setValue(value)
            self.scale_x.blockSignals(False)
        self._on_property_changed(None)

    def _on_reset_size_clicked(self) -> None:
        # Routed through the spinboxes, not straight into sprite.scale_x/
        # y -- reuses _on_scale_x/y_changed's existing lock-proportion,
        # undo, dirty-tracking, and live-canvas-update handling instead
        # of duplicating it. setValue() is a no-op (fires nothing) on
        # whichever of the two is already 1.0 -- harmless, since the
        # other one's own handler re-reads both anyway.
        self.scale_x.setValue(1.0)
        self.scale_y.setValue(1.0)

    def _on_reset_rotation_clicked(self) -> None:
        self.rotation.setValue(0.0)

    def _on_group_name_changed(self, _text: str) -> None:
        if self._updating_form or self._selected_id is None:
            return
        self._updating_form = True
        self._populate_state_name_combo(self.group_name.currentText(), "")
        self._updating_form = False
        self._on_property_changed(None)

    def _on_parent_changed(self, index: int) -> None:
        if self._updating_form or self._selected_id is None:
            return
        new_parent_id = self.parent_combo.itemData(index)
        if not self.rig.can_reparent(self._selected_id, new_parent_id):
            return
        self.push_undo_snapshot()
        sprite = self.rig.by_id(self._selected_id)
        sprite.parent_id = new_parent_id
        self._mark_dirty()
        selected_id = self._selected_id
        self._rebuild_scene()
        self._rebuild_list()
        self._select(selected_id)
        self.render_window.rebuild()

    def _on_frames_changed(self, value: int) -> None:
        if self._updating_form or self._selected_id is None:
            return
        sprite = self.rig.by_id(self._selected_id)
        if sprite is None or sprite.frames == value:
            return
        self.push_undo_snapshot()
        sprite.frames = value
        self._mark_dirty()
        selected_id = self._selected_id
        self._rebuild_scene()
        self._rebuild_list()
        self._select(selected_id)
        self.render_window.rebuild()

    def _on_move_up(self) -> None:
        self._move_layer(self.rig.move_layer_up)

    def _on_move_down(self) -> None:
        self._move_layer(self.rig.move_layer_down)

    def _move_layer(self, move_fn) -> None:
        if self._selected_id is None:
            return
        self.push_undo_snapshot()
        swapped_id = move_fn(self._selected_id)
        if swapped_id is None:
            self._undo_stack.pop()
            self._update_undo_redo_buttons()
            return
        self._mark_dirty()
        selected_id = self._selected_id
        self._rebuild_scene()
        self._rebuild_list()
        self._select(selected_id)
        self.render_window.rebuild()

    def _on_help(self) -> None:
        if self._help_window is None:
            self._help_window = HelpWindow(self)
        self._help_window.show()
        self._help_window.raise_()
        self._help_window.activateWindow()

    # =====================================================================
    # Structural edits: add/replace/duplicate/delete/export/check/load
    # =====================================================================

    def _on_add(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Add sprite", "", "Images (*.png)")
        if not path:
            return
        try:
            with open(path, "rb") as f:
                image_data = f.read()
        except OSError as exc:
            # Bug audit 2026-09-23, #16. Read before push_undo_snapshot()
            # (not after), so a failed read never leaves a no-op undo
            # entry behind for a change that didn't actually happen.
            QMessageBox.warning(self, "Add sprite failed", f"Could not read {path!r}:\n{exc}")
            return
        self.push_undo_snapshot()
        sprite = Sprite(id=self.rig.new_sprite_id(), path=path, image_data=image_data)
        self.rig.add_sprite(sprite)
        self._mark_dirty()
        if self.asset_watcher is not None:
            # Bug audit 2026-09-23, #14: sprite PNG watches were only
            # ever set from __main__.py's own startup/hot-reload paths,
            # never re-synced from here -- a sprite added through the
            # Control Panel was never actually watched, so re-exporting/
            # touching its source PNG afterward did nothing.
            self.asset_watcher.watch_sprite_files([s.path for s in self.rig.sprites])
        self._rebuild_scene()
        self._rebuild_list()
        self._select(sprite.id)
        self.render_window.rebuild()

    def _on_replace(self) -> None:
        if self._selected_id is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Replace sprite image", "", "Images (*.png)")
        if not path:
            return
        try:
            with open(path, "rb") as f:
                image_data = f.read()
        except OSError as exc:
            QMessageBox.warning(self, "Replace sprite failed", f"Could not read {path!r}:\n{exc}")
            return
        self.push_undo_snapshot()
        sprite = self.rig.by_id(self._selected_id)
        sprite.image_data = image_data
        sprite.path = path
        self._mark_dirty()
        if self.asset_watcher is not None:
            self.asset_watcher.watch_sprite_files([s.path for s in self.rig.sprites])
        self._rebuild_scene()
        self._rebuild_list()
        self._select(sprite.id)
        self.render_window.rebuild()

    def _on_duplicate(self) -> None:
        if self._selected_id is None:
            return
        self.push_undo_snapshot()
        original = self.rig.by_id(self._selected_id)
        copy_sprite = duplicate_sprite(original, new_id=self.rig.new_sprite_id())
        self.rig.add_sprite(copy_sprite)
        self._mark_dirty()
        self._rebuild_scene()
        self._rebuild_list()
        self._select(copy_sprite.id)
        self.render_window.rebuild()

    def _on_delete(self) -> None:
        if self._selected_id is None:
            return
        self.push_undo_snapshot()
        self.rig.remove_sprite(self._selected_id)
        self._mark_dirty()
        self._rebuild_scene()
        self._rebuild_list()
        self._select(None)
        self.render_window.rebuild()

    def _on_export_snapshot(self) -> None:
        width, ok = QInputDialog.getInt(self, "Export Snapshot", "Width (px):", 512, 1, 8192)
        if not ok:
            return
        height, ok = QInputDialog.getInt(self, "Export Snapshot", "Height (px):", 512, 1, 8192)
        if not ok:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export costume snapshot", "", "PNG image (*.png)")
        if not path:
            return
        if not path.endswith(".png"):
            path += ".png"
        try:
            export_costume_snapshot(self.rig, self.rig.active_costume, path, width, height)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Export Snapshot", f"Saved to {path}")

    def _on_check_for_issues(self) -> None:
        issues = find_rig_issues(self.rig)
        if not issues:
            QMessageBox.information(self, "Check for Issues", "No issues found.")
            return
        body = "\n\n".join(f"• {issue.message}" for issue in issues)
        QMessageBox.warning(self, "Check for Issues", body)

    def _sync_zoom_controls(self) -> None:
        """Reflects self.rig.zoom (just changed by a load/hot-reload, not
        by the spinbox itself) into the Zoom spinbox and the live Render
        Window. blockSignals so this doesn't loop back into
        _on_zoom_changed and push a spurious undo entry."""
        self.zoom.blockSignals(True)
        self.zoom.setValue(self.rig.zoom)
        self.zoom.blockSignals(False)
        if self.render_window is not None:
            self.render_window.set_zoom(self.rig.zoom)

    def refresh_after_external_change(self) -> None:
        """For hot reload (see hot_reload.py) -- the save file or a
        sprite's source PNG changed on disk outside this app entirely.
        Deliberately does not push an undo snapshot or mark dirty: an
        external file change already exists on disk exactly as loaded,
        so there's nothing unsaved about it."""
        self._rebuild_scene()
        self._rebuild_list()
        self._select(None)
        self._refresh_preview_expression_combo()
        self._refresh_expressions_section()
        self._sync_zoom_controls()
        self.render_window.rebuild()

    def refresh_after_external_avatar_reload(self) -> None:
        """__main__.py's handle_avatar_file_changed calls this instead
        of refresh_after_external_change directly, specifically for a
        reload of the *avatar file itself* (not a sprite-PNG-only
        change, which still goes straight to refresh_after_external_change).

        Bug audit 2026-09-23, #15: replace_contents_from has already
        overwritten self.rig's sprites/assignments with whatever was on
        disk by the time this runs, but self._dirty and the undo stack
        used to be left completely untouched. If there were real
        unsaved edits (_dirty already True), they're gone now with no
        warning at all -- and the stale True flag afterward gave a
        misleading reason for the title's "*" (looks like "still have
        unsaved changes" when what actually happened is "the reload
        just silently discarded some"). The undo stack is a history
        boundary here too, same reasoning as Load (#2) -- Undo
        afterward would restore pre-reload sprites that may not
        correspond to anything on disk any more."""
        had_unsaved_changes = self._dirty
        self.refresh_after_external_change()
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._update_undo_redo_buttons()
        self._dirty = False
        self._update_dirty_indicator()
        if had_unsaved_changes:
            QMessageBox.warning(
                self,
                "Avatar file changed externally",
                "This avatar's save file changed outside Unicorn Cloak and "
                "was reloaded -- your unsaved changes here were discarded.",
            )

    def _on_load(self) -> None:
        # Confirm first if dirty -- bug audit 2026-09-23, #16: this used
        # to swap avatars unconditionally, silently discarding unsaved
        # changes with no prompt at all. Same Save/Discard/Cancel dialog
        # confirm_and_quit already uses for the same situation on Quit.
        if self._dirty:
            result = QMessageBox.warning(
                self,
                "Load avatar?",
                "The current avatar has unsaved changes that will be lost.\n\n"
                "Load a different avatar anyway?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if result == QMessageBox.StandardButton.Cancel:
                return
            if result == QMessageBox.StandardButton.Save:
                self._on_save()
                if self._dirty:
                    # Save As was cancelled (no current path yet) -- don't
                    # load out from under an avatar that still isn't saved.
                    return

        path, _ = QFileDialog.getOpenFileName(
            self, "Load avatar", "", f"Unicorn Cloak avatar (*{DEFAULT_EXTENSION} *.save)"
        )
        if not path:
            return
        try:
            loaded = load_avatar_with_upgrade(path, parent=self)
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            # Bug audit 2026-09-23, #16: a malformed or unreadable file
            # used to print a traceback to the console and nothing
            # else -- no visible sign anything went wrong at all.
            QMessageBox.warning(self, "Load failed", f"Could not load {path!r}:\n{exc}")
            return
        # Not push_undo_snapshot() -- Load is a history boundary, not an
        # editable step in the current avatar's history. Bug audit
        # 2026-09-23 (#2): pushing a snapshot then re-pointing
        # _current_avatar_path at the *new* file meant Undo restored the
        # *previous* avatar's sprites while the path/title still read
        # the new file -- and the next Save overwrote the newly loaded
        # file with the old avatar's contents. Undoing "past" a Load
        # doesn't have a sensible meaning here (there's no single
        # AvatarRig field for "which file/name was this undo entry
        # for"), so Load simply starts a fresh history instead.
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._update_undo_redo_buttons()
        self.rig.replace_contents_from(loaded)
        self._current_avatar_path = path
        self.config.avatar_path = path
        if self.asset_watcher is not None:
            # Re-point both watches at the newly loaded avatar -- bug
            # audit 2026-09-23, #14: watch_avatar_file/watch_sprite_files
            # were only ever called once, at startup, so Load left the
            # *previous* avatar's file (and sprite PNGs no longer even
            # part of this rig) watched instead of the one now actually
            # open -- a hand-edit to the newly loaded file was never
            # picked up, while an edit to the old, no-longer-open file
            # would trigger a reload that read config.avatar_path, i.e.
            # this new file, not the one that actually changed.
            self.asset_watcher.watch_avatar_file(path)
            self.asset_watcher.watch_sprite_files([s.path for s in self.rig.sprites])
        self._dirty = False
        self._update_dirty_indicator()
        self._rebuild_scene()
        self._rebuild_list()
        self._select(None)
        self._refresh_preview_expression_combo()
        self._refresh_expressions_section()
        self._sync_zoom_controls()
        self._save_config()
        self.render_window.rebuild()

    # =====================================================================
    # Canvas mode / Preview state
    # =====================================================================

    def _on_canvas_mode_toggled(self, edit_mode: bool) -> None:
        self.canvas_stack.setCurrentWidget(self.edit_view if edit_mode else self.live_view)
        self.preview_controls.setVisible(edit_mode)
        self.reset_size_btn.setVisible(edit_mode)
        self.reset_rotation_btn.setVisible(edit_mode)
        self._undo_btn.setVisible(edit_mode)
        self._redo_btn.setVisible(edit_mode)
        self.guide_btn.setVisible(edit_mode)
        self.ghost_btn.setVisible(edit_mode)
        if edit_mode:
            self.edit_view.refit_to_content()
        else:
            self.live_view.refit()

    def _on_preview_talk_level_changed(self, index: int) -> None:
        self.preview_talk_level = self.preview_talk_combo.itemData(index)
        for item in self._items.values():
            self._apply_preview_opacity(item)

    def _on_preview_blink_level_changed(self, index: int) -> None:
        self.preview_blink_level = self.preview_blink_combo.itemData(index)
        for item in self._items.values():
            self._apply_preview_opacity(item)

    def _on_preview_variant_changed(self, _value: int) -> None:
        for item in self._items.values():
            self._apply_preview_opacity(item)

    def _on_preview_expression_changed(self, index: int) -> None:
        data = self.preview_expression_combo.itemData(index)
        self.preview_manual_overrides.clear()
        if data is not None:
            group, state = data
            self.preview_manual_overrides[group] = state
        for item in self._items.values():
            self._apply_preview_opacity(item)

    # =====================================================================
    # Guide / Ghost / Grid
    # =====================================================================

    def _on_guide_toggled(self, checked: bool) -> None:
        self.edit_view.show_grid = checked
        self.edit_view.viewport().update()

    def _on_ghost_toggled(self, checked: bool) -> None:
        for item in self._items.values():
            self._apply_preview_opacity(item)

    def _on_grid_spacing_changed(self, value: int) -> None:
        self.edit_view.grid_spacing_px = value
        self.edit_view.viewport().update()

    # =====================================================================
    # Audio source bar
    # =====================================================================

    def _elided_file_label(self, path: str | None = None) -> str:
        if path is None:
            path = self.config.audio.file_path
        if not path:
            return ""
        metrics = self.fontMetrics()
        width = max(200, self.width() - 24)
        return elide_path_middle(path, metrics, width)

    def _update_source_controls_enabled(self) -> None:
        is_file = self.config.audio.source == "file"
        self._browse_file_btn.setEnabled(is_file)
        has_file = is_file and bool(self.config.audio.file_path)
        self.play_file_btn.setEnabled(has_file)
        self._rewind_file_btn.setEnabled(has_file)
        is_device_source = not is_file
        self.audio_device.setEnabled(is_device_source)
        self._audio_device_refresh_btn.setEnabled(is_device_source)

    def _current_device_hint(self) -> str | None:
        if self.config.audio.source == "desktop":
            return self.config.audio.desktop_device
        return self.config.audio.device

    def _populate_audio_devices(self) -> None:
        """(Re)builds the device dropdown's item list from whatever's
        actually plugged in right now, then restores the selection for
        whichever source (Microphone/Desktop Audio) is currently active
        -- see _current_device_hint. Called once at startup and again on
        a manual Refresh click (see that button's own tooltip for why
        this never happens automatically)."""
        self.audio_device.blockSignals(True)
        self.audio_device.clear()
        self.audio_device.addItem("System default", None)
        if self.audio_manager is not None:
            for name in self.audio_manager.list_devices():
                self.audio_device.addItem(name, name)
        self.audio_device.blockSignals(False)
        self._sync_audio_device_selection()

    def _sync_audio_device_selection(self) -> None:
        hint = self._current_device_hint()
        index = self.audio_device.findData(hint) if hint else 0
        self.audio_device.blockSignals(True)
        self.audio_device.setCurrentIndex(max(index, 0))
        self.audio_device.blockSignals(False)

    def _on_audio_device_changed(self, index: int) -> None:
        device = self.audio_device.itemData(index)
        if self.audio_manager is not None:
            self.audio_manager.set_device(device)
        self._save_config()

    def _on_refresh_audio_devices_clicked(self) -> None:
        self._populate_audio_devices()

    def _update_play_button_text(self) -> None:
        playing = self.audio_manager is not None and self.audio_manager.is_file_playing
        self.play_file_btn.setText("Stop" if playing else "Play")

    def _update_record_loop_button_text(self) -> None:
        if self.audio_manager is not None and self.audio_manager.is_looping:
            self.record_loop_btn.setText("Stop loop")
        else:
            self.record_loop_btn.setText("Record 10s & loop")

    def _on_audio_source_changed(self, index: int) -> None:
        source = self.audio_source.itemData(index)
        self.config.audio.source = source
        if self.audio_manager is not None:
            if source == "file":
                self.audio_manager.switch_to_file()
            elif source == "microphone":
                self.audio_manager.switch_to_microphone()
            elif source == "desktop":
                self.audio_manager.switch_to_desktop()
        if self.render_window is not None:
            # Re-syncs the mouth-mute gate for the *new* source -- bug
            # audit addendum 2026-09-23, D4. __main__.py's own OBS
            # mute_changed handler only re-applies this gate on the
            # next actual mute *event*; switching source itself doesn't
            # fire one, so without this, muting on Microphone and then
            # switching to Desktop Audio would leave the mouth stuck
            # forced shut (or the reverse: switching back to Microphone
            # while OBS is already muted wouldn't re-close it until OBS
            # toggled mute again). self._obs_muted is this panel's own
            # live-tracked OBS mute state (see _on_obs_mute_changed),
            # the same value its status label already reflects.
            self.render_window.set_muted(self._obs_muted and source == "microphone")
        self._sync_audio_device_selection()
        self._update_source_controls_enabled()
        self._update_play_button_text()
        self._update_record_loop_button_text()
        self._save_config()

    def _on_record_loop_clicked(self) -> None:
        if self.audio_manager is None:
            return
        if self.audio_manager.is_looping:
            self.audio_manager.stop_loop()
            self._update_record_loop_button_text()
            index = self.audio_source.findData(self.config.audio.source)
            self.audio_source.setCurrentIndex(max(index, 0))
        else:
            self.audio_manager.start_recording_and_loop(duration_s=10.0)

    def _on_recording_started(self) -> None:
        self.record_loop_btn.setEnabled(False)
        self.record_loop_btn.setText("Recording… 10s")
        self._recording_deadline = time.monotonic() + 10.0
        self._recording_countdown_timer.start(200)

    def _on_recording_tick(self) -> None:
        remaining = max(0.0, self._recording_deadline - time.monotonic())
        self.record_loop_btn.setText(f"Recording… {remaining:.0f}s")
        if remaining <= 0:
            self._recording_countdown_timer.stop()

    def _on_recording_finished(self) -> None:
        self._recording_countdown_timer.stop()
        self.record_loop_btn.setEnabled(True)
        self._update_record_loop_button_text()

    def _on_calibrate_noise_gate_clicked(self) -> None:
        if self.audio_manager is None:
            return
        self.audio_manager.calibrate_noise_gate(duration_s=3.0)

    def _on_calibration_started(self) -> None:
        self._calibrate_gate_btn.setEnabled(False)
        self._calibrate_gate_btn.setText("Calibrating… stay quiet")

    def _on_calibration_finished(self, new_gate: float) -> None:
        self._calibrate_gate_btn.setEnabled(True)
        self._calibrate_gate_btn.setText("Calibrate noise gate (3s of quiet)")
        # Goes through the spin box's own setValue, not
        # self.config.audio.noise_gate directly -- that's what triggers
        # its existing valueChanged -> _setter chain (persists via
        # _save_config, same as any other hand-typed edit to this field).
        self.noise_gate_field.setValue(new_gate)

    def _on_browse_audio_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose an audio or video file",
            "",
            "Audio/video files (*.wav *.mp3 *.m4a *.flac *.ogg *.aac *.mp4 *.mov *.mkv *.webm);;All files (*)",
        )
        if not path:
            return
        self.config.audio.file_path = path
        self.audio_file_label.setText(self._elided_file_label())
        self.audio_file_label.setToolTip(path)
        self.audio_file_label.setVisible(True)
        if self.audio_manager is not None and self.config.audio.source == "file":
            self.audio_manager.switch_to_file(path)
        self._update_source_controls_enabled()
        self._save_config()

    def _on_play_file_clicked(self) -> None:
        if self.audio_manager is None:
            return
        if self.audio_manager.is_file_playing:
            self.audio_manager.stop_file()
        else:
            self.audio_manager.play_file()
        self._update_play_button_text()

    def _on_rewind_file_clicked(self) -> None:
        if self.audio_manager is None:
            return
        # Only while actually playing -- see the button's own comment
        # above. A stopped file is already sitting at 0:00 for the next
        # Play, so restarting playback here would be an unrequested
        # auto-play, not a rewind.
        if not self.audio_manager.is_file_playing:
            return
        self.audio_manager.play_file()
        self._update_play_button_text()

    def _on_file_playback_stopped(self) -> None:
        self._update_play_button_text()

    def _on_mute_mouth_toggled(self, checked: bool) -> None:
        if self.render_window is not None:
            self.render_window.set_manual_muted(checked)
        self._mute_mouth_btn.setText("Mouth muted" if checked else "Mute mouth")

    def _on_device_resolved(self, name: str) -> None:
        if name:
            self._now_capturing_label.setText(f"Now capturing: {name}")
            self._now_capturing_label.setVisible(True)
        else:
            self._now_capturing_label.setVisible(False)

    # =====================================================================
    # Envelope threshold ordering warning
    # =====================================================================

    def _refresh_threshold_warning(self) -> None:
        """Warns, live, when the Envelope thresholds cross the ordering
        `update_speaking` (audio.py) assumes -- mild_close <= mild_open
        <= wide_open, and wide_close <= wide_open. Owner's request,
        2026-09-23 (bug audit finding #20, "no threshold ordering
        checks"): a crossed pair doesn't crash, it just makes a band
        unreachable or makes it flap, so this surfaces the problem
        instead of live-clamping values the owner just typed."""
        mild_open = self.mild_open.value()
        mild_close = self.mild_close.value()
        wide_open = self.wide_open.value()
        wide_close = self.wide_close.value()

        problems = []
        if mild_close > mild_open:
            problems.append('"Mild: close below" is above "Mild: open above"')
        if mild_open > wide_open:
            problems.append('"Mild: open above" is above "Wide: open above"')
        if wide_close > wide_open:
            problems.append('"Wide: close below" is above "Wide: open above"')

        if problems:
            self._threshold_warning_label.setText(
                "Warning: " + "; ".join(problems) + " -- that band may be unreachable or flap."
            )
        self._threshold_warning_label.setVisible(bool(problems))

    # =====================================================================
    # OBS mute awareness
    # =====================================================================

    def _obs_status_text(self, connected: bool, muted: bool = False) -> str:
        if not connected:
            # ObsLinkManager._start() itself declines to even attempt a
            # connection with no Input name set (owner's report,
            # 2026-09-19: turning the checkbox on first produced a raw,
            # confusing obs-websocket error instead) -- surfaced here too,
            # so the status label says *why* rather than leaving "Not
            # connected" looking identical to "OBS just isn't running."
            if self.obs_enabled.isChecked() and not self.config.obs.input_name.strip():
                return "Not connected -- enter an Input name above"
            return "Not connected"
        return "Connected -- muted" if muted else "Connected -- not muted"

    def _refresh_obs_status_label(self) -> None:
        self.obs_status_label.setText(self._obs_status_text(self._obs_connected, self._obs_muted))

    def _on_obs_enabled_toggled(self, checked: bool) -> None:
        if self.obs_link_manager is not None:
            self.obs_link_manager.set_enabled(checked)
        else:
            self.config.obs.enabled = checked
        self._refresh_obs_status_label()
        self._save_config()

    def _on_obs_connection_field_changed(self) -> None:
        self.config.obs.host = self.obs_host.text()
        self.config.obs.port = self.obs_port.value()
        self.config.obs.password = self.obs_password.text()
        self.config.obs.input_name = self.obs_input_name.text()
        if self.obs_link_manager is not None:
            self.obs_link_manager.restart()
        self._refresh_obs_status_label()
        self._save_config()

    def _on_obs_connection_changed(self, connected: bool) -> None:
        self._obs_connected = connected
        if not connected:
            self._obs_muted = False
        self._refresh_obs_status_label()

    def _on_obs_mute_changed(self, muted: bool) -> None:
        self._obs_muted = muted
        self._refresh_obs_status_label()

    # =====================================================================
    # Display
    # =====================================================================

    def _on_background_changed(self, index: int) -> None:
        mode = self.background.itemData(index)
        self.config.window.background = mode
        if self.render_window is not None:
            self.render_window.set_background(mode)
        self._update_background_controls_visible()
        self._save_config()

    def _current_background_path(self) -> str:
        if self.config.window.background == "image":
            return self.config.window.background_image_path
        if self.config.window.background == "video":
            return self.config.window.background_video_path
        return ""

    def _update_background_controls_visible(self) -> None:
        mode = self.config.window.background
        show = mode in ("image", "video")
        self._background_browse_btn.setVisible(show)
        path = self._current_background_path()
        self.background_file_label.setVisible(show and bool(path))
        self.background_file_label.setText(self._elided_file_label(path))
        self.background_file_label.setToolTip(path or "No file chosen yet -- click Browse….")

    def _on_browse_background_file(self) -> None:
        mode = self.config.window.background
        if mode == "image":
            path, _ = QFileDialog.getOpenFileName(
                self, "Choose a background image", "",
                "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*)",
            )
        elif mode == "video":
            path, _ = QFileDialog.getOpenFileName(
                self, "Choose a background video", "",
                "Video files (*.mp4 *.mov *.mkv *.webm *.avi);;All files (*)",
            )
        else:
            return
        if not path:
            return
        if mode == "image":
            self.config.window.background_image_path = path
        else:
            self.config.window.background_video_path = path
        if self.render_window is not None:
            self.render_window.set_background(mode, path)
        self._update_background_controls_visible()
        self._save_config()

    def _on_zoom_changed(self, value: float) -> None:
        # Lazy, once-per-editing-session undo push -- same pattern
        # _on_property_changed uses for continuous sprite fields (see
        # _undo_pending_for_selection), so dragging/scrolling this spinbox
        # doesn't flood the undo stack with one entry per tick.
        if self._zoom_undo_pending:
            self.push_undo_snapshot()
            self._zoom_undo_pending = False
        self.rig.zoom = value
        self._mark_dirty()
        if self.render_window is not None:
            self.render_window.set_zoom(value)

    def _on_zoom_editing_finished(self) -> None:
        self._zoom_undo_pending = True
        self._save_config()

    # =====================================================================
    # Expressions
    # =====================================================================

    def _manual_expression_pairs(self) -> list[tuple[str, str]]:
        return sorted({
            (s.group_name, s.state_name)
            for s in self.rig.sprites
            if s.manual_driven and s.group_name and s.state_name
        })

    def _refresh_expressions_section(self) -> None:
        while self._expressions_layout.count():
            child = self._expressions_layout.takeAt(0)
            if child.widget() is not None:
                child.widget().setParent(None)
        self._expression_buttons.clear()

        pairs = self._manual_expression_pairs()
        if self.render_window is not None:
            # Drop any live override whose (group, state) no longer
            # matches a pair that actually exists in the current rig --
            # e.g. after Load swapped to a different avatar. Left alone,
            # a stale override keeps suppressing any *future* sprite
            # that happens to share its group_name (render.py's
            # suppressed_by_other_expression), invisibly, with no button
            # left in this section to ever toggle it back off (bug audit
            # 2026-09-23, #9).
            pairs_set = set(pairs)
            stale_groups = [
                group for group, state in self.render_window.manual_overrides.items()
                if (group, state) not in pairs_set
            ]
            for group in stale_groups:
                self.render_window.set_manual_override(group, None)
        if pairs:
            for group, state in pairs:
                btn = QPushButton(f"{group}: {state}")
                btn.setCheckable(True)
                # Restore checked state from the live override rather
                # than always starting unchecked -- bug audit 2026-09-23,
                # #9: this section rebuilds (destroying every button) on
                # every property edit, Load, and hot reload, so without
                # this an expression that's still actively forced live
                # showed its button as off, needing an extra click to
                # turn back on before it could be turned off again.
                if self.render_window is not None and self.render_window.manual_overrides.get(group) == state:
                    btn.setChecked(True)
                btn.setToolTip(
                    f"Forces every sprite tagged Group name {group!r}, State\n"
                    f"name {state!r} to show, live, on the real Render Window\n"
                    f"(and OBS) -- click again to turn it off. Only one state\n"
                    f"per group can be forced at a time."
                )
                btn.toggled.connect(self._make_expression_toggle_handler(group, state))
                self._expressions_layout.addWidget(btn)
                self._expression_buttons[(group, state)] = btn
        else:
            self._expressions_layout.addWidget(self._expressions_placeholder)

        # This section's content (and so its real height) just changed --
        # re-cap it against the splitter it lives in, or a stale cap from
        # before this tagging/untagging would leave dead space below it
        # (or clip a newly-added button) until some *other* section
        # happens to toggle collapsed and trigger a resync incidentally.
        # Deferred with singleShot(0), not called inline here -- sizeHint()
        # right after addWidget()/takeAt() above can still answer with the
        # *previous* layout's cached geometry until Qt actually finishes
        # processing the pending layout pass (confirmed empirically: even
        # an explicit self._expressions_layout.activate() right before the
        # resync wasn't enough); the standard Qt fix for "just changed a
        # layout, need its real sizeHint" is to let the event loop settle
        # first. Re-fetches the section fresh rather than closing over it,
        # in case this section no longer exists (or isn't in a splitter
        # yet) by the time this actually runs.
        def _resync_expressions_section_now() -> None:
            section = self._sections.get("Expressions")
            if section is not None and isinstance(section.parent(), QSplitter):
                self._resync_tab_splitter_sizes(section.parent())

        QTimer.singleShot(0, _resync_expressions_section_now)

    def _make_expression_toggle_handler(self, group: str, state: str) -> Callable[[bool], None]:
        def on_toggled(checked: bool) -> None:
            if checked:
                for (other_group, other_state), other_btn in self._expression_buttons.items():
                    if other_group == group and other_state != state and other_btn.isChecked():
                        other_btn.blockSignals(True)
                        other_btn.setChecked(False)
                        other_btn.blockSignals(False)
                if self.render_window is not None:
                    self.render_window.set_manual_override(group, state)
            elif self.render_window is not None:
                self.render_window.set_manual_override(group, None)

        return on_toggled

    # =====================================================================
    # Costume & Expression hotkey editors
    # =====================================================================
    #
    # Both editors share the same shape (owner's request, 2026-09-17: "the
    # list of numbers... each number has two drop boxes and a + button"),
    # applied to two different underlying assignments:
    #   - Costumes: rig.costume_assignments[slot], each row a (hide_id,
    #     show_id) sprite pair, write-through to costume_layers (see
    #     AvatarRig.assign_costume_pair's own comment for why).
    #   - Expressions: rig.expression_hotkeys[slot], each row a single
    #     (group_name, state_name) pair -- no second box needed, since
    #     forcing a state already suppresses its own group's automatic
    #     siblings (see render.py's manual-override handling).
    # A row only becomes a real, committed assignment once it's fully
    # filled in -- clearing a combo back to "—" just leaves it incomplete,
    # it does not remove the row. Removal is its own explicit "−" button
    # on each row (owner's report, 2026-09-19: the previous "clearing a
    # box removes the row" gesture "doesn't work lol" -- not discoverable,
    # replaced with simple +/− buttons instead).

    def _sprite_label(self, sprite: Sprite) -> str:
        name = sprite.path.rsplit("/", 1)[-1]
        return f"{name} ({sprite.id})"

    def _find_combo_index_by_data(self, combo: QComboBox, value) -> int:
        # Not combo.findData(value) -- reliable for the plain ints the
        # rest of this app already uses it for, but not trusted here for
        # the expression combo's tuple userData (QVariant-wrapped
        # arbitrary Python object equality isn't guaranteed the same way).
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                return i
        return 0

    def _populate_costume_sprite_combo(self, combo: QComboBox, current_id: int | None) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("—", None)
        for sprite in self.rig.sprites:
            combo.addItem(self._sprite_label(sprite), sprite.id)
        combo.setCurrentIndex(max(combo.findData(current_id), 0))
        combo.blockSignals(False)

    def _build_costume_pair_row(self, slot: int, hide_id: int | None, show_id: int | None) -> QWidget:
        # Hide and Show stacked vertically, not side by side -- two full
        # sprite-name dropdowns ("clothes_hoodie_front.png (5)") sharing
        # one row needed more width than a realistic (non-maximized)
        # panel actually has, forcing a horizontal scrollbar (found from
        # the owner's own screenshot, 2026-09-17; capping each combo's own
        # width first still wasn't enough at a narrower stress-tested
        # width). Stacked, each combo only ever competes with its own
        # short label for width, so this can't happen regardless of panel
        # width -- costs one extra line per pair, not a real tradeoff
        # against actually working.
        row = QWidget()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(16, 0, 0, 0)
        hide_row = QHBoxLayout()
        show_row = QHBoxLayout()
        hide_combo = QComboBox()
        show_combo = QComboBox()
        self._populate_costume_sprite_combo(hide_combo, hide_id)
        self._populate_costume_sprite_combo(show_combo, show_id)
        hide_combo.setToolTip("Hidden by default -- shown while this costume is active.")
        show_combo.setToolTip("Shown by default -- hidden while this costume is active.")
        # Labels name what this costume *does* to the picked sprite, not
        # its default state -- "Hide" under hide_combo read backwards
        # (owner's report, 2026-09-19: "show/hide labels in costumes seem
        # backwards"): hide_combo's sprite is the one this costume SHOWS
        # (it's hidden everywhere else), and show_combo's sprite is the
        # one this costume HIDES (shown everywhere else). Only the labels
        # swap here -- hide_combo/show_combo and the underlying
        # hide_id/show_id data (see assign_costume_pair) keep their
        # existing, correct meaning.
        remove_btn = QPushButton("−")
        remove_btn.setFixedWidth(28)
        remove_btn.setToolTip("Remove this swap.")
        hide_row.addWidget(QLabel("Show"))
        hide_row.addWidget(hide_combo, 1)
        hide_row.addWidget(remove_btn)
        show_row.addWidget(QLabel("Hide"))
        show_row.addWidget(show_combo, 1)
        row_layout.addLayout(hide_row)
        row_layout.addLayout(show_row)
        row.hide_combo = hide_combo
        row.show_combo = show_combo
        row.committed = (hide_id, show_id) if hide_id is not None and show_id is not None else None
        hide_combo.currentIndexChanged.connect(lambda _checked=False, s=slot, r=row: self._on_costume_row_changed(s, r))
        show_combo.currentIndexChanged.connect(lambda _checked=False, s=slot, r=row: self._on_costume_row_changed(s, r))
        remove_btn.clicked.connect(lambda _checked=False, s=slot, r=row: self._on_remove_costume_row_clicked(s, r))
        return row

    def _add_costume_row(self, slot: int, hide_id: int | None = None, show_id: int | None = None) -> None:
        row = self._build_costume_pair_row(slot, hide_id, show_id)
        # Inserted as a whole new list item, immediately before this
        # slot's "+ Add swap" item -- not appended into a variable-length
        # inner layout inside an existing item (see _build_costumes_tab's
        # own comment for why that was dropped).
        insert_at = self.costume_list.row(self._costume_add_button_items[slot])
        item = QListWidgetItem()
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.costume_list.insertItem(insert_at, item)
        item.setSizeHint(row.sizeHint())
        self.costume_list.setItemWidget(item, row)
        self._costume_rows[slot].append(row)
        self._costume_row_items[slot].append(item)

    def _remove_costume_row(self, slot: int, row: QWidget) -> None:
        index = self._costume_rows[slot].index(row)
        self._costume_rows[slot].pop(index)
        item = self._costume_row_items[slot].pop(index)
        self.costume_list.takeItem(self.costume_list.row(item))
        row.setParent(None)
        row.deleteLater()

    def _on_costume_row_changed(self, slot: int, row: QWidget) -> None:
        self.push_undo_snapshot()
        hide_id = row.hide_combo.currentData()
        show_id = row.show_combo.currentData()
        row.committed = (hide_id, show_id) if hide_id is not None and show_id is not None else None
        self._resync_costume_slot(slot)

    def _on_remove_costume_row_clicked(self, slot: int, row: QWidget) -> None:
        self.push_undo_snapshot()
        self._remove_costume_row(slot, row)
        self._resync_costume_slot(slot)

    def _resync_costume_slot(self, slot: int) -> None:
        """Rebuilds rig.costume_assignments[slot] (and its write-through
        to costume_layers) from the current row widgets -- simpler and
        less bug-prone than tracking incremental add/edit/remove by list
        index, which drifts as rows are added/removed out of order."""
        for hide_id, show_id in list(self.rig.costume_assignments[slot]):
            for sprite_id in (hide_id, show_id):
                sprite = self.rig.by_id(sprite_id)
                if sprite is not None:
                    sprite.costume_layers = with_costume_layer(sprite.costume_layers, slot, True)
        self.rig.costume_assignments[slot] = []
        for row in self._costume_rows[slot]:
            hide_id = row.hide_combo.currentData()
            show_id = row.show_combo.currentData()
            if hide_id is not None and show_id is not None:
                self.rig.assign_costume_pair(slot, hide_id, show_id)
        self._mark_dirty()

    def _populate_expression_combo(self, combo: QComboBox, current: tuple[str, str] | None) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("—", None)
        for group, state in self._manual_expression_pairs():
            combo.addItem(f"{group}: {state}", (group, state))
        combo.setCurrentIndex(self._find_combo_index_by_data(combo, current))
        combo.blockSignals(False)

    def _build_expression_hotkey_row(self, slot: int, pair: tuple[str, str] | None) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(16, 0, 0, 0)
        combo = QComboBox()
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(14)
        self._populate_expression_combo(combo, pair)
        combo.setToolTip(
            "Forces this Expression on while this hotkey slot is toggled\n"
            "on, exactly like clicking its button in the Sprites tab's\n"
            "Expressions section (they share the same live state)."
        )
        remove_btn = QPushButton("−")
        remove_btn.setFixedWidth(28)
        remove_btn.setToolTip("Remove this hotkey assignment.")
        row_layout.addWidget(QLabel("Force"))
        row_layout.addWidget(combo, 1)
        row_layout.addWidget(remove_btn)
        row.combo = combo
        row.committed = pair
        combo.currentIndexChanged.connect(lambda _checked=False, s=slot, r=row: self._on_expression_hotkey_row_changed(s, r))
        remove_btn.clicked.connect(lambda _checked=False, s=slot, r=row: self._on_remove_expression_hotkey_row_clicked(s, r))
        return row

    def _add_expression_hotkey_row(self, slot: int, pair: tuple[str, str] | None = None) -> None:
        row = self._build_expression_hotkey_row(slot, pair)
        insert_at = self.expression_hotkey_list.row(self._expression_add_button_items[slot])
        item = QListWidgetItem()
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.expression_hotkey_list.insertItem(insert_at, item)
        item.setSizeHint(row.sizeHint())
        self.expression_hotkey_list.setItemWidget(item, row)
        self._expression_hotkey_rows[slot].append(row)
        self._expression_row_items[slot].append(item)

    def _remove_expression_hotkey_row(self, slot: int, row: QWidget) -> None:
        index = self._expression_hotkey_rows[slot].index(row)
        self._expression_hotkey_rows[slot].pop(index)
        item = self._expression_row_items[slot].pop(index)
        self.expression_hotkey_list.takeItem(self.expression_hotkey_list.row(item))
        row.setParent(None)
        row.deleteLater()

    def _on_expression_hotkey_row_changed(self, slot: int, row: QWidget) -> None:
        self.push_undo_snapshot()
        row.committed = row.combo.currentData()
        self._resync_expression_hotkey_slot(slot)

    def _on_remove_expression_hotkey_row_clicked(self, slot: int, row: QWidget) -> None:
        self.push_undo_snapshot()
        self._remove_expression_hotkey_row(slot, row)
        self._resync_expression_hotkey_slot(slot)

    def _resync_expression_hotkey_slot(self, slot: int) -> None:
        self.rig.expression_hotkeys[slot] = []
        for row in self._expression_hotkey_rows[slot]:
            value = row.combo.currentData()
            if value is not None:
                group, state = value
                self.rig.assign_expression_hotkey(slot, group, state)
        self._mark_dirty()

    def _add_list_item_widget(self, list_widget: QListWidget, widget: QWidget) -> QListWidgetItem:
        """Same technique the Sprites tab's own Layer List already uses
        (QListWidgetItem + setItemWidget) -- see _build_costumes_tab's own
        comment for why this replaced an earlier QScrollArea-based
        attempt. Not selectable: these rows aren't things to select, just
        containers."""
        item = QListWidgetItem()
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        list_widget.addItem(item)
        item.setSizeHint(widget.sizeHint())
        list_widget.setItemWidget(item, widget)
        return item

    def _trigger_expression_hotkey(self, slot: int) -> None:
        """Shift+<number> (see the QShortcut wiring in __init__) --
        toggles every Expression button assigned to this slot, reusing
        the buttons' own existing toggle handler (_make_expression_toggle_
        handler) rather than duplicating its group-exclusivity logic, so
        a hotkey press and a real click always stay in sync."""
        if _is_input_widget_focused():
            return
        for group, state in self.rig.expression_hotkeys[slot]:
            btn = self._expression_buttons.get((group, state))
            if btn is not None:
                btn.click()

    def _trigger_costume_hotkey(self, slot: int) -> None:
        """Plain 1-9,0 (see the QShortcut wiring in __init__) -- same
        effect as render.py's own keyPressEvent handling for these keys,
        just triggerable from the Control Panel too."""
        if _is_input_widget_focused():
            return
        self.rig.active_costume = slot

    def _rebuild_costume_and_expression_editors(self) -> None:
        """Full rebuild from rig.costume_assignments/expression_hotkeys --
        called at the end of _rebuild_scene() (covers load, undo/redo,
        add/remove/duplicate sprite, hot reload, and initial construction,
        in one place), since the dropdown options (every sprite; every
        tagged Expression) and the assignments shown both depend on what
        currently exists in the rig."""
        for slot in range(NUM_COSTUMES):
            for row in list(self._costume_rows[slot]):
                self._remove_costume_row(slot, row)
            for hide_id, show_id in self.rig.costume_assignments[slot]:
                self._add_costume_row(slot, hide_id, show_id)

            for row in list(self._expression_hotkey_rows[slot]):
                self._remove_expression_hotkey_row(slot, row)
            for group, state in self.rig.expression_hotkeys[slot]:
                self._add_expression_hotkey_row(slot, (group, state))
