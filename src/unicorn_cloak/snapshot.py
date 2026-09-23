"""
Renders one costume slot to a static PNG at an arbitrary resolution --
for thumbnails, channel art, etc. (owner's request, 2026-09-16).

Builds a throwaway QGraphicsScene with no runtime/simulation state at
all -- every sprite sits at its rest pose (no sway, drag, rotation,
stretch, or bounce), reusing the same parent/child item-nesting
rig.py's contract describes for position composition, and the same
talk_level=0/blink_level=1/edit_mode=False convention
editor_window.py's own static preview already uses for "what does this
look like at rest" (see motion.sprite_alpha). Only sprites in the
requested costume slot and not individually hidden show up.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QGraphicsScene

from . import motion
from .rig import AvatarRig, Sprite
from .spritesheet import slice_all_frames


def _variant_pool(rig: AvatarRig, costume_index: int, *, axis: str) -> list[int]:
    """Sorted, de-duplicated `variant` values among sprites in this
    costume slot that would be gated on (and eligible to show at rest
    on) the given axis ("talk" or "blink") -- mirrors render.
    RenderWindow._talk_variant_values_at/_blink_variant_values_at (bug
    audit 2026-09-23, #4's fix), just without a live cycling timer: a
    snapshot is static, so render_costume_snapshot always shows each
    band's *lowest* variant (this list's first entry) rather than
    animating through all of them."""
    if axis == "talk":
        return sorted({
            s.variant for s in rig.sprites
            if not s.manual_driven and s.talk_state != 0
            and motion.axis_visible(s.talk_state, 0)  # rest = talk_level 0 (quiet)
            and not s.hidden and s.costume_layers[costume_index]
        })
    return sorted({
        s.variant for s in rig.sprites
        if not s.manual_driven and s.blink_state != 0
        and s.blink_state == 1  # rest = blink_level 1 (eyes open, not blinking)
        and not s.hidden and s.costume_layers[costume_index]
    })


def _rest_alpha(sprite: Sprite, talk_variant_pool: list[int], blink_variant_pool: list[int]) -> float:
    return motion.sprite_alpha(
        sprite.talk_state,
        sprite.blink_state,
        talk_level=0,
        blink_level=1,
        edit_mode=False,
        talk_variant=sprite.variant,
        active_talk_variant=talk_variant_pool[0] if talk_variant_pool else 0,
        talk_variant_count=len(talk_variant_pool),
        blink_variant=sprite.variant,
        active_blink_variant=blink_variant_pool[0] if blink_variant_pool else 0,
        blink_variant_count=len(blink_variant_pool),
        hidden=sprite.hidden,
        # manual_driven/manual_active, added 2026-09-23 bug audit #5:
        # previously omitted entirely, so sprite_alpha fell through to
        # the *ordinary* talk/blink-state check for a Manually driven
        # sprite -- and expression sprites are typically talk_state=0/
        # blink_state=0 (gated purely by the live override, not mic/
        # blink), which axis_visible treats as "always visible." A
        # snapshot has no live override active, so a manual_driven
        # sprite is always off at rest -- exactly manual_active=False,
        # never sprite.manual_driven's own live/session state (there
        # isn't one here).
        manual_driven=sprite.manual_driven,
        manual_active=False,
    )


def render_costume_snapshot(rig: AvatarRig, costume_index: int) -> QImage:
    """Renders costume `costume_index` at rest, sized tightly to fit
    every visible sprite -- callers that want a specific output
    resolution should scale the result (see export_costume_snapshot)."""
    scene = QGraphicsScene()
    by_parent: dict[int | None, list[Sprite]] = {}
    for sprite in rig.sprites:
        by_parent.setdefault(sprite.parent_id, []).append(sprite)

    talk_variant_pool = _variant_pool(rig, costume_index, axis="talk")
    blink_variant_pool = _variant_pool(rig, costume_index, axis="blink")
    visible_items: list[QGraphicsPixmapItem] = []

    def build(sprite: Sprite, parent_item):
        visible = (
            sprite.costume_layers[costume_index]
            and bool(sprite.image_data)
            and _rest_alpha(sprite, talk_variant_pool, blink_variant_pool) > 0.0
        )
        pixmap = QPixmap()
        if visible:
            pixmap.loadFromData(sprite.image_data)
            pixmap = slice_all_frames(pixmap, sprite.frames)[0]
        # Always a real (if visually empty, 0x0-pixmap) item, never None
        # -- bug audit 2026-09-23, related to #5: an *invisible* sprite
        # used to be skipped entirely, so its children (whose authored
        # Position is relative to *this* sprite, not its grandparent)
        # attached straight to the grandparent's item instead, silently
        # misplacing them. Mirrors render.py's own _build_items, which
        # never skips item creation for this exact reason -- visibility
        # there is a paint-time opacity, not an existence question.
        item = QGraphicsPixmapItem(pixmap, parent_item)
        item.setOffset(
            -pixmap.width() / 2 + sprite.offset[0],
            -pixmap.height() / 2 + sprite.offset[1],
        )
        item.setZValue(sprite.z_index)
        # z_index only orders siblings -- Qt always paints a child on top
        # of its own parent regardless of z sign, so a negative z_index
        # (a hair-back layer meant to sit behind the head) needs this
        # flag or it renders in front anyway. Matches render.py's own
        # _build_items; previously missing here entirely (bug audit
        # 2026-09-23, related to #5).
        item.setFlag(QGraphicsItem.ItemStacksBehindParent, sprite.z_index < 0)
        if sprite.clipped:
            # Also previously missing -- see render.py's own comment on
            # this same pair of calls for why MaskShape specifically.
            item.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
            item.setShapeMode(QGraphicsPixmapItem.ShapeMode.MaskShape)
        item.setPos(*sprite.position)
        # Static, authored Scale X/Y and Rotation (rig.Sprite's own
        # "permanently resizing/rotating a layer" fields) -- omitted
        # here entirely until 2026-09-20, so every sprite exported at
        # its raw native pixel size/orientation regardless of what
        # was authored to make it fit the rest of the rig. Harmless
        # for a rig where every sprite happens to share the same
        # scale (nothing to get relatively wrong), but produced
        # gross, inconsistent distortion for a real one -- the
        # owner's report, with screenshots: a snapshot export where
        # correctly-fitted sunglasses (authored at 0.34x to match a
        # head scaled to 0.843x) rendered enormous, sticking out past
        # the head like ears, because neither scale was applied.
        # Excludes render.py's own *reactive* squash/stretch/drag-
        # rotation terms (rt.scale/rt.rotation_rad) -- this module
        # has no runtime state at all, every sprite sits at rest (see
        # module docstring), so there's nothing reactive to combine
        # with.
        if sprite.rotation_deg or sprite.scale_x != 1.0 or sprite.scale_y != 1.0:
            transform = QTransform()
            transform.rotate(sprite.rotation_deg)
            transform.scale(sprite.scale_x, sprite.scale_y)
            item.setTransform(transform)
        if parent_item is None:
            scene.addItem(item)
        if visible:
            visible_items.append(item)
        for child in by_parent.get(sprite.id, []):
            build(child, item)

    for root_sprite in by_parent.get(None, []):
        build(root_sprite, None)

    # Bounds from the actually-visible items' own scene rects, not
    # scene.itemsBoundingRect() -- every sprite now has a real item
    # (see build() above), including invisible ones sitting whatever
    # zero-size point their own Position puts them at; letting those
    # into the union could pad/skew the auto-fit size around content
    # nobody will ever see in this snapshot.
    bounds = QRectF()
    for item in visible_items:
        bounds = bounds.united(item.sceneBoundingRect())
    if bounds.isEmpty():
        bounds = QRectF(0, 0, 1, 1)
    image = QImage(max(1, round(bounds.width())), max(1, round(bounds.height())), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scene.render(painter, QRectF(0, 0, image.width(), image.height()), bounds)
    painter.end()
    return image


def export_costume_snapshot(
    rig: AvatarRig,
    costume_index: int,
    output_path: str,
    width: int | None = None,
    height: int | None = None,
) -> None:
    """Renders and saves costume `costume_index` to `output_path` as a
    PNG. With width/height, the render is scaled to fit that exact size
    (aspect ratio preserved, transparent-padded, centered) -- otherwise
    it's saved at its natural size (tight to the visible sprites)."""
    image = render_costume_snapshot(rig, costume_index)
    if width is not None and height is not None:
        scaled = QImage(width, height, QImage.Format.Format_ARGB32)
        scaled.fill(Qt.GlobalColor.transparent)
        painter = QPainter(scaled)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = min(width / image.width(), height / image.height())
        target_w, target_h = image.width() * scale, image.height() * scale
        target_rect = QRectF((width - target_w) / 2, (height - target_h) / 2, target_w, target_h)
        painter.drawImage(target_rect, image)
        painter.end()
        image = scaled
    if not image.save(output_path, "PNG"):
        raise OSError(f"failed to save snapshot to {output_path!r}")
