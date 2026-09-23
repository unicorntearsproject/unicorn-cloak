"""
Load the real default avatar, show it in the Render Window, drive it from
the live microphone (or a decoded file -- see audio_manager.py), and open
the single Control Panel window (merged Editor+Settings, 2026-09-17 --
see control_panel_window.py's own docstring). Escape (or the Control
Panel's Quit button) quits the whole app, always with a confirmation, and
an extra warning if the avatar has unsaved changes.
"""
from __future__ import annotations

import contextlib
import os
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from . import theme
from .audio import SpeakingState, update_speaking
from .audio_manager import AudioManager
from .avatar_io import load_avatar_with_upgrade
from .config import load_state, save_state
from .control_panel_window import ControlPanelWindow
from .hot_reload import AssetWatcher
from .obs_link_manager import ObsLinkManager
from .render import APP_ID, WINDOW_TITLE, RenderWindow


@contextlib.contextmanager
def _suppressed_native_stderr():
    """Silences whatever's written to the process's real stderr file
    descriptor for the duration of the `with` block -- not just Python's
    own `sys.stderr` object, since the noise this hides is written
    directly by native code during Qt's platform-plugin loading,
    bypassing Python's stderr entirely (observed on the owner's machine,
    2026-09-17: a system libssh/libfido2 ABI-mismatch dlopen warning and
    a broken GIO module from an unrelated snap-installed app -- neither
    has anything to do with this app's own code, and neither is
    reachable from Python to filter more surgically). Scoped tightly
    around `QApplication(...)` construction only, not the whole process,
    so a real crash afterward still reaches the terminal."""
    stderr_fd = sys.stderr.fileno()
    saved_fd = os.dup(stderr_fd)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull_fd, stderr_fd)
        yield
    finally:
        os.dup2(saved_fd, stderr_fd)
        os.close(devnull_fd)
        os.close(saved_fd)


def reset_speaking_state_and_close_mouth(window: RenderWindow) -> SpeakingState:
    """Forces the mouth closed and hands back a fresh SpeakingState for
    the caller to keep using, bypassing update_speaking's own attack/
    hold/release envelope entirely. Module-level (not a closure inside
    main()) so it's actually testable -- see test___main__.py.

    Owner's report, 2026-09-20: "the audio file stops but the mouth
    keeps moving." update_speaking's envelope only advances when it's
    actually called -- a live mic keeps calling it every block even
    during silence, so it decays smoothly all the way to quiet on its
    own. FilePlayback's very last call (on_volume(0.0), in its own
    finally block) is one isolated call, not the start of a steady
    stream: it only nudges the envelope a single exponential step toward
    0, and nothing ever calls update_speaking again afterward to finish
    the job -- leaving talk_level stuck at whatever nonzero level it
    last reached, with the render timer's own independent mouth-wobble/
    variant-alternation animation (which runs regardless of audio
    activity) visibly animating that stuck level forever. This is the
    same "bypass the envelope entirely" approach set_muted/effective_
    talk_level already uses for OBS mute -- called whenever
    AudioManager.file_playback_stopped fires, which covers every way
    file playback can stop: a manual Stop, reaching the end of the
    file, or a decode error."""
    window.set_talk_level(0)
    window.set_envelope(0.0)
    return SpeakingState()


def handle_avatar_file_changed(rig, config, control_panel, asset_watcher) -> bool:
    """Reloads config.avatar_path into `rig` in place and refreshes the
    Control Panel/Render Window to match. Module-level (not a closure
    inside main()) so it's actually testable -- see test___main__.py,
    same reasoning as reset_speaking_state_and_close_mouth above.
    Returns True on a successful reload, False if the file failed to
    load (already printed to the console -- there's no dialog for this
    today, see the bug audit's finding #16).

    keep_active_costume=True on the replace_contents_from call below --
    see that method's own docstring: active_costume is never actually
    part of a file's persisted content, so copying it here (always 0)
    used to silently reset the live costume slot on every reload,
    including the app's own Save triggering its own hot reload (bug
    audit 2026-09-23, #3) via the same watcher this function is wired
    to."""
    try:
        reloaded = load_avatar_with_upgrade(config.avatar_path, parent=control_panel)
    except Exception as exc:
        print(f"[hot-reload] failed to reload {config.avatar_path!r}: {exc}", flush=True)
        return False
    rig.replace_contents_from(reloaded, keep_active_costume=True)
    control_panel.refresh_after_external_change()
    # The reload may have added/removed/renamed sprites -- re-point the
    # sprite watch at whatever the file now actually contains.
    asset_watcher.watch_sprite_files([s.path for s in rig.sprites])
    print(f"[hot-reload] avatar file changed, reloaded ({len(rig.sprites)} sprites)", flush=True)
    return True


