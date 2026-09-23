import threading
import time

import pytest

from unicorn_cloak.audio_manager import AudioManager
from unicorn_cloak.config import Config

from qt_helpers import make_test_wav, needs_ffmpeg


def _wait_until(qapp, predicate, timeout=10.0, interval=0.01) -> bool:
    # Every callback that crosses from a background thread (Microphone's
    # or FilePlayback's own) into a Qt signal ends up queued, not
    # direct -- pumping the event loop here is required for those to
    # actually be delivered, the same as __main__.py's real app relies
    # on its own event loop doing implicitly.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(interval)
    qapp.processEvents()
    return predicate()


def test_start_launches_a_microphone_by_default(qapp, monkeypatch):
    started = []
    monkeypatch.setattr(
        "unicorn_cloak.audio_manager.Microphone",
        lambda **kwargs: type("M", (), {"start": lambda self: started.append(True), "stop": lambda self, abandon=False: None, "blocksize": 1024, "samplerate": 44100})(),
    )
    manager = AudioManager(Config())
    manager.start()
    assert started == [True]


def test_switch_to_file_stops_the_microphone(qapp, monkeypatch):
    stopped = []
    monkeypatch.setattr(
        "unicorn_cloak.audio_manager.Microphone",
        lambda **kwargs: type("M", (), {
            "start": lambda self: None,
            "stop": lambda self, abandon=False: stopped.append(True),
            "blocksize": 1024, "samplerate": 44100,
        })(),
    )
    manager = AudioManager(Config())
    manager.start()  # source defaults to microphone
    manager.switch_to_file("/tmp/whatever.wav")
    assert stopped == [True]
    assert manager.config.audio.source == "file"
    assert manager.config.audio.file_path == "/tmp/whatever.wav"


@needs_ffmpeg
def test_play_file_drives_volume_measured_signal(qapp, tmp_path):
    path = tmp_path / "tone.wav"
    make_test_wav(path, duration_s=0.3, amplitude=0.5)

    manager = AudioManager(Config())
    volumes = []
    manager.volume_measured.connect(volumes.append)

    manager.switch_to_file(str(path))
    manager.play_file()

    assert _wait_until(qapp, lambda: len(volumes) > 0)
    assert _wait_until(qapp, lambda: not manager.is_file_playing)
    assert max(volumes) > 0.05


@needs_ffmpeg
def test_last_capture_monotonic_is_recorded_for_latency_measurement(qapp, tmp_path):
    path = tmp_path / "tone.wav"
    make_test_wav(path, duration_s=0.2)

    manager = AudioManager(Config())
    assert manager.last_capture_monotonic is None

    before = time.monotonic()
    manager.switch_to_file(str(path))
    manager.play_file()
    assert _wait_until(qapp, lambda: manager.last_capture_monotonic is not None)
    after = time.monotonic()

    assert before <= manager.last_capture_monotonic <= after
    manager.stop_file()


@needs_ffmpeg
def test_file_playback_stopped_signal_fires_when_playback_finishes(qapp, tmp_path):
    path = tmp_path / "tone.wav"
    make_test_wav(path, duration_s=0.2)

    manager = AudioManager(Config())
    stopped = threading.Event()
    manager.file_playback_stopped.connect(stopped.set)

    manager.switch_to_file(str(path))
    manager.play_file()

    assert _wait_until(qapp, stopped.is_set)


def test_play_file_does_nothing_without_a_file_path(qapp):
    manager = AudioManager(Config())
    manager.play_file()  # config.audio.file_path is None
    assert manager.is_file_playing is False


def test_stop_file_emits_file_playback_stopped_even_with_nothing_playing(qapp):
    manager = AudioManager(Config())
    received = []
    manager.file_playback_stopped.connect(lambda: received.append(True))
    manager.stop_file()
    assert received == [True]


