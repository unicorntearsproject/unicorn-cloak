"""
Watches one OBS input's mute state over obs-websocket -- the same
protocol/server the parent `obs` management repo already drives (see
`~/Repos/obs/CLAUDE.md`'s "Live control" row) -- and reports it through
the same kind of background-thread callback contract as audio.py's
`Microphone`/`FilePlayback`.

Built for a real, reported problem, 2026-09-16 (owner's words): "the
avatar talks while the stream hears silence." `audio.py` only ever sees
whatever's actually arriving at the mic hardware -- it has no way to
know the owner muted their mic *in OBS*, downstream of that. This module
closes that gap by asking OBS directly which input is muted, live, and
`render.py`'s `RenderWindow.set_muted()` forces the mouth closed
whenever it is, regardless of what the mic itself is picking up.

Uses `obsws-python` (added as a real dependency, not a diagnostic tool
like the `perf`/`py-spy` from the earlier profiling work) rather than
hand-rolling the v5 protocol's SHA256 challenge/response auth handshake.

Threading contract: identical in spirit to Microphone's -- on_mute_changed
and on_connection_changed both fire from this class's own background
thread, never touch Qt directly. The caller must marshal onto the Qt
thread first (see __main__.py's ObsLinkBridge, mirroring _AudioBridge's
established pattern).

Reconnect is automatic and indefinite, unlike Microphone's error
handling: OBS not running, or its websocket server not being enabled
yet, are both completely routine states here (the owner may not even
have OBS open while just testing the avatar), not failures to give up
after. A wrong input name is different -- that is a real configuration
mistake worth surfacing distinctly, not something more retries will fix,
so it's reported once per connection attempt rather than silently
retried into an identical failure forever.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import obsws_python as obs
from obsws_python.error import OBSSDKError, OBSSDKRequestError
from obsws_python.subs import Subs

# obsws-python logs a full traceback on every connection failure and
# every request error via its own logger -- both are completely routine
# here (OBS not running, a wrong input name) and already reported
# cleanly through on_error/on_connection_changed; verified directly
# (2026-09-16, against this app's own real, live OBS instance) that this
# is what actually silences that noise rather than leaving an alarming-
# looking traceback dump for an error this module already handles.
logging.getLogger("obsws_python").setLevel(logging.CRITICAL)

_DEFAULT_RECONNECT_DELAY_S = 3.0
_POLL_INTERVAL_S = 0.5  # how often the connection-watchdog loop wakes to check stop()


class ObsMuteWatcher:
    def __init__(
        self,
        host: str,
        port: int,
        password: str,
        input_name: str,
        on_mute_changed: Callable[[bool], None],
        on_connection_changed: Callable[[bool], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        reconnect_delay_s: float = _DEFAULT_RECONNECT_DELAY_S,
    ) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.input_name = input_name
        self._on_mute_changed = on_mute_changed
        self._on_connection_changed = on_connection_changed
        self._on_error = on_error
        self._reconnect_delay_s = reconnect_delay_s
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker_loop, name="unicorn-cloak-obs-link", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._report_connection(False)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._run_one_connection()
            except OBSSDKRequestError as exc:
                # A real config mistake (e.g. the input name doesn't
                # exist in OBS) -- worth its own message, not just
                # silently retrying into the same failure forever.
                self._report_error(
                    f'OBS input {self.input_name!r} not found ({exc}) -- '
                    f"check the name matches exactly (case-sensitive)."
                )
            except (OBSSDKError, OSError, TimeoutError):
                # OBS not running / websocket server disabled / wrong
                # host-port -- all routine here, not errors to surface
                # loudly on every retry.
                pass
            self._report_connection(False)
            if self._stop_event.is_set():
                break
            self._stop_event.wait(self._reconnect_delay_s)

    def _run_one_connection(self) -> None:
        req = obs.ReqClient(host=self.host, port=self.port, password=self.password, timeout=3)
        try:
            initial = req.get_input_mute(self.input_name)
        finally:
            req.disconnect()
        self._on_mute_changed(bool(initial.input_muted))

        event_client = obs.EventClient(
            host=self.host, port=self.port, password=self.password, subs=Subs.INPUTS
        )

        def on_input_mute_state_changed(data) -> None:
            if data.input_name == self.input_name:
                self._on_mute_changed(bool(data.input_muted))

        event_client.callback.register(on_input_mute_state_changed)
        self._report_connection(True)
        try:
            while not self._stop_event.is_set():
                # EventClient runs its own recv() loop on its own worker
                # thread (see obsws_python.EventClient.subscribe) -- this
                # loop just watches the socket's own connected state and
                # the stop flag, polling lightly rather than blocking on
                # the worker thread directly so stop() stays responsive.
                if not event_client.base_client.ws.connected:
                    break
                self._stop_event.wait(_POLL_INTERVAL_S)
        finally:
            try:
                event_client.disconnect()
            except Exception:
                pass

    def _report_connection(self, connected: bool) -> None:
        if self._on_connection_changed is not None:
            self._on_connection_changed(connected)

    def _report_error(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)
