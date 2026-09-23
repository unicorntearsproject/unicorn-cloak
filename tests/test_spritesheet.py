from unicorn_cloak.spritesheet import slice_all_frames, slice_frame

from qt_helpers import make_filmstrip_png_bytes, make_test_png_bytes


def _load(png_bytes: bytes):
    from PySide6.QtGui import QPixmap

    pixmap = QPixmap()
    pixmap.loadFromData(png_bytes)
    return pixmap


def _pixel_color(pixmap, x=0, y=0):
    return pixmap.toImage().pixelColor(x, y)


def test_frames_of_one_returns_the_whole_pixmap_unchanged(qapp):
    # frames<=1 means "not a filmstrip at all" -- the single static
    # sprite case every real rig used before this feature existed.
    pixmap = _load(make_test_png_bytes(color=(10, 20, 30, 255), size=16))
    sliced = slice_frame(pixmap, frames=1, frame_index=0)
    assert sliced.width() == pixmap.width()
    assert sliced.height() == pixmap.height()


def test_frames_of_zero_also_returns_the_whole_pixmap(qapp):
    # frames<=1, same branch -- a sprite that's never had a frame count
    # authored at all defaults to 0 (rig.Sprite.frames' own default is
    # 1, but a hand-edited or legacy file could still have 0).
    pixmap = _load(make_test_png_bytes(size=16))
    sliced = slice_frame(pixmap, frames=0, frame_index=0)
    assert sliced.width() == pixmap.width()
    assert sliced.height() == pixmap.height()


def test_slice_frame_extracts_the_requested_frame_by_color(qapp):
    colors = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)]
    pixmap = _load(make_filmstrip_png_bytes(colors, frame_size=4))
    assert pixmap.width() == 12  # 3 frames * 4px each
    assert pixmap.height() == 4

    for i, color in enumerate(colors):
        frame = slice_frame(pixmap, frames=3, frame_index=i)
        assert (frame.width(), frame.height()) == (4, 4)
        px = _pixel_color(frame)
        assert (px.red(), px.green(), px.blue()) == color[:3]


def test_slice_all_frames_returns_every_frame_in_order(qapp):
    colors = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)]
    pixmap = _load(make_filmstrip_png_bytes(colors, frame_size=4))
    frames = slice_all_frames(pixmap, frames=3)
    assert len(frames) == 3
    for frame, color in zip(frames, colors):
        px = _pixel_color(frame)
        assert (px.red(), px.green(), px.blue()) == color[:3]


def test_slice_all_frames_with_one_frame_returns_a_single_whole_pixmap(qapp):
    pixmap = _load(make_test_png_bytes(size=16))
    frames = slice_all_frames(pixmap, frames=1)
    assert len(frames) == 1
    assert frames[0].width() == pixmap.width()


def test_slice_all_frames_with_zero_frames_still_returns_one_entry(qapp):
    # slice_all_frames' own max(frames, 1) guard -- render.py indexes
    # frame_pixmaps[rt.current_frame] unconditionally, so an empty list
    # here would be an IndexError waiting to happen for any sprite whose
    # frames count is 0.
    pixmap = _load(make_test_png_bytes(size=16))
    frames = slice_all_frames(pixmap, frames=0)
    assert len(frames) == 1


def test_slice_frame_truncates_a_width_not_evenly_divisible_by_frame_count(qapp):
    # 10px wide, 3 frames -> frame_width = 10 // 3 = 3 (integer
    # division); the last pixel column is simply unused, not an error.
    pixmap = _load(make_test_png_bytes(size=10))
    frame = slice_frame(pixmap, frames=3, frame_index=0)
    assert frame.width() == 3


def test_slice_frame_with_more_frames_than_pixels_of_width_falls_back_to_the_whole_image(qapp):
    # Documents spritesheet.py's actual current behavior for this edge
    # case, empirically verified rather than assumed: frame_width =
    # width // frames floors to 0 once frames exceeds the pixmap's own
    # width, producing a zero-*width* (but not null) QRect -- and
    # QPixmap.copy() treats any empty QRect (Qt's own isEmpty(), true
    # whenever width or height is <= 0) as "copy the whole pixmap," not
    # as "produce an empty result." So every frame index silently comes
    # back as the *entire*, unsliced filmstrip image rather than a
    # (correctly) empty frame or a raised error -- the bug audit's own
    # note on this finding (#21) guessed "silently returns an empty
    # pixmap," which doesn't hold on this PySide6 version; asserting the
    # real, checked behavior here instead of repeating that guess is the
    # actual point of adding this test file. Not changed here -- #21
    # asked for the missing test file itself, and what the *right*
    # fallback should be (clamp frames? raise? something else?) is a
    # separate design question this test doesn't presume to answer.
    pixmap = _load(make_test_png_bytes(size=4))
    for frame_index in range(3):
        frame = slice_frame(pixmap, frames=10, frame_index=frame_index)
        assert (frame.width(), frame.height()) == (4, 4)
