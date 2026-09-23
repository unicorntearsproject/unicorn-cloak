"""
Owns whichever volume source is currently driving talk_level -- a live
`Microphone` or a decoded `FilePlayback` (see audio.py for both) -- and
marshals either one onto the Qt thread through the same pair of signals,
so the rest of the app (the envelope-follower math in `__main__.py`, and
the Settings window's Audio-source controls) doesn't need to know which
one is actually active. Switching sources, or clicking Play/Stop on a
file, always goes through this class -- SettingsWindow calls into it
directly, the same established pattern it already uses for
`render_window.set_background`/`set_zoom`, not a generic
settings-changed signal.

Threading: this class itself lives on the Qt thread and its public
methods (switch_to_microphone, switch_to_desktop, switch_to_file,
play_file, stop_file) are only ever called from there. The
`Microphone`/`FilePlayback` instances it
owns still run their own background threads exactly as documented in
audio.py -- volume_measured/error_occurred forward those threads'
callbacks straight through (Signal.emit() is safe to call from any
thread; it's the *receiving* slot that must be connected with an
explicit `Qt.ConnectionType.QueuedConnection`, same as before -- see
__main__.py). The one thing this class must never do is mutate its own
`_file`/`_mic` attributes from inside a callback that fired on a
background thread -- FilePlayback's `on_finished` is exactly that case,
which is why it goes through the private `_file_finished_from_bg_thread`
signal (itself connected with an explicit QueuedConnection below) rather
than clearing `self._file` directly: that keeps every actual state
mutation on the Qt thread, even the one triggered by a background
thread's own callback.

Envelope record/replay (2026-09-16): start_recording_and_loop() records
whatever's currently active (mic or file) for a fixed duration, then
automatically switches to looping the result (see audio.py's
EnvelopeRecorder/EnvelopeLoopPlayback). The "finish recording" trigger is
a QTimer.singleShot rather than EnvelopeRecorder noticing its own
deadline, specifically so it fires at exactly the requested duration on
the Qt thread even if the mic/file goes briefly silent right at the end
(EnvelopeRecorder.record() would otherwise just stop being *called*, not
proactively end itself) -- and because a QTimer created on the Qt thread
always fires on that same thread, recording_started/recording_finished
need no QueuedConnection at all, unlike volume_measured/error_occurred.
stop_loop() restores whichever source was active before recording
started, so tuning against the loop never leaves the mic silently off.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Qt, Signal

from .audio import (
    EnvelopeLoopPlayback,
    EnvelopeRecorder,
    EnvelopeRecording,
    FilePlayback,
    Microphone,
    list_input_devices,
)
from .config import Config


class AudioManager(QObject):
    volume_measured = Signal(float)
    error_occurred = Signal(str)
    # Fires when file playback stops for *any* reason (reached the end,
    # a decode error, or switching away from it) -- Settings listens so
    # its Play/Stop button can reset itself without polling.
    file_playback_stopped = Signal()
    # Fire around start_recording_and_loop()'s 10-second capture window --
    # Settings uses these to drive its "Recording... Ns" button label.
    # Both fire on the Qt thread already (see module docstring), so no
    # QueuedConnection is needed for either.
    recording_started = Signal()
    recording_finished = Signal()
    # Fire around calibrate_noise_gate()'s own capture window -- separate
    # from recording_started/recording_finished (used by "Record 10s &
    # loop") since the two features drive different buttons in the
    # Control Panel; sharing one pair of signals would make the loop
    # button relabel itself "Recording..." while calibration runs, and
    # vice versa. Both fire on the Qt thread already, same as
    # recording_started/recording_finished (see that pair's own comment).
    calibration_started = Signal()
    # Carries the newly-computed noise_gate value -- quick-win
    # enhancement E5 (bug audit addendum 2026-09-23). The Control Panel
    # writes it into config.audio.noise_gate itself (via the same
    # spin-box setter every other field already uses, so it persists and
    # displays consistently), rather than this class reaching into
    # config directly.
    calibration_finished = Signal(float)
    # Fires with the real device name Microphone actually opened, once a
    # stream connects -- quick-win enhancement E2 (bug audit addendum
    # 2026-09-23). Fires from Microphone's own background thread, same as
    # volume_measured/error_occurred (see this class's own docstring for
    # why that's safe -- Signal.emit() itself is thread-safe, only the
    # receiving slot needs a QueuedConnection).
    device_resolved = Signal(str)
    # Timeline/scrubber feature (owner's request, 2026-09-23): fire from
    # FilePlayback's own background thread, same threading contract as
    # volume_measured/error_occurred/device_resolved above (Signal.emit()
    # itself is thread-safe; only the receiving slot needs a
    # QueuedConnection). position_measured fires roughly once per decoded
    # block with elapsed seconds; duration_measured fires once per
    # play_file() call, only if the total duration could be determined
    # (see audio.probe_duration -- ffprobe is a nice-to-have, not a hard
    # requirement, so this may simply never fire for a given file).
    position_measured = Signal(float)
    duration_measured = Signal(float)
    # Private/internal: see the module and class docstrings for why
    # FilePlayback's on_finished (a background-thread callback) routes
    # through this instead of touching self._file directly. Carries the
    # FilePlayback instance that actually finished (not just a bare
    # trigger) -- see _handle_file_finished for why: a background
    # thread's stop() doesn't join (see FilePlayback.stop's own
    # docstring), so its finish can still be in flight after a Rewind or
    # a quick Stop-then-Play has already moved self._file on to a newer
    # instance; without the identity check this stale callback would
    # wrongly null out and "stop" the file that's actually still
    # playing, orphaning the real one with nothing left able to reach it
    # (owner's report, 2026-09-20: "hitting stop sometimes doesn't stop
    # the character from talking").
    _file_finished_from_bg_thread = Signal(object)

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self._mic: Microphone | None = None
        self._file: FilePlayback | None = None
        self._loop: EnvelopeLoopPlayback | None = None
        self._recorder: EnvelopeRecorder | None = None
        self.last_recording: EnvelopeRecording | None = None
        self._restore_source: str = "microphone"
        self._restore_file_path: str | None = None
        # Whether the file was actually *playing* (not just selected as
        # the source) when start_recording_and_loop was called -- bug
        # audit 2026-09-23, #18: stop_loop used to always call
        # play_file() when restoring to "file", even if the file had
        # already finished or been manually stopped before the loop
        # ever started -- the same unrequested-auto-play surprise
        # commit afd2ed0 already fixed for Rewind. A stopped file stays
        # stopped; stop_loop only resumes playback if it was actually
        # running.
        self._restore_was_playing_file: bool = False
        # Set by _handle_volume_from_source right before every emit --
        # __main__.py's on_volume_on_qt_thread reads this to measure how
        # long the hop from "audio block captured" to "Qt thread
        # processed it" actually took (Settings' level meter, Milestone
        # request 2026-09-16). A plain float set from the background
        # thread and read from the Qt thread -- safe under CPython's GIL
        # for a single attribute (no torn reads/writes), unlike the
        # class of bug _handle_file_finished avoids below, which was
        # about mutating self._file (an object reference other methods
        # branch on), not reading a timestamp for display.
        self.last_capture_monotonic: float | None = None
        self._file_finished_from_bg_thread.connect(
            self._handle_file_finished, Qt.ConnectionType.QueuedConnection
        )

    @property
    def blocksize(self) -> int:
        active = self._file or self._mic
        if active is not None:
            return active.blocksize
        # Falls back to the loop's own recorded rate, not straight to
        # the hardcoded default -- bug audit 2026-09-23, #17: neither
        # _mic nor _file is set while looping, so this used to always
        # fall through to a fixed 1024/44100 regardless of what the
        # recording actually captured at, throwing off update_speaking's
        # frame_seconds (attack/hold/release timing) during loop
        # playback. See EnvelopeRecording's own docstring.
        if self._loop is not None:
            return self._loop.recording.blocksize
        return 1024

    @property
    def samplerate(self) -> int:
        active = self._file or self._mic
        if active is not None:
            return active.samplerate
        if self._loop is not None:
            return self._loop.recording.samplerate
        return 44100

    @property
    def is_file_playing(self) -> bool:
        return self._file is not None and self._file.is_playing

    @property
    def is_recording(self) -> bool:
        return self._recorder is not None and self._recorder.is_recording

    @property
    def is_looping(self) -> bool:
        return self._loop is not None and self._loop.is_playing

    def start(self) -> None:
        """Called once at app startup. Picks up wherever config.audio.source
        already points -- but never auto-plays a file even if that's
        what a previous session left selected: starting to burn through
        a recording the instant the app opens would be a bad surprise.
        Playback is always an explicit play_file() call (a Play click).
        "microphone" and "desktop" both start capture immediately though
        -- neither one has an equivalent "don't auto-start" concern, they
        just read whatever's live."""
        if self.config.audio.source in ("microphone", "desktop"):
            self._start_microphone()

    def switch_to_microphone(self) -> None:
        self.config.audio.source = "microphone"
        # Stops any running capture first, unconditionally -- bug audit
        # addendum 2026-09-23, D1: microphone and desktop audio are both
        # backed by self._mic, so switching between them used to hit
        # _start_microphone()'s own "already running, no-op" guard and
        # silently keep capturing the *old* device -- the dropdown
        # showed the new source, but the mouth kept following whichever
        # one was already open.
        self._stop_microphone()
        self._stop_file()
        self._stop_loop()
        self._start_microphone()

    def switch_to_desktop(self) -> None:
        """Drives the mouth from whatever's actually playing out the
        speakers (game audio, a video, music) instead of a mic --
        owner's request, 2026-09-23. Under the hood this is the exact
        same audio.Microphone capture path as switch_to_microphone(),
        just pointed at config.audio.desktop_device (a separately
        remembered device hint, chosen from the device dropdown in
        control_panel_window.py -- see that field's own comment in
        config.py for why there's no automatic detection here)."""
        self.config.audio.source = "desktop"
        self._stop_microphone()  # see switch_to_microphone's own comment, bug audit addendum D1
        self._stop_file()
        self._stop_loop()
        self._start_microphone()

    def set_device(self, device: str | None) -> None:
        """Changes which capture device backs whichever of microphone/
        desktop is currently selected, live -- restarts capture on the
        new device immediately if one of those is actually running right
        now. Device dropdown's onChange in control_panel_window.py is
        the only caller; a "file" source has nothing here to change."""
        if self.config.audio.source == "desktop":
            self.config.audio.desktop_device = device
        else:
            self.config.audio.device = device
        if self._mic is not None:
            self._stop_microphone()
            self._start_microphone()

    def list_devices(self) -> list[str]:
        return list_input_devices()

    def switch_to_file(self, path: str | None = None) -> None:
        """Records the chosen file (if given) and stops the mic, but does
        not start decoding -- see play_file(). `path` is optional: call
        with none when the owner has only just picked "File" as the
        source and hasn't chosen a specific file yet -- the mic should
        stop driving the mouth immediately regardless, not keep running
        until a file is actually chosen (found while testing the
        Settings UI, 2026-09-16: selecting "File" alone did nothing if
        no file was already set, silently leaving the mic in control)."""
        self.config.audio.source = "file"
        if path is not None:
            self.config.audio.file_path = path
        self._stop_microphone()
        self._stop_loop()

    def play_file(self, start_offset_s: float = 0.0) -> None:
        """start_offset_s: where in the file to start decoding from --
        0.0 (the default) for a normal Play/Rewind click. Every other
        caller (Play, Rewind, stop_loop's restore-was-playing-file path)
        omits it and gets the existing from-the-beginning behavior
        unchanged; only seek_file passes a nonzero value."""
        if not self.config.audio.file_path:
            return
        self._stop_microphone()
        self._stop_file()
        # Also the loop -- bug audit 2026-09-23, #11: without this, Play
        # could start a *second*, real background thread feeding the
        # envelope alongside an already-running loop (reachable via the
        # Play/Stop button's own stale-label bug this same finding fixes
        # below, in _start_loop) -- two sources driving talk_level at
        # once, neither one in control.
        self._stop_loop()
        self._file = FilePlayback(
            self.config.audio.file_path,
            on_volume=self._handle_volume_from_source,
            on_error=self.error_occurred.emit,
            on_finished=self._file_finished_from_bg_thread.emit,
            on_position=self.position_measured.emit,
            on_duration=self.duration_measured.emit,
            start_offset_s=start_offset_s,
        )
        self._file.start()

    def seek_file(self, position_s: float) -> None:
        """Jumps file playback to `position_s` seconds in -- the Control
        Panel's timeline/scrubber (owner's request, 2026-09-23). Always
        (re)starts playback there, even if the file was stopped: unlike
        Rewind (a no-op while stopped, since 0:00 is already where the
        next Play would start anyway), seeking to an arbitrary position
        while stopped *does* have something meaningful to do -- start
        playing from wherever was clicked, same as scrubbing in an
        ordinary media player. A no-op if the file source isn't active or
        no file is chosen -- nothing to seek."""
        if self.config.audio.source != "file" or not self.config.audio.file_path:
            return
        self.play_file(start_offset_s=max(0.0, position_s))

    def stop_file(self) -> None:
        self._stop_file()
        self.file_playback_stopped.emit()

    def start_recording_and_loop(self, duration_s: float = 10.0) -> None:
        """Records `duration_s` of whatever's currently active (mic or
        file), then automatically starts looping it once the window
        closes -- see the module docstring for why a QTimer, not the
        recorder itself, decides when that window ends."""
        if self.is_recording:
            return
        self._restore_source = self.config.audio.source
        self._restore_file_path = self.config.audio.file_path
        self._restore_was_playing_file = self.is_file_playing
        # blocksize/samplerate read here, not left to EnvelopeRecorder's
        # own hardcoded defaults -- self._mic/self._file is still the
        # one actually driving self.blocksize/samplerate at this exact
        # point, before _start_loop (in _finish_recording, below) stops
        # it. See EnvelopeRecording's own docstring (bug audit
        # 2026-09-23, #17).
        self._recorder = EnvelopeRecorder(
            max_duration_s=duration_s, blocksize=self.blocksize, samplerate=self.samplerate
        )
        self._recorder.start()
        self.recording_started.emit()
        QTimer.singleShot(int(duration_s * 1000), self._finish_recording)

    def calibrate_noise_gate(self, duration_s: float = 3.0) -> None:
        """Samples `duration_s` of whatever's currently active (mic,
        desktop audio, or file -- the owner is expected to stay quiet),
        then sets Noise gate to 1.5x the loudest sample measured -- a
        safety margin above real ambient noise instead of a guess.
        Quick-win enhancement E5 (bug audit addendum 2026-09-23). Reuses
        EnvelopeRecorder exactly like start_recording_and_loop does
        (mutually exclusive with it via the same is_recording guard --
        this class only ever has one EnvelopeRecorder capturing at a
        time), just without the loop-playback step afterward: this is a
        one-shot measurement to apply once, not a tuning aid to replay."""
        if self.is_recording:
            return
        self._recorder = EnvelopeRecorder(
            max_duration_s=duration_s, blocksize=self.blocksize, samplerate=self.samplerate
        )
        self._recorder.start()
        self.calibration_started.emit()
        QTimer.singleShot(int(duration_s * 1000), self._finish_calibration)

    def _finish_calibration(self) -> None:
        if self._recorder is None:
            return
        recording = self._recorder.finish()
        self._recorder = None
        ambient_peak = max((value for _t, value in recording.samples), default=0.0)
        self.calibration_finished.emit(ambient_peak * 1.5)

    def stop_loop(self) -> None:
        """Stops looping and restores whichever source (mic, desktop
        audio, or file) was active before start_recording_and_loop() was
        called, so tuning against the loop never leaves nothing driving
        the mouth -- and never silently swaps desktop audio back to the
        mic either, now that there are two device-backed sources."""
        self._stop_loop()
        if self._restore_source == "file" and self._restore_file_path:
            self.switch_to_file(self._restore_file_path)
            # Only if it was actually playing before -- see
            # _restore_was_playing_file's own comment (bug audit
            # 2026-09-23, #18).
            if self._restore_was_playing_file:
                self.play_file()
        elif self._restore_source == "desktop":
            self.switch_to_desktop()
        else:
            self.switch_to_microphone()

    def shutdown(self) -> None:
        # abandon=True: see Microphone.stop()'s own docstring -- only
        # safe here because __main__.py's on_quit() (the only caller of
        # this method) is always immediately followed by the whole
        # process os._exit()ing, never by the app continuing to run.
        self._stop_microphone(abandon=True)
        self._stop_file()
        self._stop_loop()

    def _finish_recording(self) -> None:
        if self._recorder is None:
            return
        self.last_recording = self._recorder.finish()
        self._recorder = None
        # _start_loop() first, emit second: recording_finished is a
        # direct (non-queued) connection, so a listener's slot runs
        # synchronously inside this emit() call -- is_looping needs to
        # already be true by then, or a listener reading it (Settings'
        # button-text update) would see the pre-loop state.
        self._start_loop()
        self.recording_finished.emit()

    def _start_loop(self) -> None:
        if self.last_recording is None or not self.last_recording.samples:
            return
        self._stop_microphone()
        was_playing_a_file = self._file is not None
        self._stop_file()
        if was_playing_a_file:
            # _stop_file() (the private helper) doesn't emit
            # file_playback_stopped -- bug audit 2026-09-23, #11: a
            # loop starting while a file was playing (e.g. "Record 10s &
            # loop" clicked mid-playback) silently interrupted it with
            # no signal, so the Play/Stop button's label never refreshed
            # (stuck on "Stop") and, worse, a later Play click -- reading
            # that same now-stale is_file_playing==False -- called
            # play_file() instead of stop_file(), starting a *second*
            # real background thread feeding the envelope alongside the
            # still-running loop. Emitting this here is exactly what
            # stop_file() (the public method) itself does; only the
            # trigger differs.
            self.file_playback_stopped.emit()
        self._stop_loop()
        self._loop = EnvelopeLoopPlayback(
            self.last_recording,
            on_volume=self._handle_volume_from_loop,
            on_error=self.error_occurred.emit,
        )
        self._loop.start()

    def _stop_loop(self) -> None:
        if self._loop is not None:
            self._loop.stop()
            self._loop = None

    def _handle_file_finished(self, finished_file: FilePlayback) -> None:
        # Runs on the Qt thread (see __init__'s QueuedConnection) even
        # though it was triggered by FilePlayback's background thread
        # reaching end-of-file or a decode error. Identity check against
        # finished_file (not a bare "clear self._file"): stop() doesn't
        # wait for the background thread to actually exit, so this can
        # still fire after self._file has already moved on to a newer
        # instance (Rewind, or a fast Stop-then-Play) -- treating that
        # late callback as "the current file stopped" would wrongly
        # close the mouth while the real, current file keeps playing,
        # *and* null out the only reference able to stop it.
        if self._file is not finished_file:
            return
        self._file = None
        self.file_playback_stopped.emit()

    def _start_microphone(self) -> None:
        # Named for the common case, but this is also desktop-audio's own
        # capture path -- audio.Microphone doesn't care what's on the
        # other end of the device index, only which config field
        # supplies the hint differs (see switch_to_desktop/set_device).
        if self._mic is not None:
            return
        is_desktop = self.config.audio.source == "desktop"
        device = self.config.audio.desktop_device if is_desktop else self.config.audio.device
        if is_desktop and not device:
            # Never silently falls back to "whatever's first usable
            # device" for desktop audio -- bug audit addendum
            # 2026-09-23, D2: resolve_input_device(None)'s own fallback
            # is the *microphone* on this owner's machine (no device
            # here is actually named "default"), so leaving Desktop
            # Audio selected with no device ever chosen would silently
            # start lip-syncing to the owner's voice instead. Reported
            # the same way an OBS-not-configured-yet state already is
            # elsewhere in this app -- declines to even attempt a
            # connection, rather than attempting (and silently
            # succeeding at) the wrong one.
            self.error_occurred.emit(
                "Desktop Audio: no device chosen yet -- pick one from the Device dropdown."
            )
            return
        self._mic = Microphone(
            on_volume=self._handle_volume_from_source,
            device=device,
            on_error=self.error_occurred.emit,
            # strict_device: see audio.resolve_input_device's own
            # docstring (bug audit addendum D2/D3) -- an unmatched or
            # vanished desktop device must report and keep retrying,
            # never silently fall back to an unrelated device either.
            strict_device=is_desktop,
            on_device_resolved=self.device_resolved.emit,
        )
        self._mic.start()

    def _stop_microphone(self, *, abandon: bool = False) -> None:
        if self._mic is not None:
            self._mic.stop(abandon=abandon)
            self._mic = None
            # Clears the "Now capturing: …" label -- E2's whole point is
            # showing what's *actually* open, and nothing is once this
            # returns (a stale name left showing after Stop/switch would
            # be exactly the kind of misleading-at-a-glance state E2 was
            # meant to fix).
            self.device_resolved.emit("")

    def _stop_file(self) -> None:
        if self._file is not None:
            self._file.stop()
            self._file = None

    def _handle_volume_from_source(self, value: float) -> None:
        # Called from Microphone's, FilePlayback's, or
        # EnvelopeLoopPlayback's own background thread -- see
        # last_capture_monotonic's own comment in __init__ for why the
        # plain-attribute write here is fine. EnvelopeRecorder.record()
        # is likewise a plain, lock-free append that only ever runs
        # while is_recording is true, so feeding it here (rather than
        # only from the mic/file paths specifically) is what lets
        # start_recording_and_loop() capture whichever source -- mic or
        # file -- was actually active when it was called.
        #
        # config.audio.gain is applied here, once, at the earliest point
        # in the pipeline (added 2026-09-16 -- the owner's mic was
        # pegging the thresholds regardless of what the OS mixer showed
        # for it) -- everything downstream (the level meter, the
        # recorder, update_speaking's thresholds) sees the already-scaled
        # value, exactly as if the mic itself were that much louder or
        # quieter. Clamped to [0, 1] since RMS values above 1.0 aren't
        # meaningful and would just make the level meter's auto-scaling
        # (max(wide_open * 1.5, envelope)) chase an ever-growing number.
        value = min(max(value * self.config.audio.gain, 0.0), 1.0)
        self.last_capture_monotonic = time.monotonic()
        if self._recorder is not None:
            self._recorder.record(value)
        self.volume_measured.emit(value)

    def _handle_volume_from_loop(self, value: float) -> None:
        """EnvelopeLoopPlayback's own on_volume callback -- deliberately
        NOT _handle_volume_from_source. The recorded samples it's
        replaying already had config.audio.gain applied once, at the
        moment they were originally captured (see that method's own
        comment) -- routing loop playback back through the
        gain-applying handler would apply gain a *second* time on every
        replayed sample. Bug audit 2026-09-23, #6: at gain=2.0, a live
        0.05 input showed 0.1, but the loop -- whose whole purpose is
        tuning thresholds against a realistic, repeatable stand-in for
        live speech -- replayed 0.2, silently doubling the effective
        gain for anyone whose Sensitivity isn't exactly 1.0. Still feeds
        the recorder/last_capture_monotonic/volume_measured exactly like
        _handle_volume_from_source, just without the second gain step."""
        value = min(max(value, 0.0), 1.0)  # already gained -- just re-clamp defensively
        self.last_capture_monotonic = time.monotonic()
        if self._recorder is not None:
            self._recorder.record(value)
        self.volume_measured.emit(value)