def test_late_finish_from_a_replaced_file_does_not_stop_the_new_one(qapp, monkeypatch):
    # Regression, owner's report 2026-09-20: "hitting stop sometimes
    # doesn't stop the character from talking." FilePlayback.stop()
    # doesn't wait for the background thread to actually exit (see its
    # own docstring), so a Rewind -- or a fast Stop-then-Play -- can
    # start a new FilePlayback while the old one's thread is still
    # winding down. When that old thread finally calls on_finished, it
    # must be recognized as stale (the old instance, not the current
    # self._file) and ignored -- otherwise it wrongly nulls out and
    # "stops" the file that's actually still playing: file_playback_
    # stopped fires and closes the mouth while the orphaned old instance
    # keeps decoding real audio that self._file no longer references, so
    # nothing in the UI (including Stop) can reach it anymore.
    instances = []

    class _FakeFilePlayback:
        def __init__(self, path, on_volume, on_error=None, on_finished=None):
            self.path = path
            self.on_finished = on_finished
            self.is_playing = True
            self.blocksize = 1024
            self.samplerate = 44100
            instances.append(self)

        def start(self):
            pass

        def stop(self):
            self.is_playing = False

    monkeypatch.setattr("unicorn_cloak.audio_manager.FilePlayback", _FakeFilePlayback)

    manager = AudioManager(Config())
    manager.switch_to_file("/tmp/whatever.wav")
    manager.play_file()
    old_file = instances[0]

    manager.play_file()  # e.g. Rewind, or a fast Stop-then-Play
    new_file = instances[1]
    assert manager._file is new_file

    stopped_events = []
    manager.file_playback_stopped.connect(lambda: stopped_events.append(True))

    old_file.on_finished(old_file)  # the old thread's late, stale callback
    qapp.processEvents()  # QueuedConnection -- deliver it before asserting

    assert manager._file is new_file  # still the current, actually-playing file
    assert manager.is_file_playing is True
    assert stopped_events == []  # no false "stopped" for the file still playing


def test_blocksize_and_samplerate_default_when_nothing_active(qapp):
    manager = AudioManager(Config())
    assert manager.blocksize > 0
    assert manager.samplerate > 0


def _fake_microphone_class(
    started=None, stopped=None, devices=None, blocksize=1024, samplerate=44100, strict_flags=None
):
    started = started if started is not None else []
    stopped = stopped if stopped is not None else []
    devices = devices if devices is not None else []
    strict_flags = strict_flags if strict_flags is not None else []

    class _FakeMic:
        def __init__(self, **kwargs):
            self._on_volume = kwargs["on_volume"]
            self.blocksize = blocksize
            self.samplerate = samplerate
            devices.append(kwargs.get("device"))
            strict_flags.append(kwargs.get("strict_device"))

        def start(self):
            started.append(True)

        def stop(self, *, abandon=False):
            stopped.append(abandon)

    return _FakeMic, started, stopped


def test_starting_the_microphone_wires_a_device_resolved_callback_into_the_signal(qapp, monkeypatch):
    # Quick-win enhancement E2 (bug audit addendum 2026-09-23): whatever
    # name Microphone's own background thread reports, AudioManager just
    # forwards it through device_resolved -- no translation needed since
    # Signal.emit() is thread-safe (see this class's own docstring).
    callbacks = []

    class _FakeMic:
        def __init__(self, **kwargs):
            self.blocksize = 1024
            self.samplerate = 44100
            callbacks.append(kwargs.get("on_device_resolved"))

        def start(self):
            pass

        def stop(self, *, abandon=False):
            pass

    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", _FakeMic)

    manager = AudioManager(Config())
    resolved = []
    manager.device_resolved.connect(resolved.append)
    manager.start()

    callbacks[0]("Blue Microphones Analog Stereo")
    assert resolved == ["Blue Microphones Analog Stereo"]


def test_stopping_the_microphone_emits_an_empty_device_resolved(qapp, monkeypatch):
    # Clears the "Now capturing: …" label the moment nothing actually is
    # -- a stale name left showing after Stop/switch would be exactly the
    # kind of misleading-at-a-glance state E2 was meant to fix.
    FakeMic, _started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    resolved = []
    manager.device_resolved.connect(resolved.append)
    manager.start()
    manager.switch_to_file("/tmp/whatever.wav")

    assert resolved == [""]


