import json

import pytest

from unicorn_cloak import config as config_module
from unicorn_cloak.config import Config, load_state, save_state


def test_missing_file_returns_defaults(tmp_path):
    config = load_state(tmp_path / "does-not-exist.json")
    assert config == Config()


def test_save_state_stamps_the_current_config_version(tmp_path):
    path = tmp_path / "settings.json"
    save_state(Config(), path)
    raw = json.loads(path.read_text())
    assert raw["__config_version__"] == config_module.CURRENT_CONFIG_VERSION


def test_load_state_treats_a_missing_version_stamp_as_version_zero(tmp_path):
    # Every settings.json written before this feature existed has no
    # stamp at all -- must still load cleanly, not raise or reset.
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"avatar_path": "/tmp/some-avatar.uc"}))
    config = load_state(path)
    assert config.avatar_path == "/tmp/some-avatar.uc"


def test_load_state_applies_a_registered_migration(tmp_path, monkeypatch):
    # Proves the migration chain itself actually runs end-to-end, not
    # just that the stamp gets written -- a fake "version 0 -> 1"
    # migration that renames a key, applied before _merge ever sees the
    # dict, matching how a real future structural change would work.
    def rename_old_gain_key(raw: dict) -> dict:
        raw = dict(raw)
        audio = dict(raw.get("audio", {}))
        if "mic_gain" in audio:
            audio["gain"] = audio.pop("mic_gain")
        raw["audio"] = audio
        return raw

    monkeypatch.setitem(config_module._CONFIG_MIGRATIONS, 0, rename_old_gain_key)

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"audio": {"mic_gain": 2.5}}))  # no version stamp -> version 0
    config = load_state(path)
    assert config.audio.gain == 2.5


def test_load_state_stops_migrating_when_no_migration_is_registered_for_a_step(tmp_path):
    # A version behind current with nothing registered for *that*
    # particular step (true for step 0 -> 1, even though step 1 -> 2 now
    # has a real migration -- see _migrate_window_zoom_to_avatar) must
    # still load via _merge's own per-field defaults, not raise.
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"__config_version__": 0, "avatar_path": "/tmp/x.uc"}))
    config = load_state(path)
    assert config.avatar_path == "/tmp/x.uc"


def test_load_state_strips_old_window_zoom(tmp_path):
    # zoom moved from WindowConfig to AvatarRig 2026-09-19 -- a settings
    # .json written before that (version 1, no migration yet applied) had
    # a real "window": {"zoom": ...} key that _merge would otherwise
    # reject as unknown now that WindowConfig no longer has that field.
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"__config_version__": 1, "window": {"zoom": 2.5, "width": 1920}}))
    config = load_state(path)  # must not raise
    assert config.window.width == 1920
    assert not hasattr(config.window, "zoom")


def test_load_state_reads_a_settings_json_from_the_brief_v3_window(tmp_path):
    # control_panel.scale_lock_proportions was briefly retired (version
    # 3, stripped from raw config) and brought back the same day as its
    # own separate control alongside the new per-sprite Lock Position --
    # a settings.json written during that brief window (version 3, key
    # already stripped) must still load fine, just with the field back
    # at its dataclass default rather than whatever it used to be.
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "__config_version__": 3,
        "control_panel": {"active_tab": 2},
    }))
    config = load_state(path)  # must not raise
    assert config.control_panel.active_tab == 2
    assert config.control_panel.scale_lock_proportions is True


def test_load_state_reads_scale_lock_proportions_when_present(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "__config_version__": 1,
        "control_panel": {"scale_lock_proportions": False},
    }))
    config = load_state(path)
    assert config.control_panel.scale_lock_proportions is False


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "settings.json"
    original = Config()
    original.audio.mild_open = 0.05
    original.audio.attack_ms = 25.0
    original.motion.bounce_strength = 300.0

    save_state(original, path)
    reloaded = load_state(path)

    assert reloaded == original


def test_save_is_atomic_no_leftover_tmp_file(tmp_path):
    path = tmp_path / "settings.json"
    save_state(Config(), path)
    leftovers = [p for p in tmp_path.iterdir() if p.name != "settings.json"]
    assert leftovers == []


