import math

import pytest

from unicorn_cloak.motion import (
    TALK_QUIET_ONLY,
    BlinkState,
    BounceState,
    animation_frame_step,
    axis_visible,
    blink_step,
    bounce_step,
    bounce_trigger,
    drag_lag,
    drag_velocity_y,
    rotation_step,
    should_retrigger_bounce,
    sprite_alpha,
    stretch_step,
    sway_offset,
)


def test_axis_visible_state_zero_is_always_shown():
    for level in (0, 1, 2):
        assert axis_visible(0, level) is True


def test_axis_visible_nonzero_is_exact_match_only():
    assert axis_visible(1, active_level=1) is True
    assert axis_visible(1, active_level=2) is False
    assert axis_visible(1, active_level=0) is False
    assert axis_visible(2, active_level=2) is True
    assert axis_visible(2, active_level=1) is False


def test_axis_visible_talk_quiet_only_shows_only_at_level_zero():
    # The fix for a real bug (2026-09-16): a closed mouth authored with
    # state 0 rendered on every frame regardless of talk level, since 0
    # means "always visible" -- TALK_QUIET_ONLY is what actually lets a
    # closed/mild/wide trio be mutually exclusive.
    assert axis_visible(TALK_QUIET_ONLY, active_level=0) is True
    assert axis_visible(TALK_QUIET_ONLY, active_level=1) is False
    assert axis_visible(TALK_QUIET_ONLY, active_level=2) is False


def test_axis_visible_rejects_bad_state():
    with pytest.raises(ValueError):
        axis_visible(4, 1)


def test_sprite_alpha_three_band_mouth():
    # closed/mild/wide mouth trio: talk_state 0/1/2, always-open eyes
    # (blink_state 0), never mid-blink (blink_level 1).
    assert sprite_alpha(0, 0, talk_level=0, blink_level=1, edit_mode=False) == 1.0
    assert sprite_alpha(1, 0, talk_level=0, blink_level=1, edit_mode=False) == 0.0
    assert sprite_alpha(1, 0, talk_level=1, blink_level=1, edit_mode=False) == 1.0
    assert sprite_alpha(1, 0, talk_level=2, blink_level=1, edit_mode=False) == 0.0
    assert sprite_alpha(2, 0, talk_level=2, blink_level=1, edit_mode=False) == 1.0
    assert sprite_alpha(2, 0, talk_level=1, blink_level=1, edit_mode=False) == 0.0


def test_sprite_alpha_blink_axis_independent_of_talk_axis():
    # blink-closed sprite (blink_state=2) only shows mid-blink, regardless
    # of what the mouth is doing.
    assert sprite_alpha(0, 2, talk_level=2, blink_level=2, edit_mode=False) == 1.0
    assert sprite_alpha(0, 2, talk_level=2, blink_level=1, edit_mode=False) == 0.0


def test_sprite_alpha_ghosts_hidden_sprites_in_edit_mode():
    assert sprite_alpha(2, 0, talk_level=0, blink_level=1, edit_mode=True) == 0.4
    assert sprite_alpha(2, 0, talk_level=0, blink_level=1, edit_mode=False) == 0.0


def test_sprite_alpha_variant_defaults_are_a_no_op():
    # A talk_state with only one sprite in its band (the overwhelmingly
    # common case, and every rig before 2026-09-16) must behave exactly
    # like before variants existed, with no need to pass the new params.
    assert sprite_alpha(1, 0, talk_level=1, blink_level=1, edit_mode=False) == 1.0


def test_sprite_alpha_variant_gating_within_an_active_band():
    # Two sprites share talk_state=1 (e.g. two "mild" mouths): only the
    # one matching the currently active variant shows.
    common = dict(talk_state=1, blink_state=0, talk_level=1, blink_level=1, edit_mode=False)
    assert sprite_alpha(**common, talk_variant=0, active_talk_variant=0, talk_variant_count=2) == 1.0
    assert sprite_alpha(**common, talk_variant=1, active_talk_variant=0, talk_variant_count=2) == 0.0
    assert sprite_alpha(**common, talk_variant=1, active_talk_variant=1, talk_variant_count=2) == 1.0


