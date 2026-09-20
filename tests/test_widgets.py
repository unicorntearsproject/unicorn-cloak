from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QGraphicsScene

from unicorn_cloak import theme
from unicorn_cloak.widgets import CollapsibleSection, PreviewView, elide_path_middle


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
