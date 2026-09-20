import threading
import time

import numpy as np
import pytest

from unicorn_cloak import audio as audio_module
from unicorn_cloak.audio import (
    EnvelopeLoopPlayback,
    EnvelopeRecorder,
    EnvelopeRecording,
    FilePlayback,
    Microphone,
    SpeakingState,
    downmix_to_mono,
    ffmpeg_available,
    list_input_devices,
    resolve_input_device,
    rms_volume,
    update_speaking,
    usable_input_devices,
)

from qt_helpers import make_test_wav, needs_ffmpeg

# Shared thresholds for the tests below: gate 0.005, mild 0.01-0.02,
# wide 0.04-0.08, snappy attack, a real hold, and a moderate release.
KW = dict(
    noise_gate=0.005,
    mild_open=0.02,
    mild_close=0.01,
    wide_open=0.08,
    wide_close=0.04,
    attack_ms=10.0,
    hold_ms=100.0,
    release_ms=200.0,
)
FRAME_S = 1 / 60


def run(state, volume, frames=1, **overrides):
    kwargs = {**KW, **overrides}
    for _ in range(frames):
        state = update_speaking(state, volume, frame_seconds=FRAME_S, **kwargs)
    return state


def test_rms_volume_empty_is_zero():
    assert rms_volume(np.array([])) == 0.0


def test_rms_volume_of_constant_signal():
    block = np.full(100, 0.5, dtype=np.float32)
    assert rms_volume(block) == pytest.approx(0.5, abs=1e-6)


def test_downmix_mono_input_is_passed_through_flattened():
    data = np.array([[0.1], [0.2], [0.3]], dtype=np.float32)
    result = downmix_to_mono(data)
    assert result.shape == (3,)
    np.testing.assert_allclose(result, [0.1, 0.2, 0.3])


def test_downmix_stereo_input_averages_channels():
    data = np.array([[0.0, 1.0], [0.2, 0.4]], dtype=np.float32)
    result = downmix_to_mono(data)
    np.testing.assert_allclose(result, [0.5, 0.3], atol=1e-6)


def test_downmix_matches_generic_mean_axis_1():
    # The fast 2-channel path (found while profiling, see audio.py) must
    # stay numerically equivalent to the generic reduction it replaced.
    rng = np.random.default_rng(0)
    data = rng.uniform(-1.0, 1.0, (1024, 2)).astype(np.float32)
    np.testing.assert_allclose(downmix_to_mono(data), data.mean(axis=1), atol=1e-6)


def test_noise_gate_blocks_quiet_signal_entirely():
    state = run(SpeakingState(), volume=0.003, frames=200)
    assert state.envelope == 0.0
    assert state.talk_level == 0


def test_loud_signal_reaches_wide_band():
    state = run(SpeakingState(), volume=0.5, frames=200)
    assert state.talk_level == 2


def test_medium_signal_reaches_mild_but_not_wide():
    state = run(SpeakingState(), volume=0.03, frames=200)
    assert state.talk_level == 1


def test_hold_keeps_level_through_a_brief_dip():
    # Get loud enough to open wide, then drop to silence for less than
    # hold_ms -- the level should not have collapsed back to 0 yet.
    state = run(SpeakingState(), volume=0.5, frames=30)  # ~0.5s, well past attack
    assert state.talk_level == 2
    state = run(state, volume=0.0, frames=3)  # 3 frames @ 60fps = 50ms < hold_ms
    assert state.talk_level > 0


def test_release_eventually_returns_to_quiet():
    state = run(SpeakingState(), volume=0.5, frames=30)
    assert state.talk_level == 2
    state = run(state, volume=0.0, frames=300)  # well past hold + release
    assert state.talk_level == 0
    assert state.envelope == pytest.approx(0.0, abs=1e-4)


def test_hysteresis_holds_band_between_open_and_close_thresholds():
    # Reach wide, then ease down to a level between wide_close (0.04) and
    # wide_open (0.08) -- should stay at wide, not immediately drop to mild.
    state = run(SpeakingState(), volume=0.5, frames=200)
    assert state.talk_level == 2
    state = run(state, volume=0.06, frames=200)  # settles here, between the two
    assert state.talk_level == 2


