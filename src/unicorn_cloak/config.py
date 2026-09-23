"""
Live, app-managed settings -- not a file the owner is expected to
hand-edit. `load_state()` reads `settings.json` (defaults if it doesn't
exist yet); `save_state()` writes it atomically (temp file + `os.replace`,
so a crash or power loss mid-write can't corrupt it -- the legacy
`Saving.write_settings()` just did a direct `FileAccess.WRITE`, no such
guarantee) and keeps one `.bak` of whatever was there before, matching
persistence.py's save_avatar (added 2026-09-16, after an agent deleted
this file directly with no backup to fall back on while poking at it --
the atomic write alone doesn't help when the thing overwriting the file
isn't this function at all). `ControlPanelWindow` in
control_panel_window.py is the actual tuning UI; it mutates a shared
`Config` instance in place and calls `save_state()` on every change plus
periodically and on exit.

Also format-versioned, same idea as persistence.py's avatar files (see
CURRENT_CONFIG_VERSION below) -- a stamp for a future structural change
to migrate from, not needed for an ordinary new field with a safe
default (those already round-trip fine through `_merge`).
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .rig import NUM_COSTUMES

DEFAULT_STATE_PATH = Path(__file__).resolve().parents[2] / "settings.json"

# Format versioning (added 2026-09-17, mirroring persistence.py's own
# CURRENT_FORMAT_VERSION/needs_migration for avatar files -- owner's
# request: "we should version the file system... so we can, in the
# future, be sure we're migrating smoothly for users when we update the
# app"). A brand-new field with a safe default already round-trips fine
# without any of this (_merge just fills it in from the dataclass
# default) -- this exists for the harder case, a future *structural*
# change (a renamed or restructured key), which needs something to
# migrate *from*. Any settings.json without the stamp (every one written
# before today) is version 0.
#
# Unlike persistence.py's avatar files, this is app-internal state the
# owner never hand-edits or is shown a message about -- migrations here
# are silent, applied on load, before _merge ever sees the dict.
_CONFIG_VERSION_KEY = "__config_version__"
CURRENT_CONFIG_VERSION = 3

# One entry per version bump: raw settings dict at that version -> raw
# dict at version + 1. _migrate_raw_config applies them in sequence, so a
# file several versions behind still gets every intermediate step, not
# just the latest.


def _migrate_window_zoom_to_avatar(raw: dict) -> dict:
    """v1 -> v2, 2026-09-19: WindowConfig.zoom moved to AvatarRig.zoom
    (see that field's own comment in rig.py) -- strip it from an old
    settings.json's window block so _merge doesn't reject it as an
    unknown WindowConfig field. The value itself isn't carried over: a
    per-machine setting standing in for what's now a per-avatar one, and
    the avatar file's own zoom (defaulting to 1.0) takes over from here."""
    window = raw.get("window")
    if isinstance(window, dict):
        window.pop("zoom", None)
    return raw


# v2 -> v3 briefly stripped control_panel.scale_lock_proportions here
# (when this button's toggle was repurposed into Sprite.locked) and was
# removed again the same day once that field came back as its own
# separate control (see ControlPanelConfig.scale_lock_proportions's own
# comment) -- no migration needed for that step since the field being
# recognized again is exactly what makes an old settings.json's value
# load correctly. A settings.json that *did* pass through the brief
# stripped window (this repo's own real one did) just gets the
# dataclass default (True) back, same as the value almost always was
# anyway.


_CONFIG_MIGRATIONS: dict[int, Callable[[dict], dict]] = {
    1: _migrate_window_zoom_to_avatar,
}


def _migrate_raw_config(raw: dict) -> dict:
    # Always advances version and keeps going, even for a step with
    # nothing registered -- bug audit 2026-09-23, #12: this used to
    # `break` at the first such step, which for a version-0 file (no
    # stamp at all -- every settings.json written before versioning
    # existed) meant *immediately*, since nothing is registered at key
    # 0 (there was nothing to migrate between v0 and v1, only starting
    # at v1->v2). That skipped every real migration after it too,
    # including v1's window.zoom removal -- so an old, unstamped file
    # with a leftover window.zoom crashed at _merge with "unknown
    # WindowConfig setting(s)" instead of ever reaching the fix for it.
    version = raw.get(_CONFIG_VERSION_KEY, 0)
    while version < CURRENT_CONFIG_VERSION:
        migrate = _CONFIG_MIGRATIONS.get(version)
        if migrate is not None:
            raw = migrate(raw)
        version += 1
    return raw

# Default avatar, replaced 2026-09-17 (owner's request: "let's replace our
# default model... you can find them in unicorn-cloak/assets/unicorn-demo")
# -- the previous default lived outside this repo entirely
# (/home/jj/projects/unicorn-tears/...), on this one machine only, which
# made a fresh checkout unable to actually run without it. Package-relative
# now, matching DEFAULT_STATE_PATH above, so the app is self-contained --
# worth fixing now specifically because this folder is headed for its own
# repo (see docs/PLAN.md's git history note) and an absolute, owner-specific
# path would silently break for anyone else.
DEFAULT_AVATAR_PATH = str(
    Path(__file__).resolve().parents[2] / "assets" / "unicorn-demo" / "unicorn-demo.uc"
)


@dataclass
class AudioConfig:
    # Starting points calibrated 2026-09-15 against the owner's real mic
    # (ambient floor ~0.002 RMS, speech ~0.02-0.14 RMS) -- all of it is
    # meant to be tuned live in the Settings window while talking, not
    # trusted as-is on a different mic.
    noise_gate: float = 0.005  # RMS below this counts as pure silence

    # A multiplier applied to the raw measured RMS before it ever reaches
    # noise_gate/mild/wide -- an in-app control independent of whatever
    # the OS mixer or a mic's own physical gain knob is doing (added
    # 2026-09-16: the owner's reported mic level and this app's measured
    # level didn't obviously line up with each other -- PipeWire's own
    # volume for the device read differently from the number the owner
    # was looking at, and a hardware gain dial on a USB mic wouldn't show
    # up in PipeWire at all regardless). 1.0 = no change.
    gain: float = 1.0

    # Open/close are separate thresholds (hysteresis / Schmitt trigger):
    # the envelope must rise to *_open to enter a band but fall below the
    # lower *_close to leave it, so it doesn't flicker at one boundary.
    mild_open: float = 0.015
    mild_close: float = 0.008
    wide_open: float = 0.06
    wide_close: float = 0.035

    # Attack/hold/release, in milliseconds -- a real envelope follower,
    # not the single fixed-rate decay that made PNGTuber-Plus's mouth lag
    # ~0.7s closed after speech stopped (see
    # docs/decisions/0004-avatar-lipsync-tooling.md's "Superseded" note;
    # replacing this is the reason this app exists). Hold is what lets
    # continuous speech keep the mouth open through brief gaps between
    # syllables instead of snapping shut every time volume dips.
    attack_ms: float = 15.0
    hold_ms: float = 120.0
    release_ms: float = 200.0

    device: str | None = None  # None = system default input device, while source == "microphone"

    # Which capture-capable device backs "desktop" (see source below),
    # remembered separately from the mic's own `device` above -- same
    # reasoning as file_path staying independent of source: switching
    # between microphone/desktop shouldn't make either one forget its own
    # chosen device. None = whatever usable_input_devices() finds first
    # (audio.py), same fallback microphone gets.
    #
    # Added 2026-09-23: there's no dedicated "desktop loopback" device on
    # this owner's PipeWire/JACK setup -- unlike PulseAudio's own naming,
    # a sink's monitor isn't exposed as a separately-named "Monitor of
    # ..." device here, it's just the sink node itself also showing
    # nonzero input channels (confirmed live: e.g. "Built-in Audio
    # Analog Stereo" has both). No reliable name-based heuristic exists
    # to auto-pick "the" desktop output, so this is manual, via the
    # device dropdown (control_panel_window.py's source row) -- not
    # auto-detected.
    desktop_device: str | None = None

    # Which volume source drives talk_level -- "microphone" (default),
    # "file" (audio.FilePlayback, added 2026-09-16 for re-recording a
    # video where the avatar needs to be driven by a participant's
    # isolated track while a *different*, already-combined recording is
    # what actually gets captured -- see FilePlayback's own docstring),
    # or "desktop" (added 2026-09-23, owner's request: drive the mouth
    # from whatever's actually playing out the speakers, e.g. game/video
    # audio, without needing a separate isolated mic-style recording of
    # it -- same underlying audio.Microphone capture as "microphone",
    # just pointed at desktop_device above instead of device).
    # file_path is remembered across restarts even while source is
    # something else, so switching back to "file" doesn't lose it.
    source: str = "microphone"
    file_path: str | None = None


@dataclass
class MotionConfig:
    bounce_strength: float = 250.0
    gravity: float = 1000.0
    blink_speed: float = 1.0
    blink_chance: int = 200
    # Re-triggers the speak-bounce on a timer for as long as talk_level
    # stays above 0, so continuous speech keeps the whole avatar bobbing
    # instead of one bounce at the start that settles and goes still.
    bounce_retrigger_ms: float = 150.0
    # Extra idle wobble layered onto any sprite with a nonzero talk_state
    # (i.e. any mouth-shape sprite), on top of its own authored sway.
    mouth_wobble_freq: float = 0.3
    mouth_wobble_amp: float = 4.0
    # How many times per second sprites sharing the same nonzero talk_state
    # swap which one is showing (rig.Sprite.variant) -- e.g. two mild-open
    # mouth shapes flapping back and forth during continuous speech. A
    # talk_state with only one sprite in it ignores this entirely.
    mouth_variant_hz: float = 8.0
    # Same idea as mouth_variant_hz, but for sprites sharing a nonzero
    # blink_state instead (e.g. an "eyes open" state with a wide-open and
    # a squint shape) -- deliberately slow, an occasional expression
    # change between blinks, not a flutter like the mouth's.
    eye_variant_hz: float = 0.15


@dataclass
class WindowConfig:
    width: int = 1280
    height: int = 720
    # What's behind the avatar. "transparent" (the default -- keep it
    # that way, since it's what lets an OBS window/portal capture show
    # whatever's beneath this source in the scene), a solid backdrop for
    # chroma-keying or previewing outside OBS (see render.py's
    # BACKGROUND_COLORS), or "image"/"video" to show a chosen file
    # instead (see background_image_path/background_video_path below).
    background: str = "transparent"
    # Only read when background == "image"/"video" respectively -- kept
    # as two separate fields, not one, so switching the Background combo
    # back and forth doesn't forget whichever file was chosen for the
    # other mode. Added 2026-09-17, owner's request.
    background_image_path: str = ""
    background_video_path: str = ""
    # zoom moved to AvatarRig.zoom 2026-09-19 -- see that field's own
    # comment for why (it's per-avatar, not per-machine).


@dataclass
class HotkeysConfig:
    # One QKeySequence-parseable string per costume slot (index 0-8 ->
    # "1".."9", index 9 -> "0", matching the on-screen 1-9,0 numbering).
    # Remappable from Settings' Hotkeys group (QKeySequenceEdit widgets,
    # one key per slot -- render.py resolves each string back to a plain
    # Qt.Key live in keyPressEvent, so a rebind takes effect immediately;
    # control_panel_window.py additionally wires these as real QShortcuts,
    # rebuilt on the same rebind, added 2026-09-19 so costume switching
    # also works from the Control Panel, not just the Render Window).
    #
    # These only fire while the Render Window or the Control Panel has
    # keyboard focus (and, in the Control Panel, only while no text/combo/
    # key-capture field is itself focused). A global variant (usable while
    # OBS or another app has focus, which
    # would otherwise be the actually-useful case while streaming) was
    # considered and deliberately dropped 2026-09-16 -- owner's call: it
    # would fight with whatever else on the system already claims those
    # same keys (games, other overlays, DAW shortcuts), and that collision
    # risk isn't worth it. Not "not built yet" -- rejected as a bad idea.
    costume_keys: tuple[str, ...] = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0")


@dataclass
class ObsConfig:
    # Mute awareness (added 2026-09-16, see obs_link.py): reads the mute
    # state of a named OBS input over obs-websocket -- the same server
    # the parent `obs` management repo already drives -- and forces the
    # avatar's mouth closed whenever it's muted, so it doesn't keep
    # "talking" while the stream hears silence.
    #
    # Off by default: this tries to connect (silently, indefinitely
    # retrying -- OBS not running is routine, not an error) the moment
    # it's turned on, which is pointless noise for anyone who hasn't set
    # host/port/password/input_name up yet. The owner enables it once
    # those are filled in.
    enabled: bool = False
    host: str = "localhost"
    port: int = 4455
    # The owner types this into the running app's Settings window
    # directly -- never pre-filled or copied in from OBS's own config by
    # this app, and never written anywhere but this app's own
    # settings.json (which, like the rest of unicorn-cloak/, stays
    # outside the parent `obs` repo's git tracking -- see docs/PLAN.md's
    # "Open questions" section).
    password: str = ""
    # Must match an OBS input's name exactly (case-sensitive) -- e.g.
    # "Mic/Aux". No default: there's no way to guess the owner's actual
    # input name, and guessing wrong would fail silently different from
    # "not configured yet" (see obs_link.py's OBSSDKRequestError
    # handling for what an actual typo looks like once this is set).
    input_name: str = ""


@dataclass
class ControlPanelConfig:
    """State for the single merged Editor+Settings window (added
    2026-09-17, replacing the separate EditorWindow/SettingsWindow
    top-level windows -- owner's request: "remember all settings/state
    ... when closing and reopening"). Geometry fields are None until the
    window has actually been shown once; None means "let Qt pick a
    default position/size" rather than forcing a fixed first-launch
    layout."""

    x: int | None = None
    y: int | None = None
    # Wide enough that the canvas pane (60% of this, see
    # control_panel_window.py's _apply_initial_splitter_sizes) shows the
    # avatar close to its real Render Window size by default, not as a
    # cramped sidebar -- owner's request, 2026-09-17: "the preview/editor
    # should be the primary feature."
    width: int = 1600
    height: int = 880
    active_tab: int = 0
    # "live_preview" mirrors the real Render Window (reacts to actual
    # mic/blink); "edit" is the interactive drag-to-position canvas.
    # Defaults to live_preview per owner's explicit choice.
    canvas_mode: str = "live_preview"
    # None = use the default 60/40 canvas/tabs split; once the user drags
    # the splitter, this remembers exactly where they left it.
    splitter_sizes: tuple[int, int] | None = None
    show_origin_guides: bool = False
    show_hidden_ghosted: bool = False
    # Pixel spacing of the edit-canvas grid overlay (replaces the old
    # origin crosshair) -- configurable per owner's request.
    grid_spacing_px: int = 100
    # Which collapsible sections (identified by their header title) are
    # currently collapsed. "Position & Hierarchy"/"Animation" start
    # collapsed on a first launch (owner's request, 2026-09-17, when both
    # moved from the Sprites tab to the Behavior tab: Motion is what most
    # people tune first) -- _apply_persisted_ui_state() applies this
    # tuple unconditionally on construction, so this default, not the
    # CollapsibleSection constructor's own `collapsed=` arg, is what
    # actually controls first-launch state.
    # Costumes/Expressions briefly joined this default 2026-09-17 (their
    # per-slot editor rows made the whole panel's minimum size balloon
    # when expanded, since a hidden CollapsibleSection body doesn't count
    # toward layout size but a big expanded one does) -- moved to their
    # own tabs the same day instead, each wrapped in a QScrollArea, which
    # fixes the same problem without needing to hide the section by
    # default (a QScrollArea's own sizeHint doesn't grow with its
    # content).
    collapsed_sections: tuple[str, ...] = ("Position & Hierarchy", "Animation")

    # Whether Scale X/Y (Position & Hierarchy) are linked -- editing one,
    # or dragging a corner handle on the Edit canvas, updates/scales the
    # other to match, keeping the sprite's proportions. On by default per
    # the owner's own request, 2026-09-17. Briefly retired 2026-09-19
    # when this button's own toggle was repurposed into per-sprite
    # AvatarRig.Sprite.locked ("Lock Position") -- brought back the same
    # day, as its own separate control again, once the owner clarified
    # both were wanted side by side, not one replacing the other.
    scale_lock_proportions: bool = True


@dataclass
class Config:
    avatar_path: str = DEFAULT_AVATAR_PATH
    audio: AudioConfig = field(default_factory=AudioConfig)
    motion: MotionConfig = field(default_factory=MotionConfig)
    window: WindowConfig = field(default_factory=WindowConfig)
    hotkeys: HotkeysConfig = field(default_factory=HotkeysConfig)
    obs: ObsConfig = field(default_factory=ObsConfig)
    control_panel: ControlPanelConfig = field(default_factory=ControlPanelConfig)


def _merge(cls, current, overrides: dict):
    known = {f.name for f in fields(cls)}
    unknown = set(overrides) - known
    if unknown:
        raise ValueError(f"unknown {cls.__name__} setting(s): {sorted(unknown)}")
    return cls(**{**vars(current), **overrides})


def _read_config_from_file(path: Path) -> Config:
    """Raises on any parse/migrate/merge failure -- load_state below is
    the only caller, and it alone decides what to fall back to."""
    config = Config()
    with path.open() as f:
        raw = json.load(f)
    raw = _migrate_raw_config(raw)

    if "avatar_path" in raw:
        config.avatar_path = raw["avatar_path"]
    if "audio" in raw:
        config.audio = _merge(AudioConfig, config.audio, raw["audio"])
    if "motion" in raw:
        config.motion = _merge(MotionConfig, config.motion, raw["motion"])
    if "window" in raw:
        config.window = _merge(WindowConfig, config.window, raw["window"])
    if "hotkeys" in raw:
        config.hotkeys = _merge(HotkeysConfig, config.hotkeys, raw["hotkeys"])
        # JSON has no tuple type -- _merge hands back whatever list came
        # out of the file verbatim; normalize back to a tuple so this
        # field's type stays consistent regardless of load vs. default.
        #
        # Also padded/truncated to exactly NUM_COSTUMES entries here --
        # bug audit 2026-09-23, #20 ("short hotkey list crash"): nothing
        # enforced this length before, so a hand-edited settings.json
        # with fewer than 10 costume_keys left control_panel_window.py's
        # _costume_add_button_items missing the remaining slots entirely
        # -- loading an avatar with a costume_assignments entry in one
        # of those slots then raised a bare KeyError. Short lists are
        # padded from the dataclass default's own keys for the missing
        # slots (the same keys a fresh config would already have there);
        # long ones are truncated, since only NUM_COSTUMES slots exist
        # anywhere else in the app.
        keys = list(config.hotkeys.costume_keys)[:NUM_COSTUMES]
        if len(keys) < NUM_COSTUMES:
            keys += list(HotkeysConfig().costume_keys[len(keys):NUM_COSTUMES])
        config.hotkeys.costume_keys = tuple(keys)
    if "obs" in raw:
        config.obs = _merge(ObsConfig, config.obs, raw["obs"])
    if "control_panel" in raw:
        config.control_panel = _merge(ControlPanelConfig, config.control_panel, raw["control_panel"])
        # Same tuple-normalization as hotkeys.costume_keys above.
        config.control_panel.collapsed_sections = tuple(config.control_panel.collapsed_sections)
        if config.control_panel.splitter_sizes is not None:
            config.control_panel.splitter_sizes = tuple(config.control_panel.splitter_sizes)
    return config


# What _read_config_from_file can actually raise: malformed JSON,
# _merge's own ValueError on an unrecognized key, or a raw dict shaped
# unexpectedly (a hand-edited or corrupted file -- TypeError/KeyError
# from indexing into something that isn't the dict/list shape expected).
_CONFIG_LOAD_ERRORS = (OSError, ValueError, TypeError, KeyError)


def load_state(path: str | Path = DEFAULT_STATE_PATH) -> Config:
    """Falls back to `path`'s own `.bak` (save_state's own backup,
    rewritten on every save -- see its docstring) if the primary file
    fails to parse or load, and to a fresh default Config() if even
    that fails -- bug audit 2026-09-23, #12: this used to have no
    fallback at all, so a genuinely malformed or unrecognized
    settings.json crashed the whole app at startup, even with a valid
    backup sitting right next to it."""
    path = Path(path)
    if not path.exists():
        return Config()

    try:
        return _read_config_from_file(path)
    except _CONFIG_LOAD_ERRORS as exc:
        print(f"[config] failed to load {str(path)!r}: {exc}", flush=True)

    backup_path = path.with_suffix(path.suffix + ".bak")
    if backup_path.exists():
        try:
            config = _read_config_from_file(backup_path)
            print(f"[config] recovered settings from {str(backup_path)!r}", flush=True)
            return config
        except _CONFIG_LOAD_ERRORS as exc:
            print(f"[config] backup {str(backup_path)!r} also failed to load: {exc}", flush=True)

    print("[config] starting with default settings", flush=True)
    return Config()


def save_state(config: Config, path: str | Path = DEFAULT_STATE_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        _CONFIG_VERSION_KEY: CURRENT_CONFIG_VERSION,
        "avatar_path": config.avatar_path,
        "audio": asdict(config.audio),
        "motion": asdict(config.motion),
        "window": asdict(config.window),
        "hotkeys": asdict(config.hotkeys),
        "obs": asdict(config.obs),
        "control_panel": asdict(config.control_panel),
    }

    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))

    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.remove(tmp_name)
        except FileNotFoundError:
            pass
        raise
