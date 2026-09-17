import time
import types

import pytest

from unicorn_cloak import obs_link
from unicorn_cloak.obs_link import ObsMuteWatcher
from obsws_python.error import OBSSDKRequestError


def _wait_until(predicate, timeout=2.0, interval=0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class _FakeReqClient:
    """Stands in for obsws_python.ReqClient -- returns a fixed initial
    mute state, or raises OBSSDKRequestError for an unknown input name,
    exactly like a real GetInputMute request would for a typo'd name."""

    def __init__(self, initial_muted: bool, known_input: str, **kwargs):
        self._initial_muted = initial_muted
        self._known_input = known_input
        self.kwargs = kwargs
        self.disconnected = False

    def get_input_mute(self, name):
        if name != self._known_input:
            raise OBSSDKRequestError("GetInputMute", 600, "No source was found by that name.")
        return types.SimpleNamespace(input_muted=self._initial_muted)

    def disconnect(self):
        self.disconnected = True


class _FakeCallback:
    def __init__(self):
        self._fns = []

    def register(self, fn):
        self._fns.append(fn)

    def fire(self, **data):
        event = types.SimpleNamespace(**data)
        for fn in self._fns:
            fn(event)


class _FakeEventClient:
    """Stands in for obsws_python.EventClient. `instances` lets a test
    reach the most recently constructed one to simulate an incoming
    InputMuteStateChanged event or a server-side disconnect."""

    instances: list["_FakeEventClient"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.callback = _FakeCallback()
        self.base_client = types.SimpleNamespace(ws=types.SimpleNamespace(connected=True))
        self.disconnected = False
        _FakeEventClient.instances.append(self)

    def disconnect(self):
        self.disconnected = True
        self.base_client.ws.connected = False


@pytest.fixture(autouse=True)
def _clear_fake_event_clients():
    _FakeEventClient.instances.clear()
    yield
    _FakeEventClient.instances.clear()


def _patch_obs(monkeypatch, initial_muted=False, known_input="Mic/Aux"):
    monkeypatch.setattr(
        obs_link.obs, "ReqClient",
        lambda **kw: _FakeReqClient(initial_muted, known_input, **kw),
    )
    monkeypatch.setattr(obs_link.obs, "EventClient", _FakeEventClient)


def _make_watcher(**overrides):
    kwargs = dict(
        host="localhost", port=4455, password="", input_name="Mic/Aux",
        on_mute_changed=lambda m: None, reconnect_delay_s=0.05,
    )
    kwargs.update(overrides)
    return ObsMuteWatcher(**kwargs)


def test_reports_initial_mute_state_on_connect(monkeypatch):
    _patch_obs(monkeypatch, initial_muted=True)
    changes = []
    watcher = _make_watcher(on_mute_changed=changes.append)
    watcher.start()
    try:
        assert _wait_until(lambda: changes == [True])
    finally:
        watcher.stop()


def test_reports_mute_state_changes_from_the_event_stream(monkeypatch):
    _patch_obs(monkeypatch, initial_muted=False)
    changes = []
    watcher = _make_watcher(on_mute_changed=changes.append)
    watcher.start()
    try:
        assert _wait_until(lambda: changes == [False])
        assert _wait_until(lambda: len(_FakeEventClient.instances) == 1)
        _FakeEventClient.instances[0].callback.fire(input_name="Mic/Aux", input_muted=True)
        assert _wait_until(lambda: changes == [False, True])
    finally:
        watcher.stop()


def test_ignores_mute_changes_for_a_different_input(monkeypatch):
    _patch_obs(monkeypatch, initial_muted=False)
    changes = []
    watcher = _make_watcher(on_mute_changed=changes.append)
    watcher.start()
    try:
        assert _wait_until(lambda: len(_FakeEventClient.instances) == 1)
        _FakeEventClient.instances[0].callback.fire(input_name="Some Other Input", input_muted=True)
        time.sleep(0.1)
        assert changes == [False]  # unchanged -- not our configured input
    finally:
        watcher.stop()


def test_reports_connected_then_disconnected_on_stop(monkeypatch):
    _patch_obs(monkeypatch)
    connection_states = []
    watcher = _make_watcher(on_connection_changed=connection_states.append)
    watcher.start()
    try:
        assert _wait_until(lambda: True in connection_states)
    finally:
        watcher.stop()
    assert connection_states[-1] is False


def test_unknown_input_name_reports_an_error_not_silently_retried_the_same_way(monkeypatch):
    _patch_obs(monkeypatch, known_input="Mic/Aux")
    errors = []
    watcher = _make_watcher(input_name="Typo'd Input Name", on_error=errors.append)
    watcher.start()
    try:
        assert _wait_until(lambda: len(errors) > 0)
        assert "Typo'd Input Name" in errors[0]
    finally:
        watcher.stop()


def test_connection_refused_is_silent_and_keeps_retrying(monkeypatch):
    # OBS not running is routine here, not an error -- must not spam
    # on_error, and must keep trying (a later start of OBS should still
    # be picked up).
    attempts = []

    def flaky_req_client(**kw):
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionRefusedError()
        return _FakeReqClient(False, "Mic/Aux", **kw)

    monkeypatch.setattr(obs_link.obs, "ReqClient", flaky_req_client)
    monkeypatch.setattr(obs_link.obs, "EventClient", _FakeEventClient)

    changes = []
    errors = []
    watcher = _make_watcher(on_mute_changed=changes.append, on_error=errors.append)
    watcher.start()
    try:
        assert _wait_until(lambda: changes == [False], timeout=5.0)
    finally:
        watcher.stop()
    assert errors == []
    assert len(attempts) >= 3


def test_is_running_reflects_thread_lifecycle(monkeypatch):
    _patch_obs(monkeypatch)
    watcher = _make_watcher()
    assert watcher.is_running is False
    watcher.start()
    assert watcher.is_running is True
    watcher.stop()
    assert watcher.is_running is False


def test_stop_before_start_does_not_raise():
    watcher = _make_watcher()
    watcher.stop()  # never started
