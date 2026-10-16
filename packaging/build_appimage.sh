#!/usr/bin/env bash
# Builds dist/UnicornCloak-<version>-x86_64.AppImage.
# Needs: python3 (>=3.11) with venv, curl, tar, and appimagetool on PATH.
# Usage: packaging/build_appimage.sh
set -euo pipefail
cd "$(dirname "$0")/.."
version="$(python3 -c "import re;print(re.search(r'__version__ = \"(.+?)\"', open('src/unicorn_cloak/__init__.py').read()).group(1))")"

[[ -x packaging/vendor/ffmpeg ]] || packaging/fetch_ffmpeg.sh linux

python3 -m venv build/venv
build/venv/bin/pip install -q --upgrade pip
build/venv/bin/pip install -q ".[build]"
build/venv/bin/pyinstaller --noconfirm --clean --distpath build/dist --workpath build/work packaging/unicorn-cloak.spec

appdir=build/AppDir
rm -rf "$appdir"; mkdir -p "$appdir/usr/lib" "$appdir/usr/bin"
cp -r build/dist/unicorn-cloak "$appdir/usr/lib/unicorn-cloak"
ln -s ../lib/unicorn-cloak/unicorn-cloak "$appdir/usr/bin/unicorn-cloak"
cp packaging/unicorn-cloak.desktop "$appdir/unicorn-cloak.desktop"
cp packaging/icon/unicorn-cloak-256.png "$appdir/unicorn-cloak.png"
cp packaging/icon/unicorn-cloak-256.png "$appdir/.DirIcon"
cat > "$appdir/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/unicorn-cloak/unicorn-cloak" "$@"
RUN
chmod +x "$appdir/AppRun"

mkdir -p dist
ARCH=x86_64 appimagetool --no-appstream "$appdir" "dist/UnicornCloak-${version}-x86_64.AppImage"
echo "built dist/UnicornCloak-${version}-x86_64.AppImage"
