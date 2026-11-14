"""Linux desktop integration for the AppImage (`--install-desktop` /
`--uninstall-desktop`). Double-clicking an AppImage on Fedora/GNOME opens
the disk-image writer, because application/vnd.appimage has no "run it"
handler there (owner's report, 2026-11-14), so the reliable route is a
launcher entry: copy the AppImage somewhere stable, write
~/.local/share/applications/unicorn-cloak.desktop (the basename must stay
exactly that -- it is the Wayland app_id, see render.APP_ID) and install
the icon.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import paths

DESKTOP_NAME = "unicorn-cloak.desktop"
APPIMAGE_NAME = "UnicornCloak.AppImage"


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def applications_dir() -> Path:
    return _data_home() / "applications"


def icon_path() -> Path:
    return _data_home() / "icons" / "hicolor" / "512x512" / "apps" / "unicorn-cloak.png"


def installed_appimage_path() -> Path:
    return Path.home() / "Applications" / APPIMAGE_NAME


def desktop_entry(exec_path: str) -> str:
    # Exec paths with spaces must be quoted per the Desktop Entry spec.
    quoted = '"' + exec_path.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return (
        "[Desktop Entry]\nVersion=1.0\nType=Application\nName=Unicorn Cloak\n"
        "GenericName=Avatar Overlay\nComment=Mic-reactive layered-sprite avatar for OBS\n"
        f"Exec={quoted} %U\nIcon=unicorn-cloak\nTerminal=false\n"
        "Categories=AudioVideo;Video;\nKeywords=pngtuber;vtuber;avatar;obs;stream;overlay;\n"
        "StartupNotify=true\nStartupWMClass=unicorn-cloak\n"
    )


def _refresh_caches() -> None:
    for cmd in (
        ["update-desktop-database", str(applications_dir())],
        ["gtk-update-icon-cache", "-q", "-t", str(_data_home() / "icons" / "hicolor")],
    ):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, capture_output=True, timeout=20, check=False)


def install() -> str:
    """Returns a human-readable result; raises RuntimeError with a reason
    when it can't be done."""
    if not sys.platform.startswith("linux"):
        raise RuntimeError("desktop integration is only for Linux")
    source = os.environ.get("APPIMAGE")
    if source:
        target = installed_appimage_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        if Path(source).resolve() != target.resolve():
            shutil.copy2(source, target)
        target.chmod(0o755)
        exec_path = str(target)
    elif paths.is_frozen():
        exec_path = sys.executable  # an unpacked bundle: point at it where it is
    else:
        raise RuntimeError("run this from the AppImage (or an unpacked bundle)")

    icon_source = Path(__file__).resolve().parent / "assets" / "icons" / "unicorn-cloak.png"
    if icon_source.exists():
        icon_path().parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(icon_source, icon_path())
    applications_dir().mkdir(parents=True, exist_ok=True)
    (applications_dir() / DESKTOP_NAME).write_text(desktop_entry(exec_path))
    _refresh_caches()
    return f"Installed. Launch Unicorn Cloak from your applications menu. ({exec_path})"


def uninstall() -> str:
    removed = []
    for path in (applications_dir() / DESKTOP_NAME, icon_path(), installed_appimage_path()):
        if path.exists():
            path.unlink()
            removed.append(str(path))
    _refresh_caches()
    return "Removed: " + (", ".join(removed) if removed else "nothing was installed")
