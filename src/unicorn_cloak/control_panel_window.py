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
    QPen,
    QPixmap,
    QRadialGradient,
    QShortcut,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
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
from .rig import NUM_COSTUMES, AvatarRig, Sprite, duplicate_sprite
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

_BACKGROUND_LABELS = {
    "transparent": "Transparent (see-through to OBS -- normal setup)",
    "black": "Black",
    "white": "White",
    "green": "Green (chroma key)",
    "image": "Image (choose a file below)",
    "video": "Video, looping (choose a file below)",
}


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
_HANDLE_HALF = 6.0
_ROTATE_HANDLE_DISTANCE = 28.0


class EditableSpriteItem(QGraphicsPixmapItem):
    def __init__(self, sprite: Sprite, pixmap: QPixmap, panel: "ControlPanelWindow", parent=None) -> None:
        super().__init__(pixmap, parent)
        self.sprite = sprite
        self._panel = panel
        self._active_handle: str | None = None
        self.setOffset(-pixmap.width() / 2 + sprite.offset[0], -pixmap.height() / 2 + sprite.offset[1])
        self.setZValue(sprite.z_index)
        self.setFlag(QGraphicsItem.ItemStacksBehindParent, sprite.z_index < 0)
        if sprite.clipped:
            self.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
            self.setShapeMode(QGraphicsPixmapItem.ShapeMode.MaskShape)
        self.setTransformationMode(Qt.SmoothTransformation)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
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
            # Extended upward to include the rotate handle, which floats
            # above the pixmap's own top edge -- Qt clips paint()/hit-
            # testing to whatever boundingRect() reports, so the handle
            # would otherwise be half-invisible and half-unclickable.
            rect = rect.adjusted(0, -(_ROTATE_HANDLE_DISTANCE + _HANDLE_HALF), 0, 0)
        return rect

    def _handle_rects(self) -> dict[str, QRectF]:
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
        accent = QColor(theme.MAGENTA_500)
        pen = QPen(accent)
        pen.setWidth(2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = self._pixmap_rect()
        painter.drawRect(rect)
        handles = self._handle_rects()
        top_center = QPointF(rect.center().x(), rect.top())
        painter.drawLine(top_center, handles["rotate"].center())
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
        self._panel.push_undo_snapshot()
        handle = self._handle_at(event.pos())
        if handle is not None:
            self._active_handle = handle
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._active_handle is not None:
            self._drag_handle(event.pos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._active_handle = None
        super().mouseReleaseEvent(event)

    def _drag_handle(self, local_pos: QPointF) -> None:
        # `local_pos` (a mouse event's .pos()) is already expressed in
        # this item's own, untransformed local coordinate system -- Qt
        # inverse-maps through the item's *current* transform (whatever
        # rotation/scale is already applied) to produce it, verified
        # empirically 2026-09-17. That means these formulas compute the
        # new absolute rotation/scale directly from the current mouse
        # position, with no incremental delta-tracking needed: dividing
        # the still-original, unscaled corner point into the current
        # local mouse position gives exactly the scale factor that would
        # place that corner under the cursor, and atan2 against the
        # origin gives exactly the angle that would place the rotate
        # handle under the cursor -- regardless of whatever rotation/
        # scale was already in effect before this drag started.
        if self._active_handle == "rotate":
            # 0 deg = straight up from the origin (this item's pivot,
            # i.e. Position -- see rig.Sprite's Position/Offset comment);
            # verified empirically against QTransform.rotate's own sign
            # convention (positive = clockwise in Qt's y-down coordinate
            # system) rather than assumed.
            angle = math.degrees(math.atan2(local_pos.x(), -local_pos.y()))
            self.sprite.rotation_deg = angle
            self._apply_authored_transform()
            self._panel.on_sprite_rotated(self.sprite)
            return

        corner = {
            "tl": self._pixmap_rect().topLeft(), "tr": self._pixmap_rect().topRight(),
            "bl": self._pixmap_rect().bottomLeft(), "br": self._pixmap_rect().bottomRight(),
        }[self._active_handle]
        if abs(corner.x()) < 1e-6 or abs(corner.y()) < 1e-6:
            return  # a zero-size pixmap dimension has no meaningful corner to scale from
        new_scale_x = local_pos.x() / corner.x()
        new_scale_y = local_pos.y() / corner.y()
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


class GridCanvasView(QGraphicsView):
    """The edit canvas, plus an optional grid overlay -- replaces the
    earlier single-crosshair "origin guides" (owner's request,
    2026-09-17: "origin guide change to 'grid', add grid lines @ 100px
    intervals"). Drawn in drawForeground() so it survives scene.clear()
    with no recreate-it-every-time bookkeeping, and can never be
    accidentally selected or dragged like a real item could. The origin
    axes (through scene (0, 0), where a root-level sprite's own Position
    of (0, 0) sits) are still drawn, brighter than the rest of the grid,
    so that reference point stays easy to find at a glance."""

    show_grid = False
    grid_spacing_px = 100

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
        autosave_interval_ms: int = AUTOSAVE_INTERVAL_MS,
    ) -> None:
        super().__init__()
        self.rig = rig
        self.config = config
        self.render_window = render_window
        self._state_path = state_path
        self.audio_manager = audio_manager
        self.obs_link_manager = obs_link_manager

        # --- sprite-editing state (was EditorWindow) ---
        self._items: dict[int, EditableSpriteItem] = {}
        self._rebuilding_scene = False
        self._selected_id: int | None = None
        self._updating_form = False
        self._undo_pending_for_selection = False
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

        mode_row = QHBoxLayout()
        self.canvas_mode_btn = QPushButton("Live Preview")
        self.canvas_mode_btn.setCheckable(True)
        self.canvas_mode_btn.setToolTip(
            "Live Preview mirrors the real Render Window -- reacts to your\n"
            "actual mic and blinking, read-only. Edit Sprites is the\n"
            "interactive canvas -- drag sprites to position them, driven by\n"
            "the Preview state controls below instead of live audio.\n"
            "Neither view is captured by OBS; only the Render Window is."
        )
        self.canvas_mode_btn.toggled.connect(self._on_canvas_mode_toggled)
        mode_row.addWidget(self.canvas_mode_btn)
        mode_row.addStretch(1)
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
        # Root cause, 2026-09-17, owner's report ("the behavior tab
        # started all collapsed & centered"): once every section in a
        # splitter is collapsed, QSplitter's own effective maximumHeight
        # shrinks to the sum of its (now Maximum-policy) children's
        # sizeHints -- a plain QVBoxLayout, with no alignment set,
        # centers a child that can't grow to fill the space it's given
        # rather than pegging it to the top. This only actually shows up
        # once QTabWidget performs a real layout pass on the page (i.e.
        # once that tab is actually switched to) -- confirmed empirically
        # by comparing the splitter's own geometry before vs. after
        # switching to it, not assumed. AlignTop is a no-op whenever the
        # splitter *can* fill the available height (any section
        # expanded), since alignment only matters once a widget is
        # smaller than its allotted space -- so this doesn't affect the
        # normal, mostly-expanded case at all.
        outer.setAlignment(splitter, Qt.AlignmentFlag.AlignTop)

    def _on_section_collapsed_changed(
        self, splitter: QSplitter, section: CollapsibleSection, collapsed: bool
    ) -> None:
        self._resync_tab_splitter_sizes(splitter)
        if not collapsed:
            self._make_room_if_needed(splitter, section)

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
                sizes.append(pane.sizeHint().height())
            else:
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
        self.tabs.addTab(self._build_sprites_tab(), "Sprites")
        self.tabs.addTab(self._build_behavior_tab(), "Behavior")
        self.tabs.addTab(self._build_audio_tab(), "Audio")
        self.tabs.addTab(self._build_application_tab(), "Application")
        root.addWidget(self.tabs, stretch=3)

    def _build_sprites_tab(self) -> QWidget:
        layer_section = CollapsibleSection("Layer List")
        self.sprite_list = QListWidget()
        self.sprite_list.setToolTip(
            "Every sprite in this avatar, listed front-to-back -- top of\n"
            "the list is drawn in front of (on top of) everything below it.\n"
            "Indentation shows parent/child grouping. Click to select."
        )
        self.sprite_list.currentItemChanged.connect(self._on_list_selection_changed)
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
        state_form = QFormLayout()
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
        state_form.addRow("Group name", self.group_name)
        state_form.addRow("State name", self.state_name)
        state_form.addRow(self.manual_driven)
        state_form.addRow("Talk state", self.talk_state)
        state_form.addRow("Blink state", self.blink_state)
        for widget in (self.group_name, self.state_name, self.talk_state, self.blink_state):
            label = state_form.labelForField(widget)
            if label is not None:
                label.setToolTip(widget.toolTip())
        state_section.body_layout.addLayout(state_form)

        self.talk_state.currentIndexChanged.connect(self._on_property_changed)
        self.blink_state.currentIndexChanged.connect(self._on_property_changed)
        self.manual_driven.toggled.connect(self._on_manual_driven_toggled)
        # editTextChanged, not currentIndexChanged: verified empirically
        # that for an editable QComboBox, picking an existing item fires
        # both, but typing a brand-new value that isn't in the list fires
        # only editTextChanged.
        self.group_name.editTextChanged.connect(self._on_group_name_changed)
        self.state_name.editTextChanged.connect(self._on_property_changed)

        self._per_sprite_widgets.extend(
            (self.group_name, self.state_name, self.manual_driven, self.talk_state, self.blink_state)
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
            motion_form, "Gravity", 0.0, 5000.0, 10.0, 0,
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
        zoom_form = QFormLayout()
        self.zoom = ScrollSafeDoubleSpinBox()
        self.zoom.setRange(0.1, 5.0)
        self.zoom.setSingleStep(0.05)
        self.zoom.setDecimals(2)
        self.zoom.setValue(self.config.window.zoom)
        zoom_tooltip = (
            "Scales the whole avatar bigger/smaller within the Render\n"
            "Window, around its own center -- doesn't change the window's\n"
            "own size, and applies no matter which sprite (if any) is\n"
            "selected below. 1.0 = normal size."
        )
        self.zoom.setToolTip(zoom_tooltip)
        self.zoom.valueChanged.connect(self._on_zoom_changed)
        self._add_row_with_reset_and_lock(
            zoom_form, "Zoom (whole avatar)", self.zoom,
            self._default_for(self.config.window, "zoom"), zoom_tooltip,
        )
        position_section.body_layout.addLayout(zoom_form)

        self.property_form = QFormLayout()
        self.pos_x = self._spin(-4000, 4000)
        self.pos_y = self._spin(-4000, 4000)
        self.offset_x = self._spin(-4000, 4000)
        self.offset_y = self._spin(-4000, 4000)
        self.z_index = QSpinBox()
        self.z_index.setRange(-1000, 1000)
        self.parent_combo = QComboBox()

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
        self.rotation = self._spin(-360.0, 360.0)
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
        # scales x & y maintaining proportions." A toggle QPushButton, not
        # a checkbox -- matches Guide/Ghost's own established convention
        # in this app. Linking is handled in _on_scale_x/y_changed, not
        # here; this row just lays the three widgets out.
        self.scale_x = self._spin(0.01, 100.0)
        self.scale_y = self._spin(0.01, 100.0)
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
            "While on (default), editing Scale X or Scale Y updates the\n"
            "other to match, so the sprite always scales proportionally.\n"
            "Turn off to stretch width and height independently."
        )
        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("X"))
        scale_row.addWidget(self.scale_x)
        scale_row.addWidget(QLabel("Y"))
        scale_row.addWidget(self.scale_y)
        scale_row.addWidget(self.scale_lock)
        self.property_form.addRow("Scale", scale_row)
        position_section.body_layout.addLayout(self.property_form)

        animation_section = CollapsibleSection("Animation", collapsed=True)
        self.animation_form = QFormLayout()
        self.frames = QSpinBox()
        self.frames.setRange(1, 60)
        self.anim_speed = self._spin(0.0, 60.0)
        self.variant = QSpinBox()
        self.variant.setRange(0, 9)
        self.frames.setToolTip(
            "Number of equal-width frames in this sprite's image, for a\n"
            "simple looping animation. 1 = a plain static image."
        )
        self.anim_speed.setToolTip(
            "Animation speed in frames per second. Only matters if Frames is greater than 1."
        )
        self.variant.setToolTip(
            "Alternation slot for sprites that share the same Talk state\n"
            "(e.g. two \"mild\" mouths) -- they take turns showing, cycling\n"
            "0, 1, 2... at this tab's \"Mouth alternate rate\". A Talk state\n"
            "with only one sprite in it ignores this."
        )
        self.animation_form.addRow("Frames", self.frames)
        self.animation_form.addRow("Anim speed (fps)", self.anim_speed)
        self.animation_form.addRow("Variant", self.variant)
        animation_section.body_layout.addLayout(self.animation_form)

        property_fields = (
            self.pos_x, self.pos_y, self.offset_x, self.offset_y, self.z_index, self.parent_combo,
            self.rotation, self.scale_x, self.scale_y, self.scale_lock,
            self.frames, self.anim_speed, self.variant,
        )
        for form, fields in (
            (self.property_form, (self.pos_x, self.pos_y, self.offset_x, self.offset_y, self.z_index, self.parent_combo, self.rotation)),
            (self.animation_form, (self.frames, self.anim_speed, self.variant)),
        ):
            for field_widget in fields:
                label = form.labelForField(field_widget)
                if label is not None:
                    label.setToolTip(field_widget.toolTip())
        for box in (self.pos_x, self.pos_y, self.offset_x, self.offset_y, self.z_index, self.rotation, self.variant, self.anim_speed):
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

        tab = QWidget()
        outer = QVBoxLayout(tab)
        self._add_tab_splitter(outer, [motion_section, position_section, animation_section])
        return tab

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
        self._add_double(
            envelope_form, "Noise gate", 0.0, 0.5, 0.001, 4,
            self.config.audio, "noise_gate",
            "RMS volume below this is treated as silence -- filters out\n"
            "mic hiss and room noise so it never registers as speech.",
        )
        self._add_double(
            envelope_form, "Mild: open above", 0.0, 1.0, 0.001, 4,
            self.config.audio, "mild_open",
            "Volume must rise above this to open the mouth to \"mild\".",
        )
        self._add_double(
            envelope_form, "Mild: close below", 0.0, 1.0, 0.001, 4,
            self.config.audio, "mild_close",
            "Volume must fall below this to close the mouth again.\n"
            "Kept lower than \"open above\" on purpose (hysteresis) so it\n"
            "doesn't flicker open/closed right at one boundary value.",
        )
        self._add_double(
            envelope_form, "Wide: open above", 0.0, 1.0, 0.001, 4,
            self.config.audio, "wide_open",
            "Volume must rise above this for the \"wide\" (loud) mouth shape.",
        )
        self._add_double(
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
        self.obs_port.valueChanged.connect(self._on_obs_connection_field_changed)
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

        tab = QWidget()
        outer = QVBoxLayout(tab)
        self._add_tab_splitter(outer, [envelope_section, obs_section])
        return tab

    def _build_application_tab(self) -> QWidget:
        display_section = CollapsibleSection("Display")
        display_form = QFormLayout()
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

        canvas_section = CollapsibleSection("Canvas")
        canvas_form = QFormLayout()
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
        canvas_section.body_layout.addLayout(canvas_form)

        hotkeys_section = CollapsibleSection("Hotkeys — costume switching")
        hotkeys_form = QFormLayout()
        self._hotkey_edits: list[QKeySequenceEdit] = []
        for slot, key_text in enumerate(self.config.hotkeys.costume_keys[:NUM_COSTUMES]):
            edit = QKeySequenceEdit()
            edit.setMaximumSequenceLength(1)
            edit.setKeySequence(QKeySequence(key_text))
            edit.setToolTip(
                "Press a key to switch to this costume slot -- only while\n"
                "the Render Window has keyboard focus. Escape can't be\n"
                "bound here -- it always quits the app, no matter what.\n"
                "Avoid reusing the same key on two slots -- only the first\n"
                "matching slot fires. Modifiers (Ctrl/Alt/Shift) aren't\n"
                "distinguished from the plain key."
            )
            edit.keySequenceChanged.connect(self._hotkey_setter(slot, edit))
            hotkeys_form.addRow(f"Costume {slot + 1}", edit)
            self._set_label_tooltip(hotkeys_form, edit, edit.toolTip())
            self._hotkey_edits.append(edit)
        hotkeys_section.body_layout.addLayout(hotkeys_form)

        tab = QWidget()
        outer = QVBoxLayout(tab)
        self._add_tab_splitter(outer, [display_section, canvas_section, hotkeys_section])
        return tab

    # =====================================================================
    # Construction: persistent bottom bar
    # =====================================================================

    def _build_bottom_bar(self, root: QVBoxLayout) -> None:
        # Owner's request, 2026-09-17: audio source controls live in the
        # always-visible global area too, on their own bar, with the
        # chosen file's path shown (middle-elided) just below it.
        source_row = QHBoxLayout()
        self.audio_source = QComboBox()
        self.audio_source.addItem("Microphone", "microphone")
        self.audio_source.addItem("File (play a recording instead)", "file")
        self.audio_source.setToolTip(
            "What drives the mouth: a live microphone (normal setup), or a\n"
            "local audio/video file played back through this app instead --\n"
            "for driving the avatar from a pre-recorded isolated track\n"
            "while a *different* recording is what actually gets captured\n"
            "(e.g. a combined track played separately through an OBS\n"
            "Media Source). See the Help window for the full workflow."
        )
        index = self.audio_source.findData(self.config.audio.source)
        self.audio_source.setCurrentIndex(max(index, 0))
        self.audio_source.currentIndexChanged.connect(self._on_audio_source_changed)
        source_row.addWidget(self.audio_source, stretch=1)

        self.play_file_btn = QPushButton("Play")
        self.play_file_btn.setToolTip(
            "Start or stop playing the chosen file to drive the mouth.\n"
            "Silent by design -- it never plays out loud, only extracts\n"
            "the volume envelope from it in real time."
        )
        self.play_file_btn.clicked.connect(self._on_play_file_clicked)
        source_row.addWidget(self.play_file_btn)

        self._browse_file_btn = QPushButton("Browse…")
        self._browse_file_btn.setToolTip(
            "Choose an audio or video file. Its audio track drives the\n"
            "mouth once you click Play -- this app never plays its sound\n"
            "out loud, only extracts its volume, so play the actual\n"
            "recording you want captured separately (e.g. in OBS)."
        )
        self._browse_file_btn.clicked.connect(self._on_browse_audio_file)
        source_row.addWidget(self._browse_file_btn)

        self.record_loop_btn = QPushButton("Record 10s & loop")
        self.record_loop_btn.setToolTip(
            "Captures 10 seconds of whatever's currently driving the\n"
            "mouth (mic or file), then loops it continuously so you can\n"
            "tune the Audio tab's thresholds without talking the whole\n"
            "time. Click again (or switch Source) to stop the loop and go\n"
            "back to whatever was active before."
        )
        self.record_loop_btn.clicked.connect(self._on_record_loop_clicked)
        source_row.addWidget(self.record_loop_btn)
        root.addLayout(source_row)

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
        self._update_source_controls_enabled()
        self._update_play_button_text()
        self._update_record_loop_button_text()

        # Split across two rows, not one -- an 11-button single row was
        # the single biggest driver of this pane's minimum width
        # (measured, 2026-09-17: 1021px), which is exactly what forced
        # the canvas down to a sliver regardless of the splitter's
        # requested ratio. Two rows roughly halves that.
        actions_row_1 = QHBoxLayout()
        actions_row_2 = QHBoxLayout()

        self._undo_btn = QPushButton("Undo")
        self._redo_btn = QPushButton("Redo")
        self._undo_btn.setToolTip("Undo the last change (Ctrl+Z).")
        self._redo_btn.setToolTip("Redo the last undone change (Ctrl+Shift+Z).")
        self._undo_btn.clicked.connect(self.undo)
        self._redo_btn.clicked.connect(self.redo)
        actions_row_1.addWidget(self._undo_btn)
        actions_row_1.addWidget(self._redo_btn)
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, activated=self.redo)

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

        # Toggle buttons, not checkboxes with paragraph-long labels
        # (owner's request, 2026-09-17) -- the detail lives in the
        # tooltip instead.
        self.guide_btn = QPushButton("Guide")
        self.guide_btn.setCheckable(True)
        self.guide_btn.setToolTip(
            "Shows a grid on the Edit canvas (spacing set on the\n"
            "Application tab), plus the origin axes through (0, 0) -- where\n"
            "a root-level sprite's own Position of (0, 0) sits. Off by\n"
            "default."
        )
        self.guide_btn.toggled.connect(self._on_guide_toggled)
        actions_row_2.addWidget(self.guide_btn)

        self.ghost_btn = QPushButton("Ghost")
        self.ghost_btn.setCheckable(True)
        self.ghost_btn.setToolTip(
            "Shows hidden layers and sprites not visible in the current\n"
            "Preview state at 40% opacity on the Edit canvas, so you can\n"
            "see where they are. Never affects the Render Window/OBS,\n"
            "which always renders them at true 0%. Off by default."
        )
        self.ghost_btn.toggled.connect(self._on_ghost_toggled)
        actions_row_2.addWidget(self.ghost_btn)

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
    def _spin(lo: float, hi: float) -> QDoubleSpinBox:
        box = ScrollSafeDoubleSpinBox()
        box.setRange(lo, hi)
        return box

    def _add_double(
        self, form, label, lo, hi, step, decimals, target, field_name, tooltip: str
    ) -> None:
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
            self._save_config()

        return on_change

    # =====================================================================
    # Undo/redo
    # =====================================================================

    def push_undo_snapshot(self) -> None:
        self._undo_stack.append(self._snapshot())
        self._redo_stack.clear()
        self._update_undo_redo_buttons()

    def _snapshot(self) -> list[Sprite]:
        return [copy.copy(s) for s in self.rig.sprites]

    def _restore(self, snapshot: list[Sprite]) -> None:
        self.rig.sprites = [copy.copy(s) for s in snapshot]
        self._rebuild_scene()
        self._rebuild_list()
        self._select(None)
        self._mark_dirty()
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
        save_avatar(self.rig, self._current_avatar_path)
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
        save_avatar(self.rig, path)
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
        self.canvas_mode_btn.setChecked(cp.canvas_mode == "edit")
        self._on_canvas_mode_toggled(self.canvas_mode_btn.isChecked())
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
        cp.canvas_mode = "edit" if self.canvas_mode_btn.isChecked() else "live_preview"
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

    def _preview_variant_counts(self) -> tuple[int, int]:
        talk_count = 0
        blink_count = 0
        for item in self._items.values():
            sprite = item.sprite
            if sprite.manual_driven or sprite.hidden or not sprite.costume_layers[self.rig.active_costume]:
                continue
            if sprite.talk_state != 0 and motion.axis_visible(sprite.talk_state, self.preview_talk_level):
                talk_count += 1
            if sprite.blink_state != 0 and sprite.blink_state == self.preview_blink_level:
                blink_count += 1
        return max(1, talk_count), max(1, blink_count)

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
        self._updating_form = False

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
        self.push_undo_snapshot()
        with open(path, "rb") as f:
            image_data = f.read()
        sprite = Sprite(id=self.rig.new_sprite_id(), path=path, image_data=image_data)
        self.rig.add_sprite(sprite)
        self._mark_dirty()
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
        self.push_undo_snapshot()
        sprite = self.rig.by_id(self._selected_id)
        with open(path, "rb") as f:
            sprite.image_data = f.read()
        sprite.path = path
        self._mark_dirty()
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
        self.render_window.rebuild()

    def _on_load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load avatar", "", f"Unicorn Cloak avatar (*{DEFAULT_EXTENSION} *.save)"
        )
        if not path:
            return
        self.push_undo_snapshot()
        loaded = load_avatar_with_upgrade(path, parent=self)
        self.rig.name = loaded.name
        self.rig.sprites = loaded.sprites
        self.rig.active_costume = loaded.active_costume
        self._current_avatar_path = path
        self.config.avatar_path = path
        self._dirty = False
        self._update_dirty_indicator()
        self._rebuild_scene()
        self._rebuild_list()
        self._select(None)
        self._refresh_preview_expression_combo()
        self._refresh_expressions_section()
        self._save_config()
        self.render_window.rebuild()

    # =====================================================================
    # Canvas mode / Preview state
    # =====================================================================

    def _on_canvas_mode_toggled(self, edit_mode: bool) -> None:
        self.canvas_mode_btn.setText("Edit Sprites" if edit_mode else "Live Preview")
        self.canvas_stack.setCurrentWidget(self.edit_view if edit_mode else self.live_view)
        self.preview_controls.setVisible(edit_mode)
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
        self.play_file_btn.setEnabled(is_file and bool(self.config.audio.file_path))

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

    def _on_file_playback_stopped(self) -> None:
        self._update_play_button_text()

    # =====================================================================
    # OBS mute awareness
    # =====================================================================

    def _obs_status_text(self, connected: bool, muted: bool = False) -> str:
        if not connected:
            return "Not connected"
        return "Connected -- muted" if muted else "Connected -- not muted"

    def _on_obs_enabled_toggled(self, checked: bool) -> None:
        if self.obs_link_manager is not None:
            self.obs_link_manager.set_enabled(checked)
        else:
            self.config.obs.enabled = checked
        self._save_config()

    def _on_obs_connection_field_changed(self) -> None:
        self.config.obs.host = self.obs_host.text()
        self.config.obs.port = self.obs_port.value()
        self.config.obs.password = self.obs_password.text()
        self.config.obs.input_name = self.obs_input_name.text()
        if self.obs_link_manager is not None:
            self.obs_link_manager.restart()
        self._save_config()

    def _on_obs_connection_changed(self, connected: bool) -> None:
        self._obs_connected = connected
        if not connected:
            self._obs_muted = False
        self.obs_status_label.setText(self._obs_status_text(self._obs_connected, self._obs_muted))

    def _on_obs_mute_changed(self, muted: bool) -> None:
        self._obs_muted = muted
        self.obs_status_label.setText(self._obs_status_text(self._obs_connected, self._obs_muted))

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
        self.config.window.zoom = value
        if self.render_window is not None:
            self.render_window.set_zoom(value)
        self._save_config()

    # =====================================================================
    # Expressions
    # =====================================================================

    def _refresh_expressions_section(self) -> None:
        while self._expressions_layout.count():
            child = self._expressions_layout.takeAt(0)
            if child.widget() is not None:
                child.widget().setParent(None)
        self._expression_buttons.clear()

        pairs = sorted({
            (s.group_name, s.state_name)
            for s in self.rig.sprites
            if s.manual_driven and s.group_name and s.state_name
        })
        if pairs:
            for group, state in pairs:
                btn = QPushButton(f"{group}: {state}")
                btn.setCheckable(True)
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
