from unicorn_cloak.rig import AvatarRig, Sprite, duplicate_sprite, generate_sprite_id


def make_sprite(id, parent_id=None, position=(0.0, 0.0), z_index=0):
    return Sprite(id=id, path=f"/tmp/{id}.png", parent_id=parent_id, position=position, z_index=z_index)


def test_sprite_scale_defaults_to_native_size():
    sprite = make_sprite(1)
    assert sprite.scale_x == 1.0
    assert sprite.scale_y == 1.0


def test_sprite_rotation_deg_defaults_to_unrotated():
    sprite = make_sprite(1)
    assert sprite.rotation_deg == 0.0


def test_zoom_defaults_to_native_size():
    rig = AvatarRig(name="t", sprites=[make_sprite(1)])
    assert rig.zoom == 1.0


def test_sprite_locked_defaults_to_false():
    sprite = make_sprite(1)
    assert sprite.locked is False


def test_costume_assignments_and_expression_hotkeys_default_to_empty_per_slot():
    from unicorn_cloak.rig import NUM_COSTUMES

    rig = AvatarRig(name="t", sprites=[make_sprite(1)])
    assert len(rig.costume_assignments) == NUM_COSTUMES
    assert all(pairs == [] for pairs in rig.costume_assignments)
    assert len(rig.expression_hotkeys) == NUM_COSTUMES
    assert all(pairs == [] for pairs in rig.expression_hotkeys)


def test_assign_costume_pair_shows_the_first_sprite_and_hides_the_second():
    rig = AvatarRig(name="t", sprites=[make_sprite(1), make_sprite(2)])
    rig.assign_costume_pair(2, hide_id=1, show_id=2)
    assert rig.costume_assignments[2] == [(1, 2)]
    assert rig.by_id(1).costume_layers[2] is True  # "hide" sprite: assumed off, shown here
    assert rig.by_id(2).costume_layers[2] is False  # "show" sprite: assumed on, hidden here
    # Untouched slots/sprites keep the "visible everywhere" default.
    assert rig.by_id(1).costume_layers[0] is True
    assert rig.by_id(2).costume_layers[0] is True


def test_assign_costume_pair_is_a_noop_for_an_unknown_sprite_id():
    rig = AvatarRig(name="t", sprites=[make_sprite(1)])
    rig.assign_costume_pair(0, hide_id=1, show_id=999)
    assert rig.costume_assignments[0] == []
    assert rig.by_id(1).costume_layers[0] is True


def test_remove_costume_pair_reverts_both_sprites_to_visible():
    rig = AvatarRig(name="t", sprites=[make_sprite(1), make_sprite(2)])
    rig.assign_costume_pair(2, hide_id=1, show_id=2)
    rig.remove_costume_pair(2, 0)
    assert rig.costume_assignments[2] == []
    assert rig.by_id(1).costume_layers[2] is True
    assert rig.by_id(2).costume_layers[2] is True


def test_costume_pair_can_be_added_multiple_times_to_the_same_slot():
    rig = AvatarRig(name="t", sprites=[make_sprite(1), make_sprite(2), make_sprite(3), make_sprite(4)])
    rig.assign_costume_pair(2, hide_id=1, show_id=2)
    rig.assign_costume_pair(2, hide_id=3, show_id=4)
    assert rig.costume_assignments[2] == [(1, 2), (3, 4)]
    assert rig.by_id(1).costume_layers[2] is True
    assert rig.by_id(3).costume_layers[2] is True


def test_assign_and_remove_expression_hotkey():
    rig = AvatarRig(name="t", sprites=[make_sprite(1)])
    rig.assign_expression_hotkey(4, "Mouth", "Laughing")
    assert rig.expression_hotkeys[4] == [("Mouth", "Laughing")]
    rig.remove_expression_hotkey(4, 0)
    assert rig.expression_hotkeys[4] == []


def test_generate_sprite_id_avoids_collisions():
    existing = {1, 2, 3}
    for _ in range(50):
        new_id = generate_sprite_id(existing)
        assert new_id not in existing
        existing.add(new_id)


def test_duplicate_sprite_gets_new_id_and_offset_position():
    original = make_sprite(1, position=(10.0, 20.0))
    copy = duplicate_sprite(original, new_id=2)
    assert copy.id == 2
    assert copy.position == (26.0, 36.0)
    assert copy.path == original.path
    assert original.position == (10.0, 20.0)  # original untouched


