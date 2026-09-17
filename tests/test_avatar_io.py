import json

from unicorn_cloak import avatar_io as avatar_io_module
from unicorn_cloak.avatar_io import load_avatar_with_upgrade
from unicorn_cloak.persistence import CURRENT_FORMAT_VERSION, needs_migration
from unicorn_cloak.rig import AvatarRig, Sprite


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


def test_legacy_file_gets_upgraded_and_warned_about(qapp, monkeypatch, tmp_path):
    path = tmp_path / "legacy.save"
    path.write_text(json.dumps({"0": _sprite_entry()}))

    warnings = []
    monkeypatch.setattr(
        avatar_io_module.QMessageBox,
        "information",
        lambda parent, title, text: warnings.append((title, text)),
    )

    rig = load_avatar_with_upgrade(path)

    assert isinstance(rig, AvatarRig)
    assert len(warnings) == 1
    title, text = warnings[0]
    assert "updated" in title.lower()
    assert "backup" in text.lower()
    assert str(path.with_suffix(path.suffix + ".bak")) in text

    # The file on disk is now current -- loading it again must not re-warn.
    assert needs_migration(path) is False


def test_current_file_is_not_touched_or_warned_about(qapp, monkeypatch, tmp_path):
    path = tmp_path / "current.save"
    rig = AvatarRig(name="t", sprites=[Sprite(id=1, path="x.png")])
    from unicorn_cloak.persistence import save_avatar

    save_avatar(rig, path)
    original_mtime = path.stat().st_mtime_ns

    warnings = []
    monkeypatch.setattr(
        avatar_io_module.QMessageBox,
        "information",
        lambda parent, title, text: warnings.append((title, text)),
    )

    load_avatar_with_upgrade(path)

    assert warnings == []
    assert path.stat().st_mtime_ns == original_mtime  # not re-saved
    assert not path.with_suffix(path.suffix + ".bak").exists()  # no backup created


def test_upgraded_file_matches_current_format_version(qapp, monkeypatch, tmp_path):
    path = tmp_path / "legacy.save"
    path.write_text(json.dumps({"0": _sprite_entry()}))
    monkeypatch.setattr(avatar_io_module.QMessageBox, "information", lambda *a: None)

    load_avatar_with_upgrade(path)

    with path.open() as f:
        raw = json.load(f)
    assert raw["__format_version__"] == CURRENT_FORMAT_VERSION
