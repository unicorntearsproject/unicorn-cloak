"""
The Render Window: the transparent, frameless PySide6 window OBS actually
captures (see docs/PLAN.md's "Window model" decision — confirmed two-window
split). Builds one QGraphicsPixmapItem per sprite, nested to match the
rig's parent/child tree so Qt's own item-transform inheritance gives us
"child follows parent" for free, and drives position/rotation/scale/opacity
from unicorn_cloak.motion. All the actual motion/visibility math lives in
motion.py and is unit tested there — this module is just the Qt plumbing
around it, deliberately kept thin.

Simulation runs on a fixed 60Hz timestep via an accumulator, decoupled
from how often we actually get to paint (see _on_frame). This machine's
iGPU is shared with OBS's encoder, so the paint callback can and will
drop below 60fps under encode load; without decoupling, that would slow
down and distort blink timing and sway character rather than just look
choppy, since motion.py's functions advance state once per *call*, not
per fixed unit of wall-clock time.
"""
from __future__ import annotations

import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QKeySequence, QPixmap, QTransform
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QVBoxLayout,
    QWidget,
)

from . import motion
from .config import HotkeysConfig, MotionConfig
from .rig import NUM_COSTUMES, AvatarRig, Sprite
from .spritesheet import slice_all_frames

PAINT_INTERVAL_MS = 16  # how often we wake up to check the accumulator and paint
SIM_DT = 1.0 / 60.0  # fixed simulation timestep -- independent of paint rate
MAX_CATCH_UP_SECONDS = 0.25  # cap a single _on_frame's accumulated debt (e.g.
# after the window was minimized or the process was stalled) so it can't
# try to run hundreds of simulation steps in one burst
WINDOW_TITLE = "Unicorn Cloak"
# Wayland app_id (set via QGuiApplication.setDesktopFileName in
# __main__.py) -- distinct from WINDOW_TITLE because window managers and
# xdg-desktop-portal use app_id for identity, not the title text. Keeping
# both constant across launches is what "no re-pick on relaunch" in OBS
# depends on; see __main__.py's comment and docs/PLAN.md's cutover check.
APP_ID = "unicorn-cloak"

# "transparent" paints no scene background at all -- combined with
# WA_TranslucentBackground on the window, that's what lets OBS's
# window/portal capture show whatever's beneath this source. A solid
# color instead is a normal opaque scene background, useful for chroma
# keying (OBS's Chroma Key filter, most commonly against the green here)
# or just previewing outside OBS.
BACKGROUND_COLORS: dict[str, QColor | None] = {
    "transparent": None,
    "black": QColor(0, 0, 0, 255),
    "white": QColor(255, 255, 255, 255),
    "green": QColor(0, 255, 0, 255),
}

# "image" and "video" are handled separately from BACKGROUND_COLORS above --
# each needs its own scene item (a pixmap or a QGraphicsVideoItem) rather
# than a plain background brush, since a brush can't be scaled to fill the
# window. That item sits far enough behind every sprite (root_item and its
# children stay in the roughly -1000..1000 z_index range, see rig.Sprite)
# to never fight for stacking order, regardless of layer count.
BACKGROUND_MEDIA_ITEM_Z = -100_000

MIN_ZOOM = 0.1
MAX_ZOOM = 5.0


def _clamp_zoom(zoom: float) -> float:
    return max(MIN_ZOOM, min(MAX_ZOOM, zoom))


def _plain_key_from_sequence(text: str) -> int | None:
    """Resolves a single-key QKeySequence string (e.g. "1", "F5") back to
    a plain Qt.Key int comparable against QKeyEvent.key(). Costume
    hotkeys are always a single key, never a chord -- HotkeysConfig.
    costume_keys entries come from a QKeySequenceEdit capped at length 1
    (see settings_window.py). Returns None for an empty/unparseable
    string rather than raising, so a bad hand-edited config.json value
    just fails to match any key instead of crashing the app."""
    sequence = QKeySequence(text)
    if sequence.count() == 0:
        return None
    return int(sequence[0].key())


@dataclass
class _SpriteRuntime:
    sprite: Sprite
    item: QGraphicsPixmapItem
    drag_pos: tuple[float, float]
    prev_drag_y: float
    rotation_rad: float = 0.0
    scale: tuple[float, float] = (1.0, 1.0)
    # How far this sprite's lagged position has drifted from its own
    # authored `position`, in a "cumulative drift" space that already
    # folds in every ancestor's own drift (and, for a root sprite, the
    # avatar-wide bounce). A child adds this onto its own local target
    # before lagging -- see the contract in rig.py and _simulate_step --
    # so it actually lags *behind a moving parent*, not just its own
    # independent sway. Qt still wants a parent-local position for
    # setPos(), so _apply_to_scene subtracts the parent's drift back out.
    world_drift: tuple[float, float] = (0.0, 0.0)
    # Sprite-sheet animation. frame_pixmaps has exactly one entry (the
    # whole image, unsliced) for the overwhelmingly common frames<=1
    # case -- see motion.animation_frame_step and spritesheet.py.
    frame_pixmaps: list[QPixmap] = field(default_factory=list)
    current_frame: int = 0
    anim_ticks: int = 0
    # True whenever this item's on-screen QTransform is (or already was)
    # a plain identity -- lets _apply_to_scene skip setTransform() for
    # every sprite that never rotates/stretches, see its comment for why
    # that's the overwhelmingly common case, not a rare one.
    transform_is_identity: bool = True


