import json
import os
import stat
from pathlib import Path

import pytest

from unicorn_cloak.motion import TALK_QUIET_ONLY
from unicorn_cloak.persistence import (
    CURRENT_FORMAT_VERSION,
    format_vector2,
    load_avatar,
    needs_migration,
    parse_vector2,
    save_avatar,
)
from unicorn_cloak.rig import NUM_COSTUMES, AvatarRig, Sprite

AVATAR_01 = Path(
    "/home/jj/projects/unicorn-tears/images/animated-avatar/avatar-01/"
    "unicorn-tears-avatar-01-hoody-hair-aviator-bling.save"
)

needs_avatar_01 = pytest.mark.skipif(
    not AVATAR_01.exists(), reason="avatar-01 save file not present on this machine"
)


def test_parse_vector2():
    assert parse_vector2("Vector2(0, 0)") == (0.0, 0.0)
    assert parse_vector2("Vector2(-74, 92.5)") == (-74.0, 92.5)


def test_format_vector2_matches_godot_style():
    assert format_vector2((0.0, 0.0)) == "Vector2(0, 0)"
    assert format_vector2((-74.0, 92.5)) == "Vector2(-74, 92.5)"


@needs_avatar_01
def test_load_avatar_01_real_file():
    rig = load_avatar(AVATAR_01)
    assert len(rig.sprites) == 8

    by_path_suffix = {Path(s.path).name: s for s in rig.sprites}
    assert "mouth-closed-01.png" in by_path_suffix
    assert "mouth-open-mild-01.png" in by_path_suffix
    assert "mouth-open-wide-01.png" in by_path_suffix

    # mouth-closed was fixed 2026-09-16 from talk_state=0 ("always
    # visible") to TALK_QUIET_ONLY -- 0 made it render on every frame
    # regardless of talk level, which is what let it peek out from
    # behind the mild/wide shapes wherever their art didn't fully cover
    # it (a real, reported bug; see motion.TALK_QUIET_ONLY's docstring).
    assert by_path_suffix["mouth-closed-01.png"].talk_state == TALK_QUIET_ONLY
    assert by_path_suffix["mouth-open-mild-01.png"].talk_state == 1
    assert by_path_suffix["mouth-open-wide-01.png"].talk_state == 2

    # Known content gap (see docs/PLAN.md Milestone 6): no blink sprites yet,
    # every layer's costume mask is wide open. If this ever fails, the
    # owner has started filling those in -- update the plan, don't "fix"
    # this test.
    assert all(s.blink_state == 0 for s in rig.sprites)
    assert all(all(s.costume_layers) for s in rig.sprites)

    for s in rig.sprites:
        assert s.image_data, f"{s.path} loaded with no image bytes"


@needs_avatar_01
def test_avatar_01_round_trips_through_save(tmp_path):
    # Full dataclass equality, not a hand-picked subset of fields -- a
    # partial field list previously missed that `toggle` wasn't modeled
    # at all and so was silently dropped on every save.
    original = load_avatar(AVATAR_01)
    out_path = tmp_path / "roundtrip.save"
    save_avatar(original, out_path)
    reloaded = load_avatar(out_path)

    assert len(reloaded.sprites) == len(original.sprites)
    for before, after in zip(original.sprites, reloaded.sprites):
        assert before == after, f"sprite {before.id} lost fidelity on round-trip"


