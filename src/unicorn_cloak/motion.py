"""
Pure motion/visibility functions for the avatar rig. No Qt, no I/O, no
wall-clock reads — every function here advances by exactly one fixed
simulation tick per call and is unit-tested in isolation. The caller
(render.py) is responsible for calling these at a true fixed rate
(SIM_DT, via an accumulator decoupled from paint timing) — that's what
makes sway frequency/amplitude values mean a consistent, real-time thing
regardless of how often the app actually manages to paint.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Vec2 = tuple[float, float]

# --- Visibility -------------------------------------------------------
#
# Each sprite's talk_state/blink_state is a slot in a driver's level, not
# a boolean flag:
#   state 0 -> always visible (an ungated base/accessory layer -- body,
#              head, hair, etc. all sit here, unaffected by the driver)
#   state N (1 or 2) -> visible only when the driver's current level == N
#   state TALK_QUIET_ONLY (3, talk axis only) -> visible only when
#              talk_level == 0 ("quiet")
#
# talk_level comes from amplitude banding (see audio.update_speaking):
# 0 = quiet, 1 = mild, 2 = loud. A real closed/mild/wide mouth trio needs
# all three of quiet/mild/wide individually gated -- state 0 can't be
# reused for "closed" because it already means "always visible" (a more
# common need: hair/body/etc. that should show regardless of talk level
# at all) -- so TALK_QUIET_ONLY exists specifically to let "closed" be
# gated the same exclusive way "mild"/"wide" already are.
#
# Found in production, 2026-09-16 (owner's report: "looks like his closed
# mouth is showing beneath the opens"): the real avatar-01's closed mouth
# was authored with talk_state=0, meaning it rendered on *every* frame
# regardless of talk level -- mild/wide only ever drew on top of it, and
# wherever their art didn't fully cover the closed mouth's opaque pixels
# (confirmed empirically: ~15-17% of it, concentrated at the lip
# corners), the closed mouth visibly peeked through. TALK_QUIET_ONLY
# makes a real, mutually-exclusive trio possible without depending on
# exact art coverage at all -- the art gap is real too and worth fixing
# separately, but this is what makes correctness not depend on it.
#
# blink_level is 1 (not blinking) or 2 (blinking) -- exactly two real
# bands, both already representable via state 1/2, so blink_state has no
# equivalent gap and no third sentinel of its own.

TALK_QUIET_ONLY = 3

# Shared with editor_window.py's Talk/Blink state dropdowns and
# rig_lint.py's warning messages, so the human-facing wording only lives
# in one place. Dict order is presentation order (Always, Quiet, Mild,
# Wide), not numeric order -- TALK_QUIET_ONLY (3) reads first among the
# gated values despite having the highest int.
TALK_STATE_LABELS: dict[int, str] = {
    0: "Always visible",
    TALK_QUIET_ONLY: "Only when quiet",
    1: "Only mild",
    2: "Only wide",
}
BLINK_STATE_LABELS: dict[int, str] = {
    0: "Always visible",
    1: "Only eyes open",
    2: "Only mid-blink",
}
# The values that actually gate visibility on each axis (i.e. everything
# except "always visible") -- a real closed/mild/wide trio needs exactly
# these three talk_state values covered between its sprites; an eyes
# open/mid-blink pair needs both of these two blink_state values covered.
# Used by rig_lint.py's completeness check.
GATED_TALK_STATES: frozenset[int] = frozenset({TALK_QUIET_ONLY, 1, 2})
GATED_BLINK_STATES: frozenset[int] = frozenset({1, 2})


def axis_visible(state_value: int, active_level: int) -> bool:
    if state_value == 0:
        return True
    if state_value in (1, 2):
        return state_value == active_level
    if state_value == TALK_QUIET_ONLY:
        return active_level == 0
    raise ValueError(
        f"state_value must be 0, 1, 2, or {TALK_QUIET_ONLY}, got {state_value}"
    )


def sprite_alpha(
    talk_state: int,
    blink_state: int,
    talk_level: int,
    blink_level: int,
    edit_mode: bool,
    talk_variant: int = 0,
    active_talk_variant: int = 0,
    talk_variant_count: int = 1,
    blink_variant: int = 0,
    active_blink_variant: int = 0,
    blink_variant_count: int = 1,
    hidden: bool = False,
    manual_driven: bool = False,
    manual_active: bool = False,
) -> float:
    """1.0 if visible, 0.0 if hidden, 0.4 if hidden-but-ghosted-for-editing
    (bumped from an earlier 0.2, 2026-09-16: too faint to read as a
    deliberate outline rather than a rendering glitch).

    `hidden` (rig.Sprite.hidden) is a manual override that always wins,
    regardless of talk/blink state, variant, or manual_driven -- checked
    first, before any of the gating below.

    `manual_driven` (added 2026-09-16, for a named expression like
    "Laughing" that isn't tied to mic volume or the blink timer at all):
    when True, talk_state/blink_state and every *_variant parameter are
    ignored entirely -- visibility is exactly `manual_active`, which the
    caller computes by comparing this sprite's rig.Sprite.group_name/
    state_name against whatever's currently live-overridden for that
    group (see render.RenderWindow.manual_overrides /
    EditorWindow's own preview-only copy). Keeping that comparison out of
    this function is deliberate: sprite_alpha stays Qt-free and knows
    nothing about "groups" as a concept, just a plain bool.

    The *_variant/active_*_variant/*_variant_count triples let more than
    one sprite share the same nonzero state on a given axis and take
    turns showing -- e.g. two "mild"-open mouth shapes flapping during
    continuous speech (talk axis), or two "eyes open" shapes (wide-open,
    squint) giving idle expression some variety between blinks (blink
    axis) -- instead of all trying to show at once. See render.py's two
    independent swap timers, which are what actually advance
    active_talk_variant/active_blink_variant over time. Only applied to a
    sprite's nonzero axis with more than one sprite in that band; the
    defaults are a no-op, so every existing single-sprite-per-band caller
    is unaffected, and a sprite gated on one axis is never accidentally
    gated by the other axis's variant state.
    """
    if hidden:
        return 0.4 if edit_mode else 0.0

    if manual_driven:
        return 1.0 if manual_active else (0.4 if edit_mode else 0.0)

    visible = axis_visible(talk_state, talk_level) and axis_visible(
        blink_state, blink_level
    )
    if visible and talk_state != 0 and talk_variant_count > 1:
        visible = talk_variant == active_talk_variant
    if visible and blink_state != 0 and blink_variant_count > 1:
        visible = blink_variant == active_blink_variant
    if visible:
        return 1.0
    return 0.4 if edit_mode else 0.0


# --- Idle sway ----------------------------------------------------------


def sway_offset(tick: int, x_freq: float, x_amp: float, y_freq: float, y_amp: float) -> Vec2:
    return (math.sin(tick * x_freq) * x_amp, math.sin(tick * y_freq) * y_amp)


# --- Drag / spring lag ----------------------------------------------------


def drag_lag(current: Vec2, target: Vec2, drag_speed: float) -> Vec2:
    """One frame of exponential smoothing of `current` toward `target`.

    drag_speed == 0 means "rigid": snap straight to the target, no lag.
    Otherwise the original lerps by a factor of 1/drag_speed per frame —
    larger drag_speed means slower, laggier secondary motion.
    """
    if drag_speed == 0:
        return target
    t = 1.0 / drag_speed
    return (
        current[0] + (target[0] - current[0]) * t,
        current[1] + (target[1] - current[1]) * t,
    )


# --- Rotation & stretch (driven by this frame's drag velocity) ----------


def drag_velocity_y(
    prev_dragger_y: float,
    new_dragger_y: float,
    ignore_bounce: bool,
    bounce_delta_y: float,
) -> float:
    """Vertical "velocity" of the lagged position this frame.

    For ignore_bounce sprites, the avatar-wide speak-bounce's own
    contribution (bounce_delta_y, from bounce_step below) is subtracted
    out first, so accessories marked ignore_bounce don't rock/stretch
    from the bounce itself, only from their own independent sway/drag.
    """
    if ignore_bounce:
        prev_dragger_y = prev_dragger_y - bounce_delta_y
    return prev_dragger_y - new_dragger_y


def rotation_step(
    current_rotation_rad: float,
    velocity: float,
    rotation_drag_strength: float,
    limit_min_deg: float,
    limit_max_deg: float,
) -> float:
    target_deg = velocity * rotation_drag_strength
    target_deg = max(limit_min_deg, min(limit_max_deg, target_deg))
    target_rad = math.radians(target_deg)
    return _lerp_angle(current_rotation_rad, target_rad, 0.25)


def stretch_step(current_scale: Vec2, velocity: float, stretch_amount: float) -> Vec2:
    delta = velocity * stretch_amount * 0.01
    target = (1.0 - delta, 1.0 + delta)
    return (
        current_scale[0] + (target[0] - current_scale[0]) * 0.5,
        current_scale[1] + (target[1] - current_scale[1]) * 0.5,
    )


def _lerp_angle(current: float, target: float, t: float) -> float:
    diff = (target - current + math.pi) % (2 * math.pi) - math.pi
    return current + diff * t


# --- Avatar-wide speak bounce --------------------------------------------


@dataclass
class BounceState:
    y_velocity: float = 0.0
    y_position: float = 0.0  # always <= 0: how far the avatar has bounced up


def bounce_trigger(state: BounceState, bounce_strength: float) -> BounceState:
    """Fire one upward impulse. Caller must gate this with
    should_retrigger_bounce when re-firing on a timer during continuous
    speech -- calling it again before the previous bounce has settled
    stacks a fresh -bounce_strength velocity onto one that hasn't decayed
    yet, with no ceiling, and the avatar accelerates upward forever."""
    return BounceState(y_velocity=-bounce_strength, y_position=state.y_position)


def should_retrigger_bounce(
    state: BounceState, ticks_since_last_trigger: int, retrigger_ticks: int
) -> bool:
    """True once the bounce has settled back to rest AND the configured
    interval has elapsed -- so a short configured interval can't outrun
    the natural settle time (roughly 2*bounce_strength/gravity) and stack
    impulses. The realized cadence is max(configured interval, settle
    time), never faster."""
    at_rest = state.y_position >= -0.5 and state.y_velocity >= 0
    return at_rest and ticks_since_last_trigger >= retrigger_ticks


def bounce_step(state: BounceState, gravity: float, frame_seconds: float = 1 / 60) -> tuple[BounceState, float]:
    """One frame of the bounce-and-settle integrator.

    Returns the new state and bounce_delta_y (previous y_position minus
    new y_position) for drag_velocity_y's ignore_bounce compensation.
    """
    prev_y = state.y_position
    new_y = state.y_position + state.y_velocity * frame_seconds
    new_velocity = state.y_velocity + gravity * frame_seconds
    if new_y > 0:
        new_y = 0.0
    return BounceState(y_velocity=new_velocity, y_position=new_y), prev_y - new_y


# --- Blink timer ----------------------------------------------------------


@dataclass
class BlinkState:
    # float, not int: mirrors the original's loosely-typed blinkTick,
    # which becomes a float as soon as it's assigned `420 * blink_speed`.
    tick: float = 0.0
    blinking: bool = False


def blink_step(state: BlinkState, blink_speed: float, blink_chance: int, rand01: float, randint_mod: int) -> BlinkState:
    """One frame of the randomized blink timer.

    rand01 should be a fresh uniform-random float in [-1, 1) (only
    consumed on the frame the tick counter resets); randint_mod should be
    a fresh `random.randrange(blink_chance)` (only consumed once the
    minimum interval has elapsed). Passing them in keeps this function
    deterministic/testable instead of reaching for `random` itself.
    """
    tick = state.tick + 1
    blinking = state.blinking

    if tick == 0:
        blinking = False
        if rand01 > 0.5:
            tick = (420 * blink_speed) + 1

    if tick > 420 * blink_speed:
        if randint_mod == 0:
            blinking = True
            tick = -12

    return BlinkState(tick=tick, blinking=blinking)


# --- Sprite-sheet animation ------------------------------------------
#
# A multi-frame sprite's image is `frames` equal-width horizontal slices
# (a filmstrip); this just decides which slice is current. anim_speed is
# an honest frames-per-second value -- not a port of legacy's animation()
# formula (`max(animSpeed, max_fps*6.0)` then `tick % int(speed/animSpeed)
# == 0`), which in practice let max_fps*6.0 dominate almost always and
# made animSpeed barely do what its name implies. Every sprite currently
# in avatar-01 has frames=1, so this has never actually run against real
# content yet.


def animation_frame_step(
    current_frame: int,
    ticks_since_change: int,
    frames: int,
    anim_speed: float,
    frame_seconds: float,
) -> tuple[int, int]:
    """One fixed-timestep tick of frame cycling. Returns (frame,
    ticks_since_change). frames<=1 or anim_speed<=0 means "never advance"
    -- a static sprite."""
    if frames <= 1 or anim_speed <= 0:
        return 0, 0
    ticks_since_change += 1
    ticks_per_frame = max(1, round(1.0 / (anim_speed * frame_seconds)))
    if ticks_since_change >= ticks_per_frame:
        return (current_frame + 1) % frames, 0
    return current_frame, ticks_since_change
