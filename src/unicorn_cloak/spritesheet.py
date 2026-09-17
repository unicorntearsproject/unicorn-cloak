"""
Sprite-sheet slicing: a multi-frame sprite's source image is `frames`
equal-width horizontal slices (a filmstrip), per the contract in rig.py.
Shared by render.py (animates through all frames) and editor_window.py
(always shows frame 0 -- the editor is a static preview).
"""
from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QPixmap


def slice_frame(pixmap: QPixmap, frames: int, frame_index: int) -> QPixmap:
    if frames <= 1:
        return pixmap
    frame_width = pixmap.width() // frames
    return pixmap.copy(QRect(frame_index * frame_width, 0, frame_width, pixmap.height()))


def slice_all_frames(pixmap: QPixmap, frames: int) -> list[QPixmap]:
    return [slice_frame(pixmap, frames, i) for i in range(max(frames, 1))]