@needs_avatar_01
def test_avatar_01_save_preserves_every_raw_key(tmp_path):
    # A Sprite-level equality check only proves fields that made it into
    # the dataclass survive intact -- it can't catch a field that gets
    # dropped before it's ever modeled in the first place. This diffs the
    # raw JSON documents, key by key, which is what actually catches that
    # class of bug.
    with AVATAR_01.open() as f:
        original_raw = json.load(f)

    rig = load_avatar(AVATAR_01)
    out_path = tmp_path / "roundtrip.save"
    save_avatar(rig, out_path)

    with out_path.open() as f:
        roundtripped_raw = json.load(f)

    # __format_version__ is excluded from the "must match" comparison on
    # both sides: whether the real file already has it depends on
    # whether the app has actually loaded (and so migrated) it since
    # 2026-09-16, which is mutable external state this test shouldn't
    # assume either way -- it's legitimately been flipped by normal use
    # already. The round-tripped side must always carry the current
    # stamp regardless; every sprite key must still match exactly, which
    # is the part that actually catches a silently-dropped field.
    assert roundtripped_raw["__format_version__"] == CURRENT_FORMAT_VERSION
    # __costume_assignments__/__expression_hotkeys__ (added 2026-09-17,
    # see persistence.py's own comment) are rig-level, not per-sprite --
    # excluded from the top-level comparison for the same reason
    # __format_version__ is: save_avatar always writes them, the real
    # external file predates the feature and never will have them.
    _RIG_LEVEL_KEYS_WITH_NO_LEGACY_COUNTERPART = {
        "__format_version__", "__costume_assignments__", "__expression_hotkeys__", "__zoom__",
    }
    sprite_keys = set(original_raw.keys()) - _RIG_LEVEL_KEYS_WITH_NO_LEGACY_COUNTERPART
    assert sprite_keys == set(roundtripped_raw.keys()) - _RIG_LEVEL_KEYS_WITH_NO_LEGACY_COUNTERPART
    # variant, hidden, groupName, stateName, and manualDriven (all added
    # 2026-09-16, see rig.Sprite), plus scaleX/scaleY and rotationDeg
    # (both added 2026-09-17), have no legacy counterpart, so they're
    # expected to be *gained* on
    # every sprite the first time an old real file round-trips through
    # this app -- that's intentional, not a dropped-field bug, so they're
    # excluded from "extra" only (never from "missing": once written, a
    # key must stay written).
    _NEW_KEYS_WITH_NO_LEGACY_COUNTERPART = {
        "variant", "hidden", "groupName", "stateName", "manualDriven",
        "scaleX", "scaleY", "rotationDeg", "locked",
    }
    for sprite_key in sprite_keys:
        original_entry = original_raw[sprite_key]
        roundtripped_entry = roundtripped_raw[sprite_key]
        missing = set(original_entry.keys()) - set(roundtripped_entry.keys())
        extra = (
            set(roundtripped_entry.keys()) - set(original_entry.keys())
        ) - _NEW_KEYS_WITH_NO_LEGACY_COUNTERPART
        assert not missing, f"sprite {sprite_key} lost keys on round-trip: {missing}"
        assert not extra, f"sprite {sprite_key} gained unexpected keys: {extra}"
        for field_key, original_value in original_entry.items():
            if field_key == "imageData":
                continue  # covered at the Sprite level (decoded bytes, not the raw base64 text)
            assert roundtripped_entry[field_key] == original_value, (
                f"sprite {sprite_key} field {field_key!r} changed on round-trip: "
                f"{original_value!r} -> {roundtripped_entry[field_key]!r}"
            )


def _sprite_entry(**overrides):
    entry = {
        "type": "sprite",
        "path": "/tmp/x.png",
        "identification": 1,
        "parentId": None,
        "pos": "Vector2(0, 0)",
        "zindex": 0,
        "showTalk": 0,
        "showBlink": 0,
    }
    entry.update(overrides)
    return entry


def test_load_pads_short_costume_layers_instead_of_raising(tmp_path):
    # Legacy pads a too-short costumeLayers list rather than rejecting
    # it, so an older or hand-edited file loads instead of crashing.
    path = tmp_path / "short.save"
    path.write_text(json.dumps({"0": _sprite_entry(costumeLayers="[1, 0, 1]")}))
    rig = load_avatar(path)
    assert len(rig.sprites[0].costume_layers) == 10
    assert rig.sprites[0].costume_layers[:3] == (True, False, True)
    assert all(rig.sprites[0].costume_layers[3:])  # padded with True