def test_attack_is_gradual_not_instant():
    state = update_speaking(SpeakingState(), volume=0.5, frame_seconds=FRAME_S, **KW)
    assert 0.0 < state.envelope < 0.5


# --- Device filtering ---------------------------------------------------
#
# This fixture is a trimmed copy of what `sd.query_devices()`/
# `sd.query_hostapis()` actually returned on this machine (2026-09-16):
# three host APIs (ALSA, OSS, JACK -- the last is PipeWire's JACK-shim,
# where the real devices live), the real USB mic reporting 0 input
# channels under raw ALSA and 4 under the shim for the same physical
# device, and ALSA's own "default" pseudo-device reporting a placeholder
# 128 channels.

_HOSTAPIS = [
    {"name": "ALSA"},
    {"name": "OSS"},
    {"name": "JACK Audio Connection Kit"},
]

_DEVICES = [
    {"name": "HDA Intel PCH: ALC269VB Analog (hw:0,0)", "hostapi": 0, "max_input_channels": 2},
    {"name": "Blue Microphones: USB Audio (hw:6,0)", "hostapi": 0, "max_input_channels": 0},
    {"name": "sysdefault", "hostapi": 0, "max_input_channels": 128},
    {"name": "default", "hostapi": 0, "max_input_channels": 128},
    {"name": "Blue Microphones Analog Stereo", "hostapi": 2, "max_input_channels": 4},
    {"name": "DDJ-REV1 Analog Stereo", "hostapi": 2, "max_input_channels": 2},
    {"name": "speech-dispatcher-dummy", "hostapi": 2, "max_input_channels": 2},
    {"name": "PipeWire ALSA [python3.14]/ALSA Capture [python3.14]", "hostapi": 2, "max_input_channels": 2},
]


def _patch_devices(monkeypatch):
    monkeypatch.setattr(audio_module.sd, "query_hostapis", lambda: _HOSTAPIS)
    monkeypatch.setattr(audio_module.sd, "query_devices", lambda: _DEVICES)


def test_usable_input_devices_excludes_raw_alsa(monkeypatch):
    _patch_devices(monkeypatch)
    names = [d["name"] for d in usable_input_devices()]
    assert "HDA Intel PCH: ALC269VB Analog (hw:0,0)" not in names
    assert "sysdefault" not in names
    assert "default" not in names  # the ALSA one specifically


def test_usable_input_devices_excludes_pseudo_inputs(monkeypatch):
    _patch_devices(monkeypatch)
    names = [d["name"] for d in usable_input_devices()]
    assert "speech-dispatcher-dummy" not in names
    assert "PipeWire ALSA [python3.14]/ALSA Capture [python3.14]" not in names


def test_usable_input_devices_keeps_real_pipewire_devices(monkeypatch):
    _patch_devices(monkeypatch)
    names = [d["name"] for d in usable_input_devices()]
    assert "Blue Microphones Analog Stereo" in names
    assert "DDJ-REV1 Analog Stereo" in names


def test_list_input_devices_matches_usable_devices(monkeypatch):
    _patch_devices(monkeypatch)
    assert list_input_devices() == [d["name"] for d in usable_input_devices()]


def test_resolve_input_device_matches_hint(monkeypatch):
    _patch_devices(monkeypatch)
    index = resolve_input_device("Blue Microphones")
    assert _DEVICES[index]["name"] == "Blue Microphones Analog Stereo"


def test_resolve_input_device_hint_never_matches_excluded_device(monkeypatch):
    _patch_devices(monkeypatch)
    # "default" as a hint should not resolve to the excluded raw-ALSA
    # "default" pseudo-device just because the substring matches.
    index = resolve_input_device("default")
    assert index is None or _DEVICES[index]["hostapi"] != 0


def test_resolve_input_device_falls_back_when_hint_matches_nothing(monkeypatch):
    _patch_devices(monkeypatch)
    index = resolve_input_device("some device that does not exist")
    assert index is not None
    assert _DEVICES[index]["name"] == "Blue Microphones Analog Stereo"  # first usable


