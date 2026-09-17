"""
A heuristic sanity-check pass over an AvatarRig's talk/blink/group
assignments -- surfaces likely mistakes for a human to review, not a hard
validator with a single correct answer. Built 2026-09-16 after the owner
pointed out there was no way to tell whether a set of sprites (e.g. a
mouth trio) was actually correctly configured, or just coincidentally
working out (which is exactly what let the mouth-stacking bug go
unnoticed -- see motion.TALK_QUIET_ONLY's docstring).

Sprites are bucketed by `group_name` when set (the explicit, reliable
signal -- see rig.Sprite's own comment), falling back to `parent_id` for
older/ungrouped content that predates group_name entirely. The parent_id
fallback is a real heuristic, not a guarantee: sprites that happen to
share a parent but aren't actually related (e.g. every root-level sprite
in a rig with a flat hierarchy) get bucketed together too -- harmless for
the checks here, since they only ever look at sprites that are already
gated (state != 0) or already labeled, never at ungated/unlabeled ones.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import motion
from .rig import AvatarRig, Sprite


@dataclass
class RigIssue:
    message: str
    sprite_ids: tuple[int, ...]


def _bucket_key(sprite: Sprite) -> tuple[str, object]:
    if sprite.group_name:
        return ("group", sprite.group_name)
    return ("parent", sprite.parent_id)


def _label_for_bucket(key: tuple[str, object]) -> str:
    kind, value = key
    if kind == "group":
        return f'group "{value}"'
    if value is None:
        return "the root-level sprites"
    return f"the sprites parented under sprite {value}"


def find_rig_issues(rig: AvatarRig) -> list[RigIssue]:
    issues: list[RigIssue] = []
    issues.extend(_check_manual_driven_sprites(rig))

    buckets: dict[tuple[str, object], list[Sprite]] = {}
    for sprite in rig.sprites:
        buckets.setdefault(_bucket_key(sprite), []).append(sprite)

    for key, members in buckets.items():
        automatic = [s for s in members if not s.manual_driven]
        label = _label_for_bucket(key)
        issues.extend(_check_axis_completeness(
            automatic, "talk_state", motion.GATED_TALK_STATES, motion.TALK_STATE_LABELS,
            "talk level", label,
        ))
        issues.extend(_check_axis_completeness(
            automatic, "blink_state", motion.GATED_BLINK_STATES, motion.BLINK_STATE_LABELS,
            "blink state", label,
        ))
        issues.extend(_check_variant_collisions(automatic, "talk_state", motion.TALK_STATE_LABELS, label))
        issues.extend(_check_variant_collisions(automatic, "blink_state", motion.BLINK_STATE_LABELS, label))

    issues.extend(_check_inconsistent_state_labeling(rig))
    return issues


def _check_manual_driven_sprites(rig: AvatarRig) -> list[RigIssue]:
    issues = []
    for sprite in rig.sprites:
        if sprite.manual_driven and not (sprite.group_name and sprite.state_name):
            issues.append(RigIssue(
                message=(
                    f"Sprite {sprite.id} is Manually driven but has no "
                    f"Group name and/or State name set -- it can never be "
                    f"forced live (there's nothing for a live override to "
                    f"match) and will never show."
                ),
                sprite_ids=(sprite.id,),
            ))
    return issues


def _order_key(labels: dict[int, str]):
    order = {v: i for i, v in enumerate(labels)}
    return lambda v: order[v]


def _check_axis_completeness(
    siblings: list[Sprite], attr: str, gated_values: frozenset[int],
    labels: dict[int, str], axis_name: str, bucket_label: str,
) -> list[RigIssue]:
    used = {getattr(s, attr) for s in siblings if getattr(s, attr) in gated_values}
    if not used or used == gated_values:
        return []
    key = _order_key(labels)
    missing = sorted(gated_values - used, key=key)
    involved = [s.id for s in siblings if getattr(s, attr) in gated_values]
    used_text = ", ".join(labels[v] for v in sorted(used, key=key))
    missing_text = ", ".join(repr(labels[v]) for v in missing)
    return [RigIssue(
        message=(
            f"In {bucket_label}, {len(involved)} sprite(s) use exclusive "
            f"{axis_name} gating ({used_text}) but none is {missing_text} "
            f"-- nothing will show in that state."
        ),
        sprite_ids=tuple(involved),
    )]


def _check_variant_collisions(
    siblings: list[Sprite], attr: str, labels: dict[int, str], bucket_label: str,
) -> list[RigIssue]:
    issues = []
    by_state: dict[int, list[Sprite]] = {}
    for s in siblings:
        state = getattr(s, attr)
        if state != 0:
            by_state.setdefault(state, []).append(s)
    for state, sprites in by_state.items():
        if len(sprites) < 2:
            continue
        by_variant: dict[int, list[Sprite]] = {}
        for s in sprites:
            by_variant.setdefault(s.variant, []).append(s)
        for variant, group in by_variant.items():
            if len(group) > 1:
                issues.append(RigIssue(
                    message=(
                        f"In {bucket_label}, {len(group)} sprites share "
                        f"{labels[state]!r} and Variant {variant} -- "
                        f"they'll always show/hide together instead of "
                        f"alternating; give each a different Variant number."
                    ),
                    sprite_ids=tuple(s.id for s in group),
                ))
    return issues


def _check_inconsistent_state_labeling(rig: AvatarRig) -> list[RigIssue]:
    issues = []
    by_pair: dict[tuple[str, str], list[Sprite]] = {}
    for s in rig.sprites:
        if s.group_name and s.state_name:
            by_pair.setdefault((s.group_name, s.state_name), []).append(s)
    for (group, state), sprites in by_pair.items():
        if len(sprites) < 2:
            continue
        signatures = {(s.talk_state, s.blink_state, s.manual_driven) for s in sprites}
        if len(signatures) > 1:
            issues.append(RigIssue(
                message=(
                    f'Sprites labeled Group "{group}" / State "{state}" '
                    f"don't all have the same Talk state/Blink state/"
                    f"Manually driven settings -- likely a copy-paste "
                    f"mistake, since sprites sharing a state name are "
                    f"usually meant to be interchangeable."
                ),
                sprite_ids=tuple(s.id for s in sprites),
            ))
    return issues
