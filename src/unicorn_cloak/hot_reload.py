"""
Watches the avatar's save file and every sprite's own source PNG for
changes, so art iteration never needs an app restart (owner's request,
2026-09-16). Built on QFileSystemWatcher -- this is inherently
Qt-facing (the watcher itself is a QObject and its signals already fire
on the Qt thread), unlike audio.py's/obs_link.py's background-thread
callbacks, so there is no cross-thread marshaling needed here at all.

Known QFileSystemWatcher quirk this works around: many editors and
export tools replace a file via write-to-temp-then-rename rather than
writing to it in place. That changes the file's inode, which silently
drops it from the watch -- re-adding the path after every change (see
_emit_for_path) is what keeps watching working across more than the
first save, not just the first one.

Debounced: a single logical save can still produce more than one
low-level write event in quick succession (e.g. a temp-file-then-rename
sequence touches the directory too) -- a short timer coalesces a burst
of fileChanged signals for the same path into one reload instead of
several redundant ones.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

_DEBOUNCE_MS = 200


class AssetWatcher(QObject):
    avatar_file_changed = Signal()
    sprite_file_changed = Signal(str)  # the changed sprite's path

    def __init__(self) -> None:
        super().__init__()
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._avatar_path: str | None = None
        self._sprite_paths: set[str] = set()
        self._debounce_timers: dict[str, QTimer] = {}

    def watch_avatar_file(self, path: str | None) -> None:
        if self._avatar_path and self._avatar_path in self._watcher.files():
            self._watcher.removePath(self._avatar_path)
        self._avatar_path = path or None
        if self._avatar_path and os.path.exists(self._avatar_path):
            self._watcher.addPath(self._avatar_path)

    def watch_sprite_files(self, paths: list[str]) -> None:
        """Replaces the whole watched-sprite set -- call this again after
        every reload, since sprites can be added/removed/renamed and a
        stale watch on a path nothing references any more is just noise."""
        existing = [p for p in self._sprite_paths if p in self._watcher.files()]
        if existing:
            self._watcher.removePaths(existing)
        self._sprite_paths = {p for p in paths if p}
        real_paths = [p for p in self._sprite_paths if os.path.exists(p)]
        if real_paths:
            self._watcher.addPaths(real_paths)

    def stop(self) -> None:
        files = self._watcher.files()
        if files:
            self._watcher.removePaths(files)
        self._avatar_path = None
        self._sprite_paths.clear()
        for timer in self._debounce_timers.values():
            timer.stop()
        self._debounce_timers.clear()

    def _on_file_changed(self, path: str) -> None:
        timer = self._debounce_timers.get(path)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda p=path: self._emit_for_path(p))
            self._debounce_timers[path] = timer
        timer.start(_DEBOUNCE_MS)

    def _emit_for_path(self, path: str) -> None:
        # Re-add defensively: many editors/exporters replace a file via
        # write-to-temp + rename, which changes its inode and silently
        # drops it from QFileSystemWatcher -- without this, only the
        # first save after startup would ever be noticed.
        if os.path.exists(path) and path not in self._watcher.files():
            self._watcher.addPath(path)
        if path == self._avatar_path:
            self.avatar_file_changed.emit()
        elif path in self._sprite_paths:
            self.sprite_file_changed.emit(path)