def test_calibrate_noise_gate_sets_gate_to_1_5x_the_loudest_ambient_sample(qapp, monkeypatch):
    # Quick-win enhancement E5 (bug audit addendum 2026-09-23):
    # calibrate_noise_gate should report 1.5x the loudest sample it saw
    # during the capture window, not an average or the raw peak itself.
    FakeMic, _started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.start()
    started_events = []
    finished_values = []
    manager.calibration_started.connect(lambda: started_events.append(True))
    manager.calibration_finished.connect(finished_values.append)

    manager.calibrate_noise_gate(duration_s=0.02)
    assert started_events == [True]

    manager._handle_volume_from_source(0.01)
    manager._handle_volume_from_source(0.03)
    manager._handle_volume_from_source(0.02)

    assert _wait_until(qapp, lambda: len(finished_values) == 1)
    assert finished_values[0] == pytest.approx(0.03 * 1.5)
    manager.shutdown()


def test_calibrate_noise_gate_does_not_start_a_loop_afterward(qapp, monkeypatch):
    # Distinct from "Record 10s & loop" -- a one-shot measurement, not a
    # tuning aid to replay.
    FakeMic, _started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.start()
    manager.calibrate_noise_gate(duration_s=0.02)
    manager._handle_volume_from_source(0.01)

    assert _wait_until(qapp, lambda: manager.is_recording is False)
    assert manager.is_looping is False
    manager.shutdown()


def test_calibrate_noise_gate_is_a_noop_while_already_recording(qapp, monkeypatch):
    FakeMic, _started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.start()
    started_events = []
    manager.calibration_started.connect(lambda: started_events.append(True))

    manager.start_recording_and_loop(duration_s=1.0)
    manager.calibrate_noise_gate(duration_s=1.0)

    assert started_events == []  # calibration never started -- a loop recording is already in progress
    manager.shutdown()


def test_start_recording_and_loop_captures_fed_volumes_then_loops(qapp, monkeypatch):
    FakeMic, _started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.start()  # mic active by default
    manager.start_recording_and_loop(duration_s=0.05)
    assert manager.is_recording is True

    manager._handle_volume_from_source(0.2)
    manager._handle_volume_from_source(0.4)

    assert _wait_until(qapp, lambda: manager.is_recording is False)
    assert _wait_until(qapp, lambda: manager.is_looping is True)
    assert manager.last_recording is not None
    assert [v for _t, v in manager.last_recording.samples] == [0.2, 0.4]

    volumes = []
    manager.volume_measured.connect(volumes.append)
    assert _wait_until(qapp, lambda: len(volumes) >= 2)

    manager.shutdown()


def test_recording_started_and_finished_signals_fire(qapp, monkeypatch):
    FakeMic, _started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.start()
    started_events = []
    finished_events = []
    manager.recording_started.connect(lambda: started_events.append(True))
    manager.recording_finished.connect(lambda: finished_events.append(True))

    manager.start_recording_and_loop(duration_s=0.02)
    assert started_events == [True]
    assert _wait_until(qapp, lambda: finished_events == [True])
    manager.shutdown()


def test_stop_loop_restores_microphone_by_default(qapp, monkeypatch):
    FakeMic, started, stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.start()
    manager.start_recording_and_loop(duration_s=0.02)
    manager._handle_volume_from_source(0.3)
    assert _wait_until(qapp, lambda: manager.is_looping is True)

    started.clear()
    manager.stop_loop()
    assert manager.is_looping is False
    assert started == [True]  # switch_to_microphone restarted the mic
    manager.shutdown()


def test_stop_loop_resumes_a_file_that_was_playing_before_the_loop(qapp, monkeypatch):
    FakeFilePlayback, instances = _fake_file_playback_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.FilePlayback", FakeFilePlayback)

    manager = AudioManager(Config())
    manager.switch_to_file("/tmp/whatever.wav")
    manager.play_file()
    assert manager.is_file_playing is True

    manager.start_recording_and_loop(duration_s=0.02)
    manager._handle_volume_from_source(0.3)
    assert _wait_until(qapp, lambda: manager.is_looping is True)

    manager.stop_loop()

    assert manager.is_looping is False
    assert manager.is_file_playing is True