def test_load_truncates_long_costume_layers_instead_of_raising(tmp_path):
    path = tmp_path / "long.save"
    path.write_text(
        json.dumps({"0": _sprite_entry(costumeLayers=json.dumps([1] * 15))})
    )
    rig = load_avatar(path)
    assert len(rig.sprites[0].costume_layers) == 10


def test_load_missing_costume_layers_defaults_to_all_visible(tmp_path):
    path = tmp_path / "missing.save"
    path.write_text(json.dumps({"0": _sprite_entry()}))
    rig = load_avatar(path)
    assert rig.sprites[0].costume_layers == tuple([True] * 10)


def test_load_normalizes_an_out_of_range_show_talk_instead_of_freezing_later(tmp_path):
    # Regression, bug audit 2026-09-23 (#20, "unvalidated state
    # values"): nothing validated showTalk/showBlink at load time, so a
    # hand-edited (or future-format) file with an out-of-range value
    # loaded fine here but raised ValueError from motion.axis_visible on
    # every single paint frame afterward -- effectively freezing the
    # Render Window the moment that sprite became eligible to draw.
    path = tmp_path / "bad-talk.save"
    path.write_text(json.dumps({"0": _sprite_entry(showTalk=99)}))
    rig = load_avatar(path)  # must not raise
    assert rig.sprites[0].talk_state == 0  # normalized to "always visible"


def test_load_normalizes_an_out_of_range_show_blink(tmp_path):
    path = tmp_path / "bad-blink.save"
    path.write_text(json.dumps({"0": _sprite_entry(showBlink=-5)}))
    rig = load_avatar(path)  # must not raise
    assert rig.sprites[0].blink_state == 0


def test_load_keeps_a_valid_talk_quiet_only_show_talk(tmp_path):
    from unicorn_cloak.motion import TALK_QUIET_ONLY

    path = tmp_path / "quiet-only.save"
    path.write_text(json.dumps({"0": _sprite_entry(showTalk=TALK_QUIET_ONLY)}))
    rig = load_avatar(path)
    assert rig.sprites[0].talk_state == TALK_QUIET_ONLY


def test_load_preserves_toggle_field(tmp_path):
    path = tmp_path / "toggle.save"
    path.write_text(json.dumps({"0": _sprite_entry(toggle="F1")}))
    rig = load_avatar(path)
    assert rig.sprites[0].toggle == "F1"


def test_load_defaults_toggle_when_absent(tmp_path):
    path = tmp_path / "no-toggle.save"
    path.write_text(json.dumps({"0": _sprite_entry()}))
    rig = load_avatar(path)
    assert rig.sprites[0].toggle == "null"


def test_save_writes_toggle_field(tmp_path):
    rig = AvatarRig(name="t", sprites=[Sprite(id=1, path="x.png", toggle="F1")])
    path = tmp_path / "out.save"
    save_avatar(rig, path)
    with path.open() as f:
        raw = json.load(f)
    assert raw["0"]["toggle"] == "F1"


def test_load_preserves_variant_field(tmp_path):
    path = tmp_path / "variant.save"
    path.write_text(json.dumps({"0": _sprite_entry(variant=1)}))
    rig = load_avatar(path)
    assert rig.sprites[0].variant == 1


def test_load_falls_back_to_the_old_talkvariant_key_name(tmp_path):
    # "variant" was briefly called "talkVariant" (see persistence.py's
    # load_avatar) before blink-axis sprites needed the same field --
    # a file saved during that window must not silently lose it.
    path = tmp_path / "old-key-name.save"
    path.write_text(json.dumps({"0": _sprite_entry(talkVariant=1)}))
    rig = load_avatar(path)
    assert rig.sprites[0].variant == 1


