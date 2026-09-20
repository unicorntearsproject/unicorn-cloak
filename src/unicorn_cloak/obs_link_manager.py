"""
Owns the `ObsMuteWatcher` (see obs_link.py) that `RenderWindow.set_muted()`
needs -- starts/stops it based on `config.obs.enabled`, restarts it
whenever the connection settings change while enabled, and marshals its
callbacks onto the Qt thread through signals. Mirrors
`audio_manager.AudioManager`'s own shape and the same threading
discipline: `ObsMuteWatcher.on_mute_changed`/`on_connection_changed`/
`on_error` all fire from its own background thread (see obs_link.py's
docstring), so an explicit `Qt.ConnectionType.QueuedConnection` is
required wherever this class's signals are connected (see __main__.py) --
`Signal.emit()` itself is safe from any thread, but nothing here ever
mutates plain Python state from inside a callback the way an earlier
draft of `AudioManager._handle_file_finished` did before that was caught
in review; every method that touches `self._watcher` is only ever called
from the Qt thread (Settings' UI callbacks, `__main__.py`'s setup).
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .config import Config
from .obs_link import ObsMuteWatcher


class ObsLinkManager(QObject):
    mute_changed = Signal(bool)
    connection_changed = Signal(bool)
    error_occurred = Signal(str)

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self._watcher: ObsMuteWatcher | None = None

    @property
    def is_running(self) -> bool:
        return self._watcher is not None and self._watcher.is_running

    def start_if_enabled(self) -> None:
        """Called once at app startup."""
        if self.config.obs.enabled:
            self._start()

    def set_enabled(self, enabled: bool) -> None:
        self.config.obs.enabled = enabled
        if enabled:
            self._start()
        else:
            self._stop()

    def restart(self) -> None:
        """Call after changing host/port/password/input_name while
        enabled, so the new settings actually take effect -- a running
        ObsMuteWatcher doesn't pick up config changes on its own."""
        if not self.config.obs.enabled:
            return
        self._stop()
        self._start()

    def shutdown(self) -> None:
        self._stop()

    def _start(self) -> None:
        if self._watcher is not None:
            return
        obs = self.config.obs
        if not obs.input_name.strip():
            # Checkbox on, but the owner hasn't (yet) filled in an Input
            # name -- the checkbox's own tooltip already warns "otherwise
            # this would just retry a connection with nothing configured
            # yet," but nothing previously enforced that (owner's report,
            # 2026-09-19: exactly this -- obsws-python's GetInputMute
            # rejected an empty input name with a confusing raw SDK
            # error). Silently doesn't start rather than attempting (and
            # failing) a connection with an input name that was never
            # going to be valid.
            return
        self._watcher = ObsMuteWatcher(
            host=obs.host,
            port=obs.port,
            password=obs.password,
            input_name=obs.input_name,
            on_mute_changed=self.mute_changed.emit,
            on_connection_changed=self.connection_changed.emit,
            on_error=self.error_occurred.emit,
        )
        self._watcher.start()

    def _stop(self) -> None:
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None
            self.connection_changed.emit(False)
