"""Shared helpers for tests that need a real (tiny) PNG or a minimal rig,
without depending on the owner's actual avatar file."""
import math
import struct
import wave

import pytest
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage, QPainter

from unicorn_cloak.audio import ffmpeg_available
from unicorn_cloak.rig import AvatarRig, Sprite

needs_ffmpeg = pytest.mark.skipif(
    not ffmpeg_available(), reason="ffmpeg not installed on this machine"
)


def make_test_wav(path, duration_s=0.3, samplerate=8000, amplitude=0.5, frequency=440):
    """Writes a short mono sine-tone WAV to `path` -- for tests that need
    a real, decodable audio file (audio.FilePlayback) without shipping a
    binary fixture. Pure stdlib (`wave`), so creating it never needs
    ffmpeg -- only *decoding* it (what FilePlayback actually tests) does."""
    n = int(duration_s * samplerate)
    samples = [
        int(amplitude * 32767 * math.sin(2 * math.pi * frequency * i / samplerate))
        for i in range(n)
    ]
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)  # 16-bit PCM
        f.setframerate(samplerate)
        f.writeframes(struct.pack(f"<{n}h", *samples))


def make_test_png_bytes(color=(255, 0, 0, 255)) -> bytes:
    image = QImage(4, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor(*color))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return bytes(buf.data())


def make_filmstrip_png_bytes(frame_colors: list[tuple[int, int, int, int]], frame_size: int = 4) -> bytes:
    """A horizontal filmstrip -- len(frame_colors) frames, each a solid
    frame_size x frame_size square of its own color -- for verifying
    which frame render.py/control_panel_window.py actually show."""
    image = QImage(frame_size * len(frame_colors), frame_size, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    for i, color in enumerate(frame_colors):
        painter.fillRect(i * frame_size, 0, frame_size, frame_size, QColor(*color))
    painter.end()
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return bytes(buf.data())


def make_test_rig() -> AvatarRig:
    png = make_test_png_bytes()
    sprites = [
        Sprite(id=1, path="a.png", image_data=png, position=(0.0, 0.0), z_index=0),
        Sprite(
            id=2,
            path="b.png",
            parent_id=1,
            image_data=png,
            position=(5.0, 5.0),
            talk_state=1,
        ),
    ]
    return AvatarRig(name="test", sprites=sprites)
