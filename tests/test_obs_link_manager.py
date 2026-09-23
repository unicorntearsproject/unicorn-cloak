from unicorn_cloak.config import Config
from unicorn_cloak.obs_link_manager import ObsLinkManager


def _patch_watcher(monkeypatch, started=None, stopped=None):
    started = started if started is not None else []
    stopped = stopped if stopped is not None else []

    class _FakeWatcher:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            started.append(self.kwargs)

        def stop(self):
            stopped.append(True)

        @property
        def is_running(self):
            return len(started) > len(stopped)

    monkeypatch.setattr(
        "unicorn_cloak.obs_link_manager.ObsMuteWatcher", lambda **kw: _FakeWatcher(**kw)
    )
    return started, stopped


def test_start_if_enabled_does_nothing_when_disabled(qapp, monkeypatch):
    started, stopped = _patch_watcher(monkeypatch)
    config = Config()
    assert config.obs.enabled is False
    manager = ObsLinkManager(config)
    manager.start_if_enabled()
    assert started == []
    assert manager.is_running is False


def test_start_if_enabled_starts_a_watcher_when_enabled(qapp, monkeypatch):
    started, stopped = _patch_watcher(monkeypatch)
    config = Config()
    config.obs.enabled = True
    config.obs.host = "localhost"
    config.obs.port = 4455
    config.obs.input_name = "Mic/Aux"
    manager = ObsLinkManager(config)
    manager.start_if_enabled()
    assert len(started) == 1
    assert started[0]["input_name"] == "Mic/Aux"
    assert manager.is_running is True


def _config_with_input_name() -> Config:
    config = Config()
    config.obs.input_name = "Mic/Aux"  # _start() no-ops with a blank one (see its own comment)
    return config


def test_set_enabled_true_starts_and_false_stops(qapp, monkeypatch):
    started, stopped = _patch_watcher(monkeypatch)
    manager = ObsLinkManager(_config_with_input_name())

    manager.set_enabled(True)
    assert len(started) == 1
    assert manager.config.obs.enabled is True

    manager.set_enabled(False)
    assert len(stopped) == 1
    assert manager.config.obs.enabled is False


def test_restart_does_nothing_when_disabled(qapp, monkeypatch):
    started, stopped = _patch_watcher(monkeypatch)
    manager = ObsLinkManager(Config())
    manager.restart()
    assert started == []
    assert stopped == []


def test_restart_stops_and_starts_a_fresh_watcher_when_enabled(qapp, monkeypatch):
    started, stopped = _patch_watcher(monkeypatch)
    manager = ObsLinkManager(_config_with_input_name())
    manager.set_enabled(True)
    assert len(started) == 1

    manager.restart()
    assert len(stopped) == 1
    assert len(started) == 2


def test_shutdown_stops_a_running_watcher(qapp, monkeypatch):
    started, stopped = _patch_watcher(monkeypatch)
    manager = ObsLinkManager(_config_with_input_name())
    manager.set_enabled(True)
    manager.shutdown()
    assert len(stopped) == 1
    assert manager.is_running is False


def test_connection_changed_emits_false_on_stop(qapp, monkeypatch):
    _patch_watcher(monkeypatch)
    manager = ObsLinkManager(_config_with_input_name())
    received = []
    manager.connection_changed.connect(received.append)
    manager.set_enabled(True)
    manager.set_enabled(False)
    assert received == [False]


def test_mute_changed_emits_false_on_stop(qapp, monkeypatch):
    # Regression, bug audit 2026-09-23 (#8): _stop() used to emit
    # connection_changed(False) but never mute_changed(False) --
    # RenderWindow.set_muted only ever hears about mute state through
    # mute_changed, so stopping while muted (OBS closing, the checkbox
    # unticked, an Input name change while restart()ing) left the avatar's
    # mouth force-closed forever, with no way back short of OBS
    # reconnecting and reporting that input unmuted again, or an app
    # restart.
    _patch_watcher(monkeypatch)
    manager = ObsLinkManager(_config_with_input_name())
    manager.set_enabled(True)
    manager.mute_changed.emit(True)  # simulate OBS reporting muted

    mute_events = []
    manager.mute_changed.connect(mute_events.append)
    manager.set_enabled(False)

    assert mute_events == [False]


def test_enabling_with_a_blank_input_name_does_not_start_a_watcher(qapp, monkeypatch):
    # Regression 2026-09-19, owner's report: turning the checkbox on
    # before filling in an Input name produced a raw obs-websocket error
    # ("OBS input '' not found ...") instead of the routine, silent
    # not-configured-yet state this is everywhere else in the app.
    started, stopped = _patch_watcher(monkeypatch)
    config = Config()
    assert config.obs.input_name == ""
    manager = ObsLinkManager(config)

    manager.set_enabled(True)

    assert started == []
    assert manager.is_running is False


def test_enabling_with_a_whitespace_only_input_name_does_not_start_a_watcher(qapp, monkeypatch):
    started, stopped = _patch_watcher(monkeypatch)
    config = Config()
    config.obs.input_name = "   "
    manager = ObsLinkManager(config)

    manager.set_enabled(True)

    assert started == []


def test_restart_after_filling_in_a_blank_input_name_starts_the_watcher(qapp, monkeypatch):
    # The natural real-world order: check the box first, notice nothing
    # happens, then fill in the Input name -- control_panel_window.py's
    # _on_obs_connection_field_changed calls restart() on every field
    # edit, which must actually start the watcher once there's finally a
    # real name to connect with.
    started, stopped = _patch_watcher(monkeypatch)
    config = Config()
    manager = ObsLinkManager(config)
    manager.set_enabled(True)
    assert started == []  # nothing yet -- still blank

    config.obs.input_name = "Mic/Aux"
    manager.restart()

    assert len(started) == 1
    assert started[0]["input_name"] == "Mic/Aux"