def test_stop_loop_does_not_auto_play_a_file_that_was_already_stopped(qapp, monkeypatch):
    # Regression, bug audit 2026-09-23 (#18): stop_loop used to always
    # call play_file() when restoring to "file" -- even if the file had
    # already finished or been manually stopped before the loop ever
    # started (e.g. "Record 10s & loop" clicked from a stopped state, to
    # tune against ambient silence). Same unrequested-auto-play surprise
    # commit afd2ed0 already fixed for Rewind -- a stopped file must
    # stay stopped.
    FakeFilePlayback, instances = _fake_file_playback_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.FilePlayback", FakeFilePlayback)
    FakeMic, _started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.switch_to_file("/tmp/whatever.wav")
    assert manager.is_file_playing is False  # source is "file", but nothing is playing

    manager.start_recording_and_loop(duration_s=0.02)
    manager._handle_volume_from_source(0.3)
    assert _wait_until(qapp, lambda: manager.is_looping is True)

    manager.stop_loop()

    assert manager.is_looping is False
    assert manager.config.audio.source == "file"
    assert manager.is_file_playing is False  # still stopped, not auto-played
    assert instances == []  # play_file() was never even called


def test_shutdown_abandons_the_microphone_but_switching_sources_does_not(qapp, monkeypatch):
    # Regression 2026-09-17, owner's report (real machine, OBS open
    # sharing the mic): PortAudio's own JACK hostapi hit a hard C-level
    # assertion inside Microphone.stop()'s stream.abort()/close() calls.
    # shutdown() is the one caller that's always immediately followed by
    # the whole process os._exit()ing (see __main__.py's on_quit()), so
    # it's the only one that should skip that teardown -- a mid-session
    # source switch must still release the device properly.
    FakeMic, _started, stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.start()
    manager.switch_to_file("/tmp/whatever.mp3")
    assert stopped == [False]  # normal switch -- real teardown, not abandoned

    stopped.clear()
    manager.shutdown()
    assert stopped == []  # mic was already stopped by the switch above -- nothing to shut down

    stopped.clear()
    manager2 = AudioManager(Config())
    manager2.start()  # fresh mic, running
    manager2.shutdown()
    assert stopped == [True]  # shutdown's own stop -- abandon=True


def test_calling_start_recording_and_loop_twice_is_a_noop_while_recording(qapp, monkeypatch):
    FakeMic, _started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.start()
    started_events = []
    manager.recording_started.connect(lambda: started_events.append(True))

    manager.start_recording_and_loop(duration_s=1.0)
    manager.start_recording_and_loop(duration_s=1.0)
    assert started_events == [True]
    manager.shutdown()


def test_switching_to_microphone_stops_an_active_loop(qapp, monkeypatch):
    FakeMic, _started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.start()
    manager.start_recording_and_loop(duration_s=0.02)
    manager._handle_volume_from_source(0.3)
    assert _wait_until(qapp, lambda: manager.is_looping is True)

    manager.switch_to_microphone()
    assert manager.is_looping is False
    manager.shutdown()


@needs_ffmpeg
def test_blocksize_and_samplerate_reflect_the_active_file(qapp, tmp_path):
    from unicorn_cloak.audio import DEFAULT_FILE_SAMPLERATE

    # FilePlayback asks ffmpeg to resample to a fixed target rate (see
    # audio.py) regardless of the source file's own native rate (8000
    # here, deliberately different) -- that's what makes frame_seconds
    # predictable downstream, so the *target* rate is what should show
    # up here, not the source file's.
    path = tmp_path / "tone.wav"
    make_test_wav(path, duration_s=2.0, samplerate=8000)

    manager = AudioManager(Config())
    manager.switch_to_file(str(path))
    manager.play_file()
    assert _wait_until(qapp, lambda: manager.is_file_playing)

    assert manager.samplerate == DEFAULT_FILE_SAMPLERATE
    manager.stop_file()


def test_gain_multiplies_the_raw_volume_before_it_is_emitted(qapp):
    config = Config()
    config.audio.gain = 2.0
    manager = AudioManager(config)
    volumes = []
    manager.volume_measured.connect(volumes.append)

    manager._handle_volume_from_source(0.1)

    assert volumes == [0.2]


def test_gain_of_one_leaves_the_volume_unchanged(qapp):
    config = Config()
    assert config.audio.gain == 1.0
    manager = AudioManager(config)
    volumes = []
    manager.volume_measured.connect(volumes.append)

    manager._handle_volume_from_source(0.35)

    assert volumes == [0.35]


