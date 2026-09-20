"""
Microphone-driven talk-level detection: an RMS envelope follower with
attack/hold/release timing (in milliseconds), a noise gate, and
independent open/close thresholds per band (mild, wide) for hysteresis --
so the mouth doesn't flicker right at a boundary and doesn't snap shut
between syllables during continuous speech.

`talk_level` is 0 (quiet), 1 (mild), or 2 (wide/loud), driving
motion.axis_visible for any sprite whose talk_state is nonzero (see
motion.py and render.py). All the numbers below are starting points --
the real tuning surface is the Settings window (settings_window.py),
which writes into config.AudioConfig live.

Device handling and the capture thread are ported from unicorn-viz's
`unicornviz/audio/capture.py` (same owner, same machine, already
debugged in production there), not just inspired by it -- see
`resolve_input_device`/`usable_input_devices` and `Microphone` below for
what's carried over and why.

`FilePlayback` (added 2026-09-16) is the other supported volume source:
decodes a local audio/video file with ffmpeg instead of reading a live
mic, for re-recording a video where the avatar needs to be driven by a
participant's isolated (but not itself the audio that gets recorded)
track -- see its own docstring for the full real-world scenario this was
built for. It feeds the exact same `on_volume`/`on_error` callback
contract as `Microphone`, so `__main__.py`'s `AudioManager` can point
either one at the same downstream envelope-follower pipeline
interchangeably.
"""
from __future__ import annotations

import math
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import sounddevice as sd


@dataclass
class SpeakingState:
    envelope: float = 0.0
    hold_remaining_s: float = 0.0
    talk_level: int = 0


def rms_volume(block: np.ndarray) -> float:
    if block.size == 0:
        return 0.0
    # sqrt(dot(block, block) / n) instead of sqrt(mean(square(block))) --
    # found while profiling 2026-09-16 (perf showed this thread using a
    # disproportionate share of CPU for such a tiny, infrequent
    # calculation): np.square() materializes a whole extra array before
    # np.mean() reduces it, and the dtype=np.float64 upcast doubled the
    # memory traffic for no accuracy this app actually needs (this is a
    # volume meter driving threshold comparisons, not a measurement that
    # needs float64 precision). np.dot computes the same sum-of-squares
    # as a single reduction, no intermediate array -- measured ~4.3x
    # faster per call on a realistic 1024-sample block, identical result
    # to float32 precision.
    return float(np.sqrt(np.dot(block, block) / block.size))


def downmix_to_mono(data: np.ndarray) -> np.ndarray:
    """Collapses a (frames, channels) block to mono. `channels` is always
    1 or 2 here -- `_run_one_connection` caps `native_channels` at
    `min(2, max_input_channels)` -- so this only ever needs those two
    cases. The 2-channel path is a plain averaged sum rather than
    `.mean(axis=1)`: found while profiling 2026-09-16 that generic
    reduction machinery has real fixed overhead that dominates over the
    actual arithmetic at this size -- measured ~9x slower per call than
    this for a realistic 1024-sample block, and it was the single
    largest contributor to the audio thread's CPU share in that profile
    (bigger than rms_volume's own cost)."""
    if data.ndim > 1 and data.shape[1] > 1:
        return (data[:, 0] + data[:, 1]) * np.float32(0.5)
    return data.reshape(-1)


def _time_coeff(time_ms: float, frame_seconds: float) -> float:
    """Fraction of the remaining gap to close this frame, for a smooth
    exponential approach with the given time constant."""
    return 1.0 - math.exp(-frame_seconds / max(time_ms / 1000.0, 1e-6))