def test_duplicate_sprite_preserves_parent():
    original = make_sprite(1, parent_id=99)
    copy = duplicate_sprite(original, new_id=2)
    assert copy.parent_id == 99


def test_remove_sprite_orphans_children():
    rig = AvatarRig(name="test", sprites=[make_sprite(1), make_sprite(2, parent_id=1)])
    rig.remove_sprite(1)
    assert rig.by_id(1) is None
    child = rig.by_id(2)
    assert child is not None
    assert child.parent_id is None


def test_add_sprite():
    rig = AvatarRig(name="test", sprites=[make_sprite(1)])
    rig.add_sprite(make_sprite(2))
    assert len(rig.sprites) == 2
    assert rig.by_id(2) is not None


def test_new_sprite_id_avoids_existing():
    rig = AvatarRig(name="test", sprites=[make_sprite(1), make_sprite(2)])
    new_id = rig.new_sprite_id()
    assert new_id not in (1, 2)


def _chain_rig():
    # 1 -> 2 -> 3 (2 is child of 1, 3 is child of 2)
    return AvatarRig(
        name="test",
        sprites=[make_sprite(1), make_sprite(2, parent_id=1), make_sprite(3, parent_id=2)],
    )


def test_descendants_of_walks_whole_subtree():
    rig = _chain_rig()
    descendant_ids = {s.id for s in rig.descendants_of(1)}
    assert descendant_ids == {2, 3}
    assert {s.id for s in rig.descendants_of(2)} == {3}
    assert rig.descendants_of(3) == []


def test_can_reparent_to_root_always_allowed():
    rig = _chain_rig()
    assert rig.can_reparent(3, None) is True


def test_can_reparent_rejects_self_parent():
    rig = _chain_rig()
    assert rig.can_reparent(1, 1) is False


def test_can_reparent_rejects_own_descendant():
    rig = _chain_rig()
    # 1 becoming a child of 3 (its own grandchild) would create a cycle
    assert rig.can_reparent(1, 3) is False
    assert rig.can_reparent(1, 2) is False


def test_can_reparent_allows_unrelated_sprite():
    rig = _chain_rig()
    rig.add_sprite(make_sprite(4))
    assert rig.can_reparent(1, 4) is True


def _three_siblings_rig():
    return AvatarRig(
        name="test",
        sprites=[
            make_sprite(1, z_index=0),
            make_sprite(2, z_index=1),
            make_sprite(3, z_index=2),
        ],
    )


def test_move_layer_up_swaps_with_next_higher_sibling():
    rig = _three_siblings_rig()
    swapped_id = rig.move_layer_up(1)  # z=0 swaps with z=1
    assert swapped_id == 2
    assert rig.by_id(1).z_index == 1
    assert rig.by_id(2).z_index == 0
    assert rig.by_id(3).z_index == 2  # untouched


def test_move_layer_down_swaps_with_next_lower_sibling():
    rig = _three_siblings_rig()
    swapped_id = rig.move_layer_down(3)  # z=2 swaps with z=1
    assert swapped_id == 2
    assert rig.by_id(3).z_index == 1
    assert rig.by_id(2).z_index == 2
    assert rig.by_id(1).z_index == 0  # untouched


def test_move_layer_up_at_top_is_a_no_op():
    rig = _three_siblings_rig()
    assert rig.move_layer_up(3) is None  # already highest z among siblings
    assert [s.z_index for s in rig.sprites] == [0, 1, 2]


def test_move_layer_down_at_bottom_is_a_no_op():
    rig = _three_siblings_rig()
    assert rig.move_layer_down(1) is None
    assert [s.z_index for s in rig.sprites] == [0, 1, 2]


def test_move_layer_only_considers_siblings_with_same_parent():
    # z_index is parent-relative -- a sprite under a different parent
    # must never be swapped with, even if its z_index is numerically
    # adjacent.
    rig = AvatarRig(
        name="test",
        sprites=[
            make_sprite(1, z_index=0),
            make_sprite(2, parent_id=99, z_index=1),  # different parent
        ],
    )
    assert rig.move_layer_up(1) is None
    assert rig.by_id(1).z_index == 0
    assert rig.by_id(2).z_index == 1