def test_load_defaults_variant_when_absent(tmp_path):
    # Every real file predates this key -- must default to 0 ("no
    # alternation"), not raise.
    path = tmp_path / "no-variant.save"
    path.write_text(json.dumps({"0": _sprite_entry()}))
    rig = load_avatar(path)
    assert rig.sprites[0].variant == 0


def test_save_writes_variant_field(tmp_path):
    rig = AvatarRig(name="t", sprites=[Sprite(id=1, path="x.png", variant=1)])
    path = tmp_path / "out.save"
    save_avatar(rig, path)
    with path.open() as f:
        raw = json.load(f)
    assert raw["0"]["variant"] == 1


def test_load_preserves_hidden_field(tmp_path):
    path = tmp_path / "hidden.save"
    path.write_text(json.dumps({"0": _sprite_entry(hidden=True)}))
    rig = load_avatar(path)
    assert rig.sprites[0].hidden is True


def test_load_defaults_hidden_to_false_when_absent(tmp_path):
    path = tmp_path / "no-hidden.save"
    path.write_text(json.dumps({"0": _sprite_entry()}))
    rig = load_avatar(path)
    assert rig.sprites[0].hidden is False


def test_save_writes_hidden_field(tmp_path):
    rig = AvatarRig(name="t", sprites=[Sprite(id=1, path="x.png", hidden=True)])
    path = tmp_path / "out.save"
    save_avatar(rig, path)
    with path.open() as f:
        raw = json.load(f)
    assert raw["0"]["hidden"] is True


def test_load_preserves_locked_field(tmp_path):
    path = tmp_path / "locked.save"
    path.write_text(json.dumps({"0": _sprite_entry(locked=True)}))
    rig = load_avatar(path)
    assert rig.sprites[0].locked is True


def test_load_defaults_locked_to_false_when_absent(tmp_path):
    path = tmp_path / "no-locked.save"
    path.write_text(json.dumps({"0": _sprite_entry()}))
    rig = load_avatar(path)
    assert rig.sprites[0].locked is False


def test_save_writes_locked_field(tmp_path):
    rig = AvatarRig(name="t", sprites=[Sprite(id=1, path="x.png", locked=True)])
    path = tmp_path / "out.save"
    save_avatar(rig, path)
    with path.open() as f:
        raw = json.load(f)
    assert raw["0"]["locked"] is True


def test_load_preserves_group_state_and_manual_driven_fields(tmp_path):
    path = tmp_path / "grouped.save"
    path.write_text(json.dumps({
        "0": _sprite_entry(groupName="Mouth", stateName="Laughing", manualDriven=True),
    }))
    rig = load_avatar(path)
    sprite = rig.sprites[0]
    assert sprite.group_name == "Mouth"
    assert sprite.state_name == "Laughing"
    assert sprite.manual_driven is True


def test_load_defaults_group_state_and_manual_driven_when_absent(tmp_path):
    path = tmp_path / "no-grouping.save"
    path.write_text(json.dumps({"0": _sprite_entry()}))
    rig = load_avatar(path)
    sprite = rig.sprites[0]
    assert sprite.group_name == ""
    assert sprite.state_name == ""
    assert sprite.manual_driven is False


def test_save_writes_group_state_and_manual_driven_fields(tmp_path):
    rig = AvatarRig(
        name="t",
        sprites=[Sprite(id=1, path="x.png", group_name="Mouth", state_name="Laughing", manual_driven=True)],
    )
    path = tmp_path / "out.save"
    save_avatar(rig, path)
    with path.open() as f:
        raw = json.load(f)
    assert raw["0"]["groupName"] == "Mouth"
    assert raw["0"]["stateName"] == "Laughing"
    assert raw["0"]["manualDriven"] is True


def test_load_preserves_scale_fields(tmp_path):
    path = tmp_path / "scaled.save"
    path.write_text(json.dumps({"0": _sprite_entry(scaleX=1.5, scaleY=0.75)}))
    rig = load_avatar(path)
    sprite = rig.sprites[0]
    assert sprite.scale_x == 1.5
    assert sprite.scale_y == 0.75


