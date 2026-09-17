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


def test_set_enabled_true_starts_and_false_stops(qapp, monkeypatch):
    started, stopped = _patch_watcher(monkeypatch)
    manager = ObsLinkManager(Config())

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
    manager = ObsLinkManager(Config())
    manager.set_enabled(True)
    assert len(started) == 1

    manager.restart()
    assert len(stopped) == 1
    assert len(started) == 2


def test_shutdown_stops_a_running_watcher(qapp, monkeypatch):
    started, stopped = _patch_watcher(monkeypatch)
    manager = ObsLinkManager(Config())
    manager.set_enabled(True)
    manager.shutdown()
    assert len(stopped) == 1
    assert manager.is_running is False


def test_connection_changed_emits_false_on_stop(qapp, monkeypatch):
    _patch_watcher(monkeypatch)
    manager = ObsLinkManager(Config())
    received = []
    manager.connection_changed.connect(received.append)
    manager.set_enabled(True)
    manager.set_enabled(False)
    assert received == [False]