def _tied_z_siblings_rig():
    # Every sprite in every real file this app has ever touched leaves
    # z_index at its default (0) and relies on list order to break the
    # tie (see _siblings_by_z) -- this is the realistic case, not the
    # distinct-z-index rigs above.
    return AvatarRig(
        name="test",
        sprites=[make_sprite(1), make_sprite(2), make_sprite(3)],
    )


def test_move_layer_up_with_tied_z_index_actually_changes_stacking_order():
    # Regression 2026-09-16: swapping z_index alone between two sprites
    # that share the same value is a no-op (0 <-> 0 is still 0), which
    # silently made Move Up/Move Down do nothing for every real rig --
    # every real sprite defaults to z_index=0. move_layer_up must still
    # produce a different stacking order in this case. Sprite 1 starts
    # frontmost (see test_stacking_order_is_front_to_back_by_list_order
    # below), so move it from the back (sprite 3) instead, one step
    # toward the front.
    rig = _tied_z_siblings_rig()
    before = [s.id for s, _ in rig.sprites_in_stacking_order()]
    assert before == [1, 2, 3]
    swapped_id = rig.move_layer_up(3)
    assert swapped_id == 2
    after = [s.id for s, _ in rig.sprites_in_stacking_order()]
    assert after != before
    assert after == [1, 3, 2]  # 3 moved one step toward the front, past 2


def test_move_layer_up_when_already_frontmost_is_a_no_op():
    rig = _tied_z_siblings_rig()
    assert rig.move_layer_up(1) is None  # 1 is already frontmost
    assert [s.id for s in rig.sprites] == [1, 2, 3]


def test_move_layer_down_with_tied_z_index_actually_changes_stacking_order():
    # Sprite 3 starts backmost -- move sprite 1 (frontmost) down instead,
    # one step toward the back.
    rig = _tied_z_siblings_rig()
    before = [s.id for s, _ in rig.sprites_in_stacking_order()]
    swapped_id = rig.move_layer_down(1)
    assert swapped_id == 2
    after = [s.id for s, _ in rig.sprites_in_stacking_order()]
    assert after != before
    assert after == [2, 1, 3]  # 1 moved one step toward the back, past 2


def test_move_layer_down_when_already_backmost_is_a_no_op():
    rig = _tied_z_siblings_rig()
    assert rig.move_layer_down(3) is None  # 3 is already backmost
    assert [s.id for s in rig.sprites] == [1, 2, 3]


def test_stacking_order_is_front_to_back_by_list_order_when_z_is_tied():
    rig = _tied_z_siblings_rig()
    assert [s.id for s, _ in rig.sprites_in_stacking_order()] == [1, 2, 3]


def test_move_layer_with_distinct_z_index_does_not_also_reorder_the_list():
    # When z_index actually differs, swapping it alone already produces
    # the right order -- _swap_stacking must not additionally touch list
    # position in that case (list order should stay whatever it was).
    rig = _three_siblings_rig()
    original_list_order = [s.id for s in rig.sprites]
    rig.move_layer_up(1)
    assert [s.id for s in rig.sprites] == original_list_order


def test_stacking_order_is_highest_z_first():
    rig = _three_siblings_rig()  # z 0, 1, 2 for ids 1, 2, 3
    order = [s.id for s, _depth in rig.sprites_in_stacking_order()]
    assert order == [3, 2, 1]


def test_stacking_order_matches_move_layer_up_after_a_move():
    rig = _three_siblings_rig()
    rig.move_layer_up(1)  # 1 <-> 2: now z=[1:1, 2:0, 3:2]
    order = [s.id for s, _depth in rig.sprites_in_stacking_order()]
    assert order == [3, 1, 2]


def test_stacking_order_groups_children_under_their_parent():
    rig = _chain_rig()  # 1 -> 2 -> 3, all z=0
    result = rig.sprites_in_stacking_order()
    assert [(s.id, depth) for s, depth in result] == [(1, 0), (2, 1), (3, 2)]


def test_stacking_order_sorts_children_by_their_own_z_too():
    rig = AvatarRig(
        name="test",
        sprites=[
            make_sprite(1),
            make_sprite(2, parent_id=1, z_index=0),
            make_sprite(3, parent_id=1, z_index=5),
        ],
    )
    order = [s.id for s, _depth in rig.sprites_in_stacking_order()]
    assert order == [1, 3, 2]  # child z=5 in front of child z=0
