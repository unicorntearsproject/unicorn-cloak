#!/usr/bin/env bash
# Downloads static ffmpeg + ffprobe into packaging/vendor/ (gitignored) for
# bundling. Usage: packaging/fetch_ffmpeg.sh [linux|windows]   (default: linux)
set -euo pipefail
cd "$(dirname "$0")"
target="${1:-linux}"
mkdir -p vendor && cd vendor
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
if [[ "$target" == "linux" ]]; then
  # Static GPL build (johnvansickle.com). We only decode, never encode.
  curl -fsSL -o "$tmp/ff.tar.xz" https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
  tar -xJf "$tmp/ff.tar.xz" -C "$tmp"
  cp "$tmp"/ffmpeg-*-static/ffmpeg "$tmp"/ffmpeg-*-static/ffprobe .
else
  # LGPL build (BtbN) -- decode-only use needs nothing more.
  curl -fsSL -o "$tmp/ff.zip" https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-lgpl.zip
  unzip -q -o "$tmp/ff.zip" -d "$tmp"
  cp "$tmp"/ffmpeg-*/bin/ffmpeg.exe "$tmp"/ffmpeg-*/bin/ffprobe.exe .
fi
ls -la .