def test_unknown_key_raises(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"audio": {"typo_field": 1.0}}')
    with pytest.raises(ValueError, match="typo_field"):
        load_state(path)


def test_avatar_path_override(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"avatar_path": "/tmp/some-other-avatar.save"}')
    config = load_state(path)
    assert config.avatar_path == "/tmp/some-other-avatar.save"


def test_window_background_image_and_video_paths_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    original = Config()
    original.window.background = "video"
    original.window.background_image_path = "/tmp/bg.png"
    original.window.background_video_path = "/tmp/bg.mp4"

    save_state(original, path)
    reloaded = load_state(path)

    assert reloaded.window.background == "video"
    assert reloaded.window.background_image_path == "/tmp/bg.png"
    assert reloaded.window.background_video_path == "/tmp/bg.mp4"


def test_hotkeys_costume_keys_override(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"hotkeys": {"costume_keys": ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10"]}}')
    config = load_state(path)
    assert config.hotkeys.costume_keys == ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10")


def test_hotkeys_costume_keys_stay_a_tuple_after_loading_from_json(tmp_path):
    # JSON has no tuple type -- _merge would otherwise hand back a plain
    # list, silently changing this field's type depending on whether it
    # came from a default or a loaded file.
    path = tmp_path / "settings.json"
    save_state(Config(), path)
    config = load_state(path)
    assert isinstance(config.hotkeys.costume_keys, tuple)


def test_control_panel_state_round_trips_through_save_and_load(tmp_path):
    # Regression 2026-09-17, found by the owner: control_panel was added
    # to Config but save_state()/load_state() never actually wired it
    # into the JSON payload -- every field silently came back at its
    # class default after a real restart, even though the in-memory
    # capture into config.control_panel worked fine (nothing exercised
    # the save-then-load round trip specifically, only the in-memory
    # capture, so this went unnoticed).
    path = tmp_path / "settings.json"
    config = Config()
    config.control_panel.x = 123
    config.control_panel.y = 45
    config.control_panel.width = 1500
    config.control_panel.height = 900
    config.control_panel.active_tab = 2
    config.control_panel.canvas_mode = "edit"
    config.control_panel.show_origin_guides = True
    config.control_panel.show_hidden_ghosted = True
    config.control_panel.grid_spacing_px = 42
    config.control_panel.collapsed_sections = ("Layer List", "Motion")
    save_state(config, path)

    raw = json.loads(path.read_text())
    assert "control_panel" in raw

    loaded = load_state(path)
    assert loaded.control_panel.x == 123
    assert loaded.control_panel.y == 45
    assert loaded.control_panel.width == 1500
    assert loaded.control_panel.height == 900
    assert loaded.control_panel.active_tab == 2
    assert loaded.control_panel.canvas_mode == "edit"
    assert loaded.control_panel.show_origin_guides is True
    assert loaded.control_panel.show_hidden_ghosted is True
    assert loaded.control_panel.grid_spacing_px == 42
    assert loaded.control_panel.collapsed_sections == ("Layer List", "Motion")


def test_control_panel_collapsed_sections_stay_a_tuple_after_loading_from_json(tmp_path):
    path = tmp_path / "settings.json"
    save_state(Config(), path)
    config = load_state(path)
    assert isinstance(config.control_panel.collapsed_sections, tuple)


def test_save_keeps_one_backup_of_the_previous_version(tmp_path):
    # Added 2026-09-16 after this exact file got deleted with no way to
    # recover it -- the atomic write alone doesn't help against that,
    # only a backup does.
    path = tmp_path / "settings.json"
    config_v1 = Config()
    config_v1.audio.mild_open = 0.111
    save_state(config_v1, path)

    config_v2 = Config()
    config_v2.audio.mild_open = 0.222
    save_state(config_v2, path)

    backup_path = path.with_suffix(path.suffix + ".bak")
    assert backup_path.exists()
    backup_config = load_state(backup_path)
    assert backup_config.audio.mild_open == 0.111  # the version *before* the last save

    current_config = load_state(path)
    assert current_config.audio.mild_open == 0.222


def test_save_does_not_create_backup_on_first_write(tmp_path):
    path = tmp_path / "settings.json"
    save_state(Config(), path)
    assert not path.with_suffix(path.suffix + ".bak").exists()