def test_sprite_alpha_variant_gating_only_applies_to_the_talk_axis():
    # A base sprite (talk_state=0, always shown) must never be gated by
    # variant, even if it's handed nonsense variant params -- state 0 is
    # unconditional, full stop.
    assert sprite_alpha(
        0, 0, talk_level=1, blink_level=1, edit_mode=False,
        talk_variant=0, active_talk_variant=1, talk_variant_count=2,
    ) == 1.0


def test_sprite_alpha_variant_ghosts_in_edit_mode_like_any_other_gate():
    assert sprite_alpha(
        1, 0, talk_level=1, blink_level=1, edit_mode=True,
        talk_variant=1, active_talk_variant=0, talk_variant_count=2,
    ) == 0.4


def test_sprite_alpha_blink_variant_gating_within_an_active_band():
    # Same idea as the talk-axis variant tests, but for two sprites
    # sharing blink_state=1 (e.g. wide-open and squint "eyes open" shapes).
    common = dict(talk_state=0, blink_state=1, talk_level=0, edit_mode=False)
    assert sprite_alpha(**common, blink_level=1, blink_variant=0, active_blink_variant=0, blink_variant_count=2) == 1.0
    assert sprite_alpha(**common, blink_level=1, blink_variant=1, active_blink_variant=0, blink_variant_count=2) == 0.0
    assert sprite_alpha(**common, blink_level=1, blink_variant=1, active_blink_variant=1, blink_variant_count=2) == 1.0


def test_sprite_alpha_hidden_overrides_everything():
    # hidden=True must win even when every other gate would show the
    # sprite (state 0, matching variant, etc.) -- it's a manual override,
    # not just another band.
    assert sprite_alpha(0, 0, talk_level=0, blink_level=1, edit_mode=False, hidden=True) == 0.0
    assert sprite_alpha(
        1, 0, talk_level=1, blink_level=1, edit_mode=False,
        talk_variant=0, active_talk_variant=0, talk_variant_count=1, hidden=True,
    ) == 0.0


def test_sprite_alpha_hidden_ghosts_in_edit_mode():
    assert sprite_alpha(0, 0, talk_level=0, blink_level=1, edit_mode=True, hidden=True) == 0.4


def test_sprite_alpha_talk_and_blink_variants_are_independent():
    # A sprite gated on the talk axis must never be gated by blink-variant
    # state, and vice versa -- each *_variant_count only matters for its
    # own axis's nonzero state.
    assert sprite_alpha(
        1, 0, talk_level=1, blink_level=1, edit_mode=False,
        talk_variant=0, active_talk_variant=0, talk_variant_count=1,
        blink_variant=0, active_blink_variant=1, blink_variant_count=2,
    ) == 1.0


def test_sprite_alpha_manual_driven_ignores_talk_and_blink_state_entirely():
    # talk_state=1/blink_state=1 would normally require talk_level==1 and
    # blink_level==1 -- manual_driven bypasses both, using only
    # manual_active.
    assert sprite_alpha(
        1, 1, talk_level=0, blink_level=2, edit_mode=False,
        manual_driven=True, manual_active=True,
    ) == 1.0
    assert sprite_alpha(
        1, 1, talk_level=1, blink_level=1, edit_mode=False,
        manual_driven=True, manual_active=False,
    ) == 0.0


def test_sprite_alpha_manual_driven_ghosts_in_edit_mode_when_inactive():
    assert sprite_alpha(
        0, 0, talk_level=0, blink_level=1, edit_mode=True,
        manual_driven=True, manual_active=False,
    ) == 0.4


def test_sprite_alpha_hidden_overrides_manual_driven():
    assert sprite_alpha(
        0, 0, talk_level=0, blink_level=1, edit_mode=False,
        manual_driven=True, manual_active=True, hidden=True,
    ) == 0.0