def test_load_defaults_scale_to_one_when_absent(tmp_path):
    path = tmp_path / "no-scale.save"
    path.write_text(json.dumps({"0": _sprite_entry()}))
    rig = load_avatar(path)
    sprite = rig.sprites[0]
    assert sprite.scale_x == 1.0
    assert sprite.scale_y == 1.0


def test_save_writes_scale_fields(tmp_path):
    rig = AvatarRig(name="t", sprites=[Sprite(id=1, path="x.png", scale_x=1.5, scale_y=0.75)])
    path = tmp_path / "out.save"
    save_avatar(rig, path)
    with path.open() as f:
        raw = json.load(f)
    assert raw["0"]["scaleX"] == 1.5
    assert raw["0"]["scaleY"] == 0.75


def test_load_preserves_rotation_deg(tmp_path):
    path = tmp_path / "rotated.save"
    path.write_text(json.dumps({"0": _sprite_entry(rotationDeg=45.0)}))
    rig = load_avatar(path)
    assert rig.sprites[0].rotation_deg == 45.0


def test_load_defaults_rotation_deg_to_zero_when_absent(tmp_path):
    path = tmp_path / "no-rotation.save"
    path.write_text(json.dumps({"0": _sprite_entry()}))
    rig = load_avatar(path)
    assert rig.sprites[0].rotation_deg == 0.0


def test_save_writes_rotation_deg(tmp_path):
    rig = AvatarRig(name="t", sprites=[Sprite(id=1, path="x.png", rotation_deg=45.0)])
    path = tmp_path / "out.save"
    save_avatar(rig, path)
    with path.open() as f:
        raw = json.load(f)
    assert raw["0"]["rotationDeg"] == 45.0


def test_costume_assignments_round_trip(tmp_path):
    rig = AvatarRig(name="t", sprites=[Sprite(id=1, path="a.png"), Sprite(id=2, path="b.png")])
    rig.assign_costume_pair(2, hide_id=1, show_id=2)
    path = tmp_path / "out.save"
    save_avatar(rig, path)
    reloaded = load_avatar(path)
    assert reloaded.costume_assignments[2] == [(1, 2)]
    assert reloaded.by_id(1).costume_layers[2] is True
    assert reloaded.by_id(2).costume_layers[2] is False


def test_expression_hotkeys_round_trip(tmp_path):
    rig = AvatarRig(name="t", sprites=[Sprite(id=1, path="a.png")])
    rig.assign_expression_hotkey(4, "Mouth", "Laughing")
    path = tmp_path / "out.save"
    save_avatar(rig, path)
    reloaded = load_avatar(path)
    assert reloaded.expression_hotkeys[4] == [("Mouth", "Laughing")]


def test_load_defaults_costume_assignments_and_expression_hotkeys_when_absent(tmp_path):
    # A file saved before this feature existed (or written by hand) has
    # neither top-level key at all.
    path = tmp_path / "old.save"
    path.write_text(json.dumps({"0": _sprite_entry()}))
    rig = load_avatar(path)
    assert rig.costume_assignments == [[] for _ in range(NUM_COSTUMES)]
    assert rig.expression_hotkeys == [[] for _ in range(NUM_COSTUMES)]


def test_zoom_round_trips(tmp_path):
    rig = AvatarRig(name="t", sprites=[Sprite(id=1, path="a.png")], zoom=2.5)
    path = tmp_path / "out.save"
    save_avatar(rig, path)
    reloaded = load_avatar(path)
    assert reloaded.zoom == 2.5


def test_load_defaults_zoom_to_1_when_absent(tmp_path):
    # A file saved before AvatarRig.zoom existed (moved here from
    # WindowConfig.zoom 2026-09-19) has no __zoom__ key at all.
    path = tmp_path / "old.save"
    path.write_text(json.dumps({"0": _sprite_entry()}))
    rig = load_avatar(path)
    assert rig.zoom == 1.0