def test_gain_is_clamped_to_the_zero_to_one_range(qapp):
    config = Config()
    config.audio.gain = 10.0
    manager = AudioManager(config)
    volumes = []
    manager.volume_measured.connect(volumes.append)

    manager._handle_volume_from_source(0.5)  # 0.5 * 10.0 = 5.0, clamped to 1.0

    assert volumes == [1.0]


# --- Desktop audio source (owner's request, 2026-09-23) ---------------------


def test_switch_to_desktop_with_no_device_chosen_does_not_start_capture(qapp, monkeypatch):
    # Regression, bug audit addendum 2026-09-23, D2: desktop_device
    # defaults to None, and resolve_input_device(None)'s own fallback is
    # the microphone on this owner's machine (no device here is
    # actually named "default") -- leaving Desktop Audio selected with
    # nothing ever chosen must not silently start capturing the mic.
    FakeMic, started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    config = Config()
    assert config.audio.desktop_device is None
    manager = AudioManager(config)
    errors = []
    manager.error_occurred.connect(errors.append)

    manager.switch_to_desktop()

    assert started == []  # no capture started at all
    assert manager._mic is None
    assert errors and "Desktop Audio" in errors[0]


def test_switch_to_desktop_starts_a_microphone_with_the_desktop_device(qapp, monkeypatch):
    devices = []
    strict_flags = []
    FakeMic, started, _stopped = _fake_microphone_class(devices=devices, strict_flags=strict_flags)
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    config = Config()
    config.audio.desktop_device = "Built-in Audio Analog Stereo"
    manager = AudioManager(config)

    manager.switch_to_desktop()

    assert manager.config.audio.source == "desktop"
    assert started == [True]
    assert devices == ["Built-in Audio Analog Stereo"]  # not config.audio.device
    assert strict_flags == [True]  # D2/D3: desktop audio never silently falls back


def test_switch_to_microphone_does_not_use_strict_device(qapp, monkeypatch):
    strict_flags = []
    FakeMic, started, _stopped = _fake_microphone_class(strict_flags=strict_flags)
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.switch_to_microphone()

    assert strict_flags == [False]  # a live mic still reasonably falls back to "first usable"


def test_switching_from_microphone_to_desktop_while_running_restarts_capture(qapp, monkeypatch):
    # Regression, bug audit addendum 2026-09-23, D1: microphone and
    # desktop audio are both backed by self._mic, so switch_to_desktop()
    # used to hit _start_microphone()'s own "already running" no-op
    # guard while a mic capture was live -- the dropdown showed Desktop
    # Audio, but the mouth kept following the mic. stop() must be called
    # with the *old* device before start() opens the *new* one.
    devices = []
    stopped = []
    FakeMic, started, _stopped_ignored = _fake_microphone_class(devices=devices, stopped=stopped)
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    config = Config()
    config.audio.device = "Blue Microphones Analog Stereo"
    config.audio.desktop_device = "Built-in Audio Analog Stereo"
    manager = AudioManager(config)
    manager.switch_to_microphone()
    assert devices == ["Blue Microphones Analog Stereo"]

    manager.switch_to_desktop()

    assert stopped == [False]  # the old (mic) capture was actually torn down
    assert devices == ["Blue Microphones Analog Stereo", "Built-in Audio Analog Stereo"]


def test_switching_from_desktop_to_microphone_while_running_restarts_capture(qapp, monkeypatch):
    devices = []
    stopped = []
    FakeMic, started, _stopped_ignored = _fake_microphone_class(devices=devices, stopped=stopped)
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    config = Config()
    config.audio.device = "Blue Microphones Analog Stereo"
    config.audio.desktop_device = "Built-in Audio Analog Stereo"
    manager = AudioManager(config)
    manager.switch_to_desktop()
    assert devices == ["Built-in Audio Analog Stereo"]

    manager.switch_to_microphone()

    assert stopped == [False]
    assert devices == ["Built-in Audio Analog Stereo", "Blue Microphones Analog Stereo"]


def test_start_at_startup_picks_up_a_persisted_desktop_source(qapp, monkeypatch):
    # start() used to only ever start a mic for "anything that isn't
    # file" -- still correct today, but this pins the desktop case
    # explicitly now that "anything that isn't file" is no longer just
    # "microphone".
    FakeMic, started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    config = Config()
    config.audio.source = "desktop"
    config.audio.desktop_device = "Built-in Audio Analog Stereo"  # D2: source alone isn't enough now
    manager = AudioManager(config)

    manager.start()

    assert started == [True]


