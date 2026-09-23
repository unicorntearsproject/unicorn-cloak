import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QFontMetrics, QMouseEvent
from PySide6.QtWidgets import QGraphicsScene

from unicorn_cloak import theme
from unicorn_cloak.widgets import (
    CollapsibleSection,
    FileTimelineWidget,
    PreviewView,
    elide_path_middle,
    format_playback_time,
)


def test_elide_path_middle_leaves_a_short_path_untouched(qapp):
    fm = QFontMetrics(qapp.font())
    path = "/home/jj/file.mp3"
    assert elide_path_middle(path, fm, max_width=fm.horizontalAdvance(path) + 20) == path


def test_elide_path_middle_keeps_the_full_filename_intact(qapp):
    fm = QFontMetrics(qapp.font())
    path = "/home/jj/projects/unicorn-tears/some/very/deeply/nested/recording-final.mp3"
    result = elide_path_middle(path, fm, max_width=150)
    assert result.endswith("/recording-final.mp3")
    assert "…" in result
    assert fm.horizontalAdvance(result) <= 150


def test_elide_path_middle_shrinks_as_width_shrinks(qapp):
    fm = QFontMetrics(qapp.font())
    path = "/home/jj/projects/unicorn-tears/some/very/deeply/nested/recording-final.mp3"
    wide = elide_path_middle(path, fm, max_width=300)
    narrow = elide_path_middle(path, fm, max_width=120)
    assert len(narrow) <= len(wide)


def test_elide_path_middle_falls_back_to_just_the_filename_when_extremely_narrow(qapp):
    fm = QFontMetrics(qapp.font())
    path = "/home/jj/projects/unicorn-tears/some/very/deeply/nested/recording-final.mp3"
    result = elide_path_middle(path, fm, max_width=1)
    assert result == "…/recording-final.mp3"


def test_collapsible_section_starts_expanded_by_default(qapp):
    section = CollapsibleSection("Position & Hierarchy")
    assert section.is_collapsed() is False


def test_collapsible_section_can_start_collapsed(qapp):
    section = CollapsibleSection("Position & Hierarchy", collapsed=True)
    assert section.is_collapsed() is True


def test_collapsible_section_wants_extra_space_defaults_to_false(qapp):
    section = CollapsibleSection("Position & Hierarchy")
    assert section.wants_extra_space is False


def test_collapsible_section_wants_extra_space_can_be_set_true(qapp):
    section = CollapsibleSection("Layer List", wants_extra_space=True)
    assert section.wants_extra_space is True


def test_collapsible_section_toggling_the_header_collapses_and_expands(qapp):
    section = CollapsibleSection("Position & Hierarchy")
    section._header.setChecked(True)
    assert section.is_collapsed() is True
    section._header.setChecked(False)
    assert section.is_collapsed() is False


def test_preview_view_has_a_solid_dark_background_brush(qapp):
    # Regression 2026-09-17, owner's report ("the white background in the
    # settings section" -- this was actually the Live Preview canvas).
    # render_window.scene usually has NoBrush (transparent, correct for
    # the real, OBS-captured Render Window) -- mirrored here with nothing
    # else painting over it, PreviewView fell through to the viewport's
    # native (white) palette color. This view's own backgroundBrush must
    # override that independently of whatever the mirrored scene's own
    # brush is set to.
    scene = QGraphicsScene()
    view = PreviewView(scene)
    assert view.backgroundBrush().color().name() == theme.INK_850


def test_collapsible_section_set_collapsed_does_not_emit_a_spurious_toggle(qapp):
    section = CollapsibleSection("Position & Hierarchy")
    calls = []
    section._header.toggled.connect(calls.append)
    section.set_collapsed(True)
    assert calls == []  # blockSignals during set_collapsed -- no toggled emission
    assert section.is_collapsed() is True


def test_collapsible_section_title_is_preserved(qapp):
    section = CollapsibleSection("Audio")
    assert section.title == "Audio"


def test_collapsible_section_escapes_ampersand_in_the_header_text(qapp):
    # Regression, found via a real screenshot 2026-09-17: QPushButton
    # treats a bare "&" as a mnemonic marker, so "Position & Hierarchy"
    # rendered as "Position_Hierarchy" -- "&&" is Qt's escape for a
    # literal ampersand.
    section = CollapsibleSection("Position & Hierarchy")
    assert "&&" in section._header.text()
    assert section._header.text().count("&") == 2