def test_sway_offset_is_sinusoidal():
    assert sway_offset(0, x_freq=0.1, x_amp=10, y_freq=0.2, y_amp=5) == (0.0, 0.0)
    x, y = sway_offset(10, x_freq=0.1, x_amp=10, y_freq=0.2, y_amp=5)
    assert x == pytest.approx(math.sin(1.0) * 10)
    assert y == pytest.approx(math.sin(2.0) * 5)


def test_drag_lag_snaps_when_drag_speed_zero():
    assert drag_lag((0, 0), (100, 50), drag_speed=0) == (100, 50)


def test_drag_lag_chases_target_gradually():
    pos = (0.0, 0.0)
    target = (100.0, 0.0)
    pos = drag_lag(pos, target, drag_speed=4)
    assert 0 < pos[0] < 100
    # keep chasing a fixed target -> converges
    for _ in range(200):
        pos = drag_lag(pos, target, drag_speed=4)
    assert pos[0] == pytest.approx(100.0, abs=0.01)


def test_drag_velocity_y_plain():
    assert drag_velocity_y(10.0, 6.0, ignore_bounce=False, bounce_delta_y=99) == 4.0


def test_drag_velocity_y_cancels_bounce_when_ignored():
    # prev=10, bounce moved things by 4 this frame, new=6
    # ignoring bounce: adjusted_prev = 10 - 4 = 6; velocity = 6 - 6 = 0
    assert drag_velocity_y(10.0, 6.0, ignore_bounce=True, bounce_delta_y=4.0) == 0.0


def test_rotation_step_clamps_to_limits():
    r = rotation_step(
        current_rotation_rad=0.0,
        velocity=1000.0,
        rotation_drag_strength=1.0,
        limit_min_deg=-10.0,
        limit_max_deg=10.0,
    )
    assert r == pytest.approx(math.radians(10.0) * 0.25)


def test_stretch_step_moves_toward_target():
    scale = stretch_step((1.0, 1.0), velocity=10.0, stretch_amount=1.0)
    # delta = 10 * 1.0 * 0.01 = 0.1 -> target (0.9, 1.1), lerp 0.5
    assert scale == pytest.approx((0.95, 1.05))


def test_bounce_trigger_sets_upward_velocity():
    state = bounce_trigger(BounceState(), bounce_strength=250)
    assert state.y_velocity == -250


def test_bounce_step_settles_back_to_zero():
    state = bounce_trigger(BounceState(), bounce_strength=250)
    seen_negative = False
    for _ in range(500):
        state, _ = bounce_step(state, gravity=1000)
        if state.y_position < 0:
            seen_negative = True
        assert state.y_position <= 0
    assert seen_negative


def test_bounce_step_settles_even_with_zero_gravity():
    # Regression, bug audit 2026-09-23 (#13): gravity=0 is allowed by
    # the Behavior tab's own Gravity field (range used to start at 0.0)
    # -- with no floor inside bounce_step, y_velocity never decayed at
    # all, so the avatar's very first speak-bounce drifted permanently
    # off-screen (~2,500px within 10s) instead of settling, and
    # should_retrigger_bounce (gated on "at rest") never fired again.
    state = bounce_trigger(BounceState(), bounce_strength=250)
    settled = False
    for _ in range(10 * 60):  # 10 simulated seconds at 60fps
        state, _ = bounce_step(state, gravity=0.0)
        if should_retrigger_bounce(state, ticks_since_last_trigger=10_000, retrigger_ticks=1):
            settled = True
            break
    assert settled
    assert state.y_position > -3000  # nowhere near the old unbounded drift


def test_bounce_step_settles_even_with_negative_gravity():
    # Only reachable via a hand-edited settings.json (the UI's own
    # range floors at a positive minimum) -- motion.bounce_step floors
    # it independently regardless of how an out-of-range value arrives.
    state = bounce_trigger(BounceState(), bounce_strength=250)
    settled = False
    for _ in range(10 * 60):
        state, _ = bounce_step(state, gravity=-500.0)
        if should_retrigger_bounce(state, ticks_since_last_trigger=10_000, retrigger_ticks=1):
            settled = True
            break
    assert settled