def main() -> int:
    # Owner's request, 2026-09-17: "hide the noise unless debug mode is
    # set" -- UNICORN_CLOAK_DEBUG_AUDIO (see on_volume_on_qt_thread below)
    # is its own, separate, narrower flag for live audio-level debug
    # prints; this one is general, and only affects whether *unrelated*
    # startup noise is hidden, never a real error this app raises itself.
    debug = os.environ.get("UNICORN_CLOAK_DEBUG") == "1"
    if not debug:
        # qt.qpa.services' "Failed to register with host portal" warning
        # -- the already-investigated, already-accepted GNOME/
        # xdg-desktop-portal limitation documented in docs/PLAN.md (OBS
        # re-prompting the capture picker on every relaunch regardless of
        # app_id), not an error this app can act on. QT_LOGGING_RULES is
        # read once, early, so it must be set before QApplication exists
        # to reliably cover a category's very first use.
        os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

    if debug:
        app = QApplication(sys.argv)
    else:
        with _suppressed_native_stderr():
            app = QApplication(sys.argv)
    # Wayland has no window title/WM_CLASS the way X11 does -- app
    # identity for window-manager and portal purposes (including
    # xdg-desktop-portal's ScreenCast restore-token matching, which is
    # what lets OBS skip the picker on relaunch) is the Wayland "app_id",
    # which Qt derives from desktopFileName() if set, or otherwise falls
    # back to something derived from argv[0] (observed: the literal
    # string "-c" when run via `python -c`) -- not stable across launch
    # methods. Setting both explicitly, once, is what makes "no re-pick
    # on relaunch" achievable at all; see docs/PLAN.md's cutover check for the
    # actual verification (this alone doesn't prove the portal honors it).
    app.setApplicationName(WINDOW_TITLE)
    app.setDesktopFileName(APP_ID)
    # v2 styling (Unicorn Tears/Viz design system) -- applies to the
    # Control Panel/Help windows only, never the Render Window (see
    # theme.py's module docstring for exactly why that's safe).
    theme.apply(app)
    config = load_state()

    rig = load_avatar_with_upgrade(config.avatar_path)
    window = RenderWindow(
        rig,
        config.motion,
        hotkeys_config=config.hotkeys,
        window_size=(config.window.width, config.window.height),
        background=config.window.background,
        background_image_path=config.window.background_image_path,
        background_video_path=config.window.background_video_path,
        zoom=rig.zoom,
    )
    window.show()

    audio_manager = AudioManager(config)
    obs_link_manager = ObsLinkManager(config)
    # Created before ControlPanelWindow, not after -- passed in so Save/
    # Save As can call note_own_write() and suppress the reload their
    # own write would otherwise trigger (bug audit 2026-09-23, #3; see
    # hot_reload.py's own docstring).
    asset_watcher = AssetWatcher()

    control_panel = ControlPanelWindow(
        rig, config, window,
        audio_manager=audio_manager, obs_link_manager=obs_link_manager, asset_watcher=asset_watcher,
    )
    control_panel.show()

    # Both gated through the Control Panel's own confirm-and-maybe-save
    # flow -- see render.RenderWindow.closeEvent/mouseDoubleClickEvent
    # and control_panel_window.py's confirm_and_quit().
    window.on_quit_requested = control_panel.confirm_and_quit

    def on_avatar_double_clicked() -> None:
        control_panel.show()
        control_panel.raise_()
        control_panel.activateWindow()

    window.on_avatar_double_clicked = on_avatar_double_clicked

    asset_watcher.watch_avatar_file(config.avatar_path)
    asset_watcher.watch_sprite_files([s.path for s in rig.sprites])

    def on_avatar_file_changed_on_qt_thread() -> None:
        handle_avatar_file_changed(rig, config, control_panel, asset_watcher)

    def on_sprite_file_changed_on_qt_thread(path: str) -> None:
        sprite = next((s for s in rig.sprites if s.path == path), None)
        if sprite is None:
            return
        try:
            with open(path, "rb") as f:
                sprite.image_data = f.read()
        except OSError as exc:
            print(f"[hot-reload] failed to reload {path!r}: {exc}", flush=True)
            return
        control_panel.refresh_after_external_change()
        print(f"[hot-reload] sprite image changed: {path}", flush=True)

    # QFileSystemWatcher's signals already fire on the Qt thread (it's a
    # QObject created here, on the main thread) -- no QueuedConnection
    # needed, unlike audio_manager's/obs_link_manager's background-thread
    # callbacks above.
    asset_watcher.avatar_file_changed.connect(on_avatar_file_changed_on_qt_thread)
    asset_watcher.sprite_file_changed.connect(on_sprite_file_changed_on_qt_thread)

    speaking_state = SpeakingState()

    debug_audio = os.environ.get("UNICORN_CLOAK_DEBUG_AUDIO") == "1"
    last_print = 0.0

    def on_error_on_qt_thread(message: str) -> None:
        print(f"[audio] {message}", flush=True)

    def on_obs_error_on_qt_thread(message: str) -> None:
        print(f"[obs] {message}", flush=True)

    def on_mute_changed_on_qt_thread(muted: bool) -> None:
        window.set_muted(muted)

    def on_file_playback_stopped_on_qt_thread() -> None:
        nonlocal speaking_state
        speaking_state = reset_speaking_state_and_close_mouth(window)

    def on_volume_on_qt_thread(volume: float) -> None:
        nonlocal speaking_state, last_print
        speaking_state = update_speaking(
            speaking_state,
            volume,
            noise_gate=config.audio.noise_gate,
            mild_open=config.audio.mild_open,
            mild_close=config.audio.mild_close,
            wide_open=config.audio.wide_open,
            wide_close=config.audio.wide_close,
            attack_ms=config.audio.attack_ms,
            hold_ms=config.audio.hold_ms,
            release_ms=config.audio.release_ms,
            # Not hardcoded: whichever source is actually active (mic or
            # file) negotiates its own real rate -- see audio_manager.py's
            # blocksize/samplerate properties, which read whichever one
            # is currently active. The JACK/PipeWire hostapi in
            # particular runs at its own fixed rate for a live mic (see
            # audio.py's Microphone._run_one_connection).
            frame_seconds=audio_manager.blocksize / audio_manager.samplerate,
        )
        window.set_talk_level(speaking_state.talk_level)
        window.set_envelope(speaking_state.envelope)
        # "Audio -> frame latency" (Settings' level meter, Milestone
        # request 2026-09-16: "the owner was fighting responsiveness,
        # show it"). Measures from when this block was captured
        # (Microphone's/FilePlayback's own background thread, timestamped
        # in audio_manager.py) to right now, on the Qt thread, having
        # just finished processing it -- i.e. the audio-thread-to-Qt-
        # thread hop plus however long anything ahead of this in the Qt
        # event queue took. Deliberately does NOT include: mic hardware/
        # OS driver buffering before the block was even readable, the
        # Attack/Hold/Release smoothing above (already a separate, owner-
        # tunable knob), or the render timer's own up to ~16ms paint
        # delay after this point -- see set_measured_latency_ms's
        # docstring, and label this honestly in the UI as what it is.
        if audio_manager.last_capture_monotonic is not None:
            window.set_measured_latency_ms(
                (time.monotonic() - audio_manager.last_capture_monotonic) * 1000.0
            )
        if debug_audio:
            now = time.monotonic()
            if now - last_print > 0.1:
                last_print = now
                print(
                    f"volume={volume:.4f}  envelope={speaking_state.envelope:.4f}  "
                    f"talk_level={speaking_state.talk_level}",
                    flush=True,
                )

    # Explicit QueuedConnection: both callbacks can fire from a
    # background thread (Microphone's or FilePlayback's own -- see
    # audio.py/audio_manager.py's threading contracts), and
    # AutoConnection can't be trusted to detect that hop here since
    # these receivers are plain closures, not bound methods on a
    # QObject, so Qt has no thread-affinity to inspect on those. Without
    # this, a slot could run direct-connected on a background thread
    # instead, racing the render timer and (observed once, before this
    # was added) hanging app shutdown.
    audio_manager.volume_measured.connect(
        on_volume_on_qt_thread, Qt.ConnectionType.QueuedConnection
    )
    audio_manager.error_occurred.connect(
        on_error_on_qt_thread, Qt.ConnectionType.QueuedConnection
    )
    # Same QueuedConnection style as the others here, for consistency --
    # file_playback_stopped itself already only ever fires on the Qt
    # thread (see AudioManager's own docstring), but this file's whole
    # convention is "assume anything from audio_manager needs it."
    audio_manager.file_playback_stopped.connect(
        on_file_playback_stopped_on_qt_thread, Qt.ConnectionType.QueuedConnection
    )
    # Same reasoning as above -- ObsMuteWatcher's callbacks (see
    # obs_link.py) fire from its own background connection thread.
    obs_link_manager.mute_changed.connect(
        on_mute_changed_on_qt_thread, Qt.ConnectionType.QueuedConnection
    )
    obs_link_manager.error_occurred.connect(
        on_obs_error_on_qt_thread, Qt.ConnectionType.QueuedConnection
    )

    audio_manager.start()
    obs_link_manager.start_if_enabled()

    def on_quit() -> None:
        audio_manager.shutdown()
        obs_link_manager.shutdown()
        asset_watcher.stop()
        save_state(config)  # belt-and-suspenders: the Control Panel already
        # saves on every change and periodically; this covers the case of
        # quitting before the first autosave tick.

    app.aboutToQuit.connect(on_quit)

    print(f"Loaded avatar: {rig.name} ({len(rig.sprites)} sprites)")
    print(f"Window title for OBS Window Capture: {WINDOW_TITLE!r}")
    print("Press Escape (with confirmation) or use the Quit button to quit.")

    return app.exec()