# --- FileTimelineWidget (timeline/scrubber feature, owner's request 2026-09-23) --


def test_format_playback_time_formats_minutes_and_seconds():
    assert format_playback_time(0) == "0:00"
    assert format_playback_time(5) == "0:05"
    assert format_playback_time(65) == "1:05"
    assert format_playback_time(3725) == "62:05"  # no hours field, minutes run past 59


def test_format_playback_time_clamps_negative_to_zero():
    assert format_playback_time(-5) == "0:00"


def test_file_timeline_starts_at_zero_position_and_duration(qapp):
    timeline = FileTimelineWidget()
    assert timeline.position_s == 0.0
    assert timeline.duration_s == 0.0


def test_file_timeline_set_position_and_duration_update_state(qapp):
    timeline = FileTimelineWidget()
    timeline.set_duration(90.0)
    timeline.set_position(30.0)
    assert timeline.duration_s == 90.0
    assert timeline.position_s == 30.0


def test_file_timeline_set_position_clamps_negative_to_zero(qapp):
    timeline = FileTimelineWidget()
    timeline.set_position(-5.0)
    assert timeline.position_s == 0.0


def _mouse_event(event_type, x, button=Qt.MouseButton.LeftButton):
    buttons = button if event_type != QEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton
    return QMouseEvent(event_type, QPointF(x, 10), button, buttons, Qt.KeyboardModifier.NoModifier)


def test_file_timeline_click_does_nothing_with_no_known_duration(qapp):
    # duration_s == 0 means "nothing to seek yet" (never played, or the
    # total couldn't be probed) -- a click must not divide by zero or
    # seek to a meaningless position.
    timeline = FileTimelineWidget()
    timeline.resize(300, 28)
    seeks = []
    timeline.seek_requested.connect(seeks.append)

    timeline.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, 100))
    timeline.mouseReleaseEvent(_mouse_event(QEvent.Type.MouseButtonRelease, 100))

    assert seeks == []
    assert timeline.position_s == 0.0


def test_file_timeline_click_updates_position_immediately_but_only_seeks_on_release(qapp):
    timeline = FileTimelineWidget()
    timeline.resize(300, 28)
    timeline.set_duration(100.0)
    seeks = []
    timeline.seek_requested.connect(seeks.append)

    bar_rect = timeline._bar_rect()
    click_x = bar_rect.left() + bar_rect.width() / 2  # roughly the midpoint -> ~50s

    timeline.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, click_x))
    assert seeks == []  # not yet -- only on release
    assert timeline.position_s == pytest.approx(50.0, abs=1.0)

    timeline.mouseReleaseEvent(_mouse_event(QEvent.Type.MouseButtonRelease, click_x))
    assert len(seeks) == 1
    assert seeks[0] == pytest.approx(50.0, abs=1.0)


def test_file_timeline_dragging_ignores_incoming_set_position_until_release(qapp):
    # A live position_measured update arriving mid-drag (the file is
    # still actually playing while the owner scrubs) must not fight the
    # drag the owner is mid-gesture on.
    timeline = FileTimelineWidget()
    timeline.resize(300, 28)
    timeline.set_duration(100.0)

    bar_rect = timeline._bar_rect()
    timeline.mousePressEvent(
        _mouse_event(QEvent.Type.MouseButtonPress, bar_rect.left() + bar_rect.width() * 0.8)
    )
    dragged_position = timeline.position_s
    assert dragged_position > 50.0

    timeline.set_position(3.0)  # a "live" update arriving mid-drag
    assert timeline.position_s == dragged_position  # unchanged -- drag still wins

    timeline.mouseReleaseEvent(
        _mouse_event(QEvent.Type.MouseButtonRelease, bar_rect.left() + bar_rect.width() * 0.8)
    )
    timeline.set_position(3.0)  # now that dragging is over, live updates apply again
    assert timeline.position_s == 3.0


def test_file_timeline_right_click_does_not_seek(qapp):
    timeline = FileTimelineWidget()
    timeline.resize(300, 28)
    timeline.set_duration(100.0)
    seeks = []
    timeline.seek_requested.connect(seeks.append)

    timeline.mousePressEvent(
        _mouse_event(QEvent.Type.MouseButtonPress, 150, button=Qt.MouseButton.RightButton)
    )
    timeline.mouseReleaseEvent(
        _mouse_event(QEvent.Type.MouseButtonRelease, 150, button=Qt.MouseButton.RightButton)
    )

    assert seeks == []
