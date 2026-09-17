import pytest
from PySide6.QtCore import QPointF, Qt

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
    config, window, panel, _ = make_panel(tmp_path)
    titles = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
    assert titles == ["Sprites", "Costume Hotkeys", "Expression Hotkeys", "Behavior", "Audio", "Application"]


def test_no_tab_has_more_than_three_collapsible_sections(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    for i in range(panel.tabs.count()):
        splitter = panel.tabs.widget(i).layout().itemAt(0).widget()
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
    assert panel.canvas_mode_btn.isChecked() is False
    assert panel.canvas_stack.currentWidget() is panel.live_view
    assert panel.preview_controls.isVisible() is False


def test_toggling_canvas_mode_switches_to_edit_view(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.show()
    panel.canvas_mode_btn.setChecked(True)
    assert panel.canvas_stack.currentWidget() is panel.edit_view
    assert panel.canvas_mode_btn.text() == "Edit Sprites"
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
    panel._sections["Display"].set_collapsed(False)


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


def test_scale_lock_is_checked_by_default(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    assert panel.scale_lock.isChecked() is True


def test_scale_lock_links_x_and_y_when_checked(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    panel.scale_lock.setChecked(True)
    panel.scale_x.setValue(2.0)
    assert panel.scale_y.value() == 2.0
    assert panel.rig.by_id(1).scale_x == 2.0
    assert panel.rig.by_id(1).scale_y == 2.0


def test_scale_unlocked_allows_independent_x_and_y(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._select(1)
    panel.scale_lock.setChecked(False)
    panel.scale_x.setValue(2.0)
    assert panel.scale_y.value() != 2.0
    assert panel.rig.by_id(1).scale_x == 2.0


def test_scale_lock_proportions_round_trips_through_config(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel.scale_lock.setChecked(False)
    panel._capture_ui_state_into_config()
    assert config.control_panel.scale_lock_proportions is False


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


def test_dragging_a_corner_handle_scales_independently_when_unlocked(qapp, tmp_path):
    config, window, panel, _ = _make_square_sprite_panel(tmp_path)
    panel._select(1)
    panel.scale_lock.setChecked(False)
    item = panel._items[1]
    item._active_handle = "br"  # corner rest position (50, 50)
    item._drag_handle(QPointF(75.0, 150.0))
    sprite = panel.rig.by_id(1)
    assert sprite.scale_x == pytest.approx(1.5)  # 75 / 50
    assert sprite.scale_y == pytest.approx(3.0)  # 150 / 50
    assert panel.scale_x.value() == pytest.approx(1.5)
    assert panel.scale_y.value() == pytest.approx(3.0)


def test_dragging_a_corner_handle_keeps_proportions_when_locked(qapp, tmp_path):
    config, window, panel, _ = _make_square_sprite_panel(tmp_path)
    panel._select(1)
    panel.scale_lock.setChecked(True)
    item = panel._items[1]
    item._active_handle = "br"
    item._drag_handle(QPointF(75.0, 150.0))
    sprite = panel.rig.by_id(1)
    assert sprite.scale_x == pytest.approx(sprite.scale_y)


def test_dragging_a_corner_handle_never_produces_a_negative_scale(qapp, tmp_path):
    config, window, panel, _ = _make_square_sprite_panel(tmp_path)
    panel._select(1)
    panel.scale_lock.setChecked(False)
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


def test_clearing_hide_box_on_a_committed_row_removes_it_and_reverts(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path)
    panel._add_costume_row(2)
    row = panel._costume_rows[2][0]
    row.hide_combo.setCurrentIndex(row.hide_combo.findData(1))
    row.show_combo.setCurrentIndex(row.show_combo.findData(2))
    assert panel.rig.costume_assignments[2] == [(1, 2)]

    row.hide_combo.setCurrentIndex(row.hide_combo.findData(None))
    assert panel._costume_rows[2] == []  # the row widget itself is gone
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


def test_clearing_an_expression_hotkey_row_removes_it(qapp, tmp_path):
    config, window, panel, _ = make_panel(tmp_path, rig=_make_manual_expression_rig())
    panel._add_expression_hotkey_row(4)
    row = panel._expression_hotkey_rows[4][0]
    row.combo.setCurrentIndex(panel._find_combo_index_by_data(row.combo, ("Mouth", "Laughing")))
    row.combo.setCurrentIndex(panel._find_combo_index_by_data(row.combo, None))
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
    panel.canvas_mode_btn.setChecked(True)
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

    assert panel.canvas_mode_btn.isChecked() is True
    assert panel.guide_btn.isChecked() is True
    assert panel.ghost_btn.isChecked() is True
    assert panel.tabs.currentIndex() == 1
    assert panel._sections["Layer List"].is_collapsed() is True


def test_persisted_scale_lock_proportions_is_applied_on_construction(qapp, tmp_path):
    from unicorn_cloak.config import ControlPanelConfig

    config = Config()
    config.control_panel = ControlPanelConfig(scale_lock_proportions=False)
    rig = make_test_rig()
    window = RenderWindow(rig, config.motion, hotkeys_config=config.hotkeys)
    panel = ControlPanelWindow(rig, config, window, state_path=tmp_path / "settings.json")

    assert panel.scale_lock.isChecked() is False


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

    splitter = _tab_splitter_for(panel, "Motion")
    assert splitter.geometry().y() < 20


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
