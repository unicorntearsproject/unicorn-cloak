"""
Load/save avatars in PNGTuber-Plus's `.save` shape: a JSON object keyed by
stringified index, each entry a sprite with its rig metadata and its PNG
bytes embedded as base64 (`imageData`). Kept byte-shape-compatible on
purpose — the owner's real content,
`unicorn-tears-avatar-01-hoody-hair-aviator-bling.save`, already exists in
exactly this format (see ../docs/PLAN.md's "Default avatar" decision) — and
that path is the owner's only master copy of that file, not a working
copy, so `save_avatar` treats it accordingly (atomic write, one backup).

Godot's `var_to_str()` writes `Vector2`/list values as GDScript literals
(`"Vector2(0, 0)"`, `"[1, 1, 1, ...]"`) rather than plain JSON — the small
parse/format helpers below exist only to bridge that, not because this
format is otherwise unusual.

New files use `.uc` (branding) instead of `.save`; `.save` still loads
fine since the format itself is unchanged, only the conventional
extension is new -- see DEFAULT_EXTENSION/LEGACY_EXTENSION.

`hidden` (added 2026-09-16, see rig.Sprite.hidden) is another genuinely
new key with no legacy counterpart -- defaults to False on load, so every
file that predates it just loads with everything visible, as before.

`variant` (added 2026-09-16, see rig.Sprite.variant; briefly called
`talkVariant` for about one turn before blink-axis sprites needed it too,
see load_avatar's fallback) is a genuinely new key with no legacy
counterpart -- `.get("variant", ...)` on load so every file that predates
it just defaults every sprite to variant 0, which is exactly "no
alternation" until re-saved.

Format versioning (added 2026-09-16): `save_avatar` stamps a
`__format_version__` key so a future format change has something to
check against. Any file without that key (every file that predates
2026-09-16, including every real file in the wild right now) is treated
as version 0. `needs_migration()` is the check; `avatar_io.py`'s
`load_avatar_with_upgrade()` is what actually acts on it (load, re-save
in the current format, warn the owner) -- kept out of this module since
that's Qt-facing (a message box), and this module stays Qt-free.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from .motion import TALK_QUIET_ONLY
from .rig import NUM_COSTUMES, AvatarRig, Sprite

DEFAULT_EXTENSION = ".uc"
LEGACY_EXTENSION = ".save"

CURRENT_FORMAT_VERSION = 1
_FORMAT_VERSION_KEY = "__format_version__"
# Rig-level (not per-sprite) metadata, added 2026-09-17 for the costume/
# Expression hotkey editors -- see rig.AvatarRig's own comments on
# costume_assignments/expression_hotkeys. Excluded from sprite_keys below
# exactly like _FORMAT_VERSION_KEY, for the same reason: load_avatar sorts
# sprite_keys with `key=int`, which would crash on a non-numeric key.
_COSTUME_ASSIGNMENTS_KEY = "__costume_assignments__"
_EXPRESSION_HOTKEYS_KEY = "__expression_hotkeys__"
# Added 2026-09-19 when AvatarRig.zoom moved here from WindowConfig (see
# that field's own comment) -- absent on every file saved before today,
# defaults to 1.0 (native size) on load, same pattern as the other
# rig-level keys above.
_ZOOM_KEY = "__zoom__"
# Per-avatar Behavior/Audio tab tuning (2026-10-02) -- see rig.AvatarRig.
# Absent from every file saved before today; load leaves them None.
_MOTION_KEY = "__motion__"
_AUDIO_PROFILES_KEY = "__audio_profiles__"
_NON_SPRITE_KEYS = {
    _FORMAT_VERSION_KEY, _COSTUME_ASSIGNMENTS_KEY, _EXPRESSION_HOTKEYS_KEY, _ZOOM_KEY,
    _MOTION_KEY, _AUDIO_PROFILES_KEY,
}

_VEC2_RE = re.compile(r"Vector2\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)")


def parse_vector2(value: str) -> tuple[float, float]:
    match = _VEC2_RE.match(value.strip())
    if not match:
        raise ValueError(f"not a Vector2 string: {value!r}")
    return (float(match.group(1)), float(match.group(2)))


def format_vector2(value: tuple[float, float]) -> str:
    return f"Vector2({_format_number(value[0])}, {_format_number(value[1])})"


def _format_number(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else str(n)


_VALID_AXIS_STATES = (0, 1, 2, TALK_QUIET_ONLY)


def _normalize_axis_state(value: int) -> int:
    """showTalk/showBlink accept any int on disk, but motion.axis_visible
    only understands 0, 1, 2, or TALK_QUIET_ONLY (3) -- anything else
    raises ValueError, and it's called on *every paint frame*, so an
    out-of-range value (a hand-edited file, or a future format this
    version doesn't know yet) froze the Render Window instead of
    loading with a sane fallback. Bug audit 2026-09-23, #20
    ("unvalidated state values"). 0 ("always visible") is the same safe
    default this loader already uses for a missing key entirely."""
    return value if value in _VALID_AXIS_STATES else 0


def _normalize_costume_layers(raw_json: str | None) -> tuple[bool, ...]:
    """The legacy loader pads a too-short costumeLayers list rather than
    rejecting it (`if size < 8: append 1 five times` -- sloppy, but it
    never crashes on an older or hand-edited file). Sprite.__post_init__
    is strict on purpose for sprites this app constructs itself, so an
    out-of-range list has to be normalized *before* it gets there, or
    loading a legitimately-old-or-hand-edited file raises instead of
    loading with a sane default."""
    if not raw_json:
        return tuple([True] * NUM_COSTUMES)
    values = [bool(v) for v in json.loads(raw_json)]
    if len(values) < NUM_COSTUMES:
        values = values + [True] * (NUM_COSTUMES - len(values))
    elif len(values) > NUM_COSTUMES:
        values = values[:NUM_COSTUMES]
    return tuple(values)


def needs_migration(path: str | Path) -> bool:
    """True if this file predates format versioning, or is behind the
    current version. Doesn't load the avatar -- just checks the stamp --
    so a caller can decide what to warn about before load_avatar runs."""
    with Path(path).open() as f:
        raw = json.load(f)
    return raw.get(_FORMAT_VERSION_KEY, 0) < CURRENT_FORMAT_VERSION


def load_avatar(path: str | Path, name: str | None = None) -> AvatarRig:
    path = Path(path)
    with path.open() as f:
        raw = json.load(f)

    sprite_keys = [k for k in raw if k not in _NON_SPRITE_KEYS]
    sprites = []
    for key in sorted(sprite_keys, key=int):
        entry = raw[key]
        if entry.get("type") != "sprite":
            continue

        image_b64 = entry.get("imageData")

        sprites.append(
            Sprite(
                id=entry["identification"],
                path=entry["path"],
                parent_id=entry.get("parentId"),
                image_data=base64.b64decode(image_b64) if image_b64 else None,
                position=parse_vector2(entry["pos"]),
                offset=parse_vector2(entry.get("offset", "Vector2(0, 0)")),
                z_index=entry.get("zindex", 0),
                # New 2026-09-17, absent from every file saved before
                # today -- default to 1.0 (native size) so an older file
                # loads showing exactly what it always did.
                scale_x=entry.get("scaleX", 1.0),
                scale_y=entry.get("scaleY", 1.0),
                # New 2026-09-17, same reasoning as scaleX/Y above -- an
                # older file has no authored rotation, so 0.0 (unrotated)
                # reproduces exactly what it always showed.
                rotation_deg=entry.get("rotationDeg", 0.0),
                sway_x_freq=entry.get("xFrq", 0.0),
                sway_x_amp=entry.get("xAmp", 0.0),
                sway_y_freq=entry.get("yFrq", 0.0),
                sway_y_amp=entry.get("yAmp", 0.0),
                drag_speed=entry.get("drag", 0.0),
                rotation_drag_strength=entry.get("rotDrag", 0.0),
                rotation_limit_min_deg=entry.get("rLimitMin", -180.0),
                rotation_limit_max_deg=entry.get("rLimitMax", 180.0),
                stretch_amount=entry.get("stretchAmount", 0.0),
                ignore_bounce=bool(entry.get("ignoreBounce", False)),
                frames=entry.get("frames", 1),
                anim_speed=entry.get("animSpeed", 0.0),
                talk_state=_normalize_axis_state(entry.get("showTalk", 0)),
                blink_state=_normalize_axis_state(entry.get("showBlink", 0)),
                # "talkVariant" was this key's name for about one turn
                # before blink-axis sprites needed the same field --
                # falling back to it means the handful of sprites already
                # saved under that name (one real file) don't silently
                # lose their alternation grouping the next time they load.
                variant=entry.get("variant", entry.get("talkVariant", 0)),
                costume_layers=_normalize_costume_layers(entry.get("costumeLayers")),
                clipped=bool(entry.get("clipped", False)),
                toggle=entry.get("toggle", "null"),
                hidden=bool(entry.get("hidden", False)),
                locked=bool(entry.get("locked", False)),
                # New 2026-09-16, absent from every file saved before
                # today (including legacy PNGTuber-Plus's own format) --
                # default to "not grouped, not manually driven" so an
                # older file loads with identical behavior to before
                # these fields existed.
                group_name=entry.get("groupName", ""),
                state_name=entry.get("stateName", ""),
                manual_driven=bool(entry.get("manualDriven", False)),
            )
        )

    return AvatarRig(
        name=name or path.stem,
        sprites=sprites,
        costume_assignments=_normalize_slot_pairs(raw.get(_COSTUME_ASSIGNMENTS_KEY)),
        expression_hotkeys=_normalize_slot_pairs(raw.get(_EXPRESSION_HOTKEYS_KEY)),
        zoom=raw.get(_ZOOM_KEY, 1.0),
        motion=raw.get(_MOTION_KEY) if isinstance(raw.get(_MOTION_KEY), dict) else None,
        audio_profiles=(
            raw.get(_AUDIO_PROFILES_KEY) if isinstance(raw.get(_AUDIO_PROFILES_KEY), dict) else None
        ),
    )


def _normalize_slot_pairs(raw_slots: list | None) -> list[list[tuple]]:
    """Shared by costume_assignments/expression_hotkeys -- both are a
    per-slot (NUM_COSTUMES-length) list of pairs, JSON round-tripping
    each pair as a 2-element list (JSON has no tuple type) that needs
    turning back into an actual tuple. Absent (a file saved before this
    feature existed) or short/long normalizes the same way
    _normalize_costume_layers does, for the same reason: never raise on
    an older or hand-edited file."""
    result: list[list[tuple]] = [[] for _ in range(NUM_COSTUMES)]
    if not raw_slots:
        return result
    for slot, pairs in enumerate(raw_slots[:NUM_COSTUMES]):
        result[slot] = [tuple(pair) for pair in pairs]
    return result


MAX_TIMESTAMPED_BACKUPS = 10
_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S-%f"


def _timestamped_backup_re(path: Path) -> re.Pattern:
    return re.compile(rf"^{re.escape(path.name)}\.\d{{8}}-\d{{6}}-\d{{6}}\.bak$")


def timestamped_backups(path: str | Path) -> list[Path]:
    """This avatar's timestamped backups, oldest first (the timestamp
    format sorts lexically in time order)."""
    path = Path(path)
    pattern = _timestamped_backup_re(path)
    if not path.parent.is_dir():
        return []
    return sorted(p for p in path.parent.iterdir() if pattern.match(p.name))


def _write_timestamped_backup(path: Path) -> None:
    """Quick-win enhancement E11 (bug audit addendum 2026-09-23): a
    history of the last MAX_TIMESTAMPED_BACKUPS versions, alongside --
    not instead of -- the rolling `<file>.bak`. The rolling one stays
    because it's the single predictable place avatar_io's upgrade
    message and the Help text point to; this adds the history it lacked
    (every save used to overwrite the only backup, so two bad saves in a
    row lost the last good version for good). Named
    `<file>.<YYYYMMDD-HHMMSS-micros>.bak` -- the trailing `.bak` keeps
    them under .gitignore's existing `*.bak` rule (the bundled demo
    avatar lives inside this repo), and microseconds keep two saves in
    the same second from colliding."""
    stamp = datetime.now().strftime(_TIMESTAMP_FORMAT)
    shutil.copy2(path, path.with_name(f"{path.name}.{stamp}.bak"))
    backups = timestamped_backups(path)
    for old in backups[:-MAX_TIMESTAMPED_BACKUPS]:
        try:
            old.unlink()
        except OSError:
            pass


def save_avatar(rig: AvatarRig, path: str | Path) -> None:
    path = Path(path)
    out = {
        _FORMAT_VERSION_KEY: CURRENT_FORMAT_VERSION,
        _COSTUME_ASSIGNMENTS_KEY: rig.costume_assignments,
        _EXPRESSION_HOTKEYS_KEY: rig.expression_hotkeys,
        _ZOOM_KEY: rig.zoom,
    }
    if rig.motion is not None:
        out[_MOTION_KEY] = rig.motion
    if rig.audio_profiles is not None:
        out[_AUDIO_PROFILES_KEY] = rig.audio_profiles
    for i, sprite in enumerate(rig.sprites):
        out[str(i)] = {
            "type": "sprite",
            "path": sprite.path,
            "imageData": (
                base64.b64encode(sprite.image_data).decode("ascii")
                if sprite.image_data
                else None
            ),
            "identification": sprite.id,
            "parentId": sprite.parent_id,
            "pos": format_vector2(sprite.position),
            "offset": format_vector2(sprite.offset),
            "zindex": sprite.z_index,
            "scaleX": sprite.scale_x,
            "scaleY": sprite.scale_y,
            "rotationDeg": sprite.rotation_deg,
            "drag": sprite.drag_speed,
            "xFrq": sprite.sway_x_freq,
            "xAmp": sprite.sway_x_amp,
            "yFrq": sprite.sway_y_freq,
            "yAmp": sprite.sway_y_amp,
            "rotDrag": sprite.rotation_drag_strength,
            "showTalk": sprite.talk_state,
            "showBlink": sprite.blink_state,
            "variant": sprite.variant,
            "rLimitMin": sprite.rotation_limit_min_deg,
            "rLimitMax": sprite.rotation_limit_max_deg,
            "costumeLayers": json.dumps([int(b) for b in sprite.costume_layers]),
            "stretchAmount": sprite.stretch_amount,
            "ignoreBounce": sprite.ignore_bounce,
            "frames": sprite.frames,
            "animSpeed": sprite.anim_speed,
            "clipped": sprite.clipped,
            "toggle": sprite.toggle,
            "hidden": sprite.hidden,
            "locked": sprite.locked,
            "groupName": sprite.group_name,
            "stateName": sprite.state_name,
            "manualDriven": sprite.manual_driven,
        }

    # Atomic write (temp file + os.replace) plus one backup of whatever
    # was there before -- the default avatar path is the owner's only
    # master copy of that file, not a working copy, so a crash mid-write
    # or an unwanted overwrite must not be able to destroy it with
    # nothing to recover from.
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        _write_timestamped_backup(path)

    # Existing permissions preserved explicitly -- bug audit 2026-09-23,
    # #20 ("permissions and symlinks"). mkstemp always creates its file
    # 0600 regardless of whatever mode the real target already has, and
    # os.replace's rename doesn't carry the *old* file's permissions
    # over the *new* one -- so a first save through this app silently
    # tightened an avatar file's permissions to owner-only, even one
    # authored (and left more permissive, e.g. group-readable) by
    # another tool or hand-edited beforehand. Read before the file is
    # replaced, obviously.
    original_mode = path.stat().st_mode if path.exists() else None

    # Write through a symlink's real target, not the link itself -- same
    # finding (#20, "permissions and symlinks"). os.replace(tmp, path)
    # replaces whatever `path` itself names; for a symlink (e.g. an
    # avatar file pointed at a synced/shared location) that's the link,
    # not its target, so the very first save silently replaced the link
    # with a plain regular file. The temp file also has to live in the
    # *real* target's directory, not the symlink's own -- os.replace
    # requires both sides on the same filesystem to stay atomic, and a
    # symlink can legitimately point across a mount boundary. The .bak
    # backup above deliberately stays keyed on `path` (the symlink's own
    # location) -- that's where the owner would actually look for it.
    write_path = path.resolve() if path.is_symlink() else path

    fd, tmp_name = tempfile.mkstemp(dir=write_path.parent, prefix=f".{write_path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(out, f)
            f.flush()
            os.fsync(f.fileno())
        if original_mode is not None:
            os.chmod(tmp_name, original_mode)
        os.replace(tmp_name, write_path)
    except BaseException:
        try:
            os.remove(tmp_name)
        except FileNotFoundError:
            pass
        raise
