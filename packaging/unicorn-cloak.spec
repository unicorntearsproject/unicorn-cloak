# PyInstaller spec for Linux (AppImage payload) and Windows (.exe).
# Run from the repo root:  pyinstaller packaging/unicorn-cloak.spec
#   UC_ONEFILE=1  -> single self-extracting executable (Windows release)
#   default       -> one-folder build (what the AppImage wraps)
# ffmpeg/ffprobe are bundled from packaging/vendor/ if present (the build
# scripts download them there; it is gitignored).
import os
import sys
from pathlib import Path

root = Path(SPECPATH).parent
onefile = os.environ.get("UC_ONEFILE") == "1"
exe_name = "unicorn-cloak"

datas = [
    (str(root / "src/unicorn_cloak/assets/fonts"), "unicorn_cloak/assets/fonts"),
    (str(root / "src/unicorn_cloak/assets/icons"), "unicorn_cloak/assets/icons"),
]
# The demo avatar, minus backups and the large reference sheet.
for f in (root / "assets/unicorn-demo").iterdir():
    if f.suffix in (".png", ".uc", ".txt") and f.name != "master_reference.png":
        datas.append((str(f), "assets/unicorn-demo"))

binaries = []
vendor = root / "packaging/vendor"
for tool in ("ffmpeg", "ffprobe"):
    exe = vendor / (tool + (".exe" if sys.platform == "win32" else ""))
    if exe.is_file():
        binaries.append((str(exe), "bin"))

a = Analysis(
    [str(root / "packaging/launcher.py")],
    pathex=[str(root / "src")],
    datas=datas,
    binaries=binaries,
    hiddenimports=["unicorn_cloak", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets"],
    excludes=["tkinter", "pytest"],
)

# Don't bundle GTK/GLib/GIO (pulled in only by Qt's GTK platform-theme
# plugin): a bundled GLib reading the *system's* GSettings schemas/modules
# aborts at startup on a mismatch (seen live: "Settings schema
# 'org.gnome.settings-daemon.plugins.xsettings' does not contain a key
# named 'antialiasing'"). Without the plugin Qt uses its built-in/portal
# theme instead.
_skip = ("libgtk-3", "libgdk-3", "libgdk_pixbuf", "libgio-2", "libglib-2",
         "libgobject-2", "libgmodule-2", "libqgtk3", "libatk", "libatspi")
a.binaries = [b for b in a.binaries if not os.path.basename(b[0]).startswith(_skip)]
pyz = PYZ(a.pure)
icon = str(root / "packaging/icon/unicorn-cloak.ico") if sys.platform == "win32" else None

if onefile:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=exe_name,
              console=False, icon=icon, upx=False)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=exe_name,
              console=True, icon=icon, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name=exe_name, upx=False)