def test_set_device_writes_to_the_field_matching_the_current_source(qapp, monkeypatch):
    FakeMic, _started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())

    manager.switch_to_microphone()
    manager.set_device("USB Mic")
    assert manager.config.audio.device == "USB Mic"
    assert manager.config.audio.desktop_device is None

    manager.switch_to_desktop()
    manager.set_device("Built-in Audio Analog Stereo")
    assert manager.config.audio.desktop_device == "Built-in Audio Analog Stereo"
    assert manager.config.audio.device == "USB Mic"  # untouched by the desktop change


def test_set_device_restarts_a_running_microphone_on_the_new_device(qapp, monkeypatch):
    devices = []
    FakeMic, started, stopped = _fake_microphone_class(devices=devices)
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.switch_to_microphone()
    assert devices == [None]

    manager.set_device("USB Mic")

    assert devices == [None, "USB Mic"]
    assert stopped == [False]  # the old device's mic was torn down, not abandoned
    assert started == [True, True]


def test_set_device_does_not_start_a_microphone_while_on_file_source(qapp, monkeypatch):
    FakeMic, started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.switch_to_file("/tmp/whatever.wav")

    manager.set_device("USB Mic")  # device combo is disabled on File in the UI, but be safe

    assert started == []  # no mic should ever start just from picking a device on File
    assert manager.config.audio.device == "USB Mic"  # still recorded for next time


def test_stop_loop_restores_desktop_audio_not_the_microphone(qapp, monkeypatch):
    # Regression: stop_loop() used to fall back to switch_to_microphone()
    # for any restore_source other than "file" -- correct back when
    # "microphone" was the only non-file source, but silently wrong now
    # that desktop audio is one too (would swap the owner from desktop
    # audio to their mic the moment they stopped tuning against a loop).
    FakeMic, started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.switch_to_desktop()
    manager.start_recording_and_loop(duration_s=0.02)
    manager._handle_volume_from_source(0.3)
    assert _wait_until(qapp, lambda: manager.is_looping is True)

    manager.stop_loop()

    assert manager.config.audio.source == "desktop"


def test_list_devices_delegates_to_audio_module(qapp, monkeypatch):
    monkeypatch.setattr(
        "unicorn_cloak.audio_manager.list_input_devices",
        lambda: ["Blue Microphones Analog Stereo", "Built-in Audio Analog Stereo"],
    )
    manager = AudioManager(Config())
    assert manager.list_devices() == [
        "Blue Microphones Analog Stereo", "Built-in Audio Analog Stereo",
    ]


# --- Loop playback does not double-apply gain (bug audit 2026-09-23, #6) ----


def test_loop_volume_handler_does_not_apply_gain_again(qapp):
    # _handle_volume_from_source (mic/file) applies gain once, at
    # capture time, and that already-gained value is what gets
    # recorded. Replaying a recording through that same handler would
    # apply gain a *second* time -- _handle_volume_from_loop is the
    # loop's own, separate callback specifically to avoid that.
    config = Config()
    config.audio.gain = 2.0
    manager = AudioManager(config)
    volumes = []
    manager.volume_measured.connect(volumes.append)

    manager._handle_volume_from_loop(0.1)  # already gained when it was recorded

    assert volumes == [0.1]  # not 0.2


def _fake_file_playback_class(instances=None):
    instances = instances if instances is not None else []

    class _FakeFilePlayback:
        def __init__(self, path, on_volume, on_error=None, on_finished=None):
            self.path = path
            self.on_finished = on_finished
            self.is_playing = True
            self.blocksize = 1024
            self.samplerate = 44100
            instances.append(self)

        def start(self):
            pass

        def stop(self):
            self.is_playing = False

    return _FakeFilePlayback, instances


# --- Loop/file playback never run at the same time (bug audit 2026-09-23, #11) --


