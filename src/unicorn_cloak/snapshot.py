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
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene

from . import motion
from .rig import AvatarRig, Sprite
from .spritesheet import slice_all_frames


def _rest_alpha(sprite: Sprite) -> float:
    return motion.sprite_alpha(
        sprite.talk_state,
        sprite.blink_state,
        talk_level=0,
        blink_level=1,
        edit_mode=False,
        hidden=sprite.hidden,
    )


def render_costume_snapshot(rig: AvatarRig, costume_index: int) -> QImage:
    """Renders costume `costume_index` at rest, sized tightly to fit
    every visible sprite -- callers that want a specific output
    resolution should scale the result (see export_costume_snapshot)."""
    scene = QGraphicsScene()
    by_parent: dict[int | None, list[Sprite]] = {}
    for sprite in rig.sprites:
        by_parent.setdefault(sprite.parent_id, []).append(sprite)

    def build(sprite: Sprite, parent_item):
        item = None
        visible = (
            sprite.costume_layers[costume_index] and _rest_alpha(sprite) > 0.0
        )
        if visible and sprite.image_data:
            pixmap = QPixmap()
            pixmap.loadFromData(sprite.image_data)
            frame0 = slice_all_frames(pixmap, sprite.frames)[0]
            item = QGraphicsPixmapItem(frame0, parent_item)
            item.setOffset(
                -frame0.width() / 2 + sprite.offset[0],
                -frame0.height() / 2 + sprite.offset[1],
            )
            item.setZValue(sprite.z_index)
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
        # Children still nest under a parent item for correct position
        # composition even when their own parent is invisible right now
        # -- attach to whatever the parent's own parent item was instead
        # (root, if none), mirroring how an orphaned reparent elsewhere
        # in this app falls back to the scene root.
        for child in by_parent.get(sprite.id, []):
            build(child, item if item is not None else parent_item)

    for root_sprite in by_parent.get(None, []):
        build(root_sprite, None)

    bounds = scene.itemsBoundingRect()
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
