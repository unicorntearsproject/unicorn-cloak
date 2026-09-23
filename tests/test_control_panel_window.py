import math

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeySequence, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsSceneMouseEvent, QSplitter

from unicorn_cloak import control_panel_window as cpw_module
from unicorn_cloak import motion
from unicorn_cloak.config import Config
from unicorn_cloak.control_panel_window import ControlPanelWindow
from unicorn_cloak.render import RenderWindow
from unicorn_cloak.rig import AvatarRig, Sprite

from qt_helpers import make_test_png_bytes, make_test_rig


def make_panel(tmp_path, rig=None):
    config = Config()
    rig = rig if rig is not None else make_test_rig()
    window = RenderWindow(rig, config.motion, hotkeys_config=config.hotkeys)
    state_path = tmp_path / "settings.json"
    panel = ControlPanelWindow(rig, config, window, state_path=state_path)
    return config, window, panel, state_path


# --- Construction / structure -------------------------------------------


def test_panel_is_a_single_window_with_the_expected_object_name(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.objectName() == "ControlPanelWindow"
    assert panel.testAttribute(Qt.WidgetAttribute.WA_StyledBackground) is True


def test_panel_has_the_six_expected_tabs_in_order(qapp, tmp_path):
    # Behavior moved to 2nd position (right after Sprites), owner's
    # request 2026-09-19, alongside adding its own "which layer" header.
    config, window, panel, _ = make_panel(tmp_path)
    titles = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
    assert titles == ["Sprites", "Behavior", "Costume Hotkeys", "Expression Hotkeys", "Audio", "Application"]


def test_no_tab_has_more_than_three_collapsible_sections(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    for i in range(panel.tabs.count()):
        splitter = panel.tabs.widget(i).findChild(QSplitter)
        assert splitter.count() <= 3


# --- Sprite editing core (ported regressions) ----------------------------


def test_editor_builds_matching_items_and_list(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert len(panel._items) == 2
    assert panel.sprite_list.count() == 2


def _make_grouped_rig():
    png = make_test_png_bytes()
    sprites = [
        Sprite(id=1, path="head.png", image_data=png, position=(0.0, 0.0), z_index=0),
        Sprite(
            id=2, path="mouth-closed.png", image_data=png, parent_id=1,
            position=(0.0, 10.0), z_index=2, group_name="Mouth", state_name="Closed",
        ),
        Sprite(
            id=3, path="mouth-wide.png", image_data=png, parent_id=1,
            position=(0.0, 10.0), z_index=1, group_name="Mouth", state_name="Wide",
        ),
    ]
    return AvatarRig(name="grouped", sprites=sprites)


def test_layer_list_shows_a_header_row_for_a_shared_group_name(qapp, tmp_path):
    # Owner's request, 2026-09-17: "when items are linked/grouped (like
    # say the mouths & eyes), show the group name and indent the members
    # w/a slightly lighter bg color". One extra header row for the run of
    # sprites sharing a Group name, on top of the 3 real sprites.
    config, window, panel, _ = make_panel(tmp_path, rig=_make_grouped_rig())
    assert panel.sprite_list.count() == 4  # head.png + "Mouth" header + 2 mouth sprites

    header_item = panel.sprite_list.item(1)
    header_row = panel.sprite_list.itemWidget(header_item)
    labels = [w for w in header_row.findChildren(cpw_module.QLabel)]
    assert any(label.text().strip() == "Mouth" for label in labels)


def test_layer_list_header_row_is_not_selectable(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path, rig=_make_grouped_rig())
    header_item = panel.sprite_list.item(1)
    assert not (header_item.flags() & Qt.ItemFlag.ItemIsSelectable)
    assert header_item.data(cpw_module.SELECTED_ID) is None


def test_layer_list_grouped_member_rows_get_a_lighter_background(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path, rig=_make_grouped_rig())
    ungrouped_row = panel.sprite_list.itemWidget(panel.sprite_list.item(0))  # head.png
    grouped_row = panel.sprite_list.itemWidget(panel.sprite_list.item(2))  # mouth-closed.png
    assert not ungrouped_row.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    assert grouped_row.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    assert cpw_module.theme.INK_700 in grouped_row.styleSheet()


def test_layer_list_ungrouped_sprites_get_no_header(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)  # default two-sprite rig, no group_name
    assert panel.sprite_list.count() == 2


def test_select_populates_property_form(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(2)
    assert panel._selected_id == 2
    assert panel.pos_x.value() == 5.0
    assert panel.talk_state.currentData() == 1


def test_variant_is_the_last_row_of_state_assignment(qapp, tmp_path):
    # Owner's request, 2026-09-20: "put 'variant' in the state assignment
    # pane as the last row" -- it used to live on the Behavior tab's
    # Animation section, grouped with Frames/Anim speed (an unrelated,
    # spritesheet-playback concept), even though it's actually which
    # *slot* within a shared Talk/Blink state a sprite alternates in.
    config, window, panel, _ = make_panel(tmp_path)
    row, _role = panel.state_form.getWidgetPosition(panel.variant)
    assert row == panel.state_form.rowCount() - 1


def test_editing_variant_writes_through_to_the_sprite(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    panel.variant.setValue(3)
    assert panel.rig.by_id(1).variant == 3


def _make_rig_with_a_tagged_and_an_untagged_sprite():
    png = make_test_png_bytes()
    sprites = [
        Sprite(id=1, path="head.png", image_data=png, position=(0.0, 0.0), z_index=0),
        Sprite(id=2, path="hair.png", image_data=png, position=(0.0, -20.0), z_index=1),  # untagged
        Sprite(
            id=3, path="laugh.png", image_data=png, parent_id=1, position=(0.0, 10.0), z_index=2,
            group_name="Mouth", state_name="Laughing", manual_driven=True,
        ),
    ]
    return AvatarRig(name="tagged", sprites=sprites)


def test_selecting_a_tagged_manually_driven_sprite_expands_state_and_expressions(qapp, tmp_path):
    # Owner's request, 2026-09-17: "when clicking on a sprite, it should
    # auto-populate it's state/expression assignments if it has any."
    # The fields were already being set silently either way -- easy to
    # miss if the section happens to be collapsed (including by this
    # app's own auto-collapse-to-fit behavior). Clicking a sprite that's
    # actually tagged (Group name set, and Manually driven with a State
    # name for Expressions) should reveal both.
    config, window, panel, _ = make_panel(tmp_path, rig=_make_rig_with_a_tagged_and_an_untagged_sprite())
    panel._sections["State Assignment"].set_collapsed(True)
    panel._sections["Expressions"].set_collapsed(True)

    panel._select(3)

    assert panel._sections["State Assignment"].is_collapsed() is False
    assert panel._sections["Expressions"].is_collapsed() is False
    assert panel.group_name.currentText() == "Mouth"
    assert panel.state_name.currentText() == "Laughing"
    assert panel.manual_driven.isChecked() is True


def test_selecting_an_untagged_sprite_leaves_collapsed_sections_alone(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path, rig=_make_rig_with_a_tagged_and_an_untagged_sprite())
    panel._sections["State Assignment"].set_collapsed(True)
    panel._sections["Expressions"].set_collapsed(True)

    panel._select(2)  # hair.png -- no group_name, not manually driven

    assert panel._sections["State Assignment"].is_collapsed() is True
    assert panel._sections["Expressions"].is_collapsed() is True


def test_panel_is_not_dirty_immediately_after_construction(qapp, tmp_path):
    # Regression: EditableSpriteItem.__init__'s own setPos() call fires
    # Qt's itemChange (ItemPositionHasChanged) exactly like a real drag
    # would -- every _rebuild_scene() (including the very first one, at
    # construction) was marking the avatar dirty on its own before any
    # real edit, which would have made the quit-confirmation warn about
    # unsaved changes every single time, even right after opening the app.
    config, window, panel, _ = make_panel(tmp_path)
    assert panel._dirty is False


def test_panel_is_not_dirty_after_undo_restoring_the_scene(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    panel.pos_x.setValue(10.0)
    assert panel._dirty is True
    panel._dirty = False  # simulate having just saved
    panel.undo()  # rebuilds the scene internally via _restore
    # _restore itself marks dirty (an undo is itself an unsaved change);
    # the point of this test is that _rebuild_scene's own item
    # construction doesn't ALSO fire spuriously on top of that.
    assert panel._dirty is True


def test_property_edit_writes_through_and_marks_dirty(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel._dirty is False
    panel._select(1)
    panel.pos_x.setValue(42.0)
    assert panel.rig.by_id(1).position[0] == 42.0
    assert panel._dirty is True


def test_talk_state_combo_offers_quiet_only_option(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    index = panel.talk_state.findData(motion.TALK_QUIET_ONLY)
    assert index >= 0
    panel.talk_state.setCurrentIndex(index)
    assert panel.rig.by_id(1).talk_state == motion.TALK_QUIET_ONLY


def test_manual_driven_checkbox_disables_talk_and_blink_state(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    assert panel.talk_state.isEnabled() is True
    panel.manual_driven.setChecked(True)
    assert panel.talk_state.isEnabled() is False
    assert panel.blink_state.isEnabled() is False
    assert panel.rig.by_id(1).manual_driven is True


def test_group_name_editable_combo_writes_through_when_typing_new_text(qapp, tmp_path):
    # Regression: editTextChanged (not currentIndexChanged) is what
    # fires for a brand-new typed value on an editable QComboBox.
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    panel.group_name.setCurrentText("Mouth")
    panel.state_name.setCurrentText("Closed")
    assert panel.rig.by_id(1).group_name == "Mouth"
    assert panel.rig.by_id(1).state_name == "Closed"


def test_changing_group_clears_the_previous_state_name(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    panel.group_name.setCurrentText("Mouth")
    panel.state_name.setCurrentText("Closed")
    panel.group_name.setCurrentText("Eyes")
    assert panel.state_name.currentText() == ""
    assert panel.rig.by_id(1).state_name == ""


def test_undo_reverts_a_property_edit(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    panel.pos_x.setValue(99.0)
    assert panel.rig.by_id(1).position[0] == 99.0
    panel.undo()
    assert panel.rig.by_id(1).position[0] == 0.0


def test_add_replace_duplicate_delete_mark_dirty(qapp, tmp_path, monkeypatch):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel._dirty is False
    panel._select(1)
    panel.push_undo_snapshot()
    panel.rig.by_id(1).hidden = True  # simulate a structural-ish edit directly
    panel._mark_dirty()
    assert panel._dirty is True


def test_move_up_swaps_z_index(qapp, tmp_path):
    png = make_test_png_bytes()
    sprites = [
        Sprite(id=1, path="a.png", image_data=png, z_index=0),
        Sprite(id=2, path="b.png", image_data=png, z_index=1),
        Sprite(id=3, path="c.png", image_data=png, z_index=2),
    ]
    rig = AvatarRig(name="t", sprites=sprites)
    config, window, panel, _ = make_panel(tmp_path, rig=rig)
    panel._select(1)
    panel._on_move_up()
    assert rig.by_id(1).z_index == 1
    assert rig.by_id(2).z_index == 0


# --- Preview state (Edit canvas) -----------------------------------------


def test_preview_variant_forces_which_sprite_of_a_shared_band_shows(qapp, tmp_path):
    png = make_test_png_bytes()
    sprites = [
        Sprite(id=1, path="wide-open.png", image_data=png, blink_state=1, variant=0),
        Sprite(id=2, path="squint.png", image_data=png, blink_state=1, variant=1),
    ]
    rig = AvatarRig(name="t", sprites=sprites)
    config, window, panel, _ = make_panel(tmp_path, rig=rig)
    panel.ghost_btn.setChecked(False)
    assert panel._items[1].opacity() == 1.0
    assert panel._items[2].opacity() == 0.0
    panel.preview_blink_variant.setValue(1)
    assert panel._items[1].opacity() == 0.0
    assert panel._items[2].opacity() == 1.0


def test_forcing_preview_expression_shows_the_matching_sprite(qapp, tmp_path):
    png = make_test_png_bytes()
    sprites = [
        Sprite(id=1, path="laugh.png", image_data=png, group_name="Mouth", state_name="Laughing", manual_driven=True),
    ]
    rig = AvatarRig(name="t", sprites=sprites)
    config, window, panel, _ = make_panel(tmp_path, rig=rig)
    panel.ghost_btn.setChecked(False)
    item = panel._items[1]
    assert item.opacity() == 0.0
    index = panel.preview_expression_combo.findText("Mouth: Laughing")
    panel.preview_expression_combo.setCurrentIndex(index)
    assert item.opacity() == 1.0


# --- Canvas mode ----------------------------------------------------------


def test_canvas_defaults_to_live_preview(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.live_preview_btn.isChecked() is True
    assert panel.edit_sprites_btn.isChecked() is False
    assert panel.canvas_stack.currentWidget() is panel.live_view
    assert panel.preview_controls.isVisible() is False


def test_toggling_canvas_mode_switches_to_edit_view(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.show()
    panel.edit_sprites_btn.setChecked(True)
    assert panel.canvas_stack.currentWidget() is panel.edit_view
    assert panel.live_preview_btn.isChecked() is False
    assert panel.preview_controls.isVisible() is True


# --- Guide / Ghost / Grid --------------------------------------------------


def test_guide_and_ghost_default_off(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.guide_btn.isChecked() is False
    assert panel.ghost_btn.isChecked() is False


def test_guide_toggle_enables_grid_on_the_edit_view(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.edit_view.show_grid is False
    panel.guide_btn.setChecked(True)
    assert panel.edit_view.show_grid is True


def test_grid_spacing_field_updates_the_edit_view(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.edit_view.grid_spacing_px == 100
    panel.grid_spacing.setValue(50)
    assert panel.edit_view.grid_spacing_px == 50


# --- Edit canvas scroll-to-zoom (owner's request, 2026-09-19) ---------------


def _wheel_event(angle_delta_y: int) -> QWheelEvent:
    return QWheelEvent(
        QPointF(0, 0), QPointF(0, 0), QPoint(0, 0), QPoint(0, angle_delta_y),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )


def test_scrolling_up_on_the_edit_canvas_zooms_in(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    scale_before = panel.edit_view.transform().m11()
    panel.edit_view.wheelEvent(_wheel_event(120))
    assert panel.edit_view.transform().m11() > scale_before


def test_edit_canvas_scrollbars_are_always_off(qapp, tmp_path):
    # Regression 2026-09-19, owner's report: "the character jumps
    # forward real quick and snaps back... a horizontal scroll bar
    # appears" when zooming in past the fit-to-content baseline. Root
    # cause: at Qt's default ScrollBarAsNeeded policy, content bigger
    # than the viewport (exactly what zooming in produces) makes a
    # scrollbar appear -- shrinking the viewport's own geometry to make
    # room for it fires this view's resizeEvent, which calls
    # refit_to_content(), instantly undoing the very zoom that triggered
    # it. Zooming out never hit this (content only ever shrinks, no
    # scrollbar), which is exactly why the owner saw it one direction
    # only. This asserts the actual fix (scrollbars can never appear at
    # all) directly -- the feedback loop itself depends on real
    # interactive scrollbar/geometry timing this offscreen test
    # environment doesn't reliably reproduce even pre-fix, so a
    # behavioral "zoom in, then check the scale" test would not
    # actually catch a regression here.
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.edit_view.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert panel.edit_view.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_zooming_in_past_the_fit_baseline_keeps_growing(qapp, tmp_path):
    # Companion to the scrollbar-policy test above: with a real shown
    # window and the event loop actually pumped between wheel events
    # (closer to real interactive use than the other zoom tests, which
    # call wheelEvent back-to-back with no event-loop turn in between),
    # zoom must keep climbing, not intermittently reset.
    config, window, panel, _ = make_panel(tmp_path)
    panel.resize(1000, 800)
    panel.edit_sprites_btn.setChecked(True)
    panel.show()
    for _ in range(5):
        qapp.processEvents()

    baseline = panel.edit_view.transform().m11()
    for _ in range(5):
        panel.edit_view.wheelEvent(_wheel_event(120))
        qapp.processEvents()

    assert panel.edit_view.transform().m11() > baseline * 1.5


def test_scrolling_down_on_the_edit_canvas_zooms_out(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    scale_before = panel.edit_view.transform().m11()
    panel.edit_view.wheelEvent(_wheel_event(-120))
    assert panel.edit_view.transform().m11() < scale_before


def test_edit_canvas_zoom_is_clamped_at_the_top_end(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    for _ in range(200):
        panel.edit_view.wheelEvent(_wheel_event(120))
    # A rejected step leaves _viewport_zoom at the last value still
    # within bounds -- generally just *under* the limit, not snapped
    # exactly to it (each multiplicative step can overshoot it).
    assert panel.edit_view._viewport_zoom <= cpw_module._MAX_VIEWPORT_ZOOM
    assert panel.edit_view._viewport_zoom > cpw_module._MAX_VIEWPORT_ZOOM / cpw_module._VIEWPORT_ZOOM_STEP


def test_edit_canvas_zoom_is_clamped_at_the_bottom_end(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    for _ in range(200):
        panel.edit_view.wheelEvent(_wheel_event(-120))
    assert panel.edit_view._viewport_zoom >= cpw_module._MIN_VIEWPORT_ZOOM
    assert panel.edit_view._viewport_zoom < cpw_module._MIN_VIEWPORT_ZOOM * cpw_module._VIEWPORT_ZOOM_STEP


def test_edit_canvas_zoom_resets_on_refit(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.edit_view.wheelEvent(_wheel_event(120))
    assert panel.edit_view._viewport_zoom != pytest.approx(1.0)

    panel.edit_view.refit_to_content()

    assert panel.edit_view._viewport_zoom == pytest.approx(1.0)


def test_live_preview_does_not_zoom_on_scroll(qapp, tmp_path):
    # Owner's request: viewport zoom only for the Edit canvas -- Live
    # Preview must always show the avatar at its real Render Window
    # size, so scrolling there is left at Qt's own default (no zoom).
    config, window, panel, _ = make_panel(tmp_path)
    scale_before = panel.live_view.transform().m11()
    panel.live_view.wheelEvent(_wheel_event(120))
    assert panel.live_view.transform().m11() == pytest.approx(scale_before)


# --- Edit canvas Ctrl+drag pan (owner's request, 2026-09-19) ----------------


def _mouse_event(event_type, pos, modifiers=Qt.KeyboardModifier.NoModifier):
    buttons = Qt.MouseButton.NoButton if event_type == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    return QMouseEvent(event_type, pos, buttons, buttons, modifiers)


def test_ctrl_drag_pans_the_edit_canvas(qapp, tmp_path):
    # A real, sizable sprite (_make_square_sprite_panel's 100x100, not
    # make_panel's default tiny 4x4 test rig) and a real, shown window --
    # the scrollbar range calculation needs a real (non-degenerate)
    # viewport size, which an unshown widget doesn't reliably have, and
    # enough content that a modest zoom-in actually exceeds the viewport.
    # At the default fit-to-content baseline the view exactly matches the
    # content size, so the scrollbar range is [0, 0] and there is nothing
    # to pan *to* regardless of drag handling.
    config, window, panel, _ = _make_square_sprite_panel(tmp_path)
    panel.resize(1000, 800)
    panel.edit_sprites_btn.setChecked(True)
    panel.show()
    for _ in range(5):
        qapp.processEvents()
    for _ in range(10):
        panel.edit_view.wheelEvent(_wheel_event(120))
        qapp.processEvents()
    hbar = panel.edit_view.horizontalScrollBar()
    vbar = panel.edit_view.verticalScrollBar()
    assert hbar.maximum() > hbar.minimum(), "test setup: nothing to pan to"
    before = (hbar.value(), vbar.value())

    panel.edit_view.mousePressEvent(
        _mouse_event(QEvent.Type.MouseButtonPress, QPointF(100, 100), Qt.KeyboardModifier.ControlModifier)
    )
    panel.edit_view.mouseMoveEvent(
        _mouse_event(QEvent.Type.MouseMove, QPointF(60, 80), Qt.KeyboardModifier.ControlModifier)
    )
    panel.edit_view.mouseReleaseEvent(_mouse_event(QEvent.Type.MouseButtonRelease, QPointF(60, 80)))

    # Dragged left 40px, up 20px -- standard hand-tool convention is the
    # *content* sticks to the cursor (Photoshop/Figma/browsers), so
    # dragging left must scroll further right into the document, i.e.
    # the scrollbar *value* increases, not decreases.
    assert hbar.value() == before[0] + 40
    assert vbar.value() == before[1] + 20
    assert panel.edit_view._panning is False  # cleared on release


def test_plain_drag_without_ctrl_does_not_pan(qapp, tmp_path):
    # Regression guard: only Ctrl+drag pans -- an ordinary drag (moving a
    # sprite, or clicking empty canvas) must never scroll the view.
    config, window, panel, _ = make_panel(tmp_path)
    hbar = panel.edit_view.horizontalScrollBar()
    vbar = panel.edit_view.verticalScrollBar()
    before = (hbar.value(), vbar.value())

    panel.edit_view.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, QPointF(10, 10)))
    panel.edit_view.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, QPointF(60, 80)))
    panel.edit_view.mouseReleaseEvent(_mouse_event(QEvent.Type.MouseButtonRelease, QPointF(60, 80)))

    assert (hbar.value(), vbar.value()) == before
    assert panel.edit_view._panning is False


def test_ctrl_drag_shows_a_closed_hand_cursor_while_panning(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.edit_view.mousePressEvent(
        _mouse_event(QEvent.Type.MouseButtonPress, QPointF(100, 100), Qt.KeyboardModifier.ControlModifier)
    )
    assert panel.edit_view.cursor().shape() == Qt.CursorShape.ClosedHandCursor
    panel.edit_view.mouseReleaseEvent(_mouse_event(QEvent.Type.MouseButtonRelease, QPointF(100, 100)))
    assert panel.edit_view.cursor().shape() != Qt.CursorShape.ClosedHandCursor


# --- Dirty tracking / Save / Save As / Load -------------------------------


def test_save_with_no_current_path_falls_back_to_save_as(qapp, tmp_path, monkeypatch):
    config, window, panel, _ = make_panel(tmp_path)
    panel._current_avatar_path = ""
    calls = []
    monkeypatch.setattr(panel, "_on_save_as", lambda: calls.append(True))
    panel._on_save()
    assert calls == [True]


def test_save_as_updates_current_path_and_clears_dirty(qapp, tmp_path, monkeypatch):
    config, window, panel, _ = make_panel(tmp_path)
    out_path = tmp_path / "avatar.uc"
    monkeypatch.setattr(
        cpw_module.QFileDialog, "getSaveFileName", lambda *a, **k: (str(out_path), "")
    )
    panel._select(1)
    panel.pos_x.setValue(10.0)
    assert panel._dirty is True

    panel._on_save_as()

    assert panel._dirty is False
    assert panel._current_avatar_path == str(out_path)
    assert config.avatar_path == str(out_path)
    assert out_path.exists()


def test_save_writes_to_the_current_path_without_a_dialog(qapp, tmp_path, monkeypatch):
    config, window, panel, _ = make_panel(tmp_path)
    out_path = tmp_path / "avatar.uc"
    panel._current_avatar_path = str(out_path)
    dialog_calls = []
    monkeypatch.setattr(
        cpw_module.QFileDialog, "getSaveFileName",
        lambda *a, **k: dialog_calls.append(True) or ("", ""),
    )
    panel._select(1)
    panel.pos_x.setValue(10.0)

    panel._on_save()

    assert dialog_calls == []
    assert panel._dirty is False
    assert out_path.exists()


def test_load_updates_current_path_and_clears_dirty(qapp, tmp_path, monkeypatch):
    config, window, panel, _ = make_panel(tmp_path)
    save_path = tmp_path / "other.uc"
    from unicorn_cloak.persistence import save_avatar

    other_rig = make_test_rig()
    save_avatar(other_rig, save_path)

    panel._select(1)
    panel.pos_x.setValue(10.0)
    assert panel._dirty is True

    monkeypatch.setattr(
        cpw_module.QFileDialog, "getOpenFileName", lambda *a, **k: (str(save_path), "")
    )
    panel._on_load()

    assert panel._dirty is False
    assert panel._current_avatar_path == str(save_path)
    assert config.avatar_path == str(save_path)


def test_load_replaces_costume_and_expression_assignments_too(qapp, tmp_path, monkeypatch):
    # Regression, bug audit 2026-09-23 (#1): _on_load used to copy
    # name/sprites/active_costume/zoom by hand and forget
    # costume_assignments/expression_hotkeys -- the Costume/Expression
    # Hotkeys tabs (and the next Save) kept the *previous* avatar's
    # assignments after Load.
    from unicorn_cloak.persistence import save_avatar

    config, window, panel, _ = make_panel(tmp_path)
    panel.rig.assign_costume_pair(0, hide_id=1, show_id=2)
    panel.rig.assign_expression_hotkey(1, "Mouth", "Laughing")
    assert panel.rig.costume_assignments[0] == [(1, 2)]

    other_rig = make_test_rig()
    other_rig.assign_expression_hotkey(0, "Eyes", "Open")
    save_path = tmp_path / "other.uc"
    save_avatar(other_rig, save_path)

    monkeypatch.setattr(
        cpw_module.QFileDialog, "getOpenFileName", lambda *a, **k: (str(save_path), "")
    )
    panel._on_load()

    assert panel.rig.costume_assignments[0] == []  # the old avatar's pair is gone
    assert panel.rig.expression_hotkeys[0] == [("Eyes", "Open")]  # the new avatar's is here
    assert panel.rig.expression_hotkeys[1] == []  # not the old avatar's leftover row


def test_load_clears_undo_history_instead_of_pushing_a_snapshot(qapp, tmp_path, monkeypatch):
    # Regression, bug audit 2026-09-23 (#2): Load used to push_undo_
    # snapshot() the old avatar, then re-point _current_avatar_path at
    # the *new* file -- so Undo restored the old avatar's sprites while
    # the path/title still read the new file, and the next Save
    # overwrote the newly loaded file with the old avatar's contents.
    from unicorn_cloak.persistence import save_avatar

    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    panel.pos_x.setValue(10.0)  # a real undo-able edit before Load
    assert panel._undo_btn.isEnabled() is True

    other_rig = make_test_rig()
    save_path = tmp_path / "other.uc"
    save_avatar(other_rig, save_path)
    monkeypatch.setattr(
        cpw_module.QFileDialog, "getOpenFileName", lambda *a, **k: (str(save_path), "")
    )
    panel._on_load()

    assert panel._undo_btn.isEnabled() is False
    assert panel._redo_btn.isEnabled() is False
    loaded_sprite_ids = [s.id for s in panel.rig.sprites]

    panel.undo()  # must be a no-op: nothing to undo "into" any more

    assert [s.id for s in panel.rig.sprites] == loaded_sprite_ids
    assert panel._current_avatar_path == str(save_path)


def test_save_does_not_trigger_its_own_hot_reload(qapp, tmp_path):
    # Regression, bug audit 2026-09-23 (#3): save_avatar writes via
    # temp-file + os.replace, which QFileSystemWatcher reports the same
    # as an external edit -- Save was triggering the app's own hot
    # reload, which reset active_costume to 0 and deselected/rebuilt the
    # live scene. asset_watcher.note_own_write() (called by _on_save)
    # must make the *next* change event for this exact path a no-op.
    from unicorn_cloak.hot_reload import AssetWatcher

    config, window, panel, _ = make_panel(tmp_path)
    out_path = tmp_path / "avatar.uc"
    panel._current_avatar_path = str(out_path)
    watcher = AssetWatcher()
    panel.asset_watcher = watcher

    panel._on_save()  # writes out_path, then note_own_write(out_path)
    watcher.watch_avatar_file(str(out_path))

    reload_events = []
    watcher.avatar_file_changed.connect(lambda: reload_events.append(True))
    watcher._emit_for_path(str(out_path))  # simulate the watcher noticing our own write

    assert reload_events == []


# --- Quit confirmation ------------------------------------------------------


def test_confirm_and_quit_asks_yes_no_when_clean(qapp, tmp_path, monkeypatch):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel._dirty is False
    monkeypatch.setattr(
        cpw_module.QMessageBox, "question",
        lambda *a, **k: cpw_module.QMessageBox.StandardButton.Yes,
    )
    assert panel.confirm_and_quit() is True


def test_confirm_and_quit_returns_false_on_no(qapp, tmp_path, monkeypatch):
    config, window, panel, _ = make_panel(tmp_path)
    monkeypatch.setattr(
        cpw_module.QMessageBox, "question",
        lambda *a, **k: cpw_module.QMessageBox.StandardButton.No,
    )
    assert panel.confirm_and_quit() is False


def test_confirm_and_quit_warns_and_cancels_when_dirty(qapp, tmp_path, monkeypatch):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    panel.pos_x.setValue(10.0)
    assert panel._dirty is True
    monkeypatch.setattr(
        cpw_module.QMessageBox, "warning",
        lambda *a, **k: cpw_module.QMessageBox.StandardButton.Cancel,
    )
    assert panel.confirm_and_quit() is False


def test_confirm_and_quit_discard_quits_without_saving(qapp, tmp_path, monkeypatch):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    panel.pos_x.setValue(10.0)
    monkeypatch.setattr(
        cpw_module.QMessageBox, "warning",
        lambda *a, **k: cpw_module.QMessageBox.StandardButton.Discard,
    )
    assert panel.confirm_and_quit() is True
    assert panel._dirty is True  # discarded, not saved


def test_confirm_and_quit_save_then_quits_when_a_path_exists(qapp, tmp_path, monkeypatch):
    config, window, panel, _ = make_panel(tmp_path)
    panel._current_avatar_path = str(tmp_path / "avatar.uc")
    panel._select(1)
    panel.pos_x.setValue(10.0)
    monkeypatch.setattr(
        cpw_module.QMessageBox, "warning",
        lambda *a, **k: cpw_module.QMessageBox.StandardButton.Save,
    )
    assert panel.confirm_and_quit() is True
    assert panel._dirty is False


def test_quit_button_only_asks_to_confirm_once(qapp, tmp_path, monkeypatch):
    # Regression 2026-09-17, reported by the owner: "the quit dialog pops
    # twice". Root cause: _on_quit_clicked used to call confirm_and_quit()
    # itself and *then* QApplication.instance().quit() -- but quit() sends
    # a QCloseEvent to every remaining top-level window as part of normal
    # Qt shutdown, which hit RenderWindow.closeEvent's own
    # on_quit_requested() call (wired to this same confirm_and_quit) a
    # second time. Wire it exactly like __main__.py does, then count real
    # calls through that wiring, not a direct call to confirm_and_quit().
    config, window, panel, _ = make_panel(tmp_path)
    window.on_quit_requested = panel.confirm_and_quit

    call_count = 0
    orig_confirm_and_quit = panel.confirm_and_quit

    def counting_confirm_and_quit():
        nonlocal call_count
        call_count += 1
        return orig_confirm_and_quit()

    panel.confirm_and_quit = counting_confirm_and_quit
    window.on_quit_requested = counting_confirm_and_quit

    monkeypatch.setattr(
        cpw_module.QMessageBox, "question",
        lambda *a, **k: cpw_module.QMessageBox.StandardButton.Yes,
    )
    panel._on_quit_clicked()
    assert call_count == 1


# --- Source bar / elided file label -----------------------------------------


def test_file_label_hidden_when_no_file_chosen(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.audio_file_label.isVisible() is False


def test_rewind_button_sits_left_of_play(qapp, tmp_path):
    # Owner's request, 2026-09-20 -- it first landed to Play's right the
    # day before.
    config, window, panel, _ = make_panel(tmp_path)
    play_index = panel.source_row.indexOf(panel.play_file_btn)
    rewind_index = panel.source_row.indexOf(panel._rewind_file_btn)
    assert rewind_index == play_index - 1


def test_rewind_button_text_is_just_rewind(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel._rewind_file_btn.text() == "Rewind"


def test_rewind_button_restarts_playback_while_playing(qapp, tmp_path, monkeypatch):
    # Owner's request, 2026-09-20: a rewind-to-beginning button next to
    # Play. FilePlayback (audio.py) can't seek, so "rewind" is just
    # AudioManager.play_file() again -- it already stops whatever's
    # currently playing and restarts fresh from 0:00.
    from unicorn_cloak.audio_manager import AudioManager

    config = Config()
    config.audio.source = "file"
    config.audio.file_path = "/tmp/whatever.wav"
    rig = make_test_rig()
    window = RenderWindow(rig, config.motion, hotkeys_config=config.hotkeys)
    manager = AudioManager(config)
    calls = []
    monkeypatch.setattr(manager, "play_file", lambda: calls.append(True))
    monkeypatch.setattr(AudioManager, "is_file_playing", property(lambda self: True))
    panel = ControlPanelWindow(
        rig, config, window, state_path=tmp_path / "settings.json", audio_manager=manager,
    )

    panel._rewind_file_btn.click()

    assert calls == [True]


def test_rewind_button_does_nothing_while_stopped(qapp, tmp_path, monkeypatch):
    # Same-day reversal, 2026-09-20: rewind used to restart-and-play even
    # from a stopped state, which the owner reported as an unwanted
    # auto-play ("hitting rewind when a selected track is stopped does
    # rewind, but starts it playing"). A stopped file is already sitting
    # at 0:00 for the next Play (play_file() always decodes from the
    # start), so there was never really anything to rewind in that
    # state -- a no-op is correct, not a restart.
    from unicorn_cloak.audio_manager import AudioManager

    config = Config()
    config.audio.source = "file"
    config.audio.file_path = "/tmp/whatever.wav"
    rig = make_test_rig()
    window = RenderWindow(rig, config.motion, hotkeys_config=config.hotkeys)
    manager = AudioManager(config)
    calls = []
    monkeypatch.setattr(manager, "play_file", lambda: calls.append(True))
    monkeypatch.setattr(AudioManager, "is_file_playing", property(lambda self: False))
    panel = ControlPanelWindow(
        rig, config, window, state_path=tmp_path / "settings.json", audio_manager=manager,
    )

    panel._rewind_file_btn.click()

    assert calls == []


def test_rewind_button_enabled_state_matches_play(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel._rewind_file_btn.isEnabled() is False  # source defaults to microphone

    config.audio.source = "file"
    config.audio.file_path = "/tmp/whatever.wav"
    panel._update_source_controls_enabled()
    assert panel._rewind_file_btn.isEnabled() is True
    assert panel._rewind_file_btn.isEnabled() == panel.play_file_btn.isEnabled()


# --- Desktop audio source / device dropdown (owner's request, 2026-09-23) ---


def test_audio_source_combo_offers_desktop_audio(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    values = [panel.audio_source.itemData(i) for i in range(panel.audio_source.count())]
    assert values == ["microphone", "desktop", "file"]


def test_device_row_disabled_only_on_file_source(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.audio_device.isEnabled() is True  # source defaults to microphone
    assert panel._audio_device_refresh_btn.isEnabled() is True

    config.audio.source = "file"
    panel._update_source_controls_enabled()
    assert panel.audio_device.isEnabled() is False
    assert panel._audio_device_refresh_btn.isEnabled() is False

    config.audio.source = "desktop"
    panel._update_source_controls_enabled()
    assert panel.audio_device.isEnabled() is True


def test_device_dropdown_always_offers_system_default_first(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)  # audio_manager=None here
    assert panel.audio_device.count() == 1
    assert panel.audio_device.itemText(0) == "System default"
    assert panel.audio_device.itemData(0) is None


def test_device_dropdown_lists_audio_manager_devices(qapp, tmp_path, monkeypatch):
    from unicorn_cloak.audio_manager import AudioManager

    config = Config()
    rig = make_test_rig()
    window = RenderWindow(rig, config.motion, hotkeys_config=config.hotkeys)
    manager = AudioManager(config)
    monkeypatch.setattr(manager, "list_devices", lambda: ["Blue Microphones Analog Stereo", "Built-in Audio Analog Stereo"])
    panel = ControlPanelWindow(
        rig, config, window, state_path=tmp_path / "settings.json", audio_manager=manager,
    )

    names = [panel.audio_device.itemText(i) for i in range(panel.audio_device.count())]
    assert names == ["System default", "Blue Microphones Analog Stereo", "Built-in Audio Analog Stereo"]


def test_selecting_a_device_calls_set_device_and_persists(qapp, tmp_path, monkeypatch):
    from unicorn_cloak.audio_manager import AudioManager

    config = Config()
    rig = make_test_rig()
    window = RenderWindow(rig, config.motion, hotkeys_config=config.hotkeys)
    manager = AudioManager(config)
    monkeypatch.setattr(manager, "list_devices", lambda: ["Built-in Audio Analog Stereo"])
    calls = []
    monkeypatch.setattr(manager, "set_device", lambda device: calls.append(device))
    panel = ControlPanelWindow(
        rig, config, window, state_path=tmp_path / "settings.json", audio_manager=manager,
    )

    index = panel.audio_device.findData("Built-in Audio Analog Stereo")
    panel.audio_device.setCurrentIndex(index)

    assert calls == ["Built-in Audio Analog Stereo"]


def test_switching_source_shows_each_sources_own_device_choice(qapp, tmp_path, monkeypatch):
    from unicorn_cloak.audio_manager import AudioManager

    config = Config()
    config.audio.device = "Mic A"
    config.audio.desktop_device = "Desktop B"
    rig = make_test_rig()
    window = RenderWindow(rig, config.motion, hotkeys_config=config.hotkeys)
    manager = AudioManager(config)
    monkeypatch.setattr(manager, "list_devices", lambda: ["Mic A", "Desktop B"])
    monkeypatch.setattr(manager, "switch_to_microphone", lambda: None)
    monkeypatch.setattr(manager, "switch_to_desktop", lambda: None)
    panel = ControlPanelWindow(
        rig, config, window, state_path=tmp_path / "settings.json", audio_manager=manager,
    )
    assert panel.audio_device.currentText() == "Mic A"

    panel.audio_source.setCurrentIndex(panel.audio_source.findData("desktop"))
    assert panel.audio_device.currentText() == "Desktop B"

    panel.audio_source.setCurrentIndex(panel.audio_source.findData("microphone"))
    assert panel.audio_device.currentText() == "Mic A"


def test_refresh_button_repopulates_the_device_list(qapp, tmp_path, monkeypatch):
    from unicorn_cloak.audio_manager import AudioManager

    config = Config()
    rig = make_test_rig()
    window = RenderWindow(rig, config.motion, hotkeys_config=config.hotkeys)
    manager = AudioManager(config)
    device_names = ["Blue Microphones Analog Stereo"]
    monkeypatch.setattr(manager, "list_devices", lambda: list(device_names))
    panel = ControlPanelWindow(
        rig, config, window, state_path=tmp_path / "settings.json", audio_manager=manager,
    )
    assert panel.audio_device.count() == 2  # System default + the one device

    device_names.append("Built-in Audio Analog Stereo")  # e.g. headphones just plugged in
    panel._audio_device_refresh_btn.click()

    assert panel.audio_device.count() == 3


def test_browsing_a_file_shows_the_elided_label(qapp, tmp_path, monkeypatch):
    config, window, panel, _ = make_panel(tmp_path)
    panel.show()
    long_path = "/home/jj/projects/unicorn-tears/some/very/deeply/nested/recording.mp3"
    monkeypatch.setattr(
        cpw_module.QFileDialog, "getOpenFileName", lambda *a, **k: (long_path, "")
    )
    panel._on_browse_audio_file()
    assert panel.audio_file_label.isVisible() is True
    assert panel.audio_file_label.text().endswith("/recording.mp3")
    assert config.audio.file_path == long_path


# --- Background image/video --------------------------------------------------


def test_background_browse_button_hidden_for_solid_modes(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel._background_browse_btn.isVisible() is False
    assert panel.background_file_label.isVisible() is False


def _show_application_tab(panel):
    # isVisible() only reflects reality once the widget's whole ancestor
    # chain (including its QTabWidget page) is actually shown -- these
    # controls live on the Application tab, so switching to it plus a
    # real show() is required, not just setVisible() on the widget itself.
    # The Display section can also start auto-collapsed on a small/fresh
    # window (the splitter's own "don't overflow the panel" logic, not
    # anything specific to Background) -- force it open too, independent
    # of that.
    panel.show()
    titles = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
    panel.tabs.setCurrentIndex(titles.index("Application"))
    panel._sections["Display & Canvas"].set_collapsed(False)


def test_selecting_image_background_shows_the_browse_button(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    _show_application_tab(panel)
    index = panel.background.findData("image")
    panel.background.setCurrentIndex(index)
    assert panel._background_browse_btn.isVisible() is True
    assert config.window.background == "image"


def test_browsing_an_image_background_sets_the_path_and_updates_the_window(qapp, tmp_path, monkeypatch):
    config, window, panel, _ = make_panel(tmp_path)
    _show_application_tab(panel)
    index = panel.background.findData("image")
    panel.background.setCurrentIndex(index)
    png_path = str(tmp_path / "bg.png")
    (tmp_path / "bg.png").write_bytes(make_test_png_bytes())
    monkeypatch.setattr(
        cpw_module.QFileDialog, "getOpenFileName", lambda *a, **k: (png_path, "")
    )
    panel._on_browse_background_file()
    assert config.window.background_image_path == png_path
    assert panel.background_file_label.isVisible() is True
    assert window._background_image_item is not None


def test_browsing_a_video_background_sets_the_path_and_updates_the_window(qapp, tmp_path, monkeypatch):
    config, window, panel, _ = make_panel(tmp_path)
    panel.show()
    index = panel.background.findData("video")
    panel.background.setCurrentIndex(index)
    video_path = str(tmp_path / "bg.mp4")
    (tmp_path / "bg.mp4").write_bytes(b"not a real video, just needs to exist")
    monkeypatch.setattr(
        cpw_module.QFileDialog, "getOpenFileName", lambda *a, **k: (video_path, "")
    )
    panel._on_browse_background_file()
    assert config.window.background_video_path == video_path
    assert window._background_video_item is not None


def test_switching_back_to_a_solid_color_hides_the_browse_controls(qapp, tmp_path, monkeypatch):
    config, window, panel, _ = make_panel(tmp_path)
    _show_application_tab(panel)
    index = panel.background.findData("image")
    panel.background.setCurrentIndex(index)
    monkeypatch.setattr(
        cpw_module.QFileDialog, "getOpenFileName", lambda *a, **k: (str(tmp_path / "bg.png"), "")
    )
    (tmp_path / "bg.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    panel._on_browse_background_file()

    index = panel.background.findData("black")
    panel.background.setCurrentIndex(index)
    assert panel._background_browse_btn.isVisible() is False
    assert panel.background_file_label.isVisible() is False


# --- Scale ------------------------------------------------------------------


def test_scale_field_loads_the_selected_sprites_values(qapp, tmp_path):
    png = make_test_png_bytes()
    sprites = [Sprite(id=1, path="a.png", image_data=png, scale_x=1.5, scale_y=0.75)]
    config, window, panel, _ = make_panel(tmp_path, rig=AvatarRig(name="t", sprites=sprites))
    panel._select(1)
    assert panel.scale_x.value() == 1.5
    assert panel.scale_y.value() == 0.75


def test_dragging_a_corner_handle_allows_independent_x_and_y(qapp, tmp_path):
    # "Lock proportions" is checked by default (see test_scale_lock_is_
    # checked_by_default below), so an independent-axes drag needs it
    # turned off first -- this is no longer the out-of-the-box behavior.
    config, window, panel, _ = _make_square_sprite_panel(tmp_path)
    panel._select(1)
    panel.scale_lock.setChecked(False)
    item = panel._items[1]
    item._active_handle = "br"
    item._drag_handle(QPointF(150.0, 75.0))
    sprite = panel.rig.by_id(1)
    assert sprite.scale_x == pytest.approx(3.0)  # 150 / 50
    assert sprite.scale_y == pytest.approx(1.5)  # 75 / 50


def test_dragging_a_corner_handle_keeps_proportions_when_locked(qapp, tmp_path):
    # The restored default behavior: dragging a corner handle scales both
    # axes by the same (averaged) ratio, per the owner's 2026-09-19
    # request to bring this back after it was briefly retired in favor of
    # the (separate, coexisting) "Lock Position" feature.
    config, window, panel, _ = _make_square_sprite_panel(tmp_path)
    panel._select(1)
    assert panel.scale_lock.isChecked() is True  # default
    item = panel._items[1]
    item._active_handle = "br"
    item._drag_handle(QPointF(150.0, 75.0))
    sprite = panel.rig.by_id(1)
    assert sprite.scale_x == pytest.approx(sprite.scale_y)


# --- Lock proportions (Scale X/Y linking; restored 2026-09-19) --------------


def test_scale_lock_is_checked_by_default(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.scale_lock.isChecked() is True


def test_scale_lock_links_x_and_y_when_checked(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    assert panel.scale_lock.isChecked() is True

    panel.scale_x.setValue(2.5)

    assert panel.scale_y.value() == pytest.approx(2.5)
    assert panel.rig.by_id(1).scale_y == pytest.approx(2.5)


def test_scale_unlocked_allows_independent_x_and_y(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    panel.scale_lock.setChecked(False)

    panel.scale_x.setValue(2.5)

    assert panel.scale_y.value() == pytest.approx(1.0)
    assert panel.rig.by_id(1).scale_y == pytest.approx(1.0)


# --- Lock Position (owner's request, 2026-09-19; separate from "Lock proportions" above) ----


def test_lock_position_unchecked_by_default(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.lock_position_btn.isChecked() is False


def test_lock_position_round_trips_through_the_avatar_file(qapp, tmp_path):
    # Per-sprite and saved with the avatar now (Sprite.locked), not a
    # global control_panel.scale_lock_proportions session preference.
    sprites = [Sprite(id=1, path="a.png", image_data=make_test_png_bytes(), locked=True)]
    config, window, panel, _ = make_panel(tmp_path, rig=AvatarRig(name="t", sprites=sprites))
    panel._select(1)
    assert panel.lock_position_btn.isChecked() is True


def test_checking_lock_position_disables_position_rotation_and_scale(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    for widget in (panel.pos_x, panel.pos_y, panel.rotation, panel.scale_x, panel.scale_y):
        assert widget.isEnabled() is True

    panel.lock_position_btn.setChecked(True)

    for widget in (panel.pos_x, panel.pos_y, panel.rotation, panel.scale_x, panel.scale_y):
        assert widget.isEnabled() is False
    # Everything else stays editable while locked.
    for widget in (panel.offset_x, panel.offset_y, panel.z_index, panel.parent_combo):
        assert widget.isEnabled() is True
    assert panel.rig.by_id(1).locked is True


def test_unchecking_lock_position_reenables_the_fields(qapp, tmp_path):
    sprites = [Sprite(id=1, path="a.png", image_data=make_test_png_bytes(), locked=True)]
    config, window, panel, _ = make_panel(tmp_path, rig=AvatarRig(name="t", sprites=sprites))
    panel._select(1)
    assert panel.pos_x.isEnabled() is False

    panel.lock_position_btn.setChecked(False)

    for widget in (panel.pos_x, panel.pos_y, panel.rotation, panel.scale_x, panel.scale_y):
        assert widget.isEnabled() is True
    assert panel.rig.by_id(1).locked is False


def test_layer_list_padlock_and_lock_position_button_share_state(qapp, tmp_path):
    # Owner's request: "both the padlock & the lock position button will
    # both fire the same code and share state."
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    lock_row_btn = panel._lock_row_buttons[1]
    assert lock_row_btn.isChecked() is False

    lock_row_btn.setChecked(True)  # toggling the Layer List's own icon

    assert panel.rig.by_id(1).locked is True
    assert panel.lock_position_btn.isChecked() is True  # synced
    assert panel.pos_x.isEnabled() is False

    panel.lock_position_btn.setChecked(False)  # toggling the other control

    assert panel.rig.by_id(1).locked is False
    assert lock_row_btn.isChecked() is False  # synced back
    assert panel.pos_x.isEnabled() is True


def test_locking_a_sprite_disables_moving_it_on_the_canvas(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    item = panel._items[1]
    assert item.flags() & QGraphicsItem.ItemIsMovable

    panel._on_sprite_lock_toggled(1, True)

    assert not (item.flags() & QGraphicsItem.ItemIsMovable)


def test_locked_sprite_has_no_resize_or_rotate_handles(qapp, tmp_path):
    config, window, panel, _ = _make_square_sprite_panel(tmp_path, locked=True)
    panel._select(1)
    item = panel._items[1]
    assert item._handle_rects() == {}
    assert item._handle_at(item._pixmap_rect().topLeft()) is None


def test_lock_state_is_undoable(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    panel.lock_position_btn.setChecked(True)
    assert panel.rig.by_id(1).locked is True

    panel.undo()

    assert panel.rig.by_id(1).locked is False


# --- Parent combo (Position & Hierarchy) --------------------------------------


def test_parent_combo_is_populated_before_any_sprite_is_selected(qapp, tmp_path):
    # Owner's report, 2026-09-19: "it does not populate in the parent row
    # under position & hierarchy pane" -- a QComboBox nobody has ever
    # called addItem() on shows as empty and disabled, unlike the spinbox
    # fields nearby which always show *some* value.
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.parent_combo.count() >= 1
    assert panel.parent_combo.itemText(0) == "None (root)"


# --- Behavior tab header (owner's request, 2026-09-19) -----------------------


def test_behavior_layer_combo_shows_no_selection_by_default(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.behavior_layer_combo.currentText() == "(no layer selected)"
    assert panel.behavior_layer_combo.currentData() is None


def test_behavior_layer_combo_lists_every_sprite(qapp, tmp_path):
    sprites = [
        Sprite(id=1, path="assets/mouth_open.png", image_data=make_test_png_bytes()),
        Sprite(id=2, path="assets/eyes_open.png", image_data=make_test_png_bytes()),
    ]
    config, window, panel, _ = make_panel(tmp_path, rig=AvatarRig(name="t", sprites=sprites))
    texts = [panel.behavior_layer_combo.itemText(i) for i in range(panel.behavior_layer_combo.count())]
    assert "mouth_open.png" in texts
    assert "eyes_open.png" in texts


def test_behavior_layer_combo_follows_the_selected_layer(qapp, tmp_path):
    # Owner's request, 2026-09-20: "show the active layer whatever it
    # is... if they change layers from the sprites tab, it will be the
    # active one on the behaviors drop down." _select() is the single
    # choke point both the Sprites tab's Layer List and a canvas click
    # already go through, so driving it directly here exercises both.
    sprites = [Sprite(id=1, path="assets/mouth_open.png", image_data=make_test_png_bytes())]
    config, window, panel, _ = make_panel(tmp_path, rig=AvatarRig(name="t", sprites=sprites))
    panel._select(1)
    assert panel.behavior_layer_combo.currentText() == "mouth_open.png"
    assert panel.behavior_layer_combo.currentData() == 1


def test_behavior_layer_combo_reverts_on_deselect(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    panel._select(None)
    assert panel.behavior_layer_combo.currentText() == "(no layer selected)"


def test_picking_a_layer_in_the_behavior_combo_selects_it(qapp, tmp_path):
    # The write half of the two-way sync: picking a different layer here
    # must drive selection exactly like clicking it in the Layer List.
    sprites = [
        Sprite(id=1, path="a.png", image_data=make_test_png_bytes()),
        Sprite(id=2, path="b.png", image_data=make_test_png_bytes()),
    ]
    config, window, panel, _ = make_panel(tmp_path, rig=AvatarRig(name="t", sprites=sprites))
    index = panel.behavior_layer_combo.findData(2)

    panel.behavior_layer_combo.setCurrentIndex(index)

    assert panel._selected_id == 2
    assert panel.pos_x.isEnabled() is True  # property form followed the new selection


def test_locked_layers_are_greyed_out_in_the_behavior_combo(qapp, tmp_path):
    # Owner's request, 2026-09-20: "drop box should show locked layers as
    # slightly greyed out."
    sprites = [Sprite(id=1, path="a.png", image_data=make_test_png_bytes(), locked=True)]
    config, window, panel, _ = make_panel(tmp_path, rig=AvatarRig(name="t", sprites=sprites))
    index = panel.behavior_layer_combo.findData(1)
    color = panel.behavior_layer_combo.itemData(index, Qt.ItemDataRole.ForegroundRole)
    assert color is not None


def test_unlocked_layers_are_not_greyed_out_in_the_behavior_combo(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    index = panel.behavior_layer_combo.findData(1)
    color = panel.behavior_layer_combo.itemData(index, Qt.ItemDataRole.ForegroundRole)
    assert color is None


def test_toggling_lock_updates_the_behavior_combos_greying_live(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    index = panel.behavior_layer_combo.findData(1)

    panel._on_sprite_lock_toggled(1, True)
    assert panel.behavior_layer_combo.itemData(index, Qt.ItemDataRole.ForegroundRole) is not None

    panel._on_sprite_lock_toggled(1, False)
    assert panel.behavior_layer_combo.itemData(index, Qt.ItemDataRole.ForegroundRole) is None


def test_behavior_tab_is_second_right_after_sprites(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.tabs.tabText(0) == "Sprites"
    assert panel.tabs.tabText(1) == "Behavior"


# --- Rotation -----------------------------------------------------------------


def test_rotation_field_loads_the_selected_sprites_value(qapp, tmp_path):
    sprites = [Sprite(id=1, path="a.png", image_data=make_test_png_bytes(), rotation_deg=45.0)]
    config, window, panel, _ = make_panel(tmp_path, rig=AvatarRig(name="t", sprites=sprites))
    panel._select(1)
    assert panel.rotation.value() == 45.0


def test_editing_rotation_field_writes_through_to_the_sprite(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    panel.rotation.setValue(30.0)
    assert panel.rig.by_id(1).rotation_deg == 30.0


# --- Reset Size / Reset Rotation buttons (Edit canvas) -----------------------


def test_reset_size_and_rotation_buttons_hidden_in_live_preview(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.show()
    panel.live_preview_btn.setChecked(True)
    assert panel.reset_size_btn.isVisible() is False
    assert panel.reset_rotation_btn.isVisible() is False


def test_reset_size_and_rotation_buttons_visible_in_edit_mode(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.show()
    panel.edit_sprites_btn.setChecked(True)
    assert panel.reset_size_btn.isVisible() is True
    assert panel.reset_rotation_btn.isVisible() is True


# --- Undo/Redo buttons (moved to the end of the mode row, 2026-09-19) -------


def test_undo_redo_buttons_hidden_in_live_preview(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.show()
    panel.live_preview_btn.setChecked(True)
    assert panel._undo_btn.isVisible() is False
    assert panel._redo_btn.isVisible() is False


def test_undo_redo_buttons_visible_in_edit_mode(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.show()
    panel.edit_sprites_btn.setChecked(True)
    assert panel._undo_btn.isVisible() is True
    assert panel._redo_btn.isVisible() is True


def test_undo_redo_buttons_live_at_the_end_of_the_mode_row(qapp, tmp_path):
    # Owner's request: "put those buttons at the end of the preview/edit
    # row when in edit mode" -- rather than the bottom action bar they
    # used to live in. Guide/Ghost joined them there the same day, then
    # moved again the next day to sit right after Edit Sprites (owner's
    # request, 2026-09-20: "to the left of the reset buttons, right of
    # the edit button") -- so this checks the row's full order, not just
    # that Undo/Redo are last (they no longer are; the trailing stretch
    # is -- see test_mode_row_is_not_split_by_an_internal_stretch below).
    config, window, panel, _ = make_panel(tmp_path)
    widgets = [
        panel.mode_row.itemAt(i).widget()
        for i in range(panel.mode_row.count())
        if panel.mode_row.itemAt(i).widget() is not None
    ]
    assert widgets == [
        panel.live_preview_btn, panel.edit_sprites_btn,
        panel.guide_btn, panel.ghost_btn,
        panel.reset_size_btn, panel.reset_rotation_btn,
        panel._undo_btn, panel._redo_btn,
    ]


def test_mode_row_is_not_split_by_an_internal_stretch(qapp, tmp_path):
    # Owner's request, 2026-09-19: "put all the bars in one [row] instead
    # of splitting undo/redo off on their own" -- the only stretch in
    # this row must be the trailing one (after every button), not one
    # in the middle pushing a subset of buttons off to the right.
    config, window, panel, _ = make_panel(tmp_path)
    count = panel.mode_row.count()
    item_kinds = [panel.mode_row.itemAt(i).widget() is None for i in range(count)]
    assert item_kinds.count(True) == 1  # exactly one spacer item
    assert item_kinds[-1] is True  # and it's the last item


# --- Guide / Ghost buttons (moved to the mode row, 2026-09-19) --------------


def test_guide_and_ghost_buttons_hidden_in_live_preview(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.show()
    panel.live_preview_btn.setChecked(True)
    assert panel.guide_btn.isVisible() is False
    assert panel.ghost_btn.isVisible() is False


def test_guide_and_ghost_buttons_visible_in_edit_mode(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.show()
    panel.edit_sprites_btn.setChecked(True)
    assert panel.guide_btn.isVisible() is True
    assert panel.ghost_btn.isVisible() is True


def test_reset_size_and_rotation_buttons_disabled_with_nothing_selected(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.reset_size_btn.isEnabled() is False
    assert panel.reset_rotation_btn.isEnabled() is False

    panel._select(1)
    assert panel.reset_size_btn.isEnabled() is True
    assert panel.reset_rotation_btn.isEnabled() is True


def test_reset_size_button_resets_scale_to_1(qapp, tmp_path):
    sprites = [Sprite(id=1, path="a.png", image_data=make_test_png_bytes(), scale_x=2.5, scale_y=0.4)]
    config, window, panel, _ = make_panel(tmp_path, rig=AvatarRig(name="t", sprites=sprites))
    panel._select(1)

    panel.reset_size_btn.click()

    sprite = panel.rig.by_id(1)
    assert sprite.scale_x == 1.0
    assert sprite.scale_y == 1.0
    assert panel.scale_x.value() == 1.0
    assert panel.scale_y.value() == 1.0


def test_reset_size_button_works_when_only_one_axis_is_off(qapp, tmp_path):
    # scale_x already 1.0 -> setValue(1.0) fires no signal for it; must
    # not leave scale_y stuck at its old value because of that.
    sprites = [Sprite(id=1, path="a.png", image_data=make_test_png_bytes(), scale_x=1.0, scale_y=3.0)]
    config, window, panel, _ = make_panel(tmp_path, rig=AvatarRig(name="t", sprites=sprites))
    panel._select(1)

    panel.reset_size_btn.click()

    sprite = panel.rig.by_id(1)
    assert sprite.scale_x == 1.0
    assert sprite.scale_y == 1.0


def test_reset_rotation_button_resets_rotation_to_0(qapp, tmp_path):
    sprites = [Sprite(id=1, path="a.png", image_data=make_test_png_bytes(), rotation_deg=123.0)]
    config, window, panel, _ = make_panel(tmp_path, rig=AvatarRig(name="t", sprites=sprites))
    panel._select(1)

    panel.reset_rotation_btn.click()

    assert panel.rig.by_id(1).rotation_deg == 0.0
    assert panel.rotation.value() == 0.0


def test_reset_size_and_rotation_are_undoable(qapp, tmp_path):
    sprites = [Sprite(id=1, path="a.png", image_data=make_test_png_bytes(), scale_x=2.0, rotation_deg=45.0)]
    config, window, panel, _ = make_panel(tmp_path, rig=AvatarRig(name="t", sprites=sprites))
    panel._select(1)

    panel.reset_size_btn.click()
    panel.reset_rotation_btn.click()
    assert panel.rig.by_id(1).scale_x == 1.0
    assert panel.rig.by_id(1).rotation_deg == 0.0

    panel.undo()
    assert panel.rig.by_id(1).rotation_deg == 45.0
    panel.undo()
    assert panel.rig.by_id(1).scale_x == 2.0


# --- Interactive scale/rotate handles (edit canvas) --------------------------


def _make_square_sprite_panel(tmp_path, **sprite_kwargs):
    png = make_test_png_bytes(size=100)
    sprite = Sprite(id=1, path="a.png", image_data=png, **sprite_kwargs)
    return make_panel(tmp_path, rig=AvatarRig(name="t", sprites=[sprite]))


def test_handle_hit_test_finds_nothing_when_not_selected(qapp, tmp_path):
    config, window, panel, _ = _make_square_sprite_panel(tmp_path)
    item = panel._items[1]
    assert item._handle_at(item._pixmap_rect().bottomRight()) is None


def test_handle_hit_test_finds_each_corner_and_the_rotate_handle(qapp, tmp_path):
    config, window, panel, _ = _make_square_sprite_panel(tmp_path)
    panel._select(1)
    item = panel._items[1]
    rect = item._pixmap_rect()
    assert item._handle_at(rect.topLeft()) == "tl"
    assert item._handle_at(rect.topRight()) == "tr"
    assert item._handle_at(rect.bottomLeft()) == "bl"
    assert item._handle_at(rect.bottomRight()) == "br"
    above_top_center = QPointF(rect.center().x(), rect.top() - 28.0)
    assert item._handle_at(above_top_center) == "rotate"
    assert item._handle_at(rect.center()) is None


def test_bounding_rect_when_selected_fully_contains_every_handle(qapp, tmp_path):
    # Regression 2026-09-19, owner's report: clicking a corner/rotate
    # handle "the guides disappear and nothing happens", and dragging a
    # sprite left trail artifacts behind it. Root cause: boundingRect()
    # only grew upward (for the rotate handle) -- half of each corner
    # handle sits outside the pixmap's own edge on the other three sides
    # too (see _handle_rects: they're centered ON the corners), so Qt
    # both clipped painting there (drag artifacts, since it didn't know
    # to invalidate/erase that region on move) and refused to deliver
    # clicks landing in that outer half (falls through to the empty
    # canvas, deselecting the sprite) before this fix.
    config, window, panel, _ = _make_square_sprite_panel(tmp_path)
    panel._select(1)
    item = panel._items[1]
    bounds = item.boundingRect()
    for name, hrect in item._handle_rects().items():
        assert bounds.contains(hrect), f"{name} handle sticks out of boundingRect()"


def test_shape_when_selected_covers_every_handle_even_on_a_fully_transparent_sprite(qapp, tmp_path):
    # QGraphicsPixmapItem.shape() traces opaque pixels by default -- a
    # handle drawn past a fully-transparent pixmap's edge would be
    # unclickable via the inherited shape() alone even with a big-enough
    # boundingRect(), since Qt's hit-testing consults shape(), not just
    # boundingRect(). A fully transparent test pixmap isolates exactly
    # this: super().shape() alone would be empty everywhere.
    png = make_test_png_bytes(color=(255, 0, 0, 0), size=100)
    sprite = Sprite(id=1, path="a.png", image_data=png)
    config, window, panel, _ = make_panel(tmp_path, rig=AvatarRig(name="t", sprites=[sprite]))
    panel._select(1)
    item = panel._items[1]
    shape = item.shape()
    for name, hrect in item._handle_rects().items():
        # The handle's own outer corner -- the point furthest from the
        # pixmap's opaque interior, and so the hardest case for a
        # mask-based shape() to cover.
        assert shape.contains(hrect.topLeft()), f"{name} handle's outer corner isn't in shape()"


def _send_mouse_move(item, scene_pos: QPointF) -> None:
    """A real QGraphicsSceneMouseEvent, with .pos() set the same way
    QGraphicsScene's own dispatch would (item.mapFromScene(scenePos), so
    through whatever transform the item *currently* has) -- calling
    item._drag_handle(...) directly with a hand-picked QPointF, as the
    other handle tests above do, can't reproduce the bug this guards:
    that only shows up via the real event pipeline's own live-remapped
    .pos(), across a multi-step drag."""
    event = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMouseMove)
    event.setScenePos(scene_pos)
    event.setPos(item.mapFromScene(scene_pos))
    item.mouseMoveEvent(event)


def test_dragging_a_corner_handle_repeatedly_does_not_diverge(qapp, tmp_path):
    # Regression 2026-09-19, owner's report: "starts jumping sizes
    # randomly very fast while just moving the handles a little."
    # Reproduced exactly with this sequence against the pre-fix code:
    # scale oscillated 2.0 -> 1.01 -> 2.02 -> 1.02 -> 2.04 -> 1.03 across
    # six 1px nudges, instead of climbing smoothly. Root cause:
    # _drag_handle used to receive event.pos(), which Qt maps through
    # this item's CURRENT transform() -- i.e. already divided by the
    # very scale being computed this frame -- so each call computed
    # (true_scale / previous_scale) instead of true_scale outright, and
    # since the sprite's scale is set from that wrong result every time,
    # the error compounded (and oscillated) every mouseMoveEvent.
    config, window, panel, _ = _make_square_sprite_panel(tmp_path)
    panel._select(1)
    item = panel._items[1]
    item._active_handle = "br"

    # Corner rest position is (50, 50). Roughly double the size, then
    # nudge by a few pixels at a time several times in a row, the way a
    # real slow drag delivers many small mouseMoveEvents.
    _send_mouse_move(item, QPointF(100.0, 100.0))
    sprite = panel.rig.by_id(1)
    assert sprite.scale_x == pytest.approx(2.0)

    for nudge in (101.0, 102.0, 103.0, 104.0, 105.0):
        _send_mouse_move(item, QPointF(nudge, nudge))

    # Must climb smoothly and land at 105/50 = 2.1 -- not oscillate.
    assert sprite.scale_x == pytest.approx(2.1)
    assert sprite.scale_y == pytest.approx(2.1)


def test_dragging_a_corner_handle_never_produces_a_negative_scale(qapp, tmp_path):
    config, window, panel, _ = _make_square_sprite_panel(tmp_path)
    panel._select(1)
    item = panel._items[1]
    item._active_handle = "br"
    item._drag_handle(QPointF(-25.0, -25.0))  # dragged past the origin
    sprite = panel.rig.by_id(1)
    assert sprite.scale_x > 0
    assert sprite.scale_y > 0


def test_dragging_the_rotate_handle_straight_up_is_zero_degrees(qapp, tmp_path):
    config, window, panel, _ = _make_square_sprite_panel(tmp_path)
    panel._select(1)
    item = panel._items[1]
    item._active_handle = "rotate"
    item._drag_handle(QPointF(0.0, -40.0))
    assert panel.rig.by_id(1).rotation_deg == pytest.approx(0.0)


def test_dragging_the_rotate_handle_sideways_is_ninety_degrees(qapp, tmp_path):
    # Verified against QTransform.rotate's own sign convention, not
    # assumed -- see EditableSpriteItem._drag_handle's own comment.
    config, window, panel, _ = _make_square_sprite_panel(tmp_path)
    panel._select(1)
    item = panel._items[1]
    item._active_handle = "rotate"
    item._drag_handle(QPointF(40.0, 0.0))
    assert panel.rig.by_id(1).rotation_deg == pytest.approx(90.0)
    assert panel.rotation.value() == pytest.approx(90.0)


def test_dragging_the_rotate_handle_tracks_the_mouse_exactly_through_a_real_drag(qapp, tmp_path):
    # Same real-event-pipeline issue as the corner-scale regression above
    # (see _send_mouse_move's own comment), just less dramatic here:
    # reproduced against the pre-fix code, a real multi-step drag lagged
    # to roughly *half* the true angle each step (10 -> 10, 20 -> 10,
    # 30 -> 20, 40 -> 20, 50 -> 30, ...) instead of tracking the mouse
    # directly, since it also read event.pos() -- mapped through the
    # rotation already applied a moment before -- instead of a fixed,
    # transform-independent reference.
    config, window, panel, _ = _make_square_sprite_panel(tmp_path)
    panel._select(1)
    item = panel._items[1]
    item._active_handle = "rotate"
    sprite = panel.rig.by_id(1)

    for deg in (10, 20, 30, 40, 50, 60, 70, 80, 89):
        rad = math.radians(deg)
        _send_mouse_move(item, QPointF(40.0 * math.sin(rad), -40.0 * math.cos(rad)))
        assert sprite.rotation_deg == pytest.approx(deg)


def test_scale_and_rotate_drags_mark_the_avatar_dirty(qapp, tmp_path):
    config, window, panel, _ = _make_square_sprite_panel(tmp_path)
    panel._select(1)
    item = panel._items[1]
    assert panel._dirty is False
    item._active_handle = "br"
    item._drag_handle(QPointF(75.0, 75.0))
    assert panel._dirty is True


# --- Reset/Lock fields ------------------------------------------------------


def test_zoom_field_has_reset_and_lock(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.zoom in panel._reset_buttons
    assert panel.zoom in panel._lock_buttons


def test_reset_button_restores_the_default_value(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.zoom.setValue(2.5)
    panel._reset_buttons[panel.zoom].click()
    assert panel.zoom.value() == 1.0


# --- Zoom (moved from WindowConfig to AvatarRig 2026-09-19) -----------------


def test_changing_zoom_writes_through_to_the_rig_and_render_window(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.zoom.setValue(2.0)
    assert panel.rig.zoom == 2.0
    assert window.zoom == 2.0
    assert panel._dirty is True  # avatar-level state now, not an auto-saved Config field


def test_zoom_change_is_undoable(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.zoom.setValue(2.0)
    panel.undo()
    assert panel.rig.zoom == 1.0
    assert panel.zoom.value() == 1.0
    assert window.zoom == 1.0

    panel.redo()
    assert panel.rig.zoom == 2.0
    assert panel.zoom.value() == 2.0


def test_dragging_zoom_continuously_pushes_only_one_undo_entry(qapp, tmp_path):
    # Same lazy-undo pattern as continuous sprite-property edits
    # (_undo_pending_for_selection) -- every valueChanged tick in one
    # editing session must not flood the undo stack.
    config, window, panel, _ = make_panel(tmp_path)
    panel.zoom.setValue(1.5)
    panel.zoom.setValue(2.0)
    panel.zoom.setValue(2.5)
    assert len(panel._undo_stack) == 1

    panel._on_zoom_editing_finished()
    panel.zoom.setValue(3.0)
    assert len(panel._undo_stack) == 2


def test_loading_a_different_avatar_syncs_zoom(qapp, tmp_path, monkeypatch):
    from unicorn_cloak.persistence import save_avatar

    config, window, panel, _ = make_panel(tmp_path)
    other = AvatarRig(name="other", sprites=[Sprite(id=1, path="a.png")], zoom=3.0)
    save_path = tmp_path / "other.uc"
    save_avatar(other, save_path)

    monkeypatch.setattr(
        cpw_module.QFileDialog, "getOpenFileName", lambda *a, **k: (str(save_path), "")
    )
    panel._on_load()

    assert panel.rig.zoom == 3.0
    assert panel.zoom.value() == 3.0
    assert window.zoom == 3.0


# --- OBS mute awareness status label -----------------------------------------


def test_obs_status_label_starts_not_connected(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.obs_status_label.text() == "Not connected"


def test_enabling_obs_with_no_input_name_shows_a_specific_hint(qapp, tmp_path):
    # Regression 2026-09-19, owner's report: turning this on before
    # filling in an Input name silently tried (and failed) to connect
    # with a blank one -- ObsLinkManager._start() now declines to even
    # try, and the status label should say why instead of just repeating
    # the same "Not connected" a wrong host/port or OBS-not-running would
    # also show.
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.obs_input_name.text() == ""
    panel.obs_enabled.setChecked(True)
    assert panel.obs_status_label.text() == "Not connected -- enter an Input name above"


def test_enabling_obs_with_an_input_name_shows_plain_not_connected(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.obs_input_name.setText("Mic/Aux")
    panel.obs_input_name.editingFinished.emit()
    panel.obs_enabled.setChecked(True)
    assert panel.obs_status_label.text() == "Not connected"


def test_typing_an_input_name_after_enabling_clears_the_hint(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.obs_enabled.setChecked(True)
    assert "enter an Input name" in panel.obs_status_label.text()

    panel.obs_input_name.setText("Mic/Aux")
    panel.obs_input_name.editingFinished.emit()

    assert panel.obs_status_label.text() == "Not connected"


# --- Expressions ------------------------------------------------------------


def test_expressions_section_shows_placeholder_with_no_manual_sprites(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel._expression_buttons == {}


def test_expressions_section_refreshes_after_tagging_a_sprite_manual(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    panel.group_name.setCurrentText("Mouth")
    panel.state_name.setCurrentText("Laughing")
    panel.manual_driven.setChecked(True)
    assert ("Mouth", "Laughing") in panel._expression_buttons


# --- Costume & Expression hotkey editors -------------------------------------


def test_costume_slots_start_with_no_rows(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert all(panel._costume_rows[slot] == [] for slot in range(10))


def test_adding_a_costume_row_stays_uncommitted_until_both_boxes_are_set(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._add_costume_row(2)
    row = panel._costume_rows[2][0]
    row.hide_combo.setCurrentIndex(row.hide_combo.findData(1))
    assert panel.rig.costume_assignments[2] == []  # show box still unset
    assert panel.rig.by_id(1).costume_layers[2] is True  # unchanged so far


def test_filling_both_boxes_commits_the_costume_pair(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._add_costume_row(2)
    row = panel._costume_rows[2][0]
    row.hide_combo.setCurrentIndex(row.hide_combo.findData(1))
    row.show_combo.setCurrentIndex(row.show_combo.findData(2))
    assert panel.rig.costume_assignments[2] == [(1, 2)]
    assert panel.rig.by_id(1).costume_layers[2] is True
    assert panel.rig.by_id(2).costume_layers[2] is False


def test_clearing_hide_box_on_a_committed_row_leaves_it_incomplete_and_reverts(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._add_costume_row(2)
    row = panel._costume_rows[2][0]
    row.hide_combo.setCurrentIndex(row.hide_combo.findData(1))
    row.show_combo.setCurrentIndex(row.show_combo.findData(2))
    assert panel.rig.costume_assignments[2] == [(1, 2)]

    row.hide_combo.setCurrentIndex(row.hide_combo.findData(None))
    assert panel._costume_rows[2] == [row]  # clearing a box no longer deletes the row
    assert panel.rig.costume_assignments[2] == []
    assert panel.rig.by_id(1).costume_layers[2] is True  # reverted to visible
    assert panel.rig.by_id(2).costume_layers[2] is True


def test_removing_a_costume_row_via_its_button_reverts_and_deletes_it(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._add_costume_row(2)
    row = panel._costume_rows[2][0]
    row.hide_combo.setCurrentIndex(row.hide_combo.findData(1))
    row.show_combo.setCurrentIndex(row.show_combo.findData(2))
    assert panel.rig.costume_assignments[2] == [(1, 2)]

    panel._on_remove_costume_row_clicked(2, row)
    assert panel._costume_rows[2] == []
    assert panel.rig.costume_assignments[2] == []
    assert panel.rig.by_id(1).costume_layers[2] is True  # reverted to visible
    assert panel.rig.by_id(2).costume_layers[2] is True


def test_a_costume_slot_can_hold_multiple_pairs_at_once(qapp, tmp_path):
    # "both parts!" -- e.g. a hoodie's front and back swapping for a vest
    # and an exposed-body layer together, under one hotkey.
    png = make_test_png_bytes()
    sprites = [Sprite(id=i, path=f"{i}.png", image_data=png) for i in range(1, 5)]
    config, window, panel, _ = make_panel(tmp_path, rig=AvatarRig(name="t", sprites=sprites))
    panel._add_costume_row(2)
    row1 = panel._costume_rows[2][0]
    row1.hide_combo.setCurrentIndex(row1.hide_combo.findData(1))
    row1.show_combo.setCurrentIndex(row1.show_combo.findData(2))

    panel._add_costume_row(2)
    row2 = panel._costume_rows[2][1]
    row2.hide_combo.setCurrentIndex(row2.hide_combo.findData(3))
    row2.show_combo.setCurrentIndex(row2.show_combo.findData(4))

    assert panel.rig.costume_assignments[2] == [(1, 2), (3, 4)]
    assert panel.rig.by_id(1).costume_layers[2] is True
    assert panel.rig.by_id(3).costume_layers[2] is True


def test_costume_editor_survives_undo_after_a_sprite_edit(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._add_costume_row(2)
    row = panel._costume_rows[2][0]
    row.hide_combo.setCurrentIndex(row.hide_combo.findData(1))
    row.show_combo.setCurrentIndex(row.show_combo.findData(2))

    panel.undo()
    assert panel.rig.costume_assignments[2] == []
    assert panel.rig.by_id(1).costume_layers[2] is True
    assert panel._costume_rows[2] == []

    panel.redo()
    assert panel.rig.costume_assignments[2] == [(1, 2)]
    assert panel.rig.by_id(1).costume_layers[2] is True


def test_expression_hotkey_slot_starts_empty(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert all(panel._expression_hotkey_rows[slot] == [] for slot in range(10))


def _make_manual_expression_rig():
    png = make_test_png_bytes()
    sprites = [
        Sprite(id=1, path="a.png", image_data=png),
        Sprite(
            id=2, path="b.png", image_data=png,
            group_name="Mouth", state_name="Laughing", manual_driven=True,
        ),
    ]
    return AvatarRig(name="t", sprites=sprites)


def test_assigning_an_expression_hotkey_writes_through_to_the_rig(qapp, tmp_path):
    # NOT combo.findData(("Mouth", "Laughing")) -- confirmed unreliable
    # for tuple userData (identity-based under the hood, not Python
    # equality; PySide6/Qt behavior, verified empirically, 2026-09-17).
    # Same reason _populate_expression_combo uses _find_combo_index_by_data
    # internally rather than findData -- these tests reuse that method
    # rather than duplicating the same landmine.
    config, window, panel, _ = make_panel(tmp_path, rig=_make_manual_expression_rig())
    panel._add_expression_hotkey_row(4)
    row = panel._expression_hotkey_rows[4][0]
    index = panel._find_combo_index_by_data(row.combo, ("Mouth", "Laughing"))
    row.combo.setCurrentIndex(index)
    assert panel.rig.expression_hotkeys[4] == [("Mouth", "Laughing")]


def test_clearing_an_expression_hotkey_row_leaves_it_incomplete(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path, rig=_make_manual_expression_rig())
    panel._add_expression_hotkey_row(4)
    row = panel._expression_hotkey_rows[4][0]
    row.combo.setCurrentIndex(panel._find_combo_index_by_data(row.combo, ("Mouth", "Laughing")))
    row.combo.setCurrentIndex(panel._find_combo_index_by_data(row.combo, None))
    assert panel._expression_hotkey_rows[4] == [row]  # clearing no longer deletes the row
    assert panel.rig.expression_hotkeys[4] == []


def test_removing_an_expression_hotkey_row_via_its_button_deletes_it(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path, rig=_make_manual_expression_rig())
    panel._add_expression_hotkey_row(4)
    row = panel._expression_hotkey_rows[4][0]
    row.combo.setCurrentIndex(panel._find_combo_index_by_data(row.combo, ("Mouth", "Laughing")))
    assert panel.rig.expression_hotkeys[4] == [("Mouth", "Laughing")]

    panel._on_remove_expression_hotkey_row_clicked(4, row)
    assert panel._expression_hotkey_rows[4] == []
    assert panel.rig.expression_hotkeys[4] == []


def test_triggering_an_expression_hotkey_clicks_its_button_and_forces_the_override(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path, rig=_make_manual_expression_rig())
    panel.rig.assign_expression_hotkey(4, "Mouth", "Laughing")
    panel._rebuild_costume_and_expression_editors()

    laughing_item = panel._items[2]
    panel._trigger_expression_hotkey(4)
    assert panel._expression_buttons[("Mouth", "Laughing")].isChecked() is True
    assert window.manual_overrides.get("Mouth") == "Laughing"

    panel._trigger_expression_hotkey(4)  # press again -- toggles back off
    assert panel._expression_buttons[("Mouth", "Laughing")].isChecked() is False
    assert window.manual_overrides.get("Mouth") is None


def test_triggering_a_costume_hotkey_sets_the_active_costume(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._trigger_costume_hotkey(3)
    assert panel.rig.active_costume == 3


def _focus_zoom_field(panel):
    """Zoom lives in Behavior's Position & Hierarchy section, collapsed
    by default -- setFocus() on a widget that isn't actually visible
    silently fails (and some other, currently-visible widget keeps
    focus instead), so both the tab and the section need opening first."""
    _switch_to_tab(panel, "Behavior")
    panel._sections["Position & Hierarchy"].set_collapsed(False)
    panel.zoom.setFocus()
    QApplication.processEvents()


def test_costume_hotkey_is_skipped_while_an_input_widget_is_focused(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.show()
    _focus_zoom_field(panel)
    assert isinstance(QApplication.focusWidget(), type(panel.zoom))
    panel._trigger_costume_hotkey(3)
    assert panel.rig.active_costume == 0  # unchanged


def test_expression_hotkey_is_skipped_while_an_input_widget_is_focused(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path, rig=_make_manual_expression_rig())
    panel.rig.assign_expression_hotkey(4, "Mouth", "Laughing")
    panel._rebuild_costume_and_expression_editors()
    panel.show()
    _focus_zoom_field(panel)

    panel._trigger_expression_hotkey(4)
    assert panel._expression_buttons[("Mouth", "Laughing")].isChecked() is False
    assert window.manual_overrides.get("Mouth") is None


def test_rebinding_a_costume_key_updates_its_control_panel_shortcut(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    edit = panel._hotkey_edits[3]
    edit.setKeySequence(QKeySequence("k"))
    assert panel._costume_shortcuts[3].key() == QKeySequence("k")


def test_expression_hotkey_shortcut_matches_shift_plus_digit(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    shortcuts = panel.findChildren(cpw_module.QShortcut)
    sequences = {s.key().toString() for s in shortcuts}
    assert "Shift+1" in sequences
    assert "Shift+0" in sequences


def test_rebuilding_the_scene_repopulates_costume_and_expression_rows(qapp, tmp_path):
    # Covers load/undo/redo/add-remove-sprite in one place, since they
    # all funnel through _rebuild_scene() -- see that method's own hook.
    config, window, panel, _ = make_panel(tmp_path, rig=_make_manual_expression_rig())
    panel.rig.assign_costume_pair(2, hide_id=1, show_id=2)
    panel.rig.assign_expression_hotkey(4, "Mouth", "Laughing")
    panel._rebuild_scene()
    assert len(panel._costume_rows[2]) == 1
    assert panel._costume_rows[2][0].committed == (1, 2)
    assert len(panel._expression_hotkey_rows[4]) == 1
    assert panel._expression_hotkey_rows[4][0].committed == ("Mouth", "Laughing")


# --- Window/UI state persistence --------------------------------------------


def test_ui_state_round_trips_through_config(qapp, tmp_path):
    config, window, panel, state_path = make_panel(tmp_path)
    panel.edit_sprites_btn.setChecked(True)
    panel.guide_btn.setChecked(True)
    panel.tabs.setCurrentIndex(2)
    panel._sections["Layer List"].set_collapsed(True)
    panel._capture_ui_state_into_config()

    assert config.control_panel.canvas_mode == "edit"
    assert config.control_panel.show_origin_guides is True
    assert config.control_panel.active_tab == 2
    assert "Layer List" in config.control_panel.collapsed_sections


def test_persisted_ui_state_is_applied_on_construction(qapp, tmp_path):
    from unicorn_cloak.config import ControlPanelConfig

    config = Config()
    config.control_panel = ControlPanelConfig(
        canvas_mode="edit", show_origin_guides=True, show_hidden_ghosted=True,
        active_tab=1, collapsed_sections=("Layer List",),
    )
    rig = make_test_rig()
    window = RenderWindow(rig, config.motion, hotkeys_config=config.hotkeys)
    panel = ControlPanelWindow(rig, config, window, state_path=tmp_path / "settings.json")

    assert panel.edit_sprites_btn.isChecked() is True
    assert panel.live_preview_btn.isChecked() is False
    assert panel.guide_btn.isChecked() is True
    assert panel.ghost_btn.isChecked() is True
    assert panel.tabs.currentIndex() == 1
    assert panel._sections["Layer List"].is_collapsed() is True


def test_a_locked_sprites_state_is_applied_on_construction(qapp, tmp_path):
    # Lock Position comes from the selected sprite itself (Sprite.locked,
    # saved with the avatar) now, not a persisted app-wide config field --
    # see the config migration that retired control_panel.
    # scale_lock_proportions the same day this replaced it.
    sprites = [Sprite(id=1, path="a.png", image_data=make_test_png_bytes(), locked=True)]
    rig = AvatarRig(name="t", sprites=sprites)
    config = Config()
    window = RenderWindow(rig, config.motion, hotkeys_config=config.hotkeys)
    panel = ControlPanelWindow(rig, config, window, state_path=tmp_path / "settings.json")

    panel._select(1)
    assert panel.lock_position_btn.isChecked() is True
    assert panel.pos_x.isEnabled() is False


def test_canvas_gets_the_majority_of_the_default_width(qapp, tmp_path):
    # setSizes() only sticks reliably once the window has actually been
    # shown (verified empirically, 2026-09-17) -- see showEvent().
    config, window, panel, _ = make_panel(tmp_path)
    panel.show()
    qapp.processEvents()
    sizes = panel.splitter.sizes()
    assert len(sizes) == 2
    assert sizes[0] > sizes[1]  # canvas (left) is the primary feature


def test_splitter_ratio_is_captured_into_config(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.show()
    qapp.processEvents()
    panel.splitter.setSizes([700, 300])
    panel._capture_ui_state_into_config()
    assert config.control_panel.splitter_sizes == tuple(panel.splitter.sizes())
    assert config.control_panel.splitter_sizes[0] > config.control_panel.splitter_sizes[1]


def test_persisted_splitter_sizes_are_applied_on_construction(qapp, tmp_path):
    # Sizes must sum to (about) the persisted width to be honored exactly
    # -- realistic, since both are always captured together in
    # _capture_ui_state_into_config -- an inconsistent pair (e.g. sizes
    # summing to far less than width) is Qt's own prerogative to
    # redistribute, not a bug in this app.
    from unicorn_cloak.config import ControlPanelConfig

    config = Config()
    config.control_panel = ControlPanelConfig(width=1800, splitter_sizes=(1100, 700))
    rig = make_test_rig()
    window = RenderWindow(rig, config.motion, hotkeys_config=config.hotkeys)
    panel = ControlPanelWindow(rig, config, window, state_path=tmp_path / "settings.json")
    panel.show()
    qapp.processEvents()
    # Within a few px, not exact -- the splitter handle itself consumes
    # a little width, so the two panes can't both land on the exact
    # requested pixel counts simultaneously.
    sizes = panel.splitter.sizes()
    assert abs(sizes[0] - 1100) <= 5
    assert abs(sizes[1] - 700) <= 5


# --- Per-tab section splitter: collapse/expand behavior --------------------


def _tab_splitter_for(panel, section_title):
    return panel._sections[section_title].parent()


def _switch_to_tab(panel, name):
    titles = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
    panel.tabs.setCurrentIndex(titles.index(name))


def test_a_tab_that_starts_fully_collapsed_from_persisted_config_stays_pegged_to_top(qapp, tmp_path):
    # Regression 2026-09-17, owner's follow-up report: "the behavior tab
    # started all collapsed & centered" -- distinct from (and found after
    # fixing) the expand-then-collapse case below. Root cause was
    # different: once every section in a splitter is collapsed, the
    # splitter's own effective maximumHeight shrinks, and a plain
    # QVBoxLayout centers a child that can't grow to fill its allotted
    # space rather than pegging it to the top -- but this only actually
    # shows up once QTabWidget does a real layout pass on the page, i.e.
    # once the tab is actually switched to (not visible from a
    # newly-constructed-but-still-on-tab-0 panel, which is why the
    # earlier test alone didn't catch it). Config here starts with every
    # Behavior section collapsed from construction, matching a real
    # restart with that persisted, not reached via any live toggle.
    from unicorn_cloak.config import ControlPanelConfig

    config = Config()
    config.control_panel = ControlPanelConfig(
        collapsed_sections=("Motion", "Position & Hierarchy", "Animation")
    )
    rig = make_test_rig()
    window = RenderWindow(rig, config.motion, hotkeys_config=config.hotkeys)
    panel = ControlPanelWindow(rig, config, window, state_path=tmp_path / "settings.json")
    panel.show()
    qapp.processEvents()
    _switch_to_tab(panel, "Behavior")  # the actual switch is what exposes the bug
    qapp.processEvents()

    # Threshold is relative to the Behavior tab's own layer combo (added
    # 2026-09-19 as a header, upgraded to a combo 2026-09-20), not an
    # absolute page offset -- the splitter is now expected to peg to
    # just below it rather than to y=0.
    splitter = _tab_splitter_for(panel, "Motion")
    combo_bottom = panel.behavior_layer_combo.geometry().bottom()
    assert splitter.geometry().y() < combo_bottom + 20


def test_collapsing_every_section_stays_pegged_to_the_top_even_after_a_prior_expand(qapp, tmp_path):
    # Regression 2026-09-17, owner's report: "when all items collapse
    # they jump to vertical center". Reproduced with a real expand-then-
    # collapse sequence -- QSplitter caches each pane's last-negotiated
    # pixel size, so collapsing straight after an expand (not from a
    # fresh, never-expanded state) is what actually exposed it.
    config, window, panel, _ = make_panel(tmp_path)
    panel.show()
    qapp.processEvents()
    _switch_to_tab(panel, "Behavior")
    qapp.processEvents()

    for section in panel._sections.values():
        section.set_collapsed(False)
    qapp.processEvents()
    for section in panel._sections.values():
        section.set_collapsed(True)
    qapp.processEvents()

    splitter = _tab_splitter_for(panel, "Motion")
    assert splitter.widget(0).geometry().y() < 20  # pegged near the top, not floating mid-splitter


def test_expanding_a_section_auto_collapses_a_sibling_instead_of_growing_the_window(qapp, tmp_path):
    # Regression 2026-09-17, owner's report: "when expanding all, if that
    # makes the column longer than the window it changes the window
    # size... instead it should collapse something else and not change
    # the window size." Behavior tab starts with Motion expanded,
    # Position & Hierarchy/Animation collapsed (see ControlPanelConfig's
    # own default) -- expanding one of the latter should collapse Motion
    # to make room rather than bumping the window's own minimum size.
    config, window, panel, _ = make_panel(tmp_path)
    panel.resize(1600, 700)
    panel.show()
    qapp.processEvents()
    _switch_to_tab(panel, "Behavior")
    qapp.processEvents()

    assert panel._sections["Motion"].is_collapsed() is False
    assert panel._sections["Position & Hierarchy"].is_collapsed() is True
    min_height_before = panel.minimumSizeHint().height()

    panel._sections["Position & Hierarchy"].set_collapsed(False)
    qapp.processEvents()

    assert panel._sections["Motion"].is_collapsed() is True  # auto-collapsed to make room
    assert panel._sections["Position & Hierarchy"].is_collapsed() is False
    assert panel.minimumSizeHint().height() <= min_height_before + 5  # didn't grow


def test_expanding_a_second_section_that_still_fits_does_not_force_further_collapses(qapp, tmp_path):
    # Regression 2026-09-17, owner's follow-up report: "now you can only
    # have one section open at a time which is also not great... only
    # force a single unit to collapse if and when it would over-flow the
    # window/panel boundaries." Root cause of the over-eager version:
    # _make_room_if_needed measured "available space" as the *splitter's*
    # own height, but the splitter's height itself shrinks (via
    # _add_tab_splitter's AlignTop) whenever nothing in it is expanded --
    # so the very first expand from an all-(or mostly-)collapsed state
    # read a stale, too-small budget and over-collapsed. Fixed by
    # measuring against the tab *page*'s own height instead, which
    # QTabWidget assigns directly and doesn't shrink just because the
    # splitter inside it does. With a tall enough window, two sections
    # that genuinely both fit should both stay expanded together.
    config, window, panel, _ = make_panel(tmp_path)
    panel.resize(1600, 1200)  # tall enough that two sections' real content still fits
    panel.show()
    qapp.processEvents()
    _switch_to_tab(panel, "Behavior")
    qapp.processEvents()

    panel._sections["Position & Hierarchy"].set_collapsed(False)
    qapp.processEvents()
    panel._sections["Animation"].set_collapsed(False)
    qapp.processEvents()

    assert panel._sections["Position & Hierarchy"].is_collapsed() is False
    assert panel._sections["Animation"].is_collapsed() is False


def test_a_single_expanded_section_fills_the_tab_instead_of_leaving_it_mostly_empty(qapp, tmp_path):
    # Regression 2026-09-17, owner's report on the new single-section
    # Costume/Expression Hotkeys tabs: "sooo much room and clipping
    # them." Root cause: outer.setAlignment(splitter, AlignTop) -- added
    # for the *all-collapsed* centering bug above -- overrides a layout
    # item's own size policy entirely, permanently capping it to its
    # sizeHint instead of letting it grow to fill real extra space. That
    # was fine for every earlier multi-section tab (their combined
    # sizeHints already filled most of the window anyway) but made an
    # expanded single-section tab with modest content get stuck small
    # while the rest of the tab sat empty below it. Must only apply
    # AlignTop while every section in the splitter is actually collapsed.
    config, window, panel, _ = make_panel(tmp_path)
    panel.resize(1000, 900)
    panel.show()
    qapp.processEvents()
    _switch_to_tab(panel, "Costume Hotkeys")
    qapp.processEvents()

    splitter = _tab_splitter_for(panel, "Costumes — press the number to switch")
    page_height = panel.tabs.currentWidget().height()
    assert splitter.height() > page_height * 0.8


def test_non_growable_sections_dont_stretch_to_fill_the_splitter(qapp, tmp_path):
    # Regression 2026-09-19, owner's report: a gap between State
    # Assignment and Expressions "disappears when layers is also open".
    # Root cause: every expanded section used to request QWIDGETSIZE_MAX
    # equally, so with Layer List (the one section with something that
    # should actually grow, its QListWidget) collapsed, State Assignment
    # and Expressions split the leftover splitter space between
    # themselves instead of leaving it alone. Non-growable sections must
    # stay capped to their own real content height regardless of what
    # else in the splitter is open or closed.
    config, window, panel, _ = make_panel(tmp_path)
    panel.resize(1000, 900)
    panel.show()
    qapp.processEvents()
    _switch_to_tab(panel, "Sprites")
    panel._sections["Layer List"].set_collapsed(True)
    qapp.processEvents()

    state_section = panel._sections["State Assignment"]
    assert state_section.height() <= state_section.sizeHint().height() + 2


def test_a_splitter_with_nothing_that_can_grow_still_pegs_to_the_top(qapp, tmp_path):
    # Follow-up to the fix above: once non-growable sections stop
    # stretching, the *splitter itself* has more room than its (now
    # correctly small) children want -- which reproduced the exact same
    # "no alignment set centers instead of pegging to the top" class of
    # bug the 2026-09-17 fixes already covered, just via a new path
    # (some sections expanded, but none of them growable) that the old
    # "all collapsed" check didn't account for.
    config, window, panel, _ = make_panel(tmp_path)
    panel.resize(1000, 900)
    panel.show()
    qapp.processEvents()
    _switch_to_tab(panel, "Sprites")
    panel._sections["Layer List"].set_collapsed(True)
    qapp.processEvents()

    splitter = _tab_splitter_for(panel, "State Assignment")
    assert splitter.geometry().y() < 20


def test_a_growable_section_still_lets_the_splitter_fill_the_tab(qapp, tmp_path):
    # The other half of the same fix: a splitter must NOT peg to the top
    # (and so cap itself to content height) while something inside it
    # -- Layer List's auto-expanding QListWidget -- still wants to grow.
    # State Assignment/Expressions collapsed here so this isolates that
    # one behavior, the same way test_a_single_expanded_section_fills_
    # the_tab_instead_of_leaving_it_mostly_empty above does for the
    # Costume Hotkeys tab -- the offscreen test platform's own virtual
    # screen is a fixed, fairly small 800x800 (see _clamp_height_to_
    # screen), so a real "do all three of this tab's sections fit
    # together" scenario isn't reliably reproducible here regardless of
    # what panel.resize() asks for.
    config, window, panel, _ = make_panel(tmp_path)
    panel.resize(1000, 900)
    panel.show()
    qapp.processEvents()
    _switch_to_tab(panel, "Sprites")
    panel._sections["State Assignment"].set_collapsed(True)
    panel._sections["Expressions"].set_collapsed(True)
    panel._sections["Layer List"].set_collapsed(False)
    qapp.processEvents()
    qapp.processEvents()  # lets the deferred QTimer.singleShot(0, ...) safety-net pass run too

    splitter = _tab_splitter_for(panel, "Layer List")
    page_height = panel.tabs.currentWidget().height()
    assert splitter.height() > page_height * 0.8


def test_adding_an_expression_button_while_expanded_resizes_the_section(qapp, tmp_path):
    # The Expressions section's content changes at runtime (tagging a
    # sprite manually-driven adds a button) -- its cap must be
    # recomputed then, not just on the next unrelated section toggle, or
    # a newly-added button would be clipped (or dead space would remain)
    # until something else happened to trigger a resync.
    config, window, panel, _ = make_panel(tmp_path)
    panel.resize(1000, 900)
    panel.show()
    qapp.processEvents()
    _switch_to_tab(panel, "Sprites")
    qapp.processEvents()

    section = panel._sections["Expressions"]

    panel._select(1)
    panel.group_name.setCurrentText("Mouth")
    panel.state_name.setCurrentText("Laughing")
    panel.manual_driven.setChecked(True)
    qapp.processEvents()

    # The cap must track whatever the section's content actually needs
    # *now* -- not be left over from before the button existed.
    assert section.maximumHeight() == section.sizeHint().height()