def test_resolve_input_device_with_no_hint_picks_first_usable(monkeypatch):
    _patch_devices(monkeypatch)
    index = resolve_input_device(None)
    assert _DEVICES[index]["name"] == "Blue Microphones Analog Stereo"


def test_resolve_input_device_with_no_usable_devices_returns_none(monkeypatch):
    monkeypatch.setattr(audio_module.sd, "query_hostapis", lambda: _HOSTAPIS)
    monkeypatch.setattr(audio_module.sd, "query_devices", lambda: [_DEVICES[0]])  # only raw ALSA
    assert resolve_input_device(None) is None


# --- Microphone: reconnect on stream failure -----------------------------


class _FakeStream:
    """Stands in for sd.InputStream. `behavior` is a list of per-attempt
    outcomes: "fail_to_open", "fail_on_read", or "ok" (streams forever
    until the test's stop_event fires)."""

    _next_behavior_index = [0]  # class-level, reset per test via fixture

    def __init__(self, behavior_queue, on_read=None, **kwargs):
        self._behavior_queue = behavior_queue
        self._on_read = on_read
        self._behavior = behavior_queue.pop(0) if behavior_queue else "ok"
        self._reads = 0
        if self._behavior == "fail_to_open":
            raise RuntimeError("simulated: device not found")

    def start(self) -> None:
        pass

    @property
    def read_available(self) -> int:
        return 1024

    def read(self, n):
        self._reads += 1
        if self._behavior == "fail_on_read" and self._reads > 3:
            raise RuntimeError("simulated: device disappeared mid-stream")
        if self._on_read is not None:
            self._on_read()
        return np.zeros((n, 1), dtype=np.float32), False

    def abort(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_microphone_reports_error_and_reconnects_after_failed_open(monkeypatch):
    behavior_queue = ["fail_to_open", "ok"]
    errors = []
    volumes_received = threading.Event()

    def fake_input_stream(**kwargs):
        return _FakeStream(behavior_queue, on_read=volumes_received.set, **kwargs)

    monkeypatch.setattr(audio_module.sd, "InputStream", fake_input_stream)
    monkeypatch.setattr(audio_module, "resolve_input_device", lambda hint: None)

    mic = Microphone(
        on_volume=lambda v: None,
        reconnect_delay_s=0.01,
        on_error=errors.append,
    )
    mic.start()
    try:
        assert volumes_received.wait(timeout=2.0), "never reconnected successfully"
    finally:
        mic.stop()

    assert len(errors) >= 1
    assert "device not found" in errors[0]


def test_microphone_reconnects_after_read_failure_mid_stream(monkeypatch):
    behavior_queue = ["fail_on_read", "ok"]
    errors = []
    read_count = {"n": 0}
    reconnected = threading.Event()

    def on_read():
        read_count["n"] += 1
        if read_count["n"] > 10:  # well past the fail_on_read stream's failure point
            reconnected.set()

    def fake_input_stream(**kwargs):
        return _FakeStream(behavior_queue, on_read=on_read, **kwargs)

    monkeypatch.setattr(audio_module.sd, "InputStream", fake_input_stream)
    monkeypatch.setattr(audio_module, "resolve_input_device", lambda hint: None)

    mic = Microphone(
        on_volume=lambda v: None,
        reconnect_delay_s=0.01,
        on_error=errors.append,
    )
    mic.start()
    try:
        assert reconnected.wait(timeout=2.0), "never recovered after the simulated mid-stream failure"
    finally:
        mic.stop()

    assert any("disappeared mid-stream" in e for e in errors)


def test_microphone_stop_abandon_skips_stream_teardown(monkeypatch):
    # Regression 2026-09-17, owner's report (real machine, OBS open
    # sharing the mic): PortAudio's own JACK hostapi hit a hard C-level
    # assertion inside stream.abort()/close() -- see Microphone.stop()'s
    # own docstring. abandon=True must skip those calls entirely, not
    # just attempt-and-ignore-exceptions (a C-level abort() isn't a
    # Python exception in the first place, so "just catch it" was never
    # actually an option).
    close_calls = {"abort": 0, "close": 0}

    class _CountingStream(_FakeStream):
        def abort(self) -> None:
            close_calls["abort"] += 1

        def close(self) -> None:
            close_calls["close"] += 1

    def fake_input_stream(**kwargs):
        return _CountingStream(["ok"], **kwargs)

    monkeypatch.setattr(audio_module.sd, "InputStream", fake_input_stream)
    monkeypatch.setattr(audio_module, "resolve_input_device", lambda hint: None)

    mic = Microphone(on_volume=lambda v: None)
    mic.start()
    time.sleep(0.05)
    mic.stop(abandon=True)

    assert close_calls == {"abort": 0, "close": 0}


def test_microphone_stop_without_abandon_still_tears_down_the_stream(monkeypatch):
    close_calls = {"abort": 0, "close": 0}

    class _CountingStream(_FakeStream):
        def abort(self) -> None:
            close_calls["abort"] += 1

        def close(self) -> None:
            close_calls["close"] += 1

    def fake_input_stream(**kwargs):
        return _CountingStream(["ok"], **kwargs)

    monkeypatch.setattr(audio_module.sd, "InputStream", fake_input_stream)
    monkeypatch.setattr(audio_module, "resolve_input_device", lambda hint: None)

    mic = Microphone(on_volume=lambda v: None)
    mic.start()
    time.sleep(0.05)
    mic.stop()  # default: abandon=False

    assert close_calls == {"abort": 1, "close": 1}


def test_microphone_stop_is_prompt_even_mid_poll(monkeypatch):
    # The "ok" behavior streams forever; stop() must still return quickly
    # (bounded by the poll interval, not by waiting for a read to finish).
    def fake_input_stream(**kwargs):
        return _FakeStream(["ok"], **kwargs)

    monkeypatch.setattr(audio_module.sd, "InputStream", fake_input_stream)
    monkeypatch.setattr(audio_module, "resolve_input_device", lambda hint: None)

    mic = Microphone(on_volume=lambda v: None)
    mic.start()
    time.sleep(0.05)
    start = time.monotonic()
    mic.stop()
    assert time.monotonic() - start < 1.0


def test_microphone_never_requests_mono_directly_from_the_device(monkeypatch):
    # Regression 2026-09-16: channels=1 requested directly from a device
    # whose own native channel count is higher (this machine's mic
    # reports 4) reproducibly corrupted the process heap on the very
    # first stream.read() -- confirmed with a minimal repro isolated to
    # exactly this one parameter. A fake stream can't reproduce that
    # memory corruption (it's real PortAudio/ALSA behavior, not
    # something Python-level), but it can lock in the actual fix:
    # request the device's own channel count (capped at 2) and downmix
    # to mono in software, the same pattern unicorn-viz already uses.
    opened_with = {}

    def fake_input_stream(**kwargs):
        opened_with.update(kwargs)
        return _FakeStream(["ok"], **kwargs)

    monkeypatch.setattr(audio_module.sd, "InputStream", fake_input_stream)
    monkeypatch.setattr(audio_module, "resolve_input_device", lambda hint: None)
    monkeypatch.setattr(
        audio_module.sd,
        "query_devices",
        lambda *a, **k: {"default_samplerate": 48000.0, "max_input_channels": 4},
    )

    mic = Microphone(on_volume=lambda v: None)
    mic.start()
    try:
        for _ in range(100):
            if "channels" in opened_with:
                break
            time.sleep(0.01)
    finally:
        mic.stop()

    assert opened_with.get("channels") == 2
    assert opened_with.get("samplerate") == 48000


def test_microphone_downmixes_multichannel_blocks_to_mono(monkeypatch):
    received = []

    class StereoFakeStream(_FakeStream):
        def read(self, n):
            self._reads += 1
            # Left channel all 1.0, right all 0.0 -- mono mean should be 0.5.
            data = np.zeros((n, 2), dtype=np.float32)
            data[:, 0] = 1.0
            return data, False

    def fake_input_stream(**kwargs):
        return StereoFakeStream(["ok"], **kwargs)

    monkeypatch.setattr(audio_module.sd, "InputStream", fake_input_stream)
    monkeypatch.setattr(audio_module, "resolve_input_device", lambda hint: None)
    monkeypatch.setattr(
        audio_module.sd,
        "query_devices",
        lambda *a, **k: {"default_samplerate": 48000.0, "max_input_channels": 2},
    )

    got_reading = threading.Event()

    def on_volume(v):
        received.append(v)
        got_reading.set()

    mic = Microphone(on_volume=on_volume)
    mic.start()
    try:
        assert got_reading.wait(timeout=2.0)
    finally:
        mic.stop()

    assert received[0] == pytest.approx(0.5, abs=1e-6)


@needs_ffmpeg
def test_file_playback_reports_nonzero_volume_for_a_tone(tmp_path):
    path = tmp_path / "tone.wav"
    make_test_wav(path, duration_s=0.3, amplitude=0.5)

    volumes = []
    finished = threading.Event()
    playback = FilePlayback(
        str(path),
        on_volume=volumes.append,
        on_finished=lambda _f: finished.set(),
        blocksize=512,
        samplerate=8000,
    )
    playback.start()
    assert finished.wait(timeout=10.0)

    assert len(volumes) >= 1
    assert max(volumes) > 0.05  # a real tone, not silence throughout
    assert volumes[-1] == 0.0  # closes the mouth at the end


@needs_ffmpeg
def test_file_playback_is_not_playing_after_it_finishes(tmp_path):
    path = tmp_path / "tone.wav"
    make_test_wav(path, duration_s=0.2)

    finished = threading.Event()
    playback = FilePlayback(
        str(path), on_volume=lambda v: None, on_finished=lambda _f: finished.set(),
        blocksize=512, samplerate=8000,
    )
    playback.start()
    assert finished.wait(timeout=10.0)
    time.sleep(0.05)  # let the thread actually join itself
    assert playback.is_playing is False


@needs_ffmpeg
def test_file_playback_stop_ends_it_early_without_reporting_an_error(tmp_path):
    path = tmp_path / "tone.wav"
    make_test_wav(path, duration_s=5.0)  # long enough to still be running

    errors = []
    playback = FilePlayback(
        str(path), on_volume=lambda v: None, on_error=errors.append,
        blocksize=512, samplerate=8000,
    )
    playback.start()
    time.sleep(0.2)
    assert playback.is_playing is True

    playback.stop()

    # stop() no longer blocks waiting for the background thread/ffmpeg to
    # actually finish (2026-09-20 fix -- see stop()'s own docstring: it
    # used to block whichever thread called it, always the Qt thread in
    # practice, for however long that took), so give it a moment to wind
    # down instead of asserting immediately.
    deadline = time.monotonic() + 2.0
    while playback.is_playing and time.monotonic() < deadline:
        time.sleep(0.02)
    assert playback.is_playing is False
    assert errors == []  # a deliberate stop is not a failure


@needs_ffmpeg
def test_file_playback_stop_does_not_block_the_caller(tmp_path):
    # Regression 2026-09-20, owner's report: "it's not stopping every
    # time i press stop... sometimes it keeps going till i toggle it a
    # couple times." Root cause: stop() used to join() the background
    # thread -- which can be sitting inside a single blocking
    # process.stdout.read() call for an unbounded stretch -- on whatever
    # thread called stop(), always the Qt thread in the real app,
    # freezing the whole UI. An impatient second click during that freeze
    # landed *after* the file had already stopped, restarting it. stop()
    # itself must now return immediately, regardless of how long the
    # background thread/ffmpeg actually take to wind down.
    path = tmp_path / "tone.wav"
    make_test_wav(path, duration_s=5.0)

    playback = FilePlayback(
        str(path), on_volume=lambda v: None,
        blocksize=512, samplerate=8000,
    )
    playback.start()
    time.sleep(0.2)

    started = time.monotonic()
    playback.stop()
    assert time.monotonic() - started < 0.1


@needs_ffmpeg
def test_file_playback_reports_an_error_for_a_nonexistent_file(tmp_path):
    errors = []
    finished = threading.Event()
    playback = FilePlayback(
        str(tmp_path / "does-not-exist.wav"),
        on_volume=lambda v: None,
        on_error=errors.append,
        on_finished=lambda _f: finished.set(),
    )
    playback.start()
    assert finished.wait(timeout=10.0)
    assert errors  # ffmpeg's nonzero exit is surfaced, not swallowed


def test_file_playback_reports_an_error_when_ffmpeg_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        audio_module.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError())
    )
    errors = []
    finished = threading.Event()
    playback = FilePlayback(
        str(tmp_path / "irrelevant.wav"),
        on_volume=lambda v: None,
        on_error=errors.append,
        on_finished=lambda _f: finished.set(),
    )
    playback.start()
    assert finished.wait(timeout=2.0)
    assert errors
    assert "ffmpeg" in errors[0].lower()


