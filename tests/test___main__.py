from unicorn_cloak.__main__ import handle_avatar_file_changed, reset_speaking_state_and_close_mouth
from unicorn_cloak.audio import SpeakingState
from unicorn_cloak.config import Config, MotionConfig
from unicorn_cloak.persistence import save_avatar
from unicorn_cloak.render import RenderWindow

from qt_helpers import make_test_rig


def test_reset_speaking_state_and_close_mouth_forces_the_mouth_shut(qapp):
    # Regression 2026-09-20, owner's report: "the audio file stops but
    # the mouth keeps moving." update_speaking's attack/hold/release
    # envelope only advances when it's actually called, and nothing ever
    # calls it again once file playback fully stops -- leaving talk_level
    # stuck at whatever nonzero level it last reached (see this
    # function's own docstring in __main__.py for the full mechanism).
    rig = make_test_rig()  # sprite 2 has talk_state=1 (mild)
    window = RenderWindow(rig, MotionConfig())
    window.set_talk_level(2)
    window.set_envelope(0.9)

    result = reset_speaking_state_and_close_mouth(window)

    assert window.talk_level == 0
    assert window.current_envelope == 0.0
    assert result == SpeakingState()


def test_reset_speaking_state_and_close_mouth_is_harmless_while_muted(qapp):
    # OBS mute (set_muted) already forces effective_talk_level to 0 via
    # its own, separate path -- this just confirms the two don't fight:
    # resetting talk_level while muted still leaves the mouth closed,
    # not accidentally reopened.
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    window.set_muted(True)

    reset_speaking_state_and_close_mouth(window)

    assert window.effective_talk_level == 0


# --- handle_avatar_file_changed (bug audit 2026-09-23, #1/#3/#15) -----------


class _FakeControlPanel:
    def __init__(self) -> None:
        self.refresh_calls = 0
        self.status_messages: list[tuple[str, str]] = []

    def refresh_after_external_avatar_reload(self) -> None:
        self.refresh_calls += 1

    def show_status_message(self, source: str, message: str) -> None:
        self.status_messages.append((source, message))


class _FakeAssetWatcher:
    def __init__(self) -> None:
        self.watched_sprite_paths: list[str] | None = None

    def watch_sprite_files(self, paths: list[str]) -> None:
        self.watched_sprite_paths = paths


def test_handle_avatar_file_changed_reloads_and_keeps_the_live_active_costume(qapp, tmp_path):
    # Regression, #3: active_costume isn't actually part of a file's
    # persisted content (persistence.save_avatar/load_avatar don't
    # round-trip it -- see AvatarRig.replace_contents_from's docstring),
    # so copying it from a reload always reset the live costume slot to
    # 0 -- including on the app's own Save triggering its own hot
    # reload.
    rig = make_test_rig()
    rig.active_costume = 3
    path = tmp_path / "reloaded-avatar.uc"
    other_rig = make_test_rig()
    other_rig.zoom = 2.5
    save_avatar(other_rig, path)
    config = Config()
    config.avatar_path = str(path)
    control_panel = _FakeControlPanel()
    asset_watcher = _FakeAssetWatcher()

    result = handle_avatar_file_changed(rig, config, control_panel, asset_watcher)

    assert result is True
    # name isn't actually persisted (load_avatar derives it from the
    # filename) -- zoom is real, persisted content, so it's the more
    # meaningful signal that a genuine reload happened.
    assert rig.name == "reloaded-avatar"
    assert rig.zoom == 2.5
    assert rig.active_costume == 3  # untouched, not reset to the reload's 0
    assert control_panel.refresh_calls == 1
    assert asset_watcher.watched_sprite_paths == [s.path for s in rig.sprites]


def test_handle_avatar_file_changed_copies_costume_and_expression_assignments(qapp, tmp_path):
    # Regression, #1/#15: the inline closure this was extracted from
    # used to copy name/sprites/active_costume/zoom by hand and forget
    # costume_assignments/expression_hotkeys, same bug as Load (#1) --
    # hand-editing those in the file was never picked up by hot reload.
    rig = make_test_rig()
    rig.assign_expression_hotkey(0, "Mouth", "Laughing")  # the live/stale assignment
    path = tmp_path / "avatar.uc"
    other_rig = make_test_rig()
    other_rig.assign_costume_pair(1, hide_id=other_rig.sprites[0].id, show_id=other_rig.sprites[1].id)
    save_avatar(other_rig, path)
    config = Config()
    config.avatar_path = str(path)

    handle_avatar_file_changed(rig, config, _FakeControlPanel(), _FakeAssetWatcher())

    assert rig.expression_hotkeys[0] == []  # the stale live assignment is gone
    assert len(rig.costume_assignments[1]) == 1  # the reloaded file's own assignment is here


def test_handle_avatar_file_changed_returns_false_and_does_not_touch_the_rig_on_failure(qapp, tmp_path):
    rig = make_test_rig()
    original_name = rig.name
    config = Config()
    config.avatar_path = str(tmp_path / "does-not-exist.uc")

    panel = _FakeControlPanel()
    result = handle_avatar_file_changed(rig, config, panel, _FakeAssetWatcher())

    assert result is False
    assert rig.name == original_name
    # E3 (bug audit addendum 2026-09-23): surfaced in the UI, not just printed.
    assert len(panel.status_messages) == 1
    assert panel.status_messages[0][0] == "Hot reload"
