import sys
from pathlib import Path

from unicorn_cloak import paths


def _clean(monkeypatch):
    for var in ("UNICORN_CLOAK_APP_ROOT", "UNICORN_CLOAK_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)


def test_dev_checkout_uses_repo_root_settings_and_is_not_installed(monkeypatch):
    _clean(monkeypatch)
    assert paths.is_installed() is False
    assert paths.default_state_path() == paths.app_root() / "settings.json"
    assert (paths.app_root() / "assets" / "unicorn-demo").is_dir()


def test_app_root_env_marks_it_installed_and_moves_settings_to_the_user_dir(monkeypatch, tmp_path):
    _clean(monkeypatch)
    monkeypatch.setenv("UNICORN_CLOAK_APP_ROOT", str(tmp_path / "root"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert paths.is_installed() is True
    assert paths.app_root() == tmp_path / "root"
    assert paths.default_state_path() == tmp_path / "cfg" / "unicorn-cloak" / "settings.json"


def test_frozen_bundle_uses_meipass_and_counts_as_installed(monkeypatch, tmp_path):
    _clean(monkeypatch)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert paths.app_root() == tmp_path
    assert paths.is_installed() is True


def test_config_env_override_wins_everywhere(monkeypatch, tmp_path):
    _clean(monkeypatch)
    monkeypatch.setenv("UNICORN_CLOAK_CONFIG", str(tmp_path / "my.json"))
    assert paths.default_state_path() == tmp_path / "my.json"
    monkeypatch.setenv("UNICORN_CLOAK_APP_ROOT", str(tmp_path))
    assert paths.default_state_path() == tmp_path / "my.json"


def test_user_data_dirs_follow_xdg(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.user_avatars_dir() == tmp_path / "unicorn-cloak-data" / "avatars"


def test_windows_dirs_use_appdata(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roam"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert paths.user_config_dir() == tmp_path / "roam" / "UnicornCloak"
    assert paths.user_avatars_dir() == tmp_path / "local" / "UnicornCloak" / "avatars"


def test_find_tool_prefers_the_bundled_copy_then_path(monkeypatch, tmp_path):
    _clean(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("UNICORN_CLOAK_APP_ROOT", str(tmp_path))
    monkeypatch.setattr(paths.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert paths.find_tool("ffmpeg") == "/usr/bin/ffmpeg"

    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "ffmpeg").write_text("")
    assert paths.find_tool("ffmpeg") == str(tmp_path / "bin" / "ffmpeg")


def test_find_tool_is_none_when_missing_everywhere(monkeypatch, tmp_path):
    _clean(monkeypatch)
    monkeypatch.setenv("UNICORN_CLOAK_APP_ROOT", str(tmp_path))
    monkeypatch.setattr(paths.shutil, "which", lambda name: None)
    assert paths.find_tool("ffprobe") is None