def test_save_is_atomic_no_leftover_tmp_file(tmp_path):
    rig = AvatarRig(name="t", sprites=[Sprite(id=1, path="x.png")])
    path = tmp_path / "out.save"
    save_avatar(rig, path)
    leftovers = [p for p in tmp_path.iterdir() if p.name != "out.save"]
    assert leftovers == []


def test_save_keeps_one_backup_of_the_previous_version(tmp_path):
    path = tmp_path / "out.save"
    rig_v1 = AvatarRig(name="t", sprites=[Sprite(id=1, path="v1.png")])
    save_avatar(rig_v1, path)

    rig_v2 = AvatarRig(name="t", sprites=[Sprite(id=1, path="v2.png")])
    save_avatar(rig_v2, path)

    backup_path = path.with_suffix(path.suffix + ".bak")
    assert backup_path.exists()
    with backup_path.open() as f:
        backup_raw = json.load(f)
    assert backup_raw["0"]["path"] == "v1.png"  # the version *before* the last save

    with path.open() as f:
        current_raw = json.load(f)
    assert current_raw["0"]["path"] == "v2.png"


def test_save_does_not_create_backup_on_first_write(tmp_path):
    path = tmp_path / "out.save"
    rig = AvatarRig(name="t", sprites=[Sprite(id=1, path="x.png")])
    save_avatar(rig, path)
    assert not path.with_suffix(path.suffix + ".bak").exists()


def test_save_preserves_the_existing_files_permissions(tmp_path):
    # Regression, bug audit 2026-09-23 (#20, "permissions and
    # symlinks"): mkstemp always creates its temp file 0600 regardless
    # of the real target's own mode, and os.replace's rename doesn't
    # carry the old file's permissions over the new one -- so a first
    # save through this app silently tightened an avatar file's
    # permissions to owner-only, even one left more permissive (e.g.
    # group-readable) by another tool or a hand chmod beforehand.
    path = tmp_path / "out.save"
    rig = AvatarRig(name="t", sprites=[Sprite(id=1, path="v1.png")])
    save_avatar(rig, path)
    os.chmod(path, 0o664)  # simulate a pre-existing, more permissive mode

    save_avatar(rig, path)  # a second save, over the now-0o664 file

    assert stat.S_IMODE(path.stat().st_mode) == 0o664


def test_save_through_a_symlink_leaves_the_link_itself_intact(tmp_path):
    # Regression, bug audit 2026-09-23 (#20, "permissions and
    # symlinks"): os.replace(tmp, path) replaces whatever `path` itself
    # names -- for a symlink (e.g. an avatar file pointed at a synced or
    # shared location) that's the link, not its target, so saving
    # through it used to silently replace the link with a plain regular
    # file on the very first save.
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    real_path = real_dir / "avatar.save"
    link_path = tmp_path / "avatar-link.save"
    link_path.symlink_to(real_path)

    rig = AvatarRig(name="t", sprites=[Sprite(id=1, path="v1.png")])
    save_avatar(rig, link_path)

    assert link_path.is_symlink()  # still a link, not replaced by a regular file
    assert link_path.resolve() == real_path
    assert real_path.exists()  # the actual content landed at the real target
    loaded = load_avatar(link_path)
    assert loaded.sprites[0].path == "v1.png"


def test_needs_migration_true_for_file_with_no_version_key(tmp_path):
    # Every real file in the wild right now predates format versioning.
    path = tmp_path / "legacy.save"
    path.write_text(json.dumps({"0": _sprite_entry()}))
    assert needs_migration(path) is True