def test_ffmpeg_available_reflects_shutil_which(monkeypatch):
    monkeypatch.setattr(audio_module.shutil, "which", lambda name: None)
    assert ffmpeg_available() is False
    monkeypatch.setattr(audio_module.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    assert ffmpeg_available() is True


def test_envelope_recorder_is_not_recording_before_start():
    recorder = EnvelopeRecorder(max_duration_s=10.0)
    assert recorder.is_recording is False
    recorder.record(0.5)  # ignored -- not started yet
    assert recorder.finish().samples == []


def test_envelope_recorder_captures_values_with_elapsed_timestamps():
    recorder = EnvelopeRecorder(max_duration_s=10.0)
    recorder.start()
    assert recorder.is_recording is True
    recorder.record(0.1)
    time.sleep(0.02)
    recorder.record(0.2)
    recording = recorder.finish()
    assert recorder.is_recording is False
    assert [v for _t, v in recording.samples] == [0.1, 0.2]
    t0, t1 = (t for t, _v in recording.samples)
    assert 0 <= t0 < t1
    assert recording.duration_s == t1


def test_envelope_recorder_stops_accepting_samples_past_max_duration():
    recorder = EnvelopeRecorder(max_duration_s=0.02)
    recorder.start()
    recorder.record(0.1)
    time.sleep(0.05)
    recorder.record(0.9)  # should be dropped -- past max_duration_s
    assert recorder.is_recording is False
    recording = recorder.finish()
    assert [v for _t, v in recording.samples] == [0.1]


def test_envelope_recording_duration_is_zero_when_empty():
    assert EnvelopeRecording(samples=[]).duration_s == 0.0


def test_envelope_loop_playback_loops_recorded_values_until_stopped():
    recording = EnvelopeRecording(samples=[(0.0, 0.3), (0.01, 0.6), (0.02, 0.9)])
    values = []
    lock = threading.Lock()

    def on_volume(value):
        with lock:
            values.append(value)

    playback = EnvelopeLoopPlayback(recording, on_volume=on_volume)
    playback.start()
    assert playback.is_playing
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        with lock:
            if len(values) >= 9:  # at least three full loops
                break
        time.sleep(0.01)
    playback.stop()
    assert playback.is_playing is False
    with lock:
        assert len(values) >= 9
        # Every loop repeats the exact same three recorded values, in order.
        for i in range(0, len(values) - 2, 3):
            assert values[i:i + 3] == [0.3, 0.6, 0.9]


def test_envelope_loop_playback_does_not_start_with_no_samples():
    playback = EnvelopeLoopPlayback(EnvelopeRecording(samples=[]), on_volume=lambda v: None)
    playback.start()
    assert playback.is_playing is False


def test_envelope_loop_playback_stop_is_prompt():
    recording = EnvelopeRecording(samples=[(0.0, 0.5), (1.0, 0.5)])
    playback = EnvelopeLoopPlayback(recording, on_volume=lambda v: None)
    playback.start()
    start = time.monotonic()
    playback.stop()
    assert time.monotonic() - start < 1.5
