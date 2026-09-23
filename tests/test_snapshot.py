from PySide6.QtGui import QImage

from unicorn_cloak.rig import NUM_COSTUMES, AvatarRig, Sprite
from unicorn_cloak.snapshot import export_costume_snapshot, render_costume_snapshot

from qt_helpers import make_test_png_bytes


def _rig_with_one_sprite(**overrides) -> AvatarRig:
    sprite = Sprite(id=1, path="a.png", image_data=make_test_png_bytes(), position=(0.0, 0.0))
    for key, value in overrides.items():
        setattr(sprite, key, value)
    return AvatarRig(name="t", sprites=[sprite])


def test_snapshot_includes_a_base_sprite_at_rest(qapp):
    rig = _rig_with_one_sprite()
    image = render_costume_snapshot(rig, 0)
    assert image.width() > 0
    assert image.height() > 0


def test_snapshot_excludes_a_hidden_sprite(qapp):
    rig = _rig_with_one_sprite(hidden=True)
    image = render_costume_snapshot(rig, 0)
    # Nothing visible -- falls back to the 1x1 empty-bounds placeholder.
    assert image.width() == 1
    assert image.height() == 1


def test_snapshot_excludes_a_sprite_not_in_the_requested_costume(qapp):
    layers = tuple(i == 3 for i in range(NUM_COSTUMES))  # only costume 3
    rig = _rig_with_one_sprite(costume_layers=layers)
    image = render_costume_snapshot(rig, 0)
    assert image.width() == 1 and image.height() == 1
    image = render_costume_snapshot(rig, 3)
    assert image.width() > 1


def test_snapshot_excludes_a_mild_talk_variant_at_rest(qapp):
    # talk_state=1 ("mild") is only visible at talk_level==1 -- rest is
    # talk_level==0, so this sprite should never appear in a snapshot.
    rig = _rig_with_one_sprite(talk_state=1)
    image = render_costume_snapshot(rig, 0)
    assert image.width() == 1 and image.height() == 1


def test_snapshot_applies_the_sprites_authored_scale(qapp):
    # Regression 2026-09-20, owner's report with screenshots: an exported
    # snapshot of the real running avatar showed correctly-fitted
    # sunglasses (authored at 0.34x to match a head scaled to 0.843x)
    # rendered enormous, sticking out past the head like ears -- neither
    # scale was ever applied, so every sprite exported at its raw native
    # pixel size regardless of what render.py/the editor actually show.
    rig = _rig_with_one_sprite(image_data=make_test_png_bytes(size=100), scale_x=0.5, scale_y=0.5)
    image = render_costume_snapshot(rig, 0)
    assert (image.width(), image.height()) == (50, 50)


def test_snapshot_applies_the_sprites_authored_rotation(qapp):
    # Same root cause/fix as the scale test above -- rotation_deg was
    # equally ignored. A 45-degree rotation of a square sprite widens its
    # bounding box well past the sprite's own native size.
    rig = _rig_with_one_sprite(image_data=make_test_png_bytes(size=100), rotation_deg=45.0)
    image = render_costume_snapshot(rig, 0)
    assert image.width() > 100
    assert image.height() > 100


def test_child_position_composes_with_parent_even_when_parent_is_hidden(qapp):
    # Regression, bug audit 2026-09-23 (related to #5): an invisible
    # sprite used to contribute no item at all, so its children --
    # whose authored Position is relative to *that* sprite, not its
    # grandparent -- attached straight to the grandparent's item
    # instead, silently losing the hidden parent's own position offset.
    # This only ever asserted "doesn't raise" before, which the old,
    # buggy code also satisfied -- it never actually checked *where*
    # the child landed. A visible reference sprite at the scene origin,
    # plus a child 100px away via its (hidden) parent's own position,
    # makes the wrong-position bug visible in the exported image's tight
    # auto-fit bounds: correctly composed, the two are ~100px apart
    # (image roughly 110px wide); with the bug, the child collapses back
    # to the origin right on top of the reference sprite (~10px wide).
    reference = Sprite(id=10, path="ref.png", image_data=make_test_png_bytes(size=10), position=(0.0, 0.0))
    parent = Sprite(id=1, path="p.png", image_data=None, hidden=True, position=(100.0, 0.0))
    child = Sprite(
        id=2, path="c.png", parent_id=1, image_data=make_test_png_bytes(size=10), position=(0.0, 0.0)
    )
    rig = AvatarRig(name="t", sprites=[reference, parent, child])
    image = render_costume_snapshot(rig, 0)
    assert image.width() > 80  # composed correctly: ~100px apart, not collapsed to ~10px