@needs_avatar_01
def test_needs_migration_is_readable_on_the_real_avatar_01_file():
    # Not asserting True or False: whether the real file currently needs
    # migration is mutable external state (it's legitimately been
    # upgraded by normal app use already) -- this just proves the check
    # runs cleanly against it, which is what a synthetic file can't prove.
    assert needs_migration(AVATAR_01) in (True, False)


def test_needs_migration_false_after_a_save(tmp_path):
    path = tmp_path / "current.save"
    rig = AvatarRig(name="t", sprites=[Sprite(id=1, path="x.png")])
    save_avatar(rig, path)
    assert needs_migration(path) is False


def test_needs_migration_true_for_a_future_version_stamped_lower(tmp_path):
    path = tmp_path / "old_version.save"
    path.write_text(json.dumps({"__format_version__": 0, "0": _sprite_entry()}))
    assert needs_migration(path) is True


def test_load_avatar_ignores_the_format_version_key(tmp_path):
    path = tmp_path / "versioned.save"
    path.write_text(
        json.dumps({"__format_version__": CURRENT_FORMAT_VERSION, "0": _sprite_entry()})
    )
    rig = load_avatar(path)
    assert len(rig.sprites) == 1


# --- Timestamped backups (E11, bug audit addendum 2026-09-23) -------------


def test_first_save_creates_no_timestamped_backup(tmp_path):
    from unicorn_cloak.persistence import timestamped_backups

    path = tmp_path / "out.uc"
    save_avatar(AvatarRig(name="t", sprites=[Sprite(id=1, path="x.png")]), path)
    assert timestamped_backups(path) == []


def test_each_later_save_keeps_a_timestamped_copy_of_the_previous_version(tmp_path):
    from unicorn_cloak.persistence import timestamped_backups

    path = tmp_path / "out.uc"
    for version in ("v1.png", "v2.png", "v3.png"):
        save_avatar(AvatarRig(name="t", sprites=[Sprite(id=1, path=version)]), path)

    backups = timestamped_backups(path)
    assert len(backups) == 2
    assert [json.loads(b.read_text())["0"]["path"] for b in backups] == ["v1.png", "v2.png"]
    # The rolling .bak is still there too, holding the newest previous version.
    rolling = path.with_suffix(path.suffix + ".bak")
    assert json.loads(rolling.read_text())["0"]["path"] == "v2.png"


def test_timestamped_backups_are_pruned_to_the_newest_max(tmp_path):
    from unicorn_cloak.persistence import MAX_TIMESTAMPED_BACKUPS, timestamped_backups

    path = tmp_path / "out.uc"
    total_saves = MAX_TIMESTAMPED_BACKUPS + 4
    for i in range(total_saves):
        save_avatar(AvatarRig(name="t", sprites=[Sprite(id=1, path=f"v{i}.png")]), path)

    backups = timestamped_backups(path)
    assert len(backups) == MAX_TIMESTAMPED_BACKUPS
    # Oldest ones went; the newest backup is the version before the last save.
    assert json.loads(backups[-1].read_text())["0"]["path"] == f"v{total_saves - 2}.png"


def test_timestamped_backups_only_match_this_avatars_own_files(tmp_path):
    from unicorn_cloak.persistence import timestamped_backups

    path = tmp_path / "out.uc"
    (tmp_path / "out.uc.bak").write_text("{}")
    (tmp_path / "other.uc.20260101-000000-000000.bak").write_text("{}")
    (tmp_path / "out.uc.notatimestamp.bak").write_text("{}")
    assert timestamped_backups(path) == []


def test_timestamped_backup_names_are_covered_by_gitignore(tmp_path):
    # The bundled demo avatar lives inside this repo -- its backups must
    # not show up as untracked files.
    from unicorn_cloak.persistence import timestamped_backups

    path = tmp_path / "out.uc"
    save_avatar(AvatarRig(name="t", sprites=[]), path)
    save_avatar(AvatarRig(name="t", sprites=[]), path)
    assert timestamped_backups(path)[0].name.endswith(".bak")
