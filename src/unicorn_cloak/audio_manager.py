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
methods (switch_to_microphone, switch_to_file, play_file, stop_file) are
only ever called from there. The `Microphone`/`FilePlayback` instances it
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

from .audio import EnvelopeLoopPlayback, EnvelopeRecorder, EnvelopeRecording, FilePlayback, Microphone
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
    # Private/internal: see the module and class docstrings for why
    # FilePlayback's on_finished (a background-thread callback) routes
    # through this instead of touching self._file directly.
    _file_finished_from_bg_thread = Signal()

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
        return active.blocksize if active is not None else 1024

    @property
    def samplerate(self) -> int:
        active = self._file or self._mic
        return active.samplerate if active is not None else 44100

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
        Playback is always an explicit play_file() call (a Play click)."""
        if self.config.audio.source != "file":
            self._start_microphone()

    def switch_to_microphone(self) -> None:
        self.config.audio.source = "microphone"
        self._stop_file()
        self._stop_loop()
        self._start_microphone()

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

    def play_file(self) -> None:
        if not self.config.audio.file_path:
            return
        self._stop_microphone()
        self._stop_file()
        self._file = FilePlayback(
            self.config.audio.file_path,
            on_volume=self._handle_volume_from_source,
            on_error=self.error_occurred.emit,
            on_finished=self._file_finished_from_bg_thread.emit,
        )
        self._file.start()

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
        self._recorder = EnvelopeRecorder(max_duration_s=duration_s)
        self._recorder.start()
        self.recording_started.emit()
        QTimer.singleShot(int(duration_s * 1000), self._finish_recording)

    def stop_loop(self) -> None:
        """Stops looping and restores whichever source (mic or file) was
        active before start_recording_and_loop() was called, so tuning
        against the loop never leaves nothing driving the mouth."""
        self._stop_loop()
        if self._restore_source == "file" and self._restore_file_path:
            self.switch_to_file(self._restore_file_path)
            self.play_file()
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
        self._stop_file()
        self._stop_loop()
        self._loop = EnvelopeLoopPlayback(
            self.last_recording,
            on_volume=self._handle_volume_from_source,
            on_error=self.error_occurred.emit,
        )
        self._loop.start()

    def _stop_loop(self) -> None:
        if self._loop is not None:
            self._loop.stop()
            self._loop = None

    def _handle_file_finished(self) -> None:
        # Runs on the Qt thread (see __init__'s QueuedConnection) even
        # though it was triggered by FilePlayback's background thread
        # reaching end-of-file or a decode error.
        self._file = None
        self.file_playback_stopped.emit()

    def _start_microphone(self) -> None:
        if self._mic is not None:
            return
        self._mic = Microphone(
            on_volume=self._handle_volume_from_source,
            device=self.config.audio.device,
            on_error=self.error_occurred.emit,
        )
        self._mic.start()

    def _stop_microphone(self, *, abandon: bool = False) -> None:
        if self._mic is not None:
            self._mic.stop(abandon=abandon)
            self._mic = None

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