def test_starting_a_loop_while_a_file_is_playing_emits_file_playback_stopped(qapp, monkeypatch):
    # Regression: _start_loop used to call the private _stop_file()
    # (no signal), so the Play/Stop button's label never refreshed off
    # "Stop" -- and a later Play click, reading that stale is_file_
    # playing==False, called play_file() instead of stop_file(),
    # starting a second real background thread alongside the loop.
    FakeFilePlayback, _instances = _fake_file_playback_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.FilePlayback", FakeFilePlayback)
    FakeMic, _started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.switch_to_file("/tmp/whatever.wav")
    manager.play_file()
    assert manager.is_file_playing is True

    stopped_events = []
    manager.file_playback_stopped.connect(lambda: stopped_events.append(True))

    manager.start_recording_and_loop(duration_s=0.02)
    manager._handle_volume_from_source(0.3)
    assert _wait_until(qapp, lambda: manager.is_looping is True)

    assert stopped_events == [True]
    assert manager.is_file_playing is False

    manager.shutdown()


def test_starting_a_loop_with_no_file_playing_does_not_emit_file_playback_stopped(qapp, monkeypatch):
    # The signal is specifically for interrupting a *file* -- starting a
    # loop from the mic (the common case) has nothing to report here.
    FakeMic, _started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.start()
    stopped_events = []
    manager.file_playback_stopped.connect(lambda: stopped_events.append(True))

    manager.start_recording_and_loop(duration_s=0.02)
    manager._handle_volume_from_source(0.3)
    assert _wait_until(qapp, lambda: manager.is_looping is True)

    assert stopped_events == []
    manager.shutdown()


def test_play_file_stops_an_active_loop(qapp, monkeypatch):
    # Regression: play_file() stopped the mic and any earlier file, but
    # never the loop -- Play could start a file alongside a
    # still-running loop, two background threads feeding the envelope
    # at once.
    FakeFilePlayback, _instances = _fake_file_playback_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.FilePlayback", FakeFilePlayback)
    FakeMic, _started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.start()
    manager.start_recording_and_loop(duration_s=0.02)
    manager._handle_volume_from_source(0.3)
    assert _wait_until(qapp, lambda: manager.is_looping is True)

    manager.config.audio.file_path = "/tmp/whatever.wav"
    manager.play_file()

    assert manager.is_looping is False
    assert manager.is_file_playing is True

    manager.shutdown()


def test_start_recording_and_loop_replays_at_the_original_gained_level(qapp, monkeypatch):
    # End-to-end: record a live value through the real gain-applying
    # path, then confirm the loop it starts replays that exact recorded
    # level, not a further-multiplied one.
    FakeMic, _started, _stopped = _fake_microphone_class()
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    config = Config()
    config.audio.gain = 2.0
    manager = AudioManager(config)
    manager.start()  # mic active by default
    manager.start_recording_and_loop(duration_s=0.05)

    manager._handle_volume_from_source(0.05)  # live raw input
    assert manager.last_capture_monotonic is not None

    assert _wait_until(qapp, lambda: manager.is_looping is True)
    assert [v for _t, v in manager.last_recording.samples] == [0.1]  # 0.05 * gain 2.0, recorded once

    volumes = []
    manager.volume_measured.connect(volumes.append)
    assert _wait_until(qapp, lambda: len(volumes) > 0)
    assert all(v == 0.1 for v in volumes)  # replayed as-is, not gained a second time (0.2)

    manager.shutdown()


def test_looping_reports_the_recorded_rate_not_a_hardcoded_default(qapp, monkeypatch):
    # Regression, bug audit 2026-09-23 (#17): neither _mic nor _file is
    # set while looping, so AudioManager.blocksize/samplerate used to
    # always fall back to a hardcoded 1024/44100 -- regardless of the
    # mic's real rate, throwing off update_speaking's frame_seconds
    # (attack/hold/release timing, in __main__.py) during loop playback.
    FakeMic, _started, _stopped = _fake_microphone_class(blocksize=512, samplerate=48000)
    monkeypatch.setattr("unicorn_cloak.audio_manager.Microphone", FakeMic)

    manager = AudioManager(Config())
    manager.start()
    assert manager.blocksize == 512
    assert manager.samplerate == 48000

    manager.start_recording_and_loop(duration_s=0.02)
    manager._handle_volume_from_source(0.3)
    assert _wait_until(qapp, lambda: manager.is_looping is True)

    # Mic is gone (looping stopped it) -- these must now come from the
    # recording itself, not the old 1024/44100 fallback.
    assert manager.blocksize == 512
    assert manager.samplerate == 48000

    manager.shutdown()
