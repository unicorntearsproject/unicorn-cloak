from pathlib import Path

import pytest

from unicorn_cloak import motion
from unicorn_cloak.avatar_io import load_avatar_with_upgrade
from unicorn_cloak.config import DEFAULT_AVATAR_PATH
from unicorn_cloak.rig import AvatarRig, Sprite
from unicorn_cloak.rig_lint import find_rig_issues


def _rig(sprites) -> AvatarRig:
    return AvatarRig(name="t", sprites=sprites)


def test_a_complete_correct_trio_has_no_issues():
    rig = _rig([
        Sprite(id=1, path="closed.png", group_name="Mouth", state_name="Closed", talk_state=motion.TALK_QUIET_ONLY),
        Sprite(id=2, path="mild.png", group_name="Mouth", state_name="Mild", talk_state=1),
        Sprite(id=3, path="wide.png", group_name="Mouth", state_name="Wide", talk_state=2),
    ])
    assert find_rig_issues(rig) == []


def test_a_talk_state_zero_mouth_is_not_itself_flagged_as_incomplete():
    # state 0 ("always visible") is correct and common for non-mouth
    # sprites -- it must never be treated as "using" the talk axis.
    rig = _rig([Sprite(id=1, path="hair.png", talk_state=0)])
    assert find_rig_issues(rig) == []


def test_missing_quiet_state_in_a_talk_trio_is_flagged():
    rig = _rig([
        Sprite(id=1, path="mild.png", group_name="Mouth", state_name="Mild", talk_state=1),
        Sprite(id=2, path="wide.png", group_name="Mouth", state_name="Wide", talk_state=2),
    ])
    issues = find_rig_issues(rig)
    assert len(issues) == 1
    assert "Only when quiet" in issues[0].message
    assert set(issues[0].sprite_ids) == {1, 2}


def test_missing_blink_state_is_flagged_independently_of_talk():
    rig = _rig([
        Sprite(id=1, path="open.png", group_name="Eyes", state_name="Open", blink_state=1),
    ])
    issues = find_rig_issues(rig)
    assert len(issues) == 1
    assert "Only mid-blink" in issues[0].message


def test_variant_collision_is_flagged():
    rig = _rig([
        Sprite(id=1, path="mild-a.png", group_name="Mouth", state_name="Mild", talk_state=1, variant=0),
        Sprite(id=2, path="mild-b.png", group_name="Mouth", state_name="Mild", talk_state=1, variant=0),
    ])
    issues = find_rig_issues(rig)
    assert any("Variant 0" in i.message for i in issues)


def test_distinct_variants_sharing_a_state_are_not_flagged():
    rig = _rig([
        Sprite(id=1, path="mild-a.png", group_name="Mouth", state_name="Mild", talk_state=1, variant=0),
        Sprite(id=2, path="mild-b.png", group_name="Mouth", state_name="Mild", talk_state=1, variant=1),
        Sprite(id=3, path="closed.png", group_name="Mouth", state_name="Closed", talk_state=motion.TALK_QUIET_ONLY),
        Sprite(id=4, path="wide.png", group_name="Mouth", state_name="Wide", talk_state=2),
    ])
    assert find_rig_issues(rig) == []


def test_manual_driven_without_group_or_state_is_flagged():
    rig = _rig([Sprite(id=1, path="laugh.png", manual_driven=True)])
    issues = find_rig_issues(rig)
    assert len(issues) == 1
    assert "never show" in issues[0].message
    assert issues[0].sprite_ids == (1,)


def test_manual_driven_with_group_and_state_is_not_flagged():
    rig = _rig([
        Sprite(id=1, path="laugh.png", group_name="Mouth", state_name="Laughing", manual_driven=True),
    ])
    assert find_rig_issues(rig) == []


def test_manual_driven_sprites_are_excluded_from_axis_completeness_checks():
    # A manual-driven sprite with a leftover nonzero talk_state (e.g. from
    # before it was switched to manual) must not count toward -- or be
    # flagged for -- talk-axis completeness.
    rig = _rig([
        Sprite(
            id=1, path="laugh.png", group_name="Mouth", state_name="Laughing",
            manual_driven=True, talk_state=1,
        ),
    ])
    assert find_rig_issues(rig) == []


def test_inconsistent_state_labeling_is_flagged():
    rig = _rig([
        Sprite(id=1, path="a.png", group_name="Mouth", state_name="Closed", talk_state=motion.TALK_QUIET_ONLY),
        Sprite(id=2, path="b.png", group_name="Mouth", state_name="Closed", talk_state=1),  # mismatched
    ])
    issues = find_rig_issues(rig)
    assert any("copy-paste" in i.message for i in issues)


def test_consistent_state_labeling_across_variants_is_not_flagged():
    rig = _rig([
        Sprite(id=1, path="a.png", group_name="Mouth", state_name="Mild", talk_state=1, variant=0),
        Sprite(id=2, path="b.png", group_name="Mouth", state_name="Mild", talk_state=1, variant=1),
        Sprite(id=3, path="closed.png", group_name="Mouth", state_name="Closed", talk_state=motion.TALK_QUIET_ONLY),
        Sprite(id=4, path="wide.png", group_name="Mouth", state_name="Wide", talk_state=2),
    ])
    assert find_rig_issues(rig) == []


def test_ungrouped_sprites_fall_back_to_parent_id_bucketing():
    # No group_name set on any of these -- the parent_id heuristic should
    # still catch a real completeness gap, matching legacy/ungrouped
    # content authored before Group name existed.
    rig = _rig([
        Sprite(id=1, path="mild.png", parent_id=None, talk_state=1),
        Sprite(id=2, path="wide.png", parent_id=None, talk_state=2),
    ])
    issues = find_rig_issues(rig)
    assert any("Only when quiet" in i.message for i in issues)


def test_the_real_default_avatar_has_no_issues(qapp, tmp_path):
    # End-to-end sanity check against the shipped default avatar
    # (unicorn-demo, replaced 2026-09-17) -- confirms its real Group/State
    # tagging (Mouth/Eyes, fully wired per the owner's request) is actually
    # complete and consistent, not just superficially plausible. Package-
    # relative now (see config.py's own DEFAULT_AVATAR_PATH comment), so
    # this always runs rather than skip -- the guard stays as a defensive
    # fallback for a stripped/partial checkout, not the common case.
    if not Path(DEFAULT_AVATAR_PATH).exists():
        pytest.skip("default avatar not present on this machine")
    rig = load_avatar_with_upgrade(DEFAULT_AVATAR_PATH)
    assert find_rig_issues(rig) == []
