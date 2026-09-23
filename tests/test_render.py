import time
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem

from unicorn_cloak.config import DEFAULT_AVATAR_PATH, HotkeysConfig, MotionConfig
from unicorn_cloak.persistence import load_avatar
from unicorn_cloak.render import SIM_DT, RenderWindow
from unicorn_cloak.rig import AvatarRig, Sprite

from qt_helpers import make_filmstrip_png_bytes, make_test_png_bytes, make_test_rig


def press_key(window, key):
    event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    window.keyPressEvent(event)


def test_scene_rect_matches_widget_size_so_view_centers_correctly(qapp):
    # Regression 2026-09-15: without an explicit sceneRect, QGraphicsView
    # falls back to an auto-sized rect from itemsBoundingRect(), which
    # doesn't match the widget's pixel size -- so root_item.setPos(w/2,
    # h/2) doesn't actually land at the visual center of the window, and
    # a resize doesn't recenter it either.
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig(), window_size=(1280, 720))
    window.show()
    qapp.processEvents()
    window._apply_to_scene()
    view_center = window.view.mapToScene(window.view.viewport().rect().center())
    assert abs(view_center.x() - window.root_item.pos().x()) <= 1
    assert abs(view_center.y() - window.root_item.pos().y()) <= 1

    window.resize(800, 600)
    qapp.processEvents()
    window._apply_to_scene()
    view_center = window.view.mapToScene(window.view.viewport().rect().center())
    assert abs(view_center.x() - window.root_item.pos().x()) <= 1
    assert abs(view_center.y() - window.root_item.pos().y()) <= 1