def test_should_retrigger_bounce_waits_for_settle_not_just_elapsed_time():
    # Regression: retrigger_ticks shorter than the natural settle time
    # (~2*bounce_strength/gravity) must not fire mid-flight -- doing so
    # stacks a fresh impulse on unsettled velocity with no ceiling and
    # the avatar never comes back down (observed live 2026-09-15).
    bounce_strength, gravity = 250.0, 1000.0
    frame_seconds = 1 / 60
    retrigger_ticks = 9  # ~150ms @ 60fps, shorter than the ~500ms settle time

    state = bounce_trigger(BounceState(), bounce_strength)
    ticks_since_trigger = 0
    max_frames = 10 * 60  # 10 simulated seconds is plenty to expose runaway drift

    for _ in range(max_frames):
        state, _ = bounce_step(state, gravity, frame_seconds)
        ticks_since_trigger += 1
        if should_retrigger_bounce(state, ticks_since_trigger, retrigger_ticks):
            state = bounce_trigger(state, bounce_strength)
            ticks_since_trigger = 0
        # The old bug: this would drift arbitrarily far negative (upward)
        # over time, unbounded. With the settle gate, it must stay within
        # roughly one bounce's worth of travel (+ a few px of discrete-step
        # overshoot past the analytical peak) -- not accumulate across
        # repeated retriggers.
        assert state.y_position >= -(bounce_strength**2) / (2 * gravity) - 5.0


def test_should_retrigger_bounce_false_mid_flight():
    state = bounce_trigger(BounceState(), bounce_strength=250)
    state, _ = bounce_step(state, gravity=1000)  # one frame in, still rising
    assert should_retrigger_bounce(state, ticks_since_last_trigger=999, retrigger_ticks=1) is False


def test_should_retrigger_bounce_true_once_settled_and_interval_elapsed():
    state = BounceState()  # already at rest
    assert should_retrigger_bounce(state, ticks_since_last_trigger=10, retrigger_ticks=9) is True
    assert should_retrigger_bounce(state, ticks_since_last_trigger=5, retrigger_ticks=9) is False
    assert state.y_position == pytest.approx(0.0)


def test_blink_step_eventually_blinks():
    state = BlinkState()
    blinked = False
    for _ in range(2000):
        # rand01 fixed low so the "skip ahead" branch never fires;
        # randint_mod fixed at 0 so a blink fires as soon as eligible.
        state = blink_step(
            state, blink_speed=1.0, blink_chance=200, rand01=-1.0, randint_mod=0
        )
        if state.blinking:
            blinked = True
            break
    assert blinked


def test_animation_frame_step_static_when_frames_is_one():
    # This is the state of every sprite in avatar-01 today.
    frame, ticks = animation_frame_step(
        current_frame=0, ticks_since_change=0, frames=1, anim_speed=5.0, frame_seconds=1 / 60
    )
    assert (frame, ticks) == (0, 0)


def test_animation_frame_step_static_when_anim_speed_is_zero():
    frame, ticks = animation_frame_step(
        current_frame=0, ticks_since_change=0, frames=4, anim_speed=0.0, frame_seconds=1 / 60
    )
    assert (frame, ticks) == (0, 0)


def test_animation_frame_step_advances_at_configured_rate():
    # anim_speed=10 fps at 60Hz sim -> 6 ticks per frame
    frame, ticks = 0, 0
    frames_seen = []
    for _ in range(18):  # 3 frame-changes' worth
        frame, ticks = animation_frame_step(frame, ticks, frames=3, anim_speed=10.0, frame_seconds=1 / 60)
        frames_seen.append(frame)
    # advances on ticks 6, 12, 18 (1-indexed) -> frame becomes 1, 2, 0
    assert frames_seen[5] == 1
    assert frames_seen[11] == 2
    assert frames_seen[17] == 0


def test_animation_frame_step_loops():
    frame, ticks = 2, 0  # already at the last of 3 frames
    frame, ticks = animation_frame_step(frame, 999, frames=3, anim_speed=10.0, frame_seconds=1 / 60)
    assert frame == 0
