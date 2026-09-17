"""
Milestone 1 spike (see ../docs/PLAN.md): prove a per-pixel-transparent, frameless
PySide6 window survives an OBS Window Capture (PipeWire portal) round-trip
on this machine before any rig code gets built on top of it.

Draws three regions so a captured frame can be checked for all three alpha
cases, not just "fully see-through vs fully opaque":
  - top-left:  fully opaque red square
  - top-right: 50% translucent blue square
  - center:    a real avatar sprite (head-01.png) with its own alpha edges

Run: source ../.venv/bin/activate && python transparent_window.py
Quit: Escape, or close the window.
"""
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

SPRITE_PATH = Path(
    "/home/jj/projects/unicorn-tears/images/animated-avatar/avatar-01/"
    "for-assembly/head-01.png"
)

WINDOW_TITLE = "Unicorn Cloak — Spike"


class SpikeWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.resize(900, 900)

        self.sprite = QPixmap(str(SPRITE_PATH))
        if not self.sprite.isNull():
            self.sprite = self.sprite.scaledToWidth(
                500, Qt.SmoothTransformation
            )

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.fillRect(20, 20, 80, 80, QColor(255, 0, 0, 255))
        painter.fillRect(self.width() - 100, 20, 80, 80, QColor(0, 120, 255, 128))

        if not self.sprite.isNull():
            x = (self.width() - self.sprite.width()) // 2
            y = (self.height() - self.sprite.height()) // 2
            painter.drawPixmap(x, y, self.sprite)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.key() == Qt.Key_Escape:
            self.close()


def main() -> int:
    app = QApplication(sys.argv)
    window = SpikeWindow()
    window.show()
    print(f"Window title for OBS Window Capture: {WINDOW_TITLE!r}")
    print("Opaque red (top-left), 50% blue (top-right), avatar head (center).")
    print("Press Escape or close the window to quit.")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