def test_snapshot_excludes_a_manual_driven_expression_sprite(qapp):
    # Regression, bug audit 2026-09-23 (#5): _rest_alpha never passed
    # manual_driven/manual_active, so sprite_alpha fell through to the
    # *ordinary* talk/blink-state check -- and an expression sprite is
    # typically talk_state=0/blink_state=0 (gated purely by a live
    # override, not mic/blink), which axis_visible treats as "always
    # visible." A snapshot has no live override active, so this must
    # never show up in it.
    rig = _rig_with_one_sprite(manual_driven=True, group_name="Mouth", state_name="Laughing")
    image = render_costume_snapshot(rig, 0)
    assert image.width() == 1 and image.height() == 1


def test_snapshot_shows_only_the_lowest_variant_in_a_shared_band(qapp):
    # Regression, bug audit 2026-09-23 (#5): _rest_alpha never passed
    # talk/blink variant or variant_count, so sprite_alpha's
    # variant-gating branch never activated at all -- every sprite
    # sharing a band showed at once (the real avatar's three stacked
    # eye layers, per the audit's own repro). A snapshot is static, so
    # it deterministically shows each band's *lowest* variant, not
    # every one of them layered together.
    wide = Sprite(
        id=1, path="wide.png", image_data=make_test_png_bytes(size=10),
        blink_state=1, variant=0, position=(0.0, 0.0),
    )
    squint = Sprite(
        id=2, path="squint.png", image_data=make_test_png_bytes(size=200),
        blink_state=1, variant=1, position=(0.0, 0.0),
    )
    rig = AvatarRig(name="t", sprites=[wide, squint])
    image = render_costume_snapshot(rig, 0)
    # Only variant 0 (the small one) shown -- if both were stacked (the
    # bug), the much larger variant-1 sprite would dominate the bounds.
    assert image.width() == 10


def test_snapshot_respects_negative_z_index_stacking_behind_parent(qapp):
    # Regression, bug audit 2026-09-23 (related to #5): missing
    # ItemStacksBehindParent meant Qt's own default applied instead (a
    # child always paints on top of its parent, regardless of z_index
    # sign) -- a negative z_index (e.g. a hair-back layer meant to sit
    # behind the head) rendered in *front* of its parent, unlike
    # render.py, which sets this same flag.
    parent = Sprite(
        id=1, path="parent.png", image_data=make_test_png_bytes(color=(255, 0, 0, 255), size=20),
        position=(0.0, 0.0), z_index=0,
    )
    child = Sprite(
        id=2, path="child.png", parent_id=1,
        image_data=make_test_png_bytes(color=(0, 0, 255, 255), size=20),
        position=(0.0, 0.0), z_index=-1,
    )
    rig = AvatarRig(name="t", sprites=[parent, child])
    image = render_costume_snapshot(rig, 0)
    center = image.pixelColor(image.width() // 2, image.height() // 2)
    assert (center.red(), center.green(), center.blue()) == (255, 0, 0)  # parent (red) on top


def test_export_saves_a_real_png_file(qapp, tmp_path):
    rig = _rig_with_one_sprite()
    out_path = tmp_path / "snapshot.png"
    export_costume_snapshot(rig, 0, str(out_path))
    assert out_path.exists()
    saved = QImage(str(out_path))
    assert saved.width() > 0


def test_export_scales_to_the_requested_resolution(qapp, tmp_path):
    rig = _rig_with_one_sprite()
    out_path = tmp_path / "snapshot.png"
    export_costume_snapshot(rig, 0, str(out_path), width=200, height=100)
    saved = QImage(str(out_path))
    assert saved.width() == 200
    assert saved.height() == 100


def test_export_raises_for_an_unwritable_path(qapp, tmp_path):
    rig = _rig_with_one_sprite()
    bad_path = tmp_path / "no-such-directory" / "snapshot.png"
    try:
        export_costume_snapshot(rig, 0, str(bad_path))
        assert False, "expected an OSError"
    except OSError:
        pass
