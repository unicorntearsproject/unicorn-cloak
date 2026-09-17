"""
Data model for an avatar rig: a tree of layered sprites. Save-file shape
(JSON, embedded base64 PNG per sprite) matches
`unicorn-tears-avatar-01-hoody-hair-aviator-bling.save` so it loads
without conversion (see persistence.py).

TRANSFORM HIERARCHY CONTRACT
=============================
This is the part of the rig that's easy to implement subtly wrong, so
it's written down here as the contract render.py and editor_window.py
must honor -- not left to be reverse-engineered from render.py's Qt
plumbing. (Documented 2026-09-15, prompted by a review that found several
of these weren't yet true of the renderer; render.py was brought in line
with this the same day -- see docs/PLAN.md's status log for which parts.)

Coordinate space
  A sprite's `position` and `offset` are in its PARENT's local coordinate
  space (root sprites are relative to the avatar's own anchor point, which
  render.py keeps pinned to the Render Window's current center -- resizing
  the window must not shift the avatar, since the anchor is recomputed
  from the window's live size every frame, not cached at startup).

Parent/child inheritance -- a child sprite inherits ALL of these from its
parent, on top of its own:
  - Position: composed automatically by nesting child items under their
    parent's item in the scene graph (parent moves -> child moves with
    it, for free).
  - Rotation and stretch: same mechanism -- a parent's rotation/stretch
    transform applies to its children's rendering automatically because
    they're nested inside it.
  - Drag lag: NOT automatic, and easy to get wrong. A child's own
    drag-lag chase target must include the parent's current motion
    (its bounce contribution and its own settled drag position), not just
    the child's authored position plus its own sway. Otherwise the child
    rigidly tracks wherever the parent instantaneously is and never lags
    *behind* a moving parent -- which is the entire visual point of
    attaching, say, hair to a head with drag_speed > 0.

Z-index is relative to the parent, not global -- it only orders a sprite
among its own siblings. A negative z_index means "draw behind my parent"
(e.g. a hair-back layer behind the head, hair-front in front of it) --
this needs an explicit opt-in in Qt (QGraphicsItem.ItemStacksBehindParent
on any child with z_index < 0), because Qt's default is that a child
*always* paints on top of its parent regardless of z-value sign.

`clipped=True` means: mask this sprite's children to this sprite's own
alpha shape, not just its bounding rectangle -- e.g. contents that should
only ever show up within a silhouette. In Qt this needs
QGraphicsItem.ItemClipsChildrenToShape plus
QGraphicsPixmapItem.setShapeMode(ShapeMode.MaskShape); the flag alone
clips to the bounding rect, not the actual opaque pixels.

`frames`/`anim_speed`: sprite-sheet animation. The image is `frames`
equal-width horizontal slices (see spritesheet.py); `anim_speed` is an
honest frames-per-second value (not a port of legacy's animation()
formula, which barely used its own anim_speed parameter -- see
motion.animation_frame_step). Implemented in render.py 2026-09-15; the
editor always shows frame 0 (it's a static preview, see
editor_window.py's module docstring) and exposes both fields in the
property panel, with `frames` triggering a rebuild since it changes the
item's pixmap slicing.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field, replace

# talk_state / blink_state use the same three-value convention (see
# motion.axis_visible for what each value means).
STATE_BASE = 0
STATE_INACTIVE = 1
STATE_ACTIVE = 2

NUM_COSTUMES = 10


@dataclass
class Sprite:
    """One layer in the rig: an image plus its motion/visibility rules."""

    id: int
    path: str
    parent_id: int | None = None

    # PNG bytes, kept in memory so a save file is self-contained. Not set
    # for sprites still referencing an on-disk path only.
    image_data: bytes | None = None

    # Placement
    position: tuple[float, float] = (0.0, 0.0)
    offset: tuple[float, float] = (0.0, 0.0)
    z_index: int = 0

    # Static, authored size multiplier -- added 2026-09-17 (owner's
    # request: "add scale features to the positioning section... a lock
    # toggle... that scales x & y maintaining proportions"). 1.0 is the
    # image's own native size. Deliberately separate from
    # `stretch_amount` below, which is a *reactive* squash/stretch that
    # animates with drag velocity and always returns to (1, 1) at rest --
    # this is a fixed baseline the reactive stretch multiplies on top of,
    # for permanently resizing a layer (e.g. a smaller/larger prop) or
    # correcting art that wasn't authored at the same scale as everything
    # else it's layered with.
    scale_x: float = 1.0
    scale_y: float = 1.0

    # Static, authored rotation (degrees) -- owner's request, 2026-09-17:
    # "in the editor, drag the active sprite around and scale/rotate it."
    # Same relationship to rotation_drag_strength below as scale_x/y has
    # to stretch_amount: this is a fixed baseline angle (e.g. a permanently
    # tilted accessory), the *reactive* drag-based rotation below adds on
    # top of it and still returns to this value at rest, not to 0.
    rotation_deg: float = 0.0

    # Secondary motion: idle sway (independent sine per axis)
    sway_x_freq: float = 0.0
    sway_x_amp: float = 0.0
    sway_y_freq: float = 0.0
    sway_y_amp: float = 0.0

    # Secondary motion: drag/spring lag behind the sway+parent position.
    # 0 means "rigid, no lag" (see motion.drag_lag).
    drag_speed: float = 0.0

    # Secondary motion: rotation reacts to this sprite's own vertical
    # drag velocity (see motion.rotation_step).
    rotation_drag_strength: float = 0.0
    rotation_limit_min_deg: float = -180.0
    rotation_limit_max_deg: float = 180.0

    # Secondary motion: squash/stretch reacts to the same velocity
    # (see motion.stretch_step). 0 disables it.
    stretch_amount: float = 0.0

    # Exclude this sprite from the avatar-wide speak-bounce when
    # computing its own drag velocity (see motion.rotation_step /
    # stretch_step ignore_bounce_delta parameter).
    ignore_bounce: bool = False

    # Sprite-sheet animation
    frames: int = 1
    anim_speed: float = 0.0

    # Visibility gates. 0 = always visible. 1, 2, or motion.TALK_QUIET_ONLY
    # (talk_state only) = visible only when the driver (talk_level /
    # blink_level) is exactly at that band. See motion.axis_visible and
    # motion.sprite_alpha. Ignored entirely when manual_driven is True.
    talk_state: int = STATE_BASE
    blink_state: int = STATE_BASE

    # Purely organizational, added 2026-09-16 -- ties sprites together as
    # belonging to the same expressive slot (e.g. group_name="Mouth",
    # state_name="Closed"/"Open wide"/"Laughing") instead of them only
    # coincidentally working out via matching numbers and overlapping
    # positions, which is what let the mouth-stacking bug go unnoticed
    # (see motion.TALK_QUIET_ONLY's docstring). Neither field drives
    # anything by itself -- group_name/state_name are read by the
    # Editor's grouping UI and rig_lint.find_rig_issues, and by
    # manual_driven below when it's True. "" means "not part of any
    # named group" (hair, body, etc.).
    group_name: str = ""
    state_name: str = ""

    # If True, talk_state/blink_state are ignored entirely -- this
    # sprite is visible only when its group_name's live manual override
    # (RenderWindow.manual_overrides / EditorWindow's own preview-only
    # copy) equals state_name exactly. For an expression like "Laughing"
    # that isn't tied to mic volume or the blink timer at all -- set live
    # via a control (Settings, for the real Render Window; the Editor's
    # own Preview state, for canvas preview only), not automatically.
    manual_driven: bool = False

    # When more than one sprite shares the same nonzero state on whichever
    # axis actually gates it (talk_state OR blink_state -- a sprite is
    # only ever meaningfully driven by one of the two in practice), this
    # says which alternation slot it's in (0, 1, 2...): those sprites take
    # turns showing while that state stays active, instead of freezing on
    # one static image the whole time. Two use cases today: a talk_state
    # with two mouth shapes (e.g. mild-01/mild-02) flapping during
    # continuous speech, and a blink_state with two "eyes open" shapes
    # (e.g. wide-open/squint) giving idle expression some variety between
    # blinks. See motion.sprite_alpha's talk_variant/blink_variant params
    # and render.py's two independent swap timers. Meaningless (and
    # ignored) when a state has only one sprite in it.
    variant: int = 0

    # Which of the 10 costume slots this sprite appears in.
    costume_layers: tuple[bool, ...] = tuple([True] * NUM_COSTUMES)

    clipped: bool = False

    # A manual, always-in-effect visibility override -- independent of
    # costume/talk/blink gating and unrelated to `toggle` (a hotkey-bound
    # name, not a bool). True hides this sprite everywhere (Render Window
    # and the Editor canvas both). Meant for a quick "I'm not using this
    # layer right now" switch -- e.g. glasses vs. bare eyes, where only
    # one should ever be visible at a time -- without deleting it or
    # touching its other settings. Toggled via the eye icon next to each
    # layer in the Editor's sprite list; defaults to visible.
    hidden: bool = False

    # A hotkey-bindable per-sprite visibility toggle, independent of
    # costume/talk/blink. "null" (the literal string, not JSON null) is
    # legacy's "unbound" value and is what every sprite in avatar-01
    # actually has right now. Not read by anything yet -- no hotkey
    # wiring exists for it -- but it must survive load/save untouched;
    # it was previously dropped entirely (fixed 2026-09-15).
    toggle: str = "null"

    def __post_init__(self) -> None:
        if len(self.costume_layers) != NUM_COSTUMES:
            raise ValueError(
                f"costume_layers must have exactly {NUM_COSTUMES} entries, "
                f"got {len(self.costume_layers)}"
            )


@dataclass
class AvatarRig:
    """A named avatar: its sprite tree plus the active costume slot."""

    name: str
    sprites: list[Sprite] = field(default_factory=list)
    active_costume: int = 0  # index into costume_layers, 0-based

    def by_id(self, sprite_id: int) -> Sprite | None:
        for sprite in self.sprites:
            if sprite.id == sprite_id:
                return sprite
        return None

    def children_of(self, sprite_id: int) -> list[Sprite]:
        return [s for s in self.sprites if s.parent_id == sprite_id]

    def descendants_of(self, sprite_id: int) -> list[Sprite]:
        result = []
        for child in self.children_of(sprite_id):
            result.append(child)
            result.extend(self.descendants_of(child.id))
        return result

    def can_reparent(self, sprite_id: int, new_parent_id: int | None) -> bool:
        """False if new_parent_id is the sprite itself or one of its own
        descendants -- either would create a cycle in the tree."""
        if new_parent_id is None:
            return True
        if new_parent_id == sprite_id:
            return False
        descendant_ids = {s.id for s in self.descendants_of(sprite_id)}
        return new_parent_id not in descendant_ids

    def roots(self) -> list[Sprite]:
        return [s for s in self.sprites if s.parent_id is None]

    def visible_in_active_costume(self) -> list[Sprite]:
        return [
            s for s in self.sprites if s.costume_layers[self.active_costume]
        ]

    def sprites_in_stacking_order(self) -> list[tuple[Sprite, int]]:
        """Depth-first, front-to-back within each parent (highest
        z_index first) -- pairs of (sprite, depth), depth for a UI to
        indent by so parent/child grouping is visible. Matches
        move_layer_up/down's notion of "next sibling", so a sprite list
        built from this actually reorders when you move a layer instead
        of silently staying put while only the z-index changes -- that
        disconnect is exactly what made this unintuitive before
        (2026-09-16)."""
        result: list[tuple[Sprite, int]] = []

        def walk(parent_id: int | None, depth: int) -> None:
            siblings = sorted(
                (s for s in self.sprites if s.parent_id == parent_id),
                key=lambda s: -s.z_index,
            )
            for sprite in siblings:
                result.append((sprite, depth))
                walk(sprite.id, depth + 1)

        walk(None, 0)
        return result

    def add_sprite(self, sprite: Sprite) -> None:
        self.sprites.append(sprite)

    def remove_sprite(self, sprite_id: int) -> None:
        """Removes a sprite; any children are orphaned (reparented to
        root) rather than deleted with it."""
        for child in self.children_of(sprite_id):
            child.parent_id = None
        self.sprites = [s for s in self.sprites if s.id != sprite_id]

    def new_sprite_id(self) -> int:
        return generate_sprite_id({s.id for s in self.sprites})

    def _siblings_front_to_back(self, sprite_id: int) -> list[Sprite]:
        # z_index is relative to the parent (see the transform contract
        # above), so "move up/down" only ever reorders among siblings --
        # moving past a sprite with a different parent would silently
        # change what the number even means. Same sort key as
        # sprites_in_stacking_order's per-parent grouping (highest z
        # first, ties broken by list order) -- deliberately the *same*
        # key, not just an equivalent-looking one: move_layer_up/down
        # used to rank siblings back-to-front with ties broken the
        # opposite way round from this, which was invisible only because
        # a tied swap never touched anything (see move_layer_up's
        # docstring) -- once it did, "up" would have moved a tied sprite
        # toward the back (found and fixed 2026-09-16).
        sprite = self.by_id(sprite_id)
        siblings = [s for s in self.sprites if s.parent_id == sprite.parent_id]
        return sorted(siblings, key=lambda s: (-s.z_index, self.sprites.index(s)))

    def move_layer_up(self, sprite_id: int) -> int | None:
        """Moves the sprite one step toward the front, swapping places
        with whichever sibling is currently drawn immediately in front of
        it. Returns that sibling's id, or None if already frontmost among
        its siblings (nothing changed)."""
        front_to_back = self._siblings_front_to_back(sprite_id)
        index = next(i for i, s in enumerate(front_to_back) if s.id == sprite_id)
        if index == 0:
            return None
        this_sprite, other = front_to_back[index], front_to_back[index - 1]
        self._swap_stacking(this_sprite, other)
        return other.id

    def move_layer_down(self, sprite_id: int) -> int | None:
        """Moves the sprite one step toward the back, swapping places
        with whichever sibling is currently drawn immediately behind it.
        Returns that sibling's id, or None if already bottommost among
        its siblings (nothing changed)."""
        front_to_back = self._siblings_front_to_back(sprite_id)
        index = next(i for i, s in enumerate(front_to_back) if s.id == sprite_id)
        if index == len(front_to_back) - 1:
            return None
        this_sprite, other = front_to_back[index], front_to_back[index + 1]
        self._swap_stacking(this_sprite, other)
        return other.id

    def _swap_stacking(self, a: Sprite, b: Sprite) -> None:
        """Swaps two siblings' effective stacking order. Every real rig in
        this app leaves z_index at its default (0) on every sprite and
        relies entirely on list order to break the tie (see
        _siblings_front_to_back's own docstring) -- swapping z_index
        alone in that case swaps two identical numbers, a complete no-op
        that made Move Up/Move Down silently do nothing (found
        2026-09-16). Swapping list position too, whenever the z_index
        swap didn't actually change anything, is what actually moves a
        tied sprite; when z_index does differ, that alone already
        produces the new order, so list position is left alone in that
        case."""
        a.z_index, b.z_index = b.z_index, a.z_index
        if a.z_index == b.z_index:
            i = next(k for k, s in enumerate(self.sprites) if s.id == a.id)
            j = next(k for k, s in enumerate(self.sprites) if s.id == b.id)
            self.sprites[i], self.sprites[j] = self.sprites[j], self.sprites[i]


def generate_sprite_id(existing_ids: set[int]) -> int:
    rng = random.Random()
    while True:
        candidate = rng.randint(1, 2**31 - 1)
        if candidate not in existing_ids:
            return candidate


def duplicate_sprite(
    sprite: Sprite, new_id: int, offset: tuple[float, float] = (16.0, 16.0)
) -> Sprite:
    """A copy of `sprite` with a new id, nudged so it doesn't sit exactly
    on top of the original. parent_id is preserved."""
    return replace(
        sprite,
        id=new_id,
        position=(sprite.position[0] + offset[0], sprite.position[1] + offset[1]),
    )