if __name__ == "__main__":
    exit_code = main()
    # Owner's report, 2026-09-17: "the app *seems* to be quitting
    # properly but the cli launcher is not exiting" -- by this point,
    # on_quit() above (app.aboutToQuit fires synchronously *before*
    # exec() returns, so this already ran) has already stopped the mic
    # cleanly via Microphone.stop()'s own stream.abort()/stream.close().
    # The hang is downstream of that: sounddevice registers its own
    # `atexit` handler (see sounddevice.py's _exit_handler, confirmed by
    # reading it directly) that unconditionally calls PortAudio's global
    # Pa_Terminate() during normal Python interpreter shutdown -- and
    # PortAudio's own upstream comment in that same file admits outright
    # that "portaudio hangs when calling close()" in some conditions.
    # Confirmed live: this app uses the JACK hostapi (PipeWire's JACK
    # compat layer), and the owner has OBS open, also holding the same
    # mic on that JACK graph -- multi-client JACK graph teardown
    # contention is a known category of PortAudio hang, and it fires
    # *after* our own already-correct cleanup, not because of anything
    # wrong with it. `sys.exit()` runs every registered atexit handler,
    # including that one; `os._exit()` skips atexit entirely, which is
    # safe here specifically because on_quit() already saved everything
    # that matters before this line runs. Flushing first since
    # os._exit() also skips the normal stdout/stderr flush on exit.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