def update_speaking(
    state: SpeakingState,
    volume: float,
    *,
    noise_gate: float,
    mild_open: float,
    mild_close: float,
    wide_open: float,
    wide_close: float,
    attack_ms: float,
    hold_ms: float,
    release_ms: float,
    frame_seconds: float,
) -> SpeakingState:
    gated_volume = volume if volume >= noise_gate else 0.0

    if gated_volume > state.envelope:
        envelope = state.envelope + (gated_volume - state.envelope) * _time_coeff(
            attack_ms, frame_seconds
        )
        hold_remaining = hold_ms / 1000.0
    else:
        hold_remaining = state.hold_remaining_s - frame_seconds
        if hold_remaining > 0:
            envelope = state.envelope
        else:
            hold_remaining = 0.0
            envelope = state.envelope + (
                gated_volume - state.envelope
            ) * _time_coeff(release_ms, frame_seconds)

    level = state.talk_level
    if level < 2 and envelope >= wide_open:
        level = 2
    elif level < 1 and envelope >= mild_open:
        level = 1
    if level == 2 and envelope < wide_close:
        level = 1
    if level >= 1 and envelope < mild_close:
        level = 0

    return SpeakingState(
        envelope=envelope, hold_remaining_s=hold_remaining, talk_level=level
    )


# --- Device selection -----------------------------------------------
#
# On this machine PortAudio exposes three host APIs (ALSA, OSS, JACK --
# the last one is PipeWire's JACK-compatible shim, and is where the real,
# correctly-described devices live). The raw ALSA entries are junk: e.g.
# the actual USB mic shows 0 input channels under ALSA and 4 under the
# JACK/PipeWire shim for the exact same physical device, and ALSA's own
# "default" pseudo-device reports a placeholder 128 channels. Worse than
# just wrong metadata: unicorn-viz's audio/capture.py found PortAudio's
# ALSA backend aborts at the C level if the underlying device disappears
# mid-stream (e.g. a USB mic unplugged) -- not a catchable Python
# exception, a hard process abort. So raw ALSA devices are excluded
# outright, not merely deprioritized.
_PSEUDO_INPUT_MARKERS = (
    "speech-dispatcher",
    "dummy",
    "alsa capture [python",
    "pipewire alsa [python",
)


def _hostapi_names() -> dict[int, str]:
    try:
        return {
            i: str(info.get("name", "")).strip().lower()
            for i, info in enumerate(sd.query_hostapis())
        }
    except Exception:
        return {}


def _is_alsa_hostapi(device_info: dict, hostapi_names: dict[int, str]) -> bool:
    return hostapi_names.get(int(device_info.get("hostapi", -1)), "") == "alsa"


def _is_pseudo_input(name: str) -> bool:
    lowered = name.strip().lower()
    return any(marker in lowered for marker in _PSEUDO_INPUT_MARKERS)


def usable_input_devices() -> list[dict]:
    """Real input devices only: raw ALSA and pseudo/self-referential
    capture entries excluded (see the module-level note above). Each dict
    is sounddevice's own device-info dict plus an "index" key."""
    try:
        raw_devices = sd.query_devices()
    except Exception:
        return []
    hostapi_names = _hostapi_names()
    devices = []
    for i, info in enumerate(raw_devices):
        if info.get("max_input_channels", 0) < 1:
            continue
        if _is_alsa_hostapi(info, hostapi_names):
            continue
        if _is_pseudo_input(str(info.get("name", ""))):
            continue
        devices.append({**info, "index": i})
    return devices


def resolve_input_device(hint: str | None) -> int | None:
    """Picks a real input device index, never a raw-ALSA or pseudo one.

    `hint` is a case-insensitive name substring (see AudioConfig.device);
    None picks the first usable device -- typically a PipeWire/Pulse
    "default"-named endpoint if one exists, otherwise whatever's first.
    Returns None (PortAudio's own default) only if nothing usable was
    found at all, so a stream open attempt still surfaces a real error
    instead of this function silently doing nothing.
    """
    usable = usable_input_devices()
    if not usable:
        return None
    if hint:
        hint_lower = hint.lower()
        for info in usable:
            if hint_lower in str(info["name"]).lower():
                return info["index"]
        # An unmatched hint falls through to the default below rather than
        # silently opening an unrelated device.
    for info in usable:
        if str(info["name"]).strip().lower() == "default":
            return info["index"]
    return usable[0]["index"]