class RenderWindow(QWidget):
    def __init__(
        self,
        rig: AvatarRig,
        motion_config: MotionConfig | None = None,
        *,
        hotkeys_config: HotkeysConfig | None = None,
        edit_mode: bool = False,
        window_size: tuple[int, int] = (1280, 720),
        background: str = "transparent",
        background_image_path: str = "",
        background_video_path: str = "",
        zoom: float = 1.0,
    ) -> None:
        super().__init__()
        self.rig = rig
        # Held by reference, read live each frame/keypress -- so a
        # Settings window mutating these fields (see settings_window.py)
        # takes effect immediately, no restart or re-wiring needed.
        self.motion_config = motion_config if motion_config is not None else MotionConfig()
        self.hotkeys_config = hotkeys_config if hotkeys_config is not None else HotkeysConfig()
        self.edit_mode = edit_mode
        self.zoom = _clamp_zoom(zoom)

        # Background image/video state -- see set_background's own
        # docstring. Tracked here (rather than only ever passed in) so a
        # mode switch back to "image"/"video" after visiting another mode
        # doesn't need the caller to remember and re-pass the path.
        self._background_mode = "transparent"
        self._background_image_path = background_image_path
        self._background_video_path = background_video_path
        self._background_image_item: QGraphicsPixmapItem | None = None
        self._background_video_item: QGraphicsVideoItem | None = None
        self._background_player: QMediaPlayer | None = None
        self._background_audio_output: QAudioOutput | None = None

        self.setWindowTitle(WINDOW_TITLE)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.resize(*window_size)

        self.scene = QGraphicsScene(self)
        # Without an explicit sceneRect, QGraphicsView falls back to an
        # auto-sized rect derived from itemsBoundingRect() -- which does
        # NOT match the widget's pixel size, so scene coordinates stop
        # mapping 1:1 to viewport pixels. root_item.setPos(width/2,
        # height/2) would then center on the wrong point (confirmed: at
        # construction, before any resize). Pin it to the widget's actual
        # size and keep it there on resize (see resizeEvent).
        self.scene.setSceneRect(0, 0, *window_size)
        self.view = QGraphicsView(self.scene, self)
        self.view.setStyleSheet("background: transparent; border: none;")
        self.view.setAttribute(Qt.WA_TranslucentBackground, True)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self.set_background(background)

        self.root_item: QGraphicsItemGroup | None = None
        self._runtimes: dict[int, _SpriteRuntime] = {}
        self._init_root_item()
        self._build_items()

        self.tick = 0
        self.bounce = motion.BounceState()
        self.blink = motion.BlinkState()
        self.blink_level = 1
        self.talk_level = 0
        # True whenever OBS reports the configured mic input as muted
        # (see obs_link.py) -- forces the mouth closed regardless of
        # what the mic/file is actually saying, so the avatar doesn't
        # keep talking while the stream hears silence. Set via
        # set_muted(); everything that decides what the avatar looks
        # like reads self.effective_talk_level, never self.talk_level
        # directly, so unmuting instantly reflects whatever talk_level
        # already is without waiting for a fresh audio update.
        self.muted = False
        # A second, independent force-closed flag -- quick-win
        # enhancement E12 (bug audit addendum 2026-09-23): a manual
        # "mouth closed" toggle in the Control Panel, for a cough or an
        # aside without needing to reach for OBS's own mute at all. Kept
        # separate from self.muted (OBS's own signal) rather than reusing
        # it, since obs_link.ObsMuteWatcher's own events would otherwise
        # overwrite whichever one fired last -- effective_talk_level ORs
        # the two together instead, so either one alone is enough to
        # force the mouth shut, and neither can silently clear the other.
        self.manual_muted = False
        # Plain telemetry for Settings' level meter -- see
        # set_envelope/set_measured_latency_ms's own docstrings.
        self.current_envelope = 0.0
        self.measured_latency_ms = 0.0
        # group_name -> the state_name currently forced live for that
        # group (added 2026-09-16, for an expression like "Laughing"
        # that isn't tied to mic volume or blinking) -- read by
        # _apply_to_scene for every sprite with manual_driven=True,
        # via set_manual_override (Settings' live "Expressions" control).
        # A group with no entry here just isn't overridden -- none of its
        # manual_driven sprites will be visible, which is the correct
        # default (an expression should be off until explicitly forced).
        self.manual_overrides: dict[str, str] = {}
        # See closeEvent/mouseDoubleClickEvent's own comments -- both
        # None by default (every test and any caller that doesn't wire
        # one gets the old, unconfirmed-quit / do-nothing-on-double-click
        # behavior).
        self.on_quit_requested: Callable[[], bool] | None = None
        self.on_avatar_double_clicked: Callable[[], None] | None = None
        # Which sprite is currently showing among however many share the
        # active talk_state/blink_state band (see motion.sprite_alpha's
        # variant params) -- advanced in _simulate_step, read in
        # _apply_to_scene. Talk and blink each get their own independent
        # timer since they're driven by unrelated signals (mic volume vs.
        # the random blink timer).
        self._talk_variant_frame = 0
        self._talk_variant_ticks = 0
        self._talk_variant_values: list[int] = [0]
        self._blink_variant_frame = 0
        self._blink_variant_ticks = 0
        self._blink_variant_values: list[int] = [0]
        self._last_bounce_tick = -1_000_000  # far enough back to always
        # qualify for a bounce on the very first speaking frame
        self._accumulator = 0.0
        self._last_time = time.monotonic()

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._on_frame)
        self.timer.start(PAINT_INTERVAL_MS)

    def set_background(self, mode: str, path: str | None = None) -> None:
        """Live-updatable (see settings_window.py). `path` only matters
        for "image"/"video" -- pass a new one when the owner browses a
        different file, or omit it (None) to just switch back to a mode
        whose file was already chosen earlier. Unknown modes, an empty
        path, or a file that fails to load/play all fall back to
        transparent rather than raising -- consistent with how the rest
        of this app treats a bad settings.json value."""
        if mode == "image" and path is not None:
            self._background_image_path = path
        elif mode == "video" and path is not None:
            self._background_video_path = path
        self._background_mode = mode
        self._clear_background_media()

        if mode == "image":
            self._set_image_background(self._background_image_path)
            return
        if mode == "video":
            self._set_video_background(self._background_video_path)
            return

        color = BACKGROUND_COLORS.get(mode)
        self.scene.setBackgroundBrush(color if color is not None else Qt.BrushStyle.NoBrush)

    def _clear_background_media(self) -> None:
        if self._background_player is not None:
            self._background_player.stop()
            # deleteLater(), not just dropping the Python reference --
            # bug audit 2026-09-23, #20 ("media player leak"). Built as
            # QMediaPlayer(self), i.e. parented to this window, so Qt's
            # C++ side keeps it alive via that parent-child ownership
            # regardless of what Python's own refcounting does; without
            # this it (and its decoder resources) only actually got
            # freed when the whole Render Window itself closed -- one
            # leaked player per background switch until then.
            self._background_player.deleteLater()
            self._background_player = None
        self._background_audio_output = None
        if self._background_video_item is not None:
            self.scene.removeItem(self._background_video_item)
            self._background_video_item = None
        if self._background_image_item is not None:
            self.scene.removeItem(self._background_image_item)
            self._background_image_item = None

    def _set_image_background(self, path: str) -> None:
        pixmap = QPixmap(path) if path else QPixmap()
        if pixmap.isNull():
            self.scene.setBackgroundBrush(Qt.BrushStyle.NoBrush)
            return
        self.scene.setBackgroundBrush(Qt.BrushStyle.NoBrush)
        self._background_image_item = QGraphicsPixmapItem(pixmap)
        self._background_image_item.setZValue(BACKGROUND_MEDIA_ITEM_Z)
        self.scene.addItem(self._background_image_item)
        self._resize_background_media()

    def _set_video_background(self, path: str) -> None:
        if not path:
            self.scene.setBackgroundBrush(Qt.BrushStyle.NoBrush)
            return
        self.scene.setBackgroundBrush(Qt.BrushStyle.NoBrush)
        self._background_video_item = QGraphicsVideoItem()
        self._background_video_item.setZValue(BACKGROUND_MEDIA_ITEM_Z)
        self.scene.addItem(self._background_video_item)
        self._resize_background_media()
        # Muted, not just volume-zeroed -- this is a silent visual loop,
        # never meant to play out loud (same "never plays its own sound"
        # rule as the audio-file playback path in audio_manager.py). A
        # QMediaPlayer needs *some* QAudioOutput assigned to decode audio
        # tracks cleanly rather than erroring on files that have one.
        self._background_audio_output = QAudioOutput()
        self._background_audio_output.setMuted(True)
        self._background_player = QMediaPlayer(self)
        self._background_player.setAudioOutput(self._background_audio_output)
        self._background_player.setVideoOutput(self._background_video_item)
        self._background_player.setLoops(QMediaPlayer.Loops.Infinite)
        self._background_player.errorOccurred.connect(self._on_background_video_error)
        self._background_player.setSource(QUrl.fromLocalFile(path))
        self._background_player.play()

    def _on_background_video_error(self, error, error_string: str) -> None:
        # A hard C-level decode failure isn't something to recover from
        # mid-playback -- fall back to transparent, same as any other bad
        # background value, rather than leaving a stalled/black item on
        # screen. Logged, not raised: this can legitimately happen for an
        # OBS-connected app on someone else's machine (missing codec,
        # since Qt Multimedia's FFmpeg backend still depends on what's
        # actually built into it) and shouldn't crash the render window.
        print(f"[background] video playback failed: {error_string}", flush=True)
        self._clear_background_media()
        self.scene.setBackgroundBrush(Qt.BrushStyle.NoBrush)

    def _resize_background_media(self) -> None:
        rect = self.scene.sceneRect()
        if self._background_image_item is not None:
            pixmap = self._background_image_item.pixmap()
            if pixmap.width() and pixmap.height():
                self._background_image_item.setTransform(
                    QTransform().scale(rect.width() / pixmap.width(), rect.height() / pixmap.height())
                )
        if self._background_video_item is not None:
            self._background_video_item.setSize(rect.size())

    def set_zoom(self, zoom: float) -> None:
        """Live-updatable (see settings_window.py). Scales the avatar
        around its own center, not the window -- root_item's *position*
        (the window center + bounce) is untouched, only its scale."""
        self.zoom = _clamp_zoom(zoom)
        self.root_item.setScale(self.zoom)

    def _init_root_item(self) -> None:
        # Anchors the avatar-wide speak-bounce offset; carries no pixmap of
        # its own, only child sprite items.
        self.root_item = QGraphicsItemGroup()
        self.scene.addItem(self.root_item)
        self.root_item.setPos(self.width() / 2, self.height() / 2)
        self.root_item.setScale(self.zoom)

    def rebuild(self) -> None:
        """Rebuilds the scene from the current rig.sprites -- call after
        the editor adds/removes a sprite or swaps an image, so the
        Render Window reflects the new sprite *set* (per-field edits like
        position/z-index are already picked up live every frame without
        this -- see _simulate_step). Removing root_item alone is enough --
        every sprite item is nested under it (directly or via a parent
        sprite), and Qt detaches a whole subtree when you remove its
        top item. Also removing each child individually, as this used
        to, hits already-detached items and logs a harmless but wrong
        "different scene" warning for each one."""
        self.scene.removeItem(self.root_item)
        self._runtimes.clear()
        self._init_root_item()
        self._build_items()

    def sync_sprite_offset_and_z(self, sprite_id: int) -> None:
        """Offset and z-index are only read at build time (position and
        talk/blink state are read live every frame, see _simulate_step) --
        call this after the editor changes either so the Render Window
        picks it up without a full rebuild (which would reset every
        sprite's drag/rotation/stretch runtime state)."""
        rt = self._runtimes.get(sprite_id)
        if rt is None:
            return
        pixmap = rt.item.pixmap()
        rt.item.setOffset(
            -pixmap.width() / 2 + rt.sprite.offset[0],
            -pixmap.height() / 2 + rt.sprite.offset[1],
        )
        rt.item.setZValue(rt.sprite.z_index)
        rt.item.setFlag(QGraphicsItem.ItemStacksBehindParent, rt.sprite.z_index < 0)

    def _build_items(self) -> None:
        by_parent: dict[int | None, list[Sprite]] = {}
        for sprite in self.rig.sprites:
            by_parent.setdefault(sprite.parent_id, []).append(sprite)

        def build(sprite: Sprite, parent_item) -> None:
            pixmap = QPixmap()
            if sprite.image_data:
                pixmap.loadFromData(sprite.image_data)
            # frame_pixmaps has one entry (the whole image) when
            # frames<=1, which is every sprite that ships today.
            frame_pixmaps = slice_all_frames(pixmap, sprite.frames)
            item = QGraphicsPixmapItem(frame_pixmaps[0], parent_item)
            frame_size = frame_pixmaps[0].size()
            item.setOffset(
                -frame_size.width() / 2 + sprite.offset[0],
                -frame_size.height() / 2 + sprite.offset[1],
            )
            item.setZValue(sprite.z_index)
            # z_index is relative to the parent (only orders siblings) --
            # Qt's default is that a child always paints on top of its
            # own parent regardless of z sign, so a negative z_index
            # (e.g. a hair-back layer meant to sit behind the head) needs
            # this flag or it renders in front anyway. See the contract
            # in rig.py.
            item.setFlag(QGraphicsItem.ItemStacksBehindParent, sprite.z_index < 0)
            if sprite.clipped:
                # ItemClipsChildrenToShape alone clips to the bounding
                # rect; MaskShape makes shape() (and so the clip) follow
                # the pixmap's actual alpha, not just its rectangle.
                item.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
                item.setShapeMode(QGraphicsPixmapItem.ShapeMode.MaskShape)
            item.setTransformationMode(Qt.SmoothTransformation)
            self._runtimes[sprite.id] = _SpriteRuntime(
                sprite=sprite,
                item=item,
                drag_pos=sprite.position,
                prev_drag_y=sprite.position[1],
                frame_pixmaps=frame_pixmaps,
            )
            for child in by_parent.get(sprite.id, []):
                build(child, item)

        for root_sprite in by_parent.get(None, []):
            build(root_sprite, self.root_item)

    def set_talk_level(self, talk_level: int) -> None:
        self.talk_level = talk_level

    def set_envelope(self, envelope: float) -> None:
        """The current smoothed RMS envelope (audio.SpeakingState.envelope)
        -- plain telemetry, read live by Settings' level meter (Milestone
        request, 2026-09-16: "the owner was fighting responsiveness, show
        it") via a QTimer poll, not used by anything render-related here."""
        self.current_envelope = envelope

    def set_measured_latency_ms(self, latency_ms: float) -> None:
        """How long between an audio block being captured (mic read or
        file-decode) and this window receiving the resulting talk_level
        -- see __main__.py's on_volume_on_qt_thread for exactly what's
        measured and what it deliberately excludes (mic hardware/OS
        driver buffering, the paint timer's own up-to-16ms delay)."""
        self.measured_latency_ms = latency_ms

    def set_muted(self, muted: bool) -> None:
        """Called live from obs_link.ObsMuteWatcher (via __main__.py's
        queued-connection bridge) whenever OBS reports the configured
        mic input's mute state changing. Forces the mouth closed while
        muted -- see self.muted's own comment for the real-world reason
        this exists."""
        self.muted = muted

    def set_window_size(self, width: int, height: int) -> None:
        """Live Render Window size change -- quick-win enhancement E6
        (bug audit addendum 2026-09-23), driven by the Application tab's
        size presets/Width/Height fields. Just a plain resize():
        resizeEvent already keeps self.scene's sceneRect pinned to the
        widget's actual size and re-centers root_item (which reads
        self.width()/self.height() live, every _apply_to_scene call), so
        no extra re-layout step is needed here."""
        self.resize(width, height)

    def set_manual_muted(self, muted: bool) -> None:
        """The Control Panel's own manual "mouth closed" toggle (E12) --
        see self.manual_muted's own comment for why this is a separate
        flag from set_muted's, not the same one reused."""
        self.manual_muted = muted

    @property
    def effective_talk_level(self) -> int:
        return 0 if (self.muted or self.manual_muted) else self.talk_level

    def set_manual_override(self, group_name: str, state_name: str | None) -> None:
        """Forces every manual_driven sprite in `group_name` to show only
        its `state_name` member (or none, if state_name is None) --
        live, on the real Render Window, independent of mic volume or
        blinking. See self.manual_overrides' own comment for what an
        absent entry means."""
        if state_name is None:
            self.manual_overrides.pop(group_name, None)
        else:
            self.manual_overrides[group_name] = state_name

    def _on_frame(self) -> None:
        """Paint-driver callback: advances the simulation by exactly as
        many fixed SIM_DT steps as real wall-clock time has actually
        elapsed (via the accumulator), then paints once using whatever
        state that leaves us in. If painting is running slower than
        60Hz, this runs the simulation loop more than once per call to
        catch up -- so a stall changes how often we *paint*, never how
        fast blink/sway/bounce move in real time."""
        now = time.monotonic()
        elapsed = min(now - self._last_time, MAX_CATCH_UP_SECONDS)
        self._last_time = now

        self._accumulator += elapsed
        while self._accumulator >= SIM_DT:
            self._simulate_step()
            self._accumulator -= SIM_DT

        self._apply_to_scene()

    def _sprite_currently_eligible(self, sprite: Sprite) -> bool:
        """True if this sprite could actually be showing right now, for
        variant-count purposes -- i.e. not hidden and in the active
        costume slot. Without this, a sprite excluded by costume or the
        eye-icon toggle would still count toward talk/blink_variant_count
        (see _simulate_step), so the one sprite that's actually eligible
        in a 2-variant band would wrongly alternate on/off against a
        "rival" that was never visible to begin with, instead of just
        showing continuously like a true 1-sprite band. No real rig
        exercises this today (every sprite is visible in every costume
        slot right now), but the variant mechanism itself must still be
        correct for whenever one does."""
        return not sprite.hidden and sprite.costume_layers[self.rig.active_costume]

    def _talk_variant_values_at(self, level: int) -> list[int]:
        """The sorted, de-duplicated `variant` values actually present
        among sprites eligible to show at this talk level right now --
        the real alternation pool. Shared by _simulate_step (which uses
        it to advance self._talk_variant_frame at mouth_variant_hz, in
        real time) and _apply_to_scene (which recomputes its own,
        against whatever level is actually being painted -- see that
        method's own comment for why it can't just trust
        self._talk_variant_values the way _simulate_step's own
        advance-over-time logic does).

        Distinct *values*, not a raw sprite count -- bug audit
        2026-09-23, finding #4. The old version counted eligible
        sprites and cycled an index 0..count-1, comparing it against
        each sprite's own `variant` for an exact match. Two sprites
        that happen to share a talk_state/level by coincidence (e.g. a
        mild mouth and an unrelated talk-gated accessory), both left at
        the default variant=0 since neither was ever meant to
        alternate against the other, still counted as "2" -- so half
        the cycle landed on an index (1) neither of them had, and both
        vanished. A non-contiguous set (variants 0 and 2, no 1) had the
        same problem in reverse: the cycling index only ever reached
        0..1, so the variant=2 sprite could never show at all. Cycling
        through the sorted *set* of values actually present fixes both:
        sprites sharing one value are members of the same slot (they
        show together, not "vs" each other -- correct for any pair
        never given distinct variant numbers to begin with), and a
        pool of {0, 2} cycles between exactly those two real values.

        Still rig-wide, not scoped by group_name, despite that also
        being part of a genuinely correct fix (per the audit): two
        *different*, unrelated multi-variant groups on the same axis
        would share one timer and switch in lockstep instead of
        independently. No real rig has that today (this app's own
        docstring for Sprite.variant: "two use cases today," one per
        axis) and it's a much milder symptom (everything still shows,
        just synced) than the vanishing bug above -- not worth a
        second, genuinely more invasive per-group-timer refactor for a
        theoretical case. Flagging it here in case a future rig does
        hit it, same spirit as _sprite_currently_eligible's own "no
        real rig exercises this today" note."""
        return sorted({
            rt.sprite.variant
            for rt in self._runtimes.values()
            if not rt.sprite.manual_driven
            and rt.sprite.talk_state != 0
            # axis_visible, not a direct == check: talk_state can be
            # motion.TALK_QUIET_ONLY (3), which is "visible when
            # effective_talk_level == 0" rather than "equal to 3" --
            # a direct equality check would silently exclude a
            # quiet-only mouth from ever sharing a variant pool.
            and motion.axis_visible(rt.sprite.talk_state, level)
            and self._sprite_currently_eligible(rt.sprite)
        })

    def _blink_variant_values_at(self, level: int) -> list[int]:
        """Blink-axis counterpart of _talk_variant_values_at -- same fix,
        same reasoning (bug audit 2026-09-23, #4). Named _at, not a
        bare _blink_variant_values, to leave that name for the stored,
        _simulate_step-time value _apply_to_scene actually reads (blink_
        level is computed synchronously within _simulate_step itself,
        not set asynchronously from another thread the way talk_level
        is, so unlike the talk axis there's no cross-thread staleness
        gap to guard against -- _apply_to_scene trusts the stored value
        directly here, exactly as it already did before this fix)."""
        return sorted({
            rt.sprite.variant
            for rt in self._runtimes.values()
            if not rt.sprite.manual_driven
            and rt.sprite.blink_state != 0
            and rt.sprite.blink_state == level
            and self._sprite_currently_eligible(rt.sprite)
        })

    def _simulate_step(self) -> None:
        self.tick += 1

        self.blink = motion.blink_step(
            self.blink,
            self.motion_config.blink_speed,
            self.motion_config.blink_chance,
            random.uniform(-1.0, 1.0),
            random.randrange(self.motion_config.blink_chance),
        )
        self.blink_level = 2 if self.blink.blinking else 1

        self._blink_variant_values = self._blink_variant_values_at(self.blink_level)
        self._blink_variant_frame, self._blink_variant_ticks = motion.animation_frame_step(
            self._blink_variant_frame,
            self._blink_variant_ticks,
            len(self._blink_variant_values),
            self.motion_config.eye_variant_hz,
            SIM_DT,
        )

        # The distinct variant values sharing the active talk band -- e.g.
        # {0, 1} while talk_level is "mild" and there are two mild-open
        # mouth sprites. animation_frame_step already treats count<=1 as
        # "never advance" (see motion.py), so a band with only one variant
        # value in it (whether that's one sprite, or several sprites all
        # left at the same default variant -- see _talk_variant_values_at's
        # own docstring) just sits there forever, matching every existing
        # rig.
        self._talk_variant_values = self._talk_variant_values_at(self.effective_talk_level)
        self._talk_variant_frame, self._talk_variant_ticks = motion.animation_frame_step(
            self._talk_variant_frame,
            self._talk_variant_ticks,
            len(self._talk_variant_values),
            self.motion_config.mouth_variant_hz,
            SIM_DT,
        )

        # Re-trigger the bounce for as long as talk_level stays above 0 --
        # gives continuous speech continuous bobbing, instead of one
        # impulse at the start that settles and goes still. See
        # motion.should_retrigger_bounce for why this is gated on the
        # bounce having settled, not just elapsed time. Ticks now advance
        # at a fixed rate (SIM_DT), so this interval is accurate in real
        # time regardless of paint jitter.
        retrigger_ticks = max(
            1, round(self.motion_config.bounce_retrigger_ms / (SIM_DT * 1000))
        )
        if self.effective_talk_level > 0 and motion.should_retrigger_bounce(
            self.bounce, self.tick - self._last_bounce_tick, retrigger_ticks
        ):
            self.bounce = motion.bounce_trigger(
                self.bounce, self.motion_config.bounce_strength
            )
            self._last_bounce_tick = self.tick

        self.bounce, bounce_delta = motion.bounce_step(
            self.bounce, self.motion_config.gravity, SIM_DT
        )

        # Processing order matters: _build_items inserts parents before
        # their children (pre-order), and dicts preserve insertion order,
        # so a parent's world_drift below is always up to date by the
        # time its children read it in this same pass.
        for rt in self._runtimes.values():
            sprite = rt.sprite
            sway = motion.sway_offset(
                self.tick,
                sprite.sway_x_freq,
                sprite.sway_x_amp,
                sprite.sway_y_freq,
                sprite.sway_y_amp,
            )
            if sprite.talk_state != 0:
                wobble = motion.sway_offset(
                    self.tick,
                    self.motion_config.mouth_wobble_freq,
                    self.motion_config.mouth_wobble_amp,
                    self.motion_config.mouth_wobble_freq * 1.3,
                    self.motion_config.mouth_wobble_amp * 0.6,
                )
                sway = (sway[0] + wobble[0], sway[1] + wobble[1])

            if sprite.parent_id is None:
                # Root sprites don't need the avatar-wide bounce added
                # here to render correctly (root_item already carries it
                # in Qt), but it must still count as "parent motion" for
                # a root sprite's own children to lag behind.
                parent_drift = (0.0, self.bounce.y_position)
            else:
                parent_drift = self._runtimes[sprite.parent_id].world_drift

            target = (
                sprite.position[0] + sway[0] + parent_drift[0],
                sprite.position[1] + sway[1] + parent_drift[1],
            )
            rt.drag_pos = motion.drag_lag(rt.drag_pos, target, sprite.drag_speed)
            rt.world_drift = (
                rt.drag_pos[0] - sprite.position[0],
                rt.drag_pos[1] - sprite.position[1],
            )

            velocity = motion.drag_velocity_y(
                rt.prev_drag_y, rt.drag_pos[1], sprite.ignore_bounce, bounce_delta
            )
            rt.prev_drag_y = rt.drag_pos[1]

            rt.rotation_rad = motion.rotation_step(
                rt.rotation_rad,
                velocity,
                sprite.rotation_drag_strength,
                sprite.rotation_limit_min_deg,
                sprite.rotation_limit_max_deg,
            )
            rt.scale = motion.stretch_step(rt.scale, velocity, sprite.stretch_amount)

            rt.current_frame, rt.anim_ticks = motion.animation_frame_step(
                rt.current_frame, rt.anim_ticks, sprite.frames, sprite.anim_speed, SIM_DT
            )

    def _apply_to_scene(self) -> None:
        """Pushes the current simulation state to the Qt items. Runs
        exactly once per _on_frame call, regardless of how many
        _simulate_step calls it took to catch up -- painting an
        intermediate substep would just be wasted work, nothing needs to
        see it."""
        base_x, base_y = self.width() / 2, self.height() / 2
        self.root_item.setPos(base_x, base_y + self.bounce.y_position)

        # Recomputed fresh here rather than trusting self._talk_variant_
        # count/self._talk_variant_frame outright -- SIM_DT (~16.67ms) is
        # very slightly longer than PAINT_INTERVAL_MS (16ms), so a fair
        # number of _on_frame calls paint with zero _simulate_step in
        # between. talk_level itself is set asynchronously (set_talk_
        # level, from the audio thread via a queued connection) and can
        # change in that gap -- if it crosses a band boundary (e.g. mild
        # -> wide) without a _simulate_step in between to recompute, the
        # stale count/frame (from the *old* band's own, unrelated variant
        # numbering) gets applied to the *new* band's sprites below.
        # sprite_alpha requires an exact talk_variant == active_talk_
        # variant match once talk_variant_count > 1, so a stale index
        # that doesn't happen to also exist in the new band matches
        # nothing -- hiding every mouth sprite for that one paint (owner's
        # report, 2026-09-20: "a quick flip to a state with no active
        # mouth"). The modulo wrap is a no-op whenever the band hasn't
        # changed (the frame is already kept < count by animation_frame_
        # step's own modulo); real-time cycling speed is still entirely
        # governed by _simulate_step, this only guarantees whatever index
        # reaches sprite_alpha is always valid for the band actually
        # being painted.
        talk_level = self.effective_talk_level
        talk_variant_values = self._talk_variant_values_at(talk_level)
        talk_variant_count = len(talk_variant_values)
        active_talk_variant = (
            talk_variant_values[self._talk_variant_frame % talk_variant_count]
            if talk_variant_count > 0 else 0
        )

        for rt in self._runtimes.values():
            sprite = rt.sprite
            # rt.drag_pos lives in "cumulative drift" space (see
            # _simulate_step), which already includes the parent's own
            # drift -- Qt's setPos() wants this sprite's position
            # relative to its *parent item*, which already visually
            # carries that same drift via nesting, so subtract it back
            # out here or it would be applied twice.
            if sprite.parent_id is None:
                parent_drift = (0.0, self.bounce.y_position)
            else:
                parent_drift = self._runtimes[sprite.parent_id].world_drift
            local_pos = (
                rt.drag_pos[0] - parent_drift[0],
                rt.drag_pos[1] - parent_drift[1],
            )
            rt.item.setPos(*local_pos)
            # Rotation and non-uniform (x, y) stretch combined into one
            # QTransform -- QGraphicsItem.setScale() only takes a single
            # uniform factor, which can't express squash/stretch.
            #
            # setTransform() is skipped entirely once this settles back to
            # a plain identity (rotation 0, scale (1, 1)) -- found while
            # profiling 2026-09-16: every sprite in the real avatar has
            # rotation_drag_strength=0 and stretch_amount=0 (neither
            # feature has any real content using it yet), meaning this was
            # unconditionally calling setTransform() with a mathematically-
            # identity QTransform on all 13 sprites, every frame, forever
            # -- real raster/compositing work for a result that never
            # changes. A sprite that *does* use rotation/stretch still
            # gets a fresh QTransform exactly as before; this only skips
            # the call once its own rotation/scale have actually settled
            # back to nothing.
            # sprite.scale_x/scale_y and sprite.rotation_deg (static,
            # authored -- see rig.Sprite's own comments) combine with
            # rt.scale/rt.rotation_rad (the reactive squash/stretch/drag-
            # rotation, which return to (1, 1)/0 at rest) by multiplying
            # or adding respectively, rather than replacing them, so a
            # permanently resized/rotated layer still squashes, stretches,
            # and reacts to drag normally around its own authored baseline.
            rot_deg = sprite.rotation_deg + math.degrees(rt.rotation_rad)
            combined_scale_x = sprite.scale_x * rt.scale[0]
            combined_scale_y = sprite.scale_y * rt.scale[1]
            is_identity = (
                abs(rot_deg) < 1e-6
                and abs(combined_scale_x - 1.0) < 1e-6
                and abs(combined_scale_y - 1.0) < 1e-6
            )
            if is_identity:
                if not rt.transform_is_identity:
                    rt.item.resetTransform()
                    rt.transform_is_identity = True
            else:
                transform = QTransform()
                transform.rotate(rot_deg)
                transform.scale(combined_scale_x, combined_scale_y)
                rt.item.setTransform(transform)
                rt.transform_is_identity = False

            if sprite.frames > 1:
                rt.item.setPixmap(rt.frame_pixmaps[rt.current_frame])

            # An active Expression override forces its own group to show
            # exactly one thing: the forced state. Without this, the
            # group's ordinary *automatic* members (e.g. "Eyes: Regular"
            # picked by the real blink timer) keep showing right alongside
            # the forced one, since sprite_alpha decides each sprite
            # independently and has no idea a sibling is being overridden
            # -- confirmed empirically, 2026-09-17 (turning on "Eyes: Open"
            # while "Regular" was the live automatic pick left both drawn
            # on top of each other). Routed through the existing `hidden`
            # parameter rather than a new one: it's exactly the same
            # "always wins, ghosted in edit mode" treatment sprite.hidden
            # already gets.
            suppressed_by_other_expression = (
                not sprite.manual_driven
                and bool(sprite.group_name)
                and sprite.group_name in self.manual_overrides
            )
            alpha = motion.sprite_alpha(
                sprite.talk_state,
                sprite.blink_state,
                talk_level,
                self.blink_level,
                self.edit_mode,
                talk_variant=sprite.variant,
                active_talk_variant=active_talk_variant,
                talk_variant_count=talk_variant_count,
                blink_variant=sprite.variant,
                active_blink_variant=(
                    self._blink_variant_values[self._blink_variant_frame % len(self._blink_variant_values)]
                    if self._blink_variant_values else 0
                ),
                blink_variant_count=len(self._blink_variant_values),
                hidden=sprite.hidden or suppressed_by_other_expression,
                manual_driven=sprite.manual_driven,
                manual_active=(
                    self.manual_overrides.get(sprite.group_name) == sprite.state_name
                ),
            )
            in_costume = sprite.costume_layers[self.rig.active_costume]
            rt.item.setOpacity(alpha if in_costume else 0.0)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        # Keep the scene rect pinned to the widget's actual size -- see
        # the comment in __init__. root_item's centered position is
        # recomputed fresh every _apply_to_scene call already (it reads
        # self.width()/self.height() live), so this is the other half of
        # "stay centered across a resize."
        self.scene.setSceneRect(0, 0, self.width(), self.height())
        self._resize_background_media()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Escape is checked first and unconditionally, before costume
        # keys -- it's the only way to quit a frameless window like this
        # one, so it can never be shadowed by a costume binding. Found
        # 2026-09-16: QKeySequenceEdit does NOT treat Escape as "cancel
        # this capture" the way it's commonly assumed to (verified
        # empirically, not from docs) -- it captures Escape like any
        # other key, so a costume slot bound to it would otherwise win
        # this scan (it used to run first) and silently swallow every
        # Escape press with no way to quit. settings_window.py also
        # rejects binding Escape in the first place, but this check is
        # the actual guarantee -- it holds even against a hand-edited
        # config.json this app never validated.
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()  # routes through closeEvent below -- single confirm gate
            return
        # Costume-switch hotkeys, one per slot, remappable from Settings'
        # Hotkeys group (see HotkeysConfig.costume_keys) -- resolved live
        # against the current config every keypress, so a rebind takes
        # effect immediately with no rewiring. Only fire while this
        # window has keyboard focus, deliberately: a global variant was
        # considered and dropped (see HotkeysConfig's docstring) rather
        # than risk colliding with whatever else on the system already
        # claims the same keys.
        #
        # [:NUM_COSTUMES] found in review, 2026-09-16: unlike the old
        # hardcoded 1-9/0 mapping (exactly 10 keys, always in range),
        # costume_keys is now a free-form tuple with no length check --
        # a hand-edited config.json with more than NUM_COSTUMES entries
        # would otherwise set rig.active_costume past the end of every
        # sprite's fixed-length costume_layers tuple, IndexError-ing the
        # very next frame in _apply_to_scene/_sprite_currently_eligible.
        for slot, key_text in enumerate(self.hotkeys_config.costume_keys[:NUM_COSTUMES]):
            if _plain_key_from_sequence(key_text) == key:
                self.rig.active_costume = slot
                return

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # This is the window OBS captures -- treat closing it as "quit the
        # app", even though the Control Panel is a separate top-level
        # window that would otherwise keep the QApplication alive.
        #
        # on_quit_requested (added 2026-09-17, owner's request: quitting
        # used to happen with no confirmation at all) is the single gate
        # both Escape and this closeEvent route through -- set by
        # __main__.py to the Control Panel's own confirm-and-maybe-save
        # flow. It returns False to cancel the quit (event.ignore()),
        # leaving this window exactly as it was.
        if self.on_quit_requested is not None and not self.on_quit_requested():
            event.ignore()
            return
        super().closeEvent(event)
        QApplication.instance().quit()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Owner's request, 2026-09-17: "Settings window can be closed,
        # leaving avatar live... double click avatar to open settings
        # again." Wired by __main__.py to re-show/raise the Control
        # Panel window; None (the default, and in every test that
        # doesn't wire one) means double-clicking just does nothing.
        if self.on_avatar_double_clicked is not None:
            self.on_avatar_double_clicked()
        super().mouseDoubleClickEvent(event)