def test_render_window_builds_one_item_per_sprite(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    assert len(window._runtimes) == 2


def test_render_window_respects_parent_child_nesting(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    child_item = window._runtimes[2].item
    parent_item = window._runtimes[1].item
    assert child_item.parentItem() is parent_item


def test_render_window_simulate_step_does_not_crash(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    for _ in range(5):
        window._simulate_step()
    window._apply_to_scene()


def test_render_window_talk_level_changes_opacity(qapp):
    # _apply_to_scene reads talk_level directly, so this doesn't depend
    # on any simulation steps having run.
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    mouth_item = window._runtimes[2].item  # talk_state=1

    window.set_talk_level(0)
    window._apply_to_scene()
    assert mouth_item.opacity() == 0.0

    window.set_talk_level(1)
    window._apply_to_scene()
    assert mouth_item.opacity() == 1.0


def test_manual_override_shows_only_the_matching_sprite(qapp):
    png = make_test_png_bytes()
    sprites = [
        Sprite(id=1, path="a.png", image_data=png, group_name="Mouth", state_name="Closed"),
        Sprite(
            id=2, path="b.png", image_data=png,
            group_name="Mouth", state_name="Laughing", manual_driven=True,
        ),
    ]
    rig = AvatarRig(name="test", sprites=sprites)
    window = RenderWindow(rig, MotionConfig())
    closed_item = window._runtimes[1].item
    laughing_item = window._runtimes[2].item

    window._apply_to_scene()
    assert laughing_item.opacity() == 0.0  # no override active yet
    assert closed_item.opacity() == 1.0  # the automatic sibling shows as normal

    window.set_manual_override("Mouth", "Laughing")
    window._apply_to_scene()
    assert laughing_item.opacity() == 1.0
    # Regression 2026-09-17: sprite_alpha decides each sprite independently
    # and has no idea a sibling is being overridden -- without render.py's
    # own suppression, the automatic "Closed" mouth kept showing right
    # alongside the forced "Laughing" one (found live with unicorn-demo's
    # "Eyes: Open" expression, both eye sprites drawn on top of each
    # other). An active override must take over its whole group.
    assert closed_item.opacity() == 0.0

    window.set_manual_override("Mouth", None)
    window._apply_to_scene()
    assert laughing_item.opacity() == 0.0
    assert closed_item.opacity() == 1.0  # automatic sibling resumes


def test_manual_override_does_not_affect_a_different_group(qapp):
    png = make_test_png_bytes()
    sprites = [
        Sprite(
            id=1, path="a.png", image_data=png,
            group_name="Eyes", state_name="Laughing", manual_driven=True,
        ),
    ]
    rig = AvatarRig(name="test", sprites=sprites)
    window = RenderWindow(rig, MotionConfig())
    window.set_manual_override("Mouth", "Laughing")  # a different group
    window._apply_to_scene()
    assert window._runtimes[1].item.opacity() == 0.0


def test_manual_driven_sprite_ignores_talk_level_entirely(qapp):
    png = make_test_png_bytes()
    sprites = [
        Sprite(
            id=1, path="a.png", image_data=png, talk_state=1,
            group_name="Mouth", state_name="Laughing", manual_driven=True,
        ),
    ]
    rig = AvatarRig(name="test", sprites=sprites)
    window = RenderWindow(rig, MotionConfig())
    window.set_talk_level(1)  # would normally satisfy talk_state=1
    window._apply_to_scene()
    assert window._runtimes[1].item.opacity() == 0.0  # manual override not set

    window.set_manual_override("Mouth", "Laughing")
    window.set_talk_level(0)  # would normally NOT satisfy talk_state=1
    window._apply_to_scene()
    assert window._runtimes[1].item.opacity() == 1.0  # manual override wins


def test_muted_forces_the_mouth_closed_regardless_of_talk_level(qapp):
    # Real reported problem, 2026-09-16: "the avatar talks while the
    # stream hears silence" when the mic is muted in OBS. set_muted must
    # override talk_level entirely, not just dampen it.
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    mouth_item = window._runtimes[2].item  # talk_state=1

    window.set_talk_level(1)
    window._apply_to_scene()
    assert mouth_item.opacity() == 1.0

    window.set_muted(True)
    window._apply_to_scene()
    assert mouth_item.opacity() == 0.0


def test_unmuting_immediately_reflects_whatever_talk_level_already_is(qapp):
    # No fresh audio update should be required to "wake up" after
    # unmuting -- effective_talk_level must fall straight back to
    # whatever talk_level has been the whole time it was muted.
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    mouth_item = window._runtimes[2].item

    window.set_talk_level(1)
    window.set_muted(True)
    window._apply_to_scene()
    assert mouth_item.opacity() == 0.0

    window.set_muted(False)
    window._apply_to_scene()
    assert mouth_item.opacity() == 1.0


def test_muted_suppresses_the_speech_bounce_retrigger(qapp):
    # Judgment call, documented in docs/PLAN.md: muting suppresses the whole
    # reactive performance (mouth AND bounce), not just the mouth shape
    # -- a bouncing-but-silent avatar would still visually read as
    # "talking energetically," which defeats the point of muting.
    rig = make_test_rig()
    config = MotionConfig(bounce_strength=250.0, gravity=1000.0, bounce_retrigger_ms=10.0)
    window = RenderWindow(rig, config)
    window.set_talk_level(2)
    window.set_muted(True)
    for _ in range(120):  # 2 simulated seconds -- plenty of time to bounce if it were going to
        window._simulate_step()
    assert window.bounce.y_position == 0.0  # never triggered at all


def test_effective_talk_level_property(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    window.set_talk_level(2)
    assert window.effective_talk_level == 2
    window.set_muted(True)
    assert window.effective_talk_level == 0
    window.set_muted(False)
    assert window.effective_talk_level == 2


def test_manual_muted_forces_the_mouth_closed_independent_of_obs_mute(qapp):
    # Quick-win enhancement E12 (bug audit addendum 2026-09-23): a manual
    # "mouth closed" toggle for a cough or an aside, without touching
    # OBS -- must work whether or not OBS mute (set_muted) is also
    # currently applied.
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    window.set_talk_level(2)
    assert window.effective_talk_level == 2

    window.set_manual_muted(True)
    assert window.effective_talk_level == 0

    window.set_manual_muted(False)
    assert window.effective_talk_level == 2


def test_manual_muted_and_obs_muted_are_independent_flags(qapp):
    # Neither one silently clears the other -- both must be lifted
    # before the mouth follows talk_level again.
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    window.set_talk_level(2)

    window.set_muted(True)
    window.set_manual_muted(True)
    assert window.effective_talk_level == 0

    window.set_muted(False)  # OBS unmutes -- manual toggle still forces shut
    assert window.effective_talk_level == 0

    window.set_manual_muted(False)  # now both are lifted
    assert window.effective_talk_level == 2


def test_set_window_size_resizes_the_window_and_the_scene_rect(qapp):
    # Quick-win enhancement E6 (bug audit addendum 2026-09-23):
    # previously only editable by hand in settings.json (applied once,
    # at construction, via the window_size constructor arg) -- must now
    # also work live. resizeEvent already keeps sceneRect pinned to the
    # widget's actual size (see its own comment), so a plain resize()
    # should be enough for both to end up correct.
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig(), window_size=(1280, 720))
    window.show()
    qapp.processEvents()

    window.set_window_size(1920, 1080)
    qapp.processEvents()

    assert (window.width(), window.height()) == (1920, 1080)
    scene_rect = window.scene.sceneRect()
    assert (scene_rect.width(), scene_rect.height()) == (1920, 1080)


def test_on_frame_does_not_simulate_before_one_sim_dt_elapses(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    window._last_time = time.monotonic()  # reset right before calling
    start_tick = window.tick
    window._on_frame()
    assert window.tick == start_tick


def test_on_frame_catches_up_after_a_stall(qapp):
    # The whole point of the accumulator: a real-time gap (e.g. the paint
    # loop stalling under encode load) must be made up in simulation
    # steps, not silently lost -- otherwise blink/sway/bounce timing
    # would warp under load instead of just looking choppy.
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    window._last_time = time.monotonic() - 0.5  # simulate a 500ms stall
    start_tick = window.tick
    window._on_frame()
    elapsed_ticks = window.tick - start_tick
    # 0.5s of debt, capped by MAX_CATCH_UP_SECONDS=0.25s -> ~15 steps at
    # SIM_DT=1/60s. Allow slack for scheduling jitter in the test itself.
    assert 10 <= elapsed_ticks <= round(0.25 / SIM_DT) + 2


def test_render_window_rebuild_after_sprite_added(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    rig.add_sprite(Sprite(id=3, path="c.png", image_data=make_test_png_bytes()))
    window.rebuild()
    assert len(window._runtimes) == 3


def test_sync_sprite_offset_and_z_without_full_rebuild(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    sprite = rig.by_id(2)
    sprite.offset = (10.0, 20.0)
    sprite.z_index = 5

    window.sync_sprite_offset_and_z(2)

    item = window._runtimes[2].item
    assert item.zValue() == 5


def test_bounce_does_not_run_away_over_many_frames(qapp):
    # End-to-end regression for the bug fixed 2026-09-15: continuous
    # talk_level with a short bounce_retrigger_ms must not send the
    # avatar flying upward forever. Drives _simulate_step directly (not
    # _on_frame) since the fixed-timestep sim is now decoupled from real
    # wall-clock time -- exactly what this test doesn't want to depend on.
    rig = make_test_rig()
    config = MotionConfig(bounce_strength=250.0, gravity=1000.0, bounce_retrigger_ms=50.0)
    window = RenderWindow(rig, config)
    window.set_talk_level(2)
    for _ in range(600):  # 10 simulated seconds at the fixed 60Hz timestep
        window._simulate_step()
        assert window.bounce.y_position >= -100.0


def test_hidden_sprite_stays_invisible_regardless_of_talk_level(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    mouth_sprite = rig.by_id(2)  # talk_state=1
    mouth_sprite.hidden = True
    mouth_item = window._runtimes[2].item

    window.set_talk_level(1)  # would normally show it
    window._apply_to_scene()
    assert mouth_item.opacity() == 0.0


def test_costume_hotkeys_1_through_9_select_slots_0_through_8(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    for digit_key, expected_slot in [
        (Qt.Key.Key_1, 0),
        (Qt.Key.Key_5, 4),
        (Qt.Key.Key_9, 8),
    ]:
        press_key(window, digit_key)
        assert rig.active_costume == expected_slot


def test_costume_hotkey_0_selects_slot_9(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    press_key(window, Qt.Key.Key_0)
    assert rig.active_costume == 9


def test_costume_hotkeys_are_remappable(qapp):
    rig = make_test_rig()
    hotkeys = HotkeysConfig(costume_keys=("F1", "2", "3", "4", "5", "6", "7", "8", "9", "0"))
    window = RenderWindow(rig, MotionConfig(), hotkeys_config=hotkeys)

    press_key(window, Qt.Key.Key_1)  # slot 0's old default key, now unbound
    assert rig.active_costume == 0  # unchanged: not 0 by matching, just its initial value

    rig.active_costume = 3
    press_key(window, Qt.Key.Key_1)
    assert rig.active_costume == 3  # confirmed: "1" really doesn't match slot 0 anymore

    press_key(window, Qt.Key.Key_F1)  # slot 0's new key
    assert rig.active_costume == 0


def test_oversized_costume_keys_cannot_push_active_costume_out_of_range(qapp):
    # Regression 2026-09-16, found in review: unlike the old hardcoded
    # 1-9/0 mapping (exactly 10 keys, always in range), costume_keys has
    # no length check of its own. A hand-edited config.json with an 11th
    # entry must not be able to set active_costume past the end of every
    # sprite's fixed-length (NUM_COSTUMES=10) costume_layers tuple --
    # that would IndexError the very next frame.
    rig = make_test_rig()
    extra_keys = tuple(f"F{i}" for i in range(1, 12))  # 11 entries, one too many
    hotkeys = HotkeysConfig(costume_keys=extra_keys)
    window = RenderWindow(rig, MotionConfig(), hotkeys_config=hotkeys)

    press_key(window, Qt.Key.Key_F11)  # the 11th, out-of-range slot

    assert rig.active_costume == 0  # unchanged -- F11 was never bound
    window._apply_to_scene()  # must not raise IndexError


def test_escape_always_quits_even_if_bound_to_a_costume_slot(qapp, monkeypatch):
    # Regression 2026-09-16: QKeySequenceEdit does not treat Escape as
    # "cancel this capture" (verified empirically) -- it's a capturable
    # key like any other, so a hand-edited config.json (or a future UI
    # bug) could bind it to a costume slot. Escape must still quit
    # unconditionally; it must never be shadowed by a costume match.
    rig = make_test_rig()
    rig.active_costume = 4  # a value slot 0 would never coincidentally produce
    hotkeys = HotkeysConfig(costume_keys=("Escape", "2", "3", "4", "5", "6", "7", "8", "9", "0"))
    window = RenderWindow(rig, MotionConfig(), hotkeys_config=hotkeys)
    closed = []
    monkeypatch.setattr(window, "close", lambda: closed.append(True))

    press_key(window, Qt.Key.Key_Escape)

    assert closed == [True]
    assert rig.active_costume == 4  # unchanged -- did not treat it as a costume switch to slot 0


def test_close_event_quits_when_no_quit_hook_is_set(qapp, monkeypatch):
    from unicorn_cloak import render as render_module

    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    quit_calls = []
    monkeypatch.setattr(render_module.QApplication, "instance", lambda: type("A", (), {"quit": lambda self: quit_calls.append(True)})())
    window.close()
    assert quit_calls == [True]


def test_close_event_asks_the_quit_hook_and_quits_if_it_returns_true(qapp, monkeypatch):
    from unicorn_cloak import render as render_module

    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    window.on_quit_requested = lambda: True
    quit_calls = []
    monkeypatch.setattr(render_module.QApplication, "instance", lambda: type("A", (), {"quit": lambda self: quit_calls.append(True)})())
    window.close()
    assert quit_calls == [True]


def test_close_event_is_cancelled_when_the_quit_hook_returns_false(qapp, monkeypatch):
    from unicorn_cloak import render as render_module

    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    window.show()
    window.on_quit_requested = lambda: False
    quit_calls = []
    monkeypatch.setattr(render_module.QApplication, "instance", lambda: type("A", (), {"quit": lambda self: quit_calls.append(True)})())
    window.close()
    assert quit_calls == []
    assert window.isVisible()


def test_double_click_calls_the_avatar_double_clicked_hook(qapp):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    calls = []
    window.on_avatar_double_clicked = lambda: calls.append(True)
    event = QMouseEvent(
        QEvent.Type.MouseButtonDblClick, QPointF(5, 5), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    window.mouseDoubleClickEvent(event)
    assert calls == [True]


def test_double_click_does_nothing_when_no_hook_is_set(qapp):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    event = QMouseEvent(
        QEvent.Type.MouseButtonDblClick, QPointF(5, 5), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    window.mouseDoubleClickEvent(event)  # must not raise


def test_remapped_hotkeys_still_take_effect_live(qapp):
    # HotkeysConfig is held by reference and read fresh every keypress --
    # Settings can rebind a key with no rebuild/reconnect needed.
    rig = make_test_rig()
    hotkeys = HotkeysConfig()
    window = RenderWindow(rig, MotionConfig(), hotkeys_config=hotkeys)

    press_key(window, Qt.Key.Key_5)
    assert rig.active_costume == 4

    keys = list(hotkeys.costume_keys)
    keys[7] = "5"  # slot 7 (costume 8) now also answers to "5"
    hotkeys.costume_keys = tuple(keys)

    press_key(window, Qt.Key.Key_5)
    assert rig.active_costume == 4  # slot 4 still comes first in the scan


def _parent_child_rig(*, child_drag_speed=8.0, child_z=0, child_clipped=False):
    png = make_test_png_bytes()
    parent = Sprite(id=1, path="p.png", image_data=png, position=(0.0, 0.0))
    child = Sprite(
        id=2,
        path="c.png",
        parent_id=1,
        image_data=png,
        position=(0.0, 50.0),
        drag_speed=child_drag_speed,
        z_index=child_z,
        clipped=child_clipped,
    )
    return AvatarRig(name="t", sprites=[parent, child])


def test_child_drag_lag_includes_parent_bounce(qapp):
    # Regression 2026-09-15 (transform-hierarchy review): a child's own
    # drag lag must chase a target that includes the parent's current
    # motion (bounce here), not just the child's own authored position --
    # otherwise a laggy child rigidly tracks its parent instead of
    # trailing behind it, which defeats the entire point of drag_speed
    # on something like hair attached to a head.
    rig = _parent_child_rig(child_drag_speed=8.0)
    config = MotionConfig(bounce_strength=250.0, gravity=1000.0)
    window = RenderWindow(rig, config)
    child_item = window._runtimes[2].item

    window.set_talk_level(2)  # triggers a bounce on this same step
    window._simulate_step()
    window._apply_to_scene()

    # No sway configured, so without the fix the child's local pos would
    # sit exactly at its authored (0, 50) regardless of the parent's
    # bounce. With it, the child hasn't caught up to the shifted target.
    assert child_item.pos().y() != 50.0


def test_child_with_zero_drag_speed_still_tracks_parent_drift_exactly(qapp):
    # A rigid (drag_speed=0) child should still end up visually attached
    # correctly -- drag_lag snaps straight to the target, so it should
    # land back at its own authored local position once _apply_to_scene
    # converts back out of the shared "world drift" space.
    rig = _parent_child_rig(child_drag_speed=0.0)
    config = MotionConfig(bounce_strength=250.0, gravity=1000.0)
    window = RenderWindow(rig, config)
    child_item = window._runtimes[2].item

    window.set_talk_level(2)
    window._simulate_step()
    window._apply_to_scene()

    assert child_item.pos().y() == 50.0


def test_negative_z_index_child_stacks_behind_parent(qapp):
    rig = _parent_child_rig(child_z=-1)
    window = RenderWindow(rig, MotionConfig())
    child_item = window._runtimes[2].item
    assert child_item.flags() & QGraphicsItem.GraphicsItemFlag.ItemStacksBehindParent


def test_non_negative_z_index_child_does_not_stack_behind_parent(qapp):
    rig = _parent_child_rig(child_z=0)
    window = RenderWindow(rig, MotionConfig())
    child_item = window._runtimes[2].item
    assert not (
        child_item.flags() & QGraphicsItem.GraphicsItemFlag.ItemStacksBehindParent
    )


def test_clipped_sprite_uses_alpha_mask_shape(qapp):
    rig = _parent_child_rig(child_clipped=False)
    rig.sprites[0].clipped = True
    window = RenderWindow(rig, MotionConfig())
    parent_item = window._runtimes[1].item
    assert parent_item.flags() & QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape
    assert parent_item.shapeMode() == QGraphicsPixmapItem.ShapeMode.MaskShape


def test_unclipped_sprite_has_no_clip_flag(qapp):
    rig = _parent_child_rig()
    window = RenderWindow(rig, MotionConfig())
    parent_item = window._runtimes[1].item
    assert not (
        parent_item.flags() & QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape
    )


_FRAME_COLORS = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)]


def _rgb(color):
    return (color.red(), color.green(), color.blue())


def test_multi_frame_sprite_starts_on_frame_zero(qapp):
    png = make_filmstrip_png_bytes(_FRAME_COLORS)
    sprite = Sprite(id=1, path="strip.png", image_data=png, frames=3, anim_speed=10.0)
    rig = AvatarRig(name="t", sprites=[sprite])
    window = RenderWindow(rig, MotionConfig())
    item = window._runtimes[1].item
    assert _rgb(item.pixmap().toImage().pixelColor(1, 1)) == (255, 0, 0)


def test_multi_frame_sprite_offset_uses_single_frame_width_not_sheet_width(qapp):
    png = make_filmstrip_png_bytes(_FRAME_COLORS, frame_size=4)
    sprite = Sprite(id=1, path="strip.png", image_data=png, frames=3)
    rig = AvatarRig(name="t", sprites=[sprite])
    window = RenderWindow(rig, MotionConfig())
    item = window._runtimes[1].item
    # Centered on one 4px frame, not the whole 12px-wide filmstrip.
    assert item.offset().x() == -2.0


def test_multi_frame_sprite_cycles_through_frames(qapp):
    png = make_filmstrip_png_bytes(_FRAME_COLORS)
    # anim_speed=10fps @ SIM_DT=1/60 -> 6 ticks per frame (see motion.py)
    sprite = Sprite(id=1, path="strip.png", image_data=png, frames=3, anim_speed=10.0)
    rig = AvatarRig(name="t", sprites=[sprite])
    window = RenderWindow(rig, MotionConfig())
    item = window._runtimes[1].item

    for _ in range(6):
        window._simulate_step()
    window._apply_to_scene()
    assert _rgb(item.pixmap().toImage().pixelColor(1, 1)) == (0, 255, 0)

    for _ in range(6):
        window._simulate_step()
    window._apply_to_scene()
    assert _rgb(item.pixmap().toImage().pixelColor(1, 1)) == (0, 0, 255)


def test_single_frame_sprite_pixmap_is_never_swapped(qapp):
    rig = make_test_rig()  # frames=1 everywhere, like every shipped sprite
    window = RenderWindow(rig, MotionConfig())
    item = window._runtimes[1].item
    original_key = item.pixmap().cacheKey()

    for _ in range(30):
        window._simulate_step()
    window._apply_to_scene()

    # _apply_to_scene only calls setPixmap when sprite.frames > 1, so a
    # static sprite's pixmap is the exact same object the whole time.
    assert item.pixmap().cacheKey() == original_key


def _rendered_corner_color(window):
    from PySide6.QtGui import QImage, QPainter

    size = window.size()
    image = QImage(size, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    window.scene.render(painter)
    painter.end()
    return image.pixelColor(5, 5)  # away from the tiny centered test sprites


def test_background_defaults_to_transparent(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig(), window_size=(200, 200))
    color = _rendered_corner_color(window)
    assert color.alpha() == 0


def test_background_solid_colors_are_fully_opaque(qapp):
    rig = make_test_rig()
    expected_rgb = {
        "black": (0, 0, 0),
        "white": (255, 255, 255),
        "green": (0, 255, 0),
    }
    for mode, rgb in expected_rgb.items():
        window = RenderWindow(rig, MotionConfig(), window_size=(200, 200), background=mode)
        color = _rendered_corner_color(window)
        assert (color.red(), color.green(), color.blue()) == rgb
        assert color.alpha() == 255


def test_set_background_is_live_updatable(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig(), window_size=(200, 200))
    assert _rendered_corner_color(window).alpha() == 0

    window.set_background("green")
    color = _rendered_corner_color(window)
    assert (color.red(), color.green(), color.blue(), color.alpha()) == (0, 255, 0, 255)

    window.set_background("transparent")
    assert _rendered_corner_color(window).alpha() == 0


def test_unknown_background_mode_falls_back_to_transparent(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig(), window_size=(200, 200))
    window.set_background("not-a-real-color")
    assert _rendered_corner_color(window).alpha() == 0


def test_background_image_shows_a_pixmap_item_scaled_to_fill_the_window(qapp, tmp_path):
    png_path = tmp_path / "bg.png"
    png_path.write_bytes(make_test_png_bytes())
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig(), window_size=(200, 100))
    window.set_background("image", str(png_path))

    assert window._background_image_item is not None
    assert window.scene.backgroundBrush().style() == Qt.BrushStyle.NoBrush
    pixmap = window._background_image_item.pixmap()
    transform = window._background_image_item.transform()
    assert transform.m11() == pytest.approx(200 / pixmap.width())
    assert transform.m22() == pytest.approx(100 / pixmap.height())


def test_background_image_with_a_bad_path_falls_back_to_transparent(qapp, tmp_path):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    window.set_background("image", str(tmp_path / "does-not-exist.png"))
    assert window._background_image_item is None
    assert window.scene.backgroundBrush().style() == Qt.BrushStyle.NoBrush


def test_background_video_with_an_empty_path_falls_back_to_transparent(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    window.set_background("video", "")
    assert window._background_video_item is None
    assert window._background_player is None


def test_background_video_constructs_a_muted_looping_player(qapp, tmp_path):
    from PySide6.QtMultimedia import QMediaPlayer

    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    fake_video = tmp_path / "bg.mp4"
    fake_video.write_bytes(b"not a real video, just needs to exist for the path check")
    window.set_background("video", str(fake_video))

    assert window._background_video_item is not None
    assert window._background_player is not None
    assert window._background_audio_output.isMuted() is True
    assert window._background_player.loops() == QMediaPlayer.Loops.Infinite


def test_switching_away_from_video_background_deletes_the_player(qapp, tmp_path, monkeypatch):
    # Regression, bug audit 2026-09-23 (#20, "media player leak"):
    # _clear_background_media used to just drop the Python reference to
    # self._background_player -- built as QMediaPlayer(self), so Qt's
    # C++ side kept it alive via that parent-child ownership regardless,
    # leaking one player (and its decoder resources) per background
    # switch. Confirmed via a spy on deleteLater() itself, not by
    # checking window._background_player is None afterward (which the
    # old, buggy code already made true) or by relying on Qt's own
    # deferred-deletion timing (real, but not reliably observable from
    # plain processEvents() calls in a test, especially with FFmpeg's
    # own async decode-error probing racing it for this fake file).
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    fake_video = tmp_path / "bg.mp4"
    fake_video.write_bytes(b"not a real video, just needs to exist for the path check")
    window.set_background("video", str(fake_video))
    old_player = window._background_player
    assert old_player is not None

    delete_later_calls = []
    monkeypatch.setattr(old_player, "deleteLater", lambda: delete_later_calls.append(True))

    window.set_background("transparent")

    assert delete_later_calls == [True]


def test_switching_away_from_image_background_cleans_up_the_pixmap_item(qapp, tmp_path):
    png_path = tmp_path / "bg.png"
    png_path.write_bytes(make_test_png_bytes())
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    window.set_background("image", str(png_path))
    assert window._background_image_item is not None

    window.set_background("black")
    assert window._background_image_item is None
    assert window.scene.backgroundBrush().color().getRgb()[:3] == (0, 0, 0)


def test_set_background_remembers_the_path_across_a_mode_switch(qapp, tmp_path):
    # Owner-facing behavior: switching Background to a solid color and
    # back to Image/Video (without re-Browsing) should redisplay whatever
    # file was already chosen -- see RenderWindow.set_background's own
    # docstring for why the path is stored on the instance, not just
    # passed through each call.
    png_path = tmp_path / "bg.png"
    png_path.write_bytes(make_test_png_bytes())
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    window.set_background("image", str(png_path))
    window.set_background("black")
    window.set_background("image")
    assert window._background_image_item is not None


def test_zoom_scales_root_item(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig(), zoom=2.5)
    assert window.zoom == 2.5
    assert window.root_item.scale() == 2.5


def test_zoom_does_not_move_root_item(qapp):
    # Zoom scales around the avatar's own center -- the window-centering
    # position must stay put, only the scale changes.
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig(), window_size=(300, 200))
    pos_before = window.root_item.pos()
    window.set_zoom(3.0)
    assert window.root_item.pos() == pos_before


def test_set_zoom_is_live_updatable(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    window.set_zoom(2.0)
    assert window.zoom == 2.0
    assert window.root_item.scale() == 2.0


def test_zoom_is_clamped_to_sane_range(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    window.set_zoom(999.0)
    assert window.zoom == 5.0  # MAX_ZOOM
    window.set_zoom(-1.0)
    assert window.zoom == 0.1  # MIN_ZOOM


def test_static_sprite_transform_stays_a_plain_identity(qapp):
    # Regression 2026-09-16, found while profiling: every sprite in the
    # real avatar has rotation_drag_strength=0 and stretch_amount=0 (no
    # real content uses either yet) -- _apply_to_scene must not call
    # setTransform() at all for a sprite whose rotation/scale never
    # leaves identity, not just produce a numerically-identity transform.
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    item = window._runtimes[2].item  # has no rotation_drag_strength/stretch_amount
    for _ in range(30):
        window._simulate_step()
    window._apply_to_scene()
    assert item.transform().isIdentity()


def test_static_scale_produces_a_non_identity_transform_even_at_rest(qapp):
    png = make_test_png_bytes()
    sprite = Sprite(id=1, path="a.png", image_data=png, scale_x=1.5, scale_y=0.75)
    rig = AvatarRig(name="t", sprites=[sprite])
    window = RenderWindow(rig, MotionConfig())
    item = window._runtimes[1].item

    window._simulate_step()
    window._apply_to_scene()

    transform = item.transform()
    assert not transform.isIdentity()
    assert transform.m11() == pytest.approx(1.5)
    assert transform.m22() == pytest.approx(0.75)


def test_static_rotation_produces_a_non_identity_transform_even_at_rest(qapp):
    png = make_test_png_bytes()
    sprite = Sprite(id=1, path="a.png", image_data=png, rotation_deg=45.0)
    rig = AvatarRig(name="t", sprites=[sprite])
    window = RenderWindow(rig, MotionConfig())
    item = window._runtimes[1].item

    window._simulate_step()
    window._apply_to_scene()

    transform = item.transform()
    assert not transform.isIdentity()
    expected = QTransform()
    expected.rotate(45.0)
    assert transform.m11() == pytest.approx(expected.m11())
    assert transform.m12() == pytest.approx(expected.m12())
    assert transform.m21() == pytest.approx(expected.m21())
    assert transform.m22() == pytest.approx(expected.m22())


def test_rotating_sprite_gets_a_real_non_identity_transform(qapp):
    png = make_test_png_bytes()
    sprite = Sprite(
        id=1, path="a.png", image_data=png,
        rotation_drag_strength=5.0, drag_speed=2.0,
    )
    rig = AvatarRig(name="t", sprites=[sprite])
    config = MotionConfig(bounce_strength=400.0, gravity=800.0)
    window = RenderWindow(rig, config)
    window.set_talk_level(2)  # triggers a bounce, which drives rotation velocity
    item = window._runtimes[1].item

    for _ in range(5):
        window._simulate_step()
    window._apply_to_scene()

    assert not item.transform().isIdentity()


def test_rotation_settling_back_to_zero_resets_the_transform_to_identity(qapp):
    # The resetTransform() path: once rotation/scale decay back to
    # nothing, the item's transform must actually go back to identity,
    # not get stuck on the last near-zero-but-not-quite value.
    png = make_test_png_bytes()
    sprite = Sprite(
        id=1, path="a.png", image_data=png,
        rotation_drag_strength=5.0, drag_speed=2.0,
    )
    rig = AvatarRig(name="t", sprites=[sprite])
    config = MotionConfig(bounce_strength=400.0, gravity=800.0, bounce_retrigger_ms=100_000.0)
    window = RenderWindow(rig, config)
    item = window._runtimes[1].item

    window.set_talk_level(2)
    for _ in range(5):
        window._simulate_step()
    window._apply_to_scene()
    assert not item.transform().isIdentity()  # mid-motion, as above

    window.set_talk_level(0)  # let it settle, no more bounce retriggers
    for _ in range(600):  # 10 simulated seconds at 60Hz
        window._simulate_step()
    window._apply_to_scene()
    assert item.transform().isIdentity()


def test_zoom_survives_rebuild(qapp):
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig(), zoom=2.0)
    window.rebuild()
    assert window.root_item.scale() == 2.0


def _two_mild_mouths_rig():
    png = make_test_png_bytes()
    mild_a = Sprite(id=1, path="mild-01.png", image_data=png, talk_state=1, variant=0)
    mild_b = Sprite(id=2, path="mild-02.png", image_data=png, talk_state=1, variant=1)
    return AvatarRig(name="t", sprites=[mild_a, mild_b])


def test_talk_variant_alternates_between_sprites_sharing_a_band(qapp):
    # End-to-end for rig.Sprite.variant / motion.sprite_alpha's variant
    # params: two "mild" mouths should take turns, never both invisible
    # and never both visible, while talk_level stays in their band.
    rig = _two_mild_mouths_rig()
    config = MotionConfig(mouth_variant_hz=60.0)  # 1 flip per sim tick at 60Hz
    window = RenderWindow(rig, config)
    window.set_talk_level(1)
    item_a, item_b = window._runtimes[1].item, window._runtimes[2].item

    window._simulate_step()
    window._apply_to_scene()
    first = (item_a.opacity(), item_b.opacity())
    assert sorted(first) == [0.0, 1.0]

    window._simulate_step()
    window._apply_to_scene()
    second = (item_a.opacity(), item_b.opacity())
    assert sorted(second) == [0.0, 1.0]
    assert second != first  # actually alternated, not stuck on one


def test_talk_variant_does_not_advance_while_band_is_inactive(qapp):
    # Silence (talk_level=0): neither mild mouth is in the active band, so
    # there's nothing to alternate between -- both stay hidden, and no
    # variant math should be running against an empty/irrelevant band.
    rig = _two_mild_mouths_rig()
    window = RenderWindow(rig, MotionConfig())
    window.set_talk_level(0)
    for _ in range(30):
        window._simulate_step()
    window._apply_to_scene()
    item_a, item_b = window._runtimes[1].item, window._runtimes[2].item
    assert (item_a.opacity(), item_b.opacity()) == (0.0, 0.0)


# --- Bug audit 2026-09-23, #4: distinct variant *values*, not sprite count -


def test_two_sprites_sharing_a_band_and_default_variant_never_both_vanish(qapp):
    # The core repro: two sprites that were simply never meant to
    # alternate (neither had its Variant field ever touched, so both
    # sit at the shared default, 0) must coexist, always -- not be
    # treated as "2 rivals" that only ever half-show. Old bug: raw
    # eligible-sprite count (2) fed a cycling index 0..1; on index 1,
    # neither sprite (both variant=0) matched, and both vanished for
    # half of every cycle.
    png = make_test_png_bytes()
    mouth = Sprite(id=1, path="mild-mouth.png", image_data=png, talk_state=1, variant=0)
    eyebrows = Sprite(id=2, path="raised-eyebrows.png", image_data=png, talk_state=1, variant=0)
    rig = AvatarRig(name="t", sprites=[mouth, eyebrows])
    config = MotionConfig(mouth_variant_hz=60.0)  # 1 flip per sim tick at 60Hz
    window = RenderWindow(rig, config)
    window.set_talk_level(1)
    item_mouth, item_eyebrows = window._runtimes[1].item, window._runtimes[2].item

    for _ in range(10):
        window._simulate_step()
        window._apply_to_scene()
        assert item_mouth.opacity() == 1.0
        assert item_eyebrows.opacity() == 1.0


def test_non_contiguous_variants_both_eventually_show(qapp):
    # Variants 0 and 2 (no 1) -- the old cycling-index approach only
    # ever reached 0..count-1 (0..1 here, for 2 sprites), so the
    # variant=2 sprite could never show at all; the cycle must instead
    # visit the *real* values present, 0 and 2.
    png = make_test_png_bytes()
    variant_0 = Sprite(id=1, path="mild-0.png", image_data=png, talk_state=1, variant=0)
    variant_2 = Sprite(id=2, path="mild-2.png", image_data=png, talk_state=1, variant=2)
    rig = AvatarRig(name="t", sprites=[variant_0, variant_2])
    config = MotionConfig(mouth_variant_hz=60.0)
    window = RenderWindow(rig, config)
    window.set_talk_level(1)
    item_0, item_2 = window._runtimes[1].item, window._runtimes[2].item

    seen_variant_2_visible = False
    for _ in range(10):
        window._simulate_step()
        window._apply_to_scene()
        if item_2.opacity() == 1.0:
            seen_variant_2_visible = True
        assert (item_0.opacity(), item_2.opacity()) in [(1.0, 0.0), (0.0, 1.0)]
    assert seen_variant_2_visible


def test_blink_variant_same_default_never_both_vanish(qapp):
    # Blink-axis counterpart of the talk-axis test above -- the audit's
    # own cited realistic trigger: separate left/right eye sprites, both
    # "Only eyes open", both left at the default variant.
    png = make_test_png_bytes()
    left_eye = Sprite(id=1, path="eye-left.png", image_data=png, blink_state=1, variant=0)
    right_eye = Sprite(id=2, path="eye-right.png", image_data=png, blink_state=1, variant=0)
    rig = AvatarRig(name="t", sprites=[left_eye, right_eye])
    config = MotionConfig(eye_variant_hz=60.0)
    window = RenderWindow(rig, config)
    item_left, item_right = window._runtimes[1].item, window._runtimes[2].item

    for _ in range(10):
        window._simulate_step()
        window.blink_level = 1  # pin "eyes open" -- blink_step's own randomness isn't what this test is about
        window._apply_to_scene()
        assert item_left.opacity() == 1.0
        assert item_right.opacity() == 1.0


def _two_open_eyes_rig():
    png = make_test_png_bytes()
    wide = Sprite(id=1, path="eyes-open-wide-01.png", image_data=png, blink_state=1, variant=0)
    squint = Sprite(id=2, path="eyes-squint-01.png", image_data=png, blink_state=1, variant=1)
    return AvatarRig(name="t", sprites=[wide, squint])


def test_blink_variant_alternates_between_sprites_sharing_a_band(qapp):
    # Mirrors test_talk_variant_alternates_between_sprites_sharing_a_band,
    # but for two "eyes open" shapes on the blink axis.
    rig = _two_open_eyes_rig()
    config = MotionConfig(eye_variant_hz=60.0)  # 1 flip per sim tick at 60Hz
    window = RenderWindow(rig, config)
    # blink_level defaults to 1 (not blinking) with no simulation run yet.
    item_a, item_b = window._runtimes[1].item, window._runtimes[2].item

    window._simulate_step()
    window._apply_to_scene()
    first = (item_a.opacity(), item_b.opacity())
    assert sorted(first) == [0.0, 1.0]

    window._simulate_step()
    window._apply_to_scene()
    second = (item_a.opacity(), item_b.opacity())
    assert sorted(second) == [0.0, 1.0]
    assert second != first


def test_talk_and_blink_variant_swaps_do_not_interfere(qapp):
    # A mouth (talk axis) and a pair of eyes (blink axis) alternating at
    # the same time must each cycle independently -- neither swap timer
    # should affect the other axis's sprites.
    png = make_test_png_bytes()
    mild_a = Sprite(id=1, path="mild-01.png", image_data=png, talk_state=1, variant=0)
    mild_b = Sprite(id=2, path="mild-02.png", image_data=png, talk_state=1, variant=1)
    wide_eye = Sprite(id=3, path="eyes-open-wide-01.png", image_data=png, blink_state=1, variant=0)
    squint_eye = Sprite(id=4, path="eyes-squint-01.png", image_data=png, blink_state=1, variant=1)
    rig = AvatarRig(name="t", sprites=[mild_a, mild_b, wide_eye, squint_eye])
    config = MotionConfig(mouth_variant_hz=60.0, eye_variant_hz=60.0)
    window = RenderWindow(rig, config)
    window.set_talk_level(1)

    for _ in range(4):
        window._simulate_step()
        window._apply_to_scene()
        mouths = (window._runtimes[1].item.opacity(), window._runtimes[2].item.opacity())
        eyes = (window._runtimes[3].item.opacity(), window._runtimes[4].item.opacity())
        assert sorted(mouths) == [0.0, 1.0]
        assert sorted(eyes) == [0.0, 1.0]


def test_hidden_sprite_does_not_count_toward_talk_variant_alternation(qapp):
    # Regression 2026-09-16: variant_count used to count every sprite in
    # the matching talk band regardless of whether it could actually be
    # shown. With one of two "mild" mouths hidden via the eye icon, only
    # one sprite is left eligible -- it must show continuously, not
    # alternate on/off against a rival that was never visible.
    rig = _two_mild_mouths_rig()
    rig.sprites[1].hidden = True  # mild_b hidden
    config = MotionConfig(mouth_variant_hz=60.0)
    window = RenderWindow(rig, config)
    window.set_talk_level(1)
    visible_item = window._runtimes[1].item  # mild_a, still eligible

    for _ in range(10):
        window._simulate_step()
        window._apply_to_scene()
        assert visible_item.opacity() == 1.0


def test_the_real_default_avatars_costume_slots_swap_hoodie_for_vest(qapp):
    # End-to-end sanity check against the shipped default avatar
    # (unicorn-demo), owner's request 2026-09-17 ("wire up the costumes...
    # swap hoody [both parts!] for vest"). Confirmed already fully wired
    # (see the same date's commit "Replace default avatar with
    # unicorn-demo, fully wired") -- this pins that behavior down so a
    # future costumeLayers edit can't silently break it. Package-relative
    # path (see config.py's own DEFAULT_AVATAR_PATH comment), so this
    # always runs rather than skip; the guard is a defensive fallback for
    # a stripped/partial checkout, not the common case.
    if not Path(DEFAULT_AVATAR_PATH).exists():
        pytest.skip("default avatar not present on this machine")
    rig = load_avatar(DEFAULT_AVATAR_PATH)
    window = RenderWindow(rig, MotionConfig())
    window._simulate_step()

    def opacity_by_path(suffix: str) -> float:
        rt = next(rt for rt in window._runtimes.values() if rt.sprite.path.endswith(suffix))
        return rt.item.opacity()

    window.rig.active_costume = 0
    window._apply_to_scene()
    assert opacity_by_path("clothes_hoodie_back.png") == 1.0
    assert opacity_by_path("clothes_hoodie_front.png") == 1.0
    assert opacity_by_path("clothes_vest_heart.png") == 0.0
    assert opacity_by_path("body_white_horse.png") == 0.0

    window.rig.active_costume = 1
    window._apply_to_scene()
    assert opacity_by_path("clothes_hoodie_back.png") == 0.0
    assert opacity_by_path("clothes_hoodie_front.png") == 0.0
    assert opacity_by_path("clothes_vest_heart.png") == 1.0
    assert opacity_by_path("body_white_horse.png") == 1.0


def test_costume_inactive_sprite_does_not_count_toward_talk_variant_alternation(qapp):
    from unicorn_cloak.rig import NUM_COSTUMES

    rig = _two_mild_mouths_rig()
    # mild_b excluded from the active costume slot (0) specifically.
    layers = [True] * NUM_COSTUMES
    layers[0] = False
    rig.sprites[1].costume_layers = tuple(layers)
    config = MotionConfig(mouth_variant_hz=60.0)
    window = RenderWindow(rig, config)
    window.rig.active_costume = 0
    window.set_talk_level(1)
    visible_item = window._runtimes[1].item  # mild_a, still in this costume

    for _ in range(10):
        window._simulate_step()
        window._apply_to_scene()
        assert visible_item.opacity() == 1.0


def test_single_sprite_band_ignores_variant_swap_rate(qapp):
    # A talk_state with only one sprite (every rig before 2026-09-16, and
    # still the common case for "wide") must show continuously, never
    # blink off because of the swap timer.
    rig = make_test_rig()  # sprite 2 is the only sprite with talk_state=1
    config = MotionConfig(mouth_variant_hz=60.0)
    window = RenderWindow(rig, config)
    window.set_talk_level(1)
    item = window._runtimes[2].item
    for _ in range(10):
        window._simulate_step()
        window._apply_to_scene()
        assert item.opacity() == 1.0


def test_talk_level_change_without_a_simulate_step_does_not_blank_the_mouth(qapp):
    # Regression 2026-09-20, owner's report on the real avatar: "every
    # once in a while i'm getting a quick flip to a state with no active
    # mouth." Root cause: SIM_DT (~16.67ms) is very slightly longer than
    # PAINT_INTERVAL_MS (16ms), so a fair number of _on_frame calls paint
    # (_apply_to_scene) with zero _simulate_step in between -- and
    # set_talk_level (called asynchronously, from the audio thread via a
    # queued connection) can change the talk level in exactly that gap.
    # Without _apply_to_scene recomputing the variant count/frame fresh,
    # a stale index left over from the *old* band (here: "mild", with its
    # own unrelated variant numbering) got applied to the *new* band's
    # sprites ("wide"), matching none of them and hiding the mouth
    # entirely for that one paint. This forces exactly that gap directly,
    # without depending on real timer/thread timing.
    png = make_test_png_bytes()
    sprites = [
        Sprite(id=1, path="mild-0.png", image_data=png, talk_state=1, variant=0),
        Sprite(id=2, path="mild-1.png", image_data=png, talk_state=1, variant=1),
        Sprite(id=3, path="mild-2.png", image_data=png, talk_state=1, variant=2),
        Sprite(id=4, path="wide-0.png", image_data=png, talk_state=2, variant=0),
        Sprite(id=5, path="wide-1.png", image_data=png, talk_state=2, variant=1),
    ]
    rig = AvatarRig(name="test", sprites=sprites)
    window = RenderWindow(rig, MotionConfig())

    window.set_talk_level(1)  # mild
    window._simulate_step()
    # Force the exact stale state a real run can land in: the last real
    # simulate step landed on variant 2 within the mild band -- valid
    # there (3 mild sprites, variants 0-2), but the wide band only has
    # variants 0-1.
    window._talk_variant_frame = 2

    window.set_talk_level(2)  # wide -- no _simulate_step in between, by design
    window._apply_to_scene()

    wide_items = [window._runtimes[4].item, window._runtimes[5].item]
    assert any(item.opacity() == 1.0 for item in wide_items)  # not all hidden
    mild_items = [window._runtimes[1].item, window._runtimes[2].item, window._runtimes[3].item]
    assert all(item.opacity() == 0.0 for item in mild_items)  # wrong band, correctly hidden