def list_input_devices() -> list[str]:
    return [str(info["name"]) for info in usable_input_devices()]


# --- Capture ----------------------------------------------------------

_POLL_INTERVAL_S = 0.01  # bounds how long a read can block before re-checking stop
_DEFAULT_RECONNECT_DELAY_S = 1.0


class Microphone:
    """Blocking-read capture with automatic reconnect on stream failure.

    Ported from unicorn-viz's AudioCapture, not just its general shape:
    - Blocking-read mode (no callback= argument) in a dedicated daemon
      thread, polling `stream.read_available` before calling `read()` so
      the call itself is never allowed to block for longer than
      `_POLL_INTERVAL_S`. `stream.abort()` does not reliably unblock an
      in-flight blocking read on the ALSA-adjacent hostapis here, so this
      polling is what actually makes stop() reliable, not the abort call.
    - Takes its own copy of each block before any numpy arithmetic --
      running math on a buffer PortAudio may reclaim mid-teardown is a
      use-after-free, observed there as a heap-corruption abort nowhere
      near the real cause.

    Reconnect is error-triggered, not a periodic timer: legacy
    PNGTuber-Plus reset its mic on an unconditional 180s timer, which was
    a workaround for a Godot AudioServer-specific artifact with no
    PortAudio equivalent -- not applicable here, so it isn't ported. The
    actual real-world failure this needs to survive is a USB mic being
    unplugged mid-stream, which surfaces as a stream.read() exception,
    not a clock tick; reconnect only fires in response to that, retrying
    with `reconnect_delay_s` backoff between attempts until it succeeds
    or stop() is called.

    Threading contract: `on_volume` and `on_error` are both called
    directly from this class's background thread -- never the Qt/GUI
    thread. Neither callback may touch a Qt object directly (no QWidget,
    no QMessageBox, nothing Qt) for that reason; the caller must marshal
    onto the Qt thread first, e.g. via a QObject + Signal with an
    explicit Qt.ConnectionType.QueuedConnection (see __main__.py's
    _AudioBridge, which both callbacks go through for exactly this
    reason -- AutoConnection can't be trusted here since these are plain
    closures, not bound methods on a QObject, so Qt has no thread-affinity
    to detect the hop is needed).
    """

    def __init__(
        self,
        on_volume: Callable[[float], None],
        device: str | None = None,
        samplerate: int = 44100,
        blocksize: int = 1024,
        reconnect_delay_s: float = _DEFAULT_RECONNECT_DELAY_S,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._on_volume = on_volume
        self.device = device
        self.samplerate = samplerate
        self.blocksize = blocksize
        self._reconnect_delay_s = reconnect_delay_s
        self._on_error = on_error
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._stream: sd.InputStream | None = None
        # See stop()'s own docstring -- set just before _stop_event, read
        # by _run_one_connection's finally block on the worker thread.
        self._abandon_on_stop = False

    def start(self) -> None:
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="unicorn-cloak-audio", daemon=True
        )
        self._worker_thread.start()

    def stop(self, *, abandon: bool = False) -> None:
        """abandon=True skips this stream's own PortAudio teardown
        (stream.abort()/close()) entirely -- for the one case where the
        whole process is about to os._exit() immediately after anyway
        (see __main__.py's on_quit()), never for an in-app source switch
        that needs the device actually released while the app keeps
        running. Real-machine crash, 2026-09-17 (owner's report, with
        OBS open sharing the same mic): PortAudio's own JACK hostapi hit
        a hard C-level assertion inside its stream-close path
        ('pa_jack.c', "Expression 'result' failed") -- not a Python
        exception, so nothing here can catch it once triggered, and nothing
        upstream (this app's own os._exit() fix from earlier today) helps
        either, since this happens synchronously in this normal stop()
        call, well before that atexit-skipping code ever runs. Skipping
        the call outright, when the OS is about to reclaim the device
        handle regardless, is the only way to avoid the crash rather than
        merely reducing its odds."""
        self._abandon_on_stop = abandon
        self._stop_event.set()
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=2.0)
            self._worker_thread = None

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._run_one_connection()
            except Exception as exc:
                if not self._stop_event.is_set():
                    self._report_error(f"microphone stream failed: {exc}")
            if self._stop_event.is_set():
                break
            self._stop_event.wait(self._reconnect_delay_s)

    def _report_error(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)

    def _run_one_connection(self) -> None:
        device_index = resolve_input_device(self.device)
        # The JACK/PipeWire hostapi runs at a fixed server-wide rate
        # (commonly 48000, not the 44100 this class used to hardcode) and
        # raises "Invalid sample rate" rather than resampling -- confirmed
        # live on this machine's actual mic. Query the device's own
        # default_samplerate instead of assuming one, same as
        # unicorn-viz's _open_stream. self.samplerate is only the
        # fallback for when that query itself fails.
        native_rate = self.samplerate
        native_channels = 2
        try:
            info = (
                sd.query_devices(device_index)
                if device_index is not None
                else sd.query_devices(kind="input")
            )
            native_rate = int(info.get("default_samplerate", self.samplerate))
            native_channels = min(2, max(1, int(info.get("max_input_channels", 2))))
        except Exception:
            pass
        self.samplerate = native_rate

        # channels=1 here (rather than the device's own native_channels,
        # then downmixing ourselves) reproducibly corrupted the heap on
        # the very first stream.read() on this machine's actual mic --
        # confirmed with a minimal repro isolated to exactly this one
        # parameter, unrelated to anything else in this class. Never
        # actually observed by unicorn-viz because it never asks
        # PortAudio to downmix either; channels=min(2, max_input_channels)
        # plus doing the mono conversion in software (below) is its
        # existing, working pattern, not a new workaround invented here.
        stream = sd.InputStream(
            device=device_index,
            channels=native_channels,
            samplerate=native_rate,
            blocksize=self.blocksize,
            dtype="float32",
        )
        stream.start()
        self._stream = stream
        try:
            while not self._stop_event.is_set():
                if stream.read_available < self.blocksize:
                    time.sleep(_POLL_INTERVAL_S)
                    continue
                data, _overflow = stream.read(self.blocksize)
                # Own copy before any arithmetic -- see class docstring.
                data = np.array(data, dtype=np.float32, copy=True)
                mono = downmix_to_mono(data)
                self._on_volume(rms_volume(mono))
        finally:
            self._stream = None
            if not self._abandon_on_stop:
                try:
                    stream.abort()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass


# --- File-based playback (alternate volume source) --------------------

DEFAULT_FILE_SAMPLERATE = 48000
DEFAULT_FILE_BLOCKSIZE = 1024


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


class FilePlayback:
    """Feeds the same on_volume/on_error contract as Microphone (see its
    docstring for the full threading contract -- identical here: both
    callbacks fire from this class's background thread, never touch Qt
    directly), but the volume blocks come from decoding a local audio or
    video file with ffmpeg instead of a live mic input.

    Built for a specific real workflow (2026-09-16): re-recording a video
    interview with the avatar standing in for one participant. That
    participant's own isolated audio track survived and should drive the
    avatar's mouth, but it is *not* what should end up in the recording
    -- a separate, already-combined track (both participants, with some
    unavoidable overlap where the isolated one got damaged) is what
    actually gets captured, played back through OBS's own Media Source.
    So this class **never plays audio out loud on purpose** -- ffmpeg
    decodes straight to a pipe this process reads, never to a system
    audio sink -- it only extracts the isolated track's volume envelope,
    paced to real playback speed via ffmpeg's own `-re` flag (verified
    empirically: a 2-second test tone took ~1.6s wall-clock to decode
    with it, not near-instant) so talk_level tracks that file's speech
    at the cadence it would if it were playing out loud. The owner is
    expected to click Play here and start the combined recording in OBS
    close together by hand -- exact frame-sync isn't the goal, and the
    source material already has some overlap/slop in it regardless.

    One-shot, not looping: reaching the end of the file (or a decode
    failure) calls on_finished() once and stops, the same as a manual
    stop() -- unlike Microphone, a failure here is not retried, since a
    bad file isn't a transient condition like a disconnected mic.
    """

    def __init__(
        self,
        path: str,
        on_volume: Callable[[float], None],
        on_error: Callable[[str], None] | None = None,
        on_finished: Callable[[], None] | None = None,
        blocksize: int = DEFAULT_FILE_BLOCKSIZE,
        samplerate: int = DEFAULT_FILE_SAMPLERATE,
    ) -> None:
        self.path = path
        self.blocksize = blocksize
        self.samplerate = samplerate
        self._on_volume = on_volume
        self._on_error = on_error
        self._on_finished = on_finished
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen | None = None

    @property
    def is_playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_playing:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="unicorn-cloak-file-playback", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Signals the background thread and its ffmpeg subprocess to
        stop, but does not wait for them to actually finish -- unlike
        Microphone's own stop(), whose read loop polls a stream and so
        notices the stop event within one short sleep interval,
        _run's loop can be sitting inside a single blocking
        process.stdout.read() call for as long as ffmpeg takes to
        actually exit after terminate() (normally a handful of ms, but
        not bounded -- ffmpeg's own signal handling and the '-re'
        real-time pacing this class relies on both affect it, and it
        gets worse under system load).

        Used to join(timeout=2.0) here, on whatever thread called stop()
        -- always the Qt thread, since AudioManager's own docstring
        requires it. That blocked the entire UI, including the very Stop
        button just clicked, for however long the background thread took
        to unblock -- and a second, impatient click during that freeze
        landed *after* the file had actually already stopped, restarting
        it (owner's report, 2026-09-20: "it's not stopping every time i
        press stop... sometimes it keeps going till i toggle it a couple
        times"). The thread finishes and reports itself on its own time
        instead, via on_finished -- already routed through AudioManager's
        QueuedConnection back to the Qt thread specifically so a
        background-thread callback never needs anything to wait on it."""
        self._stop_event.set()
        if self._process is not None:
            try:
                self._process.terminate()
            except Exception:
                pass

    def _run(self) -> None:
        bytes_per_block = self.blocksize * 4  # float32 mono
        cmd = [
            "ffmpeg", "-v", "error", "-re", "-i", self.path,
            "-f", "f32le", "-ar", str(self.samplerate), "-ac", "1", "pipe:1",
        ]
        try:
            # stderr=DEVNULL, not PIPE: reading stdout and stderr from two
            # separate blocking pipes without a dedicated reader thread
            # for each is a classic deadlock (ffmpeg blocks writing to a
            # full stderr pipe while we're only draining stdout) -- not
            # worth the complexity of a second reader thread just to
            # surface ffmpeg's own log text; the exit code is enough to
            # report a failure.
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            self._report_error(
                "ffmpeg is not installed -- required to decode audio/video files."
            )
            if self._on_finished is not None:
                self._on_finished()
            return

        self._process = process
        try:
            while not self._stop_event.is_set():
                raw = process.stdout.read(bytes_per_block)
                if not raw:
                    break
                if len(raw) < bytes_per_block:
                    # Final, short block at end-of-file -- pad with
                    # silence rather than drop the last fraction of a
                    # second.
                    raw = raw + b"\x00" * (bytes_per_block - len(raw))
                block = np.frombuffer(raw, dtype=np.float32)
                self._on_volume(rms_volume(block))
        finally:
            stopped_manually = self._stop_event.is_set()
            try:
                process.terminate()
                process.wait(timeout=2.0)
            except Exception:
                pass
            self._process = None
            self._on_volume(0.0)  # close the mouth, whichever way this ended
            if not stopped_manually and process.returncode not in (0, None):
                self._report_error(
                    f"ffmpeg exited with an error (code {process.returncode}) "
                    f"decoding {self.path!r} -- is this a valid audio/video file?"
                )
            if self._on_finished is not None:
                self._on_finished()

    def _report_error(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)


@dataclass
class EnvelopeRecording:
    """A captured (seconds_since_start, volume) sequence -- what
    EnvelopeRecorder.finish() produces and EnvelopeLoopPlayback loops
    through. Kept as a plain dataclass, independent of any particular
    recorder/player implementation, so it's trivial to test on its own."""

    samples: list[tuple[float, float]]

    @property
    def duration_s(self) -> float:
        return self.samples[-1][0] if self.samples else 0.0


class EnvelopeRecorder:
    """Captures (elapsed_seconds, volume) pairs for up to max_duration_s
    of wall-clock time, then stops accepting more.

    Built for a real tuning problem (2026-09-16, owner's words): getting
    the attack/hold/release/threshold numbers right in Settings normally
    means talking continuously while watching the mouth. This records
    whatever's *currently* driving talk_level -- mic or file, it doesn't
    care which -- so AudioManager can feed it a real 10-second speech
    sample and then loop that back (see EnvelopeLoopPlayback) instead.

    Deliberately not threaded: record() is meant to be called inline from
    whatever callback is already delivering volume values (AudioManager's
    _handle_volume_from_source), on whichever thread that already runs
    on -- this class does no I/O and touches no Qt state, so it doesn't
    need its own thread or locking.
    """

    def __init__(self, max_duration_s: float = 10.0) -> None:
        self.max_duration_s = max_duration_s
        self._start_time: float | None = None
        self._samples: list[tuple[float, float]] = []
        self._finished = False

    @property
    def is_recording(self) -> bool:
        return self._start_time is not None and not self._finished

    def start(self) -> None:
        self._start_time = time.monotonic()
        self._samples = []
        self._finished = False

    def record(self, value: float) -> None:
        if not self.is_recording:
            return
        elapsed = time.monotonic() - self._start_time
        if elapsed >= self.max_duration_s:
            self._finished = True
            return
        self._samples.append((elapsed, value))

    def finish(self) -> EnvelopeRecording:
        self._finished = True
        return EnvelopeRecording(samples=list(self._samples))


class EnvelopeLoopPlayback:
    """Loops a recorded EnvelopeRecording forever, feeding on_volume at
    the same relative timing it was captured at -- a real 10-second
    speech rhythm to tune thresholds against, rather than an evenly
    spaced average that would smooth over the pauses and bursts that
    actually stress attack/hold/release timing.

    Same on_volume/on_error callback contract as Microphone/FilePlayback,
    same threading contract (fires from its own background thread, never
    touches Qt) -- see Microphone's docstring for the full rationale.
    Unlike FilePlayback, this never ends on its own: it loops until
    stop() is called, since the whole point is uninterrupted tuning time.
    """

    def __init__(
        self,
        recording: EnvelopeRecording,
        on_volume: Callable[[float], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self.recording = recording
        self._on_volume = on_volume
        self._on_error = on_error
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_playing or not self.recording.samples:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="unicorn-cloak-envelope-loop", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        samples = self.recording.samples
        try:
            while not self._stop_event.is_set():
                prev_t = 0.0
                for t, value in samples:
                    if self._stop_event.is_set():
                        return
                    wait_s = t - prev_t
                    if wait_s > 0:
                        self._stop_event.wait(wait_s)
                    prev_t = t
                    if self._stop_event.is_set():
                        return
                    self._on_volume(value)
        except Exception as exc:
            self._report_error(f"envelope loop playback failed: {exc}")

    def _report_error(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)
