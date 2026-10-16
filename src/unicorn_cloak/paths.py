"""Where things live, for a dev checkout, a PyInstaller bundle (AppImage /
Windows exe) and any other installed layout -- see
docs/planning/installation-plan.md. Qt-free, so config.py and audio.py can
use it. Nothing here touches the disk except find_tool/exists checks.

"Installed" means a frozen bundle, or UNICORN_CLOAK_APP_ROOT set (the
installers' wrappers export it). An installed copy keeps user data (settings,
avatars) under the user's own config/data directories, never in the
read-only/replaceable app root; a dev checkout keeps today's behavior
(settings.json in the repo root, which is gitignored).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "unicorn-cloak"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_installed() -> bool:
    return is_frozen() or bool(os.environ.get("UNICORN_CLOAK_APP_ROOT"))


def app_root() -> Path:
    """Directory containing `assets/` (the demo avatar) and `bin/` (bundled
    ffmpeg/ffprobe)."""
    override = os.environ.get("UNICORN_CLOAK_APP_ROOT")
    if override:
        return Path(override)
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def user_config_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "UnicornCloak"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP_NAME


def user_data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "UnicornCloak"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / f"{APP_NAME}-data"


def user_avatars_dir() -> Path:
    return user_data_dir() / "avatars"


def default_state_path() -> Path:
    override = os.environ.get("UNICORN_CLOAK_CONFIG")
    if override:
        return Path(override)
    if is_installed():
        return user_config_dir() / "settings.json"
    return Path(__file__).resolve().parents[2] / "settings.json"


def find_tool(name: str) -> str | None:
    """Path to ffmpeg/ffprobe: the copy bundled under <app root>/bin first,
    then whatever is on PATH. None if neither exists."""
    exe = f"{name}.exe" if sys.platform == "win32" else name
    bundled = app_root() / "bin" / exe
    if bundled.is_file():
        return str(bundled)
    return shutil.which(name)
