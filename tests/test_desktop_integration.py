import sys

import pytest

from unicorn_cloak import desktop_integration as di


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(di.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.setattr(di, "_refresh_caches", lambda: None)
    return tmp_path


def test_desktop_entry_quotes_a_path_with_spaces_and_keeps_the_wm_class():
    text = di.desktop_entry("/home/a b/Apps/UnicornCloak.AppImage")
    assert 'Exec="/home/a b/Apps/UnicornCloak.AppImage" %U' in text
    assert "StartupWMClass=unicorn-cloak" in text and "Icon=unicorn-cloak" in text


def test_install_copies_the_appimage_and_writes_entry_and_icon(home, monkeypatch):
    src = home / "Downloads" / "UnicornCloak-0.9.0-x86_64.AppImage"
    src.parent.mkdir()
    src.write_bytes(b"appimage")
    monkeypatch.setenv("APPIMAGE", str(src))

    message = di.install()

    target = home / "home" / "Applications" / "UnicornCloak.AppImage"
    assert target.read_bytes() == b"appimage"
    assert target.stat().st_mode & 0o111  # executable
    entry = (home / "data" / "applications" / "unicorn-cloak.desktop").read_text()
    assert str(target) in entry
    assert (home / "data" / "icons" / "hicolor" / "512x512" / "apps" / "unicorn-cloak.png").exists()
    assert "Installed" in message


def test_install_needs_an_appimage_or_bundle(home, monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    with pytest.raises(RuntimeError):
        di.install()


def test_install_refuses_on_other_platforms(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(RuntimeError):
        di.install()


def test_uninstall_removes_everything_it_installed(home, monkeypatch):
    src = home / "x.AppImage"
    src.write_bytes(b"a")
    monkeypatch.setenv("APPIMAGE", str(src))
    di.install()

    message = di.uninstall()

    assert not (home / "data" / "applications" / "unicorn-cloak.desktop").exists()
    assert not (home / "home" / "Applications" / "UnicornCloak.AppImage").exists()
    assert "Removed" in message
    assert "nothing" in di.uninstall()
