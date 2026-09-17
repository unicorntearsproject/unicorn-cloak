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


def test_child_position_composes_with_parent_even_when_parent_is_hidden(qapp):
    parent = Sprite(id=1, path="p.png", image_data=None, hidden=True, position=(50.0, 50.0))
    child = Sprite(
        id=2, path="c.png", parent_id=1, image_data=make_test_png_bytes(), position=(0.0, 0.0)
    )
    rig = AvatarRig(name="t", sprites=[parent, child])
    # Should not raise even though the parent contributes no item.
    image = render_costume_snapshot(rig, 0)
    assert image.width() > 0


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
