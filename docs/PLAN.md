# Unicorn Cloak — Project Plan

A from-scratch, Python replacement for **PNGTuber-Plus**
(`~/Repos/pngtuber-plus`, Godot 4.1.2), same intent: a mic-reactive,
layered-sprite avatar overlay window that OBS captures as a window/portal
source. The original ships with its own disclaimer ("this is a SLOP
project") and the source backs that up — inconsistent naming, no undo, a
few genuinely embarrassing internal identifiers, and a rigid single-window
edit/view toggle. This plan replaces it, in three phases, without carrying
the mess forward.

Status (last refreshed 2026-09-19): **Phase 1 nearly done, three of
Phase 2's five milestones pulled forward, running end-to-end on real
hardware.** Phase 2: design tokens (Milestone 1) and the live capture
preview (Milestone 3) are done; the performance pass (Milestone 4) is
genuinely half-done -- three real, measured fixes landed (a redundant
per-frame transform call, and two numpy inefficiencies in the audio
thread that a real `perf` sampling profile proved were the actual
largest costs, 4.3x and 9.1x faster respectively), but the full picture
is more complicated than "near-zero idle CPU" and that's stated honestly
below, not glossed over.
Milestones 1, 2, 3, 6, 7 are done; Milestone 4 (costume + hotkeys) is
done (remappable, focus-only by deliberate design — see below); Milestone
5 (Editor UI) is the only thing left in Phase 1, missing canvas
zoom/pan, multi-select, and an action-log toast panel. Milestone 7
closed out 2026-09-16: capture confirmed clean by the owner directly
("render capture is super clean"), and PNGTuber-Plus deprecation is now
final, not just planned ("this is hot garbage! ... done & dusted") --
see the `obs` repo's own changelog/decision-record update for that side
of it. Beyond the phased plan, owner-directed work has also landed
outside any milestone: a file-based audio source for re-recording
workflows, OBS mute awareness, a visual tuning meter, envelope
record/replay, hot reload of the save file and sprite PNGs, costume
snapshot export to PNG, Settings' scroll-safe spinboxes with Reset/Lock,
and — closing out a real, previously-deferred bug report — a genuine
mutually-exclusive talk-state model (`motion.TALK_QUIET_ONLY`), an
Editor "Preview state" control, descriptive Talk/Blink state dropdowns,
a mic sensitivity/gain knob, and a fix to the real avatar file's closed
mouth (was `talk_state=0`/always-visible, now correctly gated to quiet
only). Following the owner's own question ("it's all just coincidence
right now"), sprites can now be tied together on purpose: named
`group_name`/`state_name` fields, a `manual_driven` axis for expressions
like "Laughing" (live-toggled from Settings' new "Expressions" group),
Editor preview controls extended to force a specific variant or
expression, and a heuristic `rig_lint.find_rig_issues` sanity-check pass
("Check for Issues…"). Then, 2026-09-17: the separate Editor and Settings
windows (a drift from the original "two-window" decision, never
reconfirmed) were merged into one **Control Panel** window -- originally
four tabs (Sprites/Behavior/Audio/Application) of resizable, collapsible
sections, a canvas with a Live Preview/Edit Sprites toggle and an
always-visible level meter, a persistent bottom bar (audio source
controls, Save/Save As/Load/Export/Check for Issues/Guide/Ghost/Quit), a
grid replacing the old origin crosshair, dirty-tracking with a real quit
confirmation (Escape and Quit both warn about unsaved changes now, which
nothing did before), and full window/tab/toggle state persistence.

Still 2026-09-17, in a long same-day follow-up series (owner iterating
against real screenshots): whole-avatar **Zoom** moved from Application
to Behavior's Position & Hierarchy; **image/video backgrounds** added
(`QGraphicsVideoItem`/`QMediaPlayer` via PySide6's bundled FFmpeg
backend, no new dependency); the edit canvas gained real **drag-to-
scale/rotate** handles (not just spinboxes), backed by new authored
`scale_x/y`/`rotation_deg` fields; and costume/expression switching was
reworked from raw numbered hotkeys into **explicit sprite-pair
assignments** (`AvatarRig.costume_assignments`/`expression_hotkeys`,
Shift+1..0 for expressions) with their own dedicated tabs. Those tabs
were rebuilt several times the same day chasing layout bugs (two-column
→ single-column → `QScrollArea` → finally `QListWidget`+`setItemWidget`,
matching the Sprites tab's own Layer List technique) and renamed twice to
stop "Expressions" from meaning two different things a tab apart. The
**Control Panel is now six tabs**: Sprites, **Costume Hotkeys**,
**Expression Hotkeys**, Behavior, Audio, Application. Canvas zoom/pan,
multi-select, and an action-log toast panel are still not built --
Milestone 5's only genuinely open items. **411 tests total** (see the
per-file breakdown implicit in each dated entry below).

**2026-09-18 — docs reorg (this update).** The 2026-09-17 "docs reorg"
entry below only moved `PLAN.md` itself into `docs/`; two more
Unicorn-Cloak-specific docs that had been left behind in the parent `obs`
repo -- `docs/avatar-lipsync-setup.md` (the superseded PNGTuber-Plus
setup doc) and `docs/decisions/0004-avatar-lipsync-tooling.md` (the
decision to build this app in the first place) -- are now moved here too,
at `avatar-lipsync-setup.md` and `decisions/0001-avatar-lipsync-tooling.md`
respectively (renumbered as this project's own first decision record).
Every cross-reference to their old locations, in both repos, was updated
to match; see the `obs` repo's own README changelog for that side of it.
No code changed in this pass.

**2026-09-19 — notes-driven Control Panel fixes, first pass since the
standalone-repo split.** Owner kept a running scratch `notes` file of UI
complaints while using the app; worked through it item by item. The
Live Preview/Edit Sprites toggle is now two side-by-side buttons (a
`QButtonGroup`), not one button whose label swapped between the two
names -- the active one highlights via the existing `QPushButton:checked`
style, no new theme work needed. Two real layout bugs, both in the same
family as the splitter/CollapsibleSection top-alignment fixes from
2026-09-17: the Behavior tab's Position & Hierarchy section had a big gap
under Zoom because it and the per-sprite property form are two separate
`QFormLayout`s stacked in the same section, each carrying its own default
margins that double up when stacked (fixed by zeroing both); and the
Sprites tab's Expressions section centered its toggle buttons vertically
once expanded, because its own sub-layout had nothing to absorb extra
space (fixed with a trailing stretch, scoped to just that section, not
`CollapsibleSection` itself -- see 2026-09-17's own comment on why a
blanket alignment fix there breaks other sections' ability to grow into
real space). The Application tab's Display/Canvas split, down to two
single-row sections after Zoom moved out 2026-09-17, is now one "Display
& Canvas" section. Costume swap rows' Hide/Show labels were reversed
from what they actually do (the "Hide" combo picks the sprite this
costume *shows*, and vice versa) -- swapped so the label names the
action, not the picked sprite's default state. Costume and Expression
hotkeys previously worked in different windows only (costume: Render
Window focus; expression: Control Panel focus), so testing both in the
same session always made one look broken -- both now also fire from the
Control Panel, guarded against a focused text/combo/key-capture field so
typing (including remapping a costume key itself) is never hijacked;
Render Window behavior for costume keys is unchanged. The costume/
expression editors' only removal gesture -- clearing a combo back to
"—" -- wasn't discoverable ("doesn't work lol"); replaced with an
explicit "−" button per row, and clearing a combo now just leaves the
row incomplete instead of deleting it. Zoom moved from `WindowConfig`
(app-wide, `settings.json`) to `AvatarRig.zoom` (per-avatar, saved with
the `.uc` file) -- how big an avatar renders is that avatar's own
property, not the machine's; a real settings.json migration
(`_migrate_window_zoom_to_avatar`, config version 1 -> 2) strips the old
key so an existing settings.json doesn't crash on load, and Undo/Redo's
rig snapshot now covers zoom too (it didn't before the move, since
`_snapshot`/`_restore` only ever touched sprites/costume/expression
data). Net effect for real files in the wild: any avatar saved before
today has no zoom of its own and will render at the default 1.0 the next
time it's opened, even if the old app-wide setting had it at something
else -- worth re-setting once per avatar that relied on it. 425 tests
(up from 413), all touched behavior covered: the two-button toggle, all
three layout fixes' underlying causes, the hotkey guard and its Control-
Panel-side triggering, the explicit remove buttons (plus the now-inert
"clear leaves it incomplete" behavior), and zoom's full rig/persistence/
config-migration/undo round trip.

**2026-09-19, same-day follow-up: the layout-gap fix above was wrong
twice before it was right.** Real screenshots (owner) showed the
Position & Hierarchy/Application gaps *surviving* the margin fix
described above -- the actual cause was Qt spreading a section's
leftover splitter space *between* its stacked form layouts whenever
nothing else in that splitter wanted it, not doubled-up margins.
Fixed properly with a trailing `addStretch(1)` added to every plain-
form section (state/motion/position/animation/envelope/obs/display),
so leftover space always collects below the real content. Verified
with an offscreen screenshot this time, not just reasoning about the
code -- both reported tabs confirmed visually packed correctly. Then a
*third* report ("the gap... disappears when layers is also open")
exposed the real mechanism underneath both previous attempts: every
expanded section requested equal, unlimited splitter space, so
whichever *other* section in the same splitter had something that
actually wanted to grow (Layer List's auto-expanding sprite list;
Costume/Expression Hotkeys' list widgets) ended up silently absorbing
the slack that non-growing sections like State Assignment/Expressions
would otherwise have wrongly claimed. Fixed at the root: `Collapsible
Section` gained a `wants_extra_space` flag (only Layer List and the two
hotkey-list sections set it), and `_resync_tab_splitter_sizes` now caps
every non-growing expanded section to its own real content height via
`setMaximumHeight`, not just a `setSizes()` request Qt was free to
override. That, in turn, resurfaced the *original* 2026-09-17 "nothing
expanded -> centered" bug via a new path -- some sections expanded, but
none of them growable -- so `_update_splitter_top_alignment`'s condition
became "does anything *growable* here that's actually expanded"
instead of "is everything collapsed" (the latter was a special case of
the former all along). Chasing that surfaced one more real Qt quirk,
not a logic bug: a splitter's negotiated geometry could still read
stale immediately after `setAlignment()`/`setSizes()`, confirmed by
reproducing it standalone -- fixed with a deferred, once-more resync
pass via `QTimer.singleShot(0, ...)` in `_on_section_collapsed_changed`,
the standard Qt answer to "just changed layout-affecting state, need it
to actually be reflected." The Expressions section's *own* cap has the
same staleness risk on every add/remove of a toggle button (tagging a
sprite manually-driven, live), fixed the same way. 431 tests (from
425), including one that pins down the exact "disappears when layers is
open" scenario as a regression test, one confirming a growable section
still fills its tab, and one confirming the Expressions section's cap
tracks its content immediately after a live add.

**2026-09-19, same-day follow-up: edit-canvas handles unclickable, drag
left artifacts.** Owner's report: clicking a selected sprite's corner/
rotate handles on the Edit canvas "the guides disappear and nothing
happens", and dragging a sprite left visible trail marks behind it.
Both from the same root cause in `EditableSpriteItem`: `boundingRect()`
only grew upward (to fit the rotate handle, a 2026-09-17 fix) -- but
each corner handle is centered exactly ON the pixmap's own corner (see
`_handle_rects`), so its outer half sticks out past the pixmap's edge
on the *other* three sides too, which the old boundingRect() never
accounted for. Qt clips both painting and hit-testing to boundingRect():
clipped painting on move left stale handle fragments behind (Qt didn't
know to invalidate/erase a region it didn't think the item occupied --
the drag artifacts), and clipped hit-testing meant a click landing in
that outer half -- the natural place to click a handle -- fell through
to the empty canvas instead, deselecting the sprite (the "nothing
happens"). Fixed by extending boundingRect() on all four sides, not
just up. A second, related issue: `QGraphicsPixmapItem.shape()` traces
actual opaque pixels by default (so a click on a transparent part of a
sprite falls through to whatever's underneath) -- a handle sitting past
the pixmap's edge almost always lands on a transparent pixel there,
which would still make it unclickable via the inherited shape() even
with a big-enough boundingRect(), since Qt's hit-testing consults
shape(), not just boundingRect(). Fixed by overriding shape() to carve
out explicit rectangles for the handle areas only when selected,
leaving the rest of the sprite's normal click-through-transparency
behavior untouched. 433 tests (431 -> 433); both new ones confirmed to
actually fail against the pre-fix code before being confirmed to pass
against the fix, not just written to match whatever the fix happened
to produce.

**2026-09-19, same-day follow-up: OBS mute awareness failed with a raw
SDK error when enabled before an Input name was set.** Owner's terminal
log: `[obs] OBS input '' not found (Request GetInputMute returned code
300 ...)`. The checkbox's own tooltip already said "otherwise this
would just retry a connection with nothing configured yet" -- true
intent, never actually enforced: `ObsLinkManager._start()` started a
real `ObsMuteWatcher` (and so a real obs-websocket connection attempt)
the moment the checkbox was checked, regardless of whether Input name
had ever been filled in, producing exactly this confusing raw error
instead of the routine, silent "not configured yet" state every other
gap in this setup (OBS not running, wrong host/port) already gets.
Fixed by having `_start()` decline outright when `input_name.strip()`
is empty -- same silent no-op as those other routine states, not an
error. The status label (Audio tab) now also says why when this is the
case ("Not connected -- enter an Input name above"), refreshed
immediately on toggling the checkbox or editing any of the four
connection fields, not just from the background watcher's own
connection/mute callbacks. 440 tests (433 -> 440): four pre-existing
`test_obs_link_manager.py` tests needed a real Input name in their
`Config()` fixture now that starting with a blank one is correctly
inert, plus new tests for the guard itself (blank, whitespace-only,
filling it in after the fact starts the watcher) and the status label's
three states.

**2026-09-19, same-day follow-up: edit-canvas scale/rotate drag diverged
into wild jumps from tiny handle movements.** Owner's report: "starts
jumping sizes randomly very fast while just moving the handles a
little." Root cause, confirmed by simulating a real multi-step drag
through actual `QGraphicsSceneMouseEvent`s rather than calling
`_drag_handle` directly with hand-picked points (the latter can't
reproduce this at all -- see below): `_drag_handle` read `event.pos()`,
which Qt maps through the item's *current* `transform()` -- i.e.
already divided by the very scale being computed that frame. Each call
then computed `(true_scale / previous_scale)` instead of `true_scale`
outright, and since the sprite's scale is set from that wrong result
every time, the error compounded (and for scale specifically,
oscillated: a real repro climbed 2.0 -> 1.01 -> 2.02 -> 1.02 -> 2.04 ->
1.03 across six 1px nudges instead of increasing smoothly). Rotation
had the same bug but a gentler symptom -- tracked the mouse at roughly
*half* speed instead of oscillating, since a pure rotation doesn't
compound the way a scale division does. Fixed by switching to
`event.scenePos()` and manually removing only this item's own rotation
(never its scale) via `parentItem().mapFromScene(...) - self.pos()`,
anchoring every frame's computation to the sprite's fixed original
geometry regardless of whatever transform was already in effect --
correctly parent-aware too (verified against a rotated+scaled parent
with a child sprite, tracking smoothly). The two direct-call handle
tests already in the suite (a single `_drag_handle(QPointF(...))` call)
passed against the *broken* code too, which is exactly why this
survived past them -- the bug only exists in what a real, live,
multi-step Qt event sequence feeds in, not in the function's own
formula taken in isolation. New regression tests use real
`QGraphicsSceneMouseEvent`s dispatched through `mouseMoveEvent` for
that reason, each independently confirmed to reproduce the bug against
the pre-fix code first.

**Same day, also added: Reset Size / Reset Rotation buttons** next to
Edit Sprites (owner's request) -- visible only in Edit mode, disabled
with the rest of the per-sprite property form when nothing's selected,
routed through the existing Scale X/Y and Rotation spinboxes (not
straight into the sprite fields) so undo, dirty-tracking, lock-
proportions, and the live canvas update all come for free from the
handlers those spinboxes already have. 449 tests (440 -> 449).

**Same day, also added: Edit canvas scroll-to-zoom** (owner's request,
explicitly scoped as "the other zoom situation" -- distinct from
`AvatarRig.zoom`, the authored whole-avatar Render Window scale added
earlier the same day -- and "keep it simple for now"). Scrolling over
`GridCanvasView` (Edit Sprites only, never Live Preview's `PreviewView`,
which must keep showing the avatar at its real Render Window size)
scales the view via `QGraphicsView.scale()`, anchored under the cursor
(`AnchorUnderMouse`) so it zooms toward whatever you're pointing at, not
the viewport center. Clamped to 0.1x-10x of whatever `refit_to_content`
last fit, and reset back to that baseline on the next refit (a resize,
reload, or re-entering Edit mode) -- purely a transient "look closer"
aid, never touches any authored field or anything persisted, matching
the "simple" scope asked for. 455 tests (449 -> 455).

**Same day, immediate follow-up: the 0.1x-10x range was backwards for
the actual goal.** Owner's report: "we can zoom out really really far
but not in very far at all... need it vice versa if anything... need to
zoom in for precise item positioning." Root cause was really just poor
default numbers, not a logic bug: `refit_to_content`'s fit-to-content
baseline is already a small absolute scale for a typical avatar (e.g.
~0.31x for unicorn-demo at a real window size, since the avatar's own
bounding box is much bigger than the viewport) -- 0.1x of that shrank an
already-small view to a sliver, while 10x of it only reached ~3.1x
absolute, nowhere near enough magnification to place small elements
precisely. Range changed to 0.5x-50x: zooming out is now capped much
closer to the already-shows-everything baseline (rarely useful to go
further), and zooming in has far more headroom (~13.7x absolute at
unicorn-demo's real baseline, confirmed with real screenshots at both
new extremes -- max zoom-out keeps the avatar clearly visible with room
around it, max zoom-in gets close enough to see individual flat-color
regions of the art). Existing clamp tests already asserted the bound
constants symbolically (`cpw_module._MIN_VIEWPORT_ZOOM`/
`_MAX_VIEWPORT_ZOOM`), so they needed no changes for this.

See each dated entry below for the actual work and the bugs found doing
it — this paragraph is a current snapshot, not a chronological record.

`rig.py`/`persistence.py` load and save both `.save` (legacy) and `.uc`
(this app's own extension, with automatic version-upgrade-and-backup)
formats; `render.py` is a working PySide6 Render Window compositing the
rig with sway/drag/rotation/stretch/bounce, sprite-sheet animation, and
now two independent variant-alternation timers (mouths and eyes can each
have more than one sprite per state and take turns showing); `audio.py`
is a proper RMS envelope follower (attack/hold/release, noise gate,
per-band hysteresis) driving 3-level mouth shapes; `config.py`/
`settings_window.py` replace hand-edited config with a live, scrollable
Settings window (Display, Audio, Motion, and Hotkeys groups) that saves
atomically on every change; `editor_window.py` is a working character
editor (sprite list with per-layer eye-icon visibility toggles, origin
guides, click/drag select and move on a static WYSIWYG canvas, add/
replace/duplicate/delete/move-up/move-down, link/unlink via a
cycle-safe parent dropdown, undo/redo, save/load, an in-app Help
window) wired live against the same shared rig the Render Window reads
from. Costume-switch hotkeys are remappable per-slot from Settings,
focus-only by deliberate decision, not because global hotkeys haven't
been investigated yet — the owner rejected them outright (collision
risk with whatever else on the system claims the same key). `theme.py`
ports the Unicorn Tears/Viz design system's colors/type/spacing tokens
into a QSS stylesheet plus bundled brand fonts, applied to every control
panel; the Render Window is deliberately, verifiably excluded from all
of it. `render.py`/`editor_window.py`/`theme.py` all have real regression
tests (Qt run headless via `QT_QPA_PLATFORM=offscreen`), including
several live bugs these tests (or a dedicated review pass) caught and
fixed — a bounce-retrigger physics bug, a scene-rebuild crash, Move Up/
Move Down silently no-opping on every real rig, and an Escape-hijack
hotkey-binding bug found in review. The mouth art gap flagged 2026-09-15
("a 4th, alternating mild-mouth pair") has since been delivered and
wired up, along with eye-blink art — both now use the variant mechanism.

Also fixed 2026-09-15: the render loop advanced its whole simulation
(sway/drag/rotation/stretch/blink/bounce) once per *paint callback*, not
per fixed unit of wall-clock time. On this machine the iGPU is shared
with OBS's encoder, so paint can and does drop under encode load — and
because motion.py's functions each advance by one step per call, a paint
stall didn't just look choppy, it slowed down and distorted blink timing
and sway character in real time. `render.py` now runs a fixed 60Hz
simulation on a wall-clock accumulator, fully decoupled from how often
painting actually happens (paint can fall behind and catch up in a burst,
or run ahead and simply repaint unchanged state — either way the
simulation's sense of time stays correct), plus `Qt.PreciseTimer` on the
paint-driving QTimer to reduce the jitter the accumulator has to absorb
in the first place. Explicitly **not chasing legacy-parity timing** for
this or anything else going forward — the owner dropped that as a target
2026-09-15 ("our goal is really *better* and *unique*"); this fix would
have been correct either way, but it's no longer framed as preserving a
match to PNGTuber-Plus's behavior, just as the right way to run a
simulation.

Also fixed 2026-09-15, from a review of the transform hierarchy (now
documented as the authoritative contract at the top of `rig.py` — written
down *before* fixing the code, per that review, not after): three real
bugs, all currently invisible because avatar-01 has no parent/child
sprites yet, but exactly the kind of thing that breaks the moment the
owner rigs hair/accessories onto a parent:
  - **Window centering was actually broken, not just resize-fragile.**
    `QGraphicsView` had no explicit `sceneRect`, so Qt fell back to an
    auto-sized rect from `itemsBoundingRect()` that didn't match the
    widget's pixel size at all — confirmed empirically (the view's true
    visual center was nowhere near where `root_item` was positioned, even
    before any resize). Fixed by pinning `sceneRect` to the widget's
    actual size in `__init__` and a new `resizeEvent` override.
  - **A child's drag lag ignored its parent's motion entirely.** It
    chased a target built only from the child's own authored position +
    sway, so a laggy child (e.g. hair with `drag_speed > 0`) would track
    a bouncing/swaying parent perfectly rigidly instead of trailing
    behind it — the entire visual point of giving it a drag speed.
    `render.py` now composes each sprite's target from its own local
    motion plus its parent's already-computed drift (parents are always
    processed before children — see `_simulate_step`'s comment on why
    that ordering is guaranteed), then converts back to parent-local
    coordinates for Qt in `_apply_to_scene`.
  - **Negative `z_index` didn't draw behind the parent.** Qt's default is
    that a child always paints on top of its own parent regardless of
    z-value sign; got `z_index < 0` reliably behind (e.g. for a
    hair-back/hair-front split) requires `ItemStacksBehindParent`, which
    render.py and editor_window.py now set. `clipped` (mask children to
    the parent's actual alpha shape) was declared on `Sprite` but never
    read by the renderer at all — now wired via
    `ItemClipsChildrenToShape` + `ShapeMode.MaskShape`.
  - **`frames`/`anim_speed` (sprite-sheet animation) — implemented same
    day, right after being flagged as a gap.** `spritesheet.py` slices a
    multi-frame image into equal-width frames; `motion.animation_frame_step`
    (a clean frames-per-second design, not a port of legacy's confusing
    `max(animSpeed, max_fps*6.0)` formula) advances the current frame on
    the same fixed-timestep loop as everything else. The editor always
    shows frame 0 (static preview) and now exposes both fields — `frames`
    triggers a rebuild since it changes the item's pixmap dimensions,
    `anim_speed` is a normal live field. Every sprite in avatar-01 has
    frames=1, so none of this has run against real content yet, but it's
    no longer a hole.
All of the above have regression tests (headless Qt), not just the manual
verification used to confirm them, including pixel-level checks (a
generated filmstrip with a different solid color per frame) that the
right frame is actually showing.

Rewrote `audio.py`'s device handling 2026-09-16 to actually copy
unicorn-viz's `audio/capture.py` (same owner, same machine, already
debugged in production there), not just its general approach:
  - This machine exposes three PortAudio host APIs (ALSA, OSS, JACK --
    the last is PipeWire's JACK-compat shim, where the real devices
    live). Confirmed empirically: the actual USB mic reports 0 input
    channels under raw ALSA and 4 under the JACK/PipeWire shim for the
    *same physical device*, and ALSA's own "default" pseudo-device
    reports a placeholder 128 channels. Worse than wrong metadata:
    unicorn-viz found PortAudio's ALSA backend aborts at the C level if
    a device disappears mid-stream -- not a catchable Python exception.
    `usable_input_devices()`/`resolve_input_device()` now exclude the
    raw ALSA hostapi and pseudo/self-referential capture entries
    (speech-dispatcher, dummy, "[python...]" loopbacks), ported from
    unicorn-viz's `_is_alsa`/`_is_pseudo_input`.
  - Capture is now a blocking-read daemon thread (no `callback=`), not
    callback mode -- also ported, including the specific reason it's
    designed this way: `stream.abort()` doesn't reliably unblock an
    in-flight blocking `stream.read()` on the hostapis here, so the
    reader polls `read_available` before ever calling `read()`, bounding
    how long it can go without checking the stop flag. It also takes its
    own copy of each block before any numpy math, for the same reason
    unicorn-viz does: touching a PortAudio buffer that's mid-teardown is
    a use-after-free that can surface later as an unrelated-looking heap
    corruption.
  - The legacy 180s periodic mic reset does not have a PortAudio
    equivalent to root-cause -- it was a Godot AudioServer-specific
    artifact, not applicable here. The real failure this needs to
    survive is a USB mic unplugging mid-stream, which surfaces as a
    `stream.read()` exception, not a clock tick, so reconnect is
    error-triggered (retry with backoff after a read failure), not a
    timer.
  - **Two real, reproducible bugs found and fixed while wiring this up
    against the actual mic**, neither caught by the fake-based tests
    alone (confirmed live, on real hardware, before landing):
    1. Hardcoding `samplerate=44100` raised "Invalid sample rate" --
       the JACK/PipeWire hostapi runs at its own fixed rate (48000 here)
       and doesn't resample. Fixed by querying the device's own
       `default_samplerate`, same as unicorn-viz's `_open_stream`.
    2. Requesting `channels=1` directly from a device whose native
       channel count is higher (4, here) **reproducibly corrupted the
       process heap on the very first `stream.read()`** -- a real
       segfault, isolated with a minimal standalone repro to exactly
       that one parameter. Fixed by requesting `min(2,
       max_input_channels)` and downmixing to mono in software, which is
       what unicorn-viz already does and is exactly why it never hit
       this: it never asks PortAudio to downmix either.
  - `frame_seconds` in `__main__.py` now reads `mic.blocksize /
    mic.samplerate` (the actually-negotiated rate) instead of a
    hardcoded `1024 / 44100`, so the envelope timing stays correct
    regardless of which rate a given device/hostapi combination forces.

New files use `.uc` instead of `.save` (branding), added 2026-09-16 along
with automatic format-version upgrading:
  - `persistence.py` stamps every save with `__format_version__`
    (`CURRENT_FORMAT_VERSION = 1`); any file without that key -- every
    real file that existed before today, including the owner's own
    avatar-01 -- reads as version 0. `needs_migration(path)` checks the
    stamp without loading the whole avatar.
  - `avatar_io.py` (new, Qt-facing on purpose -- persistence.py stays
    Qt-free) is `load_avatar_with_upgrade()`: loads the avatar (already
    tolerant of missing fields via defaults), and if it was behind the
    current version, immediately re-saves it (stamping it current, and
    creating the usual one-`.bak` safety net) and shows the owner a
    message box explaining what happened and that the backup is
    temporary -- gone the next time that avatar is saved again, not a
    permanent archive. Both the app's startup load and the Editor's
    "Load Avatar…" button go through this now, not the bare loader.
  - Editor's Save dialog defaults to `*.uc` and auto-appends the
    extension if the owner types a bare filename (Qt's own auto-append
    isn't reliable enough to trust here); Load accepts both `*.uc` and
    `*.save`, since every real file that exists right now is `.save`.
  - Verified end-to-end against a throwaway copy of the real avatar-01
    file, not the file itself: load with no version key → warned once →
    file gets the stamp + a `.bak` of the pre-migration version → a
    second load doesn't re-warn. The actual `unicorn-tears-avatar-*.save`
    file was deliberately left untouched by this verification -- it'll
    upgrade itself, with the warning, the first time the owner actually
    opens it in the app.
  - Caught mid-task: the owner had been actively editing in a
    still-running earlier instance of this app (left open from a prior
    turn) the whole time this work was happening, saving their in-progress
    edits (two new mouth frames, a layer reorder) to their own
    self-typed `*.uc` filename via the *old* Save dialog. Both saves
    landed safely, backup and all, entirely independent of this
    migration work -- confirms the earlier atomic-write-plus-backup fix
    was protecting real, concurrent, unplanned-for usage correctly, not
    just the scenarios it was tested against.

Wayland/portal specifics for the Render Window, addressed 2026-09-16 per
owner request -- this is about what OBS needs from the window, not the
avatar itself:
  - **Stable app identity, so OBS's portal restore token keeps matching
    across launches.** Wayland has no `WM_CLASS` the way X11 does; the
    thing xdg-desktop-portal's ScreenCast restore-token matching actually
    keys on is the Wayland `app_id`, which Qt derives from
    `desktopFileName()` if set, or otherwise falls back to something
    derived from `argv[0]` (observed here: the literal string `"-c"` when
    launched via `python -c`, which is not stable across launch methods).
    `__main__.py` now sets `app.setApplicationName(WINDOW_TITLE)` and
    `app.setDesktopFileName(APP_ID)` once, both constants (`WINDOW_TITLE
    = "Unicorn Cloak"`, `APP_ID = "unicorn-cloak"`) living in `render.py`
    so the window title and the app id can never drift apart by accident.
    Verified only that Qt reports these values back correctly
    (`applicationName() == "Unicorn Cloak"`, `desktopFileName() ==
    "unicorn-cloak"`) via a standalone script, and that a real app launch
    still runs clean with them set.
    **Cutover check run 2026-09-16: it doesn't work.** The owner closed
    and relaunched both the app and OBS -- the portal picker re-prompts
    every time either way, same as it did before this fix, and (per the
    owner) the same as it does "for every other window most of the
    time" in OBS on this machine. So this isn't something a more
    stable `app_id` can fix from the app side: this Fedora 44/GNOME
    session runs `xdg-desktop-portal-gnome`, and GNOME's portal
    implementation has a long-standing reputation for not reliably
    honoring ScreenCast restore tokens for window/screen sources
    regardless of what the requesting app does -- consistent with what
    the owner is seeing across every app, not specific to this one.
    Leaving the `app_id`/`applicationName` calls in place regardless
    (still correct Wayland practice, genuinely harmless, and would still
    matter on a portal backend that *does* honor restore tokens), but
    the claim that it achieves "no re-pick on relaunch" here is
    retracted -- it doesn't, and there's no further app-side fix for it.
  - **No programmatic window positioning on Wayland.** The Wayland
    toplevel protocols give a client no way to set its own on-screen
    position -- not a Qt limitation, a protocol one -- so a frameless,
    borderless window (which this one is, for the transparent-background
    capture) also has no titlebar for the compositor's own move gesture
    to grab. `WindowConfig` deliberately has no `x`/`y` fields and only
    persists `width`/`height`; adding a position field would silently
    save a value the app can never actually restore. The fallback for
    actually moving the window is the compositor's own Super+drag (GNOME
    Mutter supports dragging a window from anywhere, not just its
    titlebar, via Super+drag, which doesn't need the app's cooperation at
    all). **Verified 2026-09-16 on the owner's actual 4-monitor
    GNOME/Wayland session: works.** No app-side keyboard-nudge fallback
    needed -- the compositor gesture alone is sufficient, so
    `WindowConfig` correctly has no `x`/`y` fields to persist.
  - **Minimized-window capture: verified 2026-09-16, the prediction was
    wrong.** Expected a minimized Render Window to stop producing frames
    under Mutter's PipeWire screencast implementation (a minimized
    window commonly isn't composited at all, and PipeWire capture
    generally rides on the compositor's existing composite output) --
    the owner confirmed it does *not* blank or freeze; OBS keeps showing
    the avatar normally even while the Render Window is minimized. Good
    news, not something this app did anything to earn -- purely Mutter's
    behavior on this machine/version. No "don't minimize" caveat needed.
  - **Audio-thread/Qt separation made explicit, not just informally true.**
    `Microphone.on_volume`/`on_error` (audio.py) already ran on the
    background capture thread, not the Qt thread, but `on_error` used to
    go straight to a bare `print()` with no bridge at all -- safe today
    only by accident, because printing happens to be thread-safe. Added
    `_AudioBridge` (`__main__.py`), a `QObject` with `volume_measured` and
    `error_occurred` signals; both audio-thread callbacks now only ever
    call `bridge.<signal>.emit(...)`, and both are connected with an
    explicit `Qt.ConnectionType.QueuedConnection` (`AutoConnection` can't
    detect the needed thread hop here, since the receivers are plain
    closures, not bound methods on a QObject -- Qt has no thread-affinity
    to inspect on those). This means no future change to what `on_error`
    does (e.g. showing a QMessageBox instead of printing) can accidentally
    reintroduce a cross-thread Qt call.
  - Two existing tests broke as a *direct, expected consequence* of real
    app usage during this same work, not a bug: the real avatar-01
    `.save` file legitimately got its `__format_version__` stamp from
    being genuinely opened by the app earlier this session, so
    `test_avatar_01_save_preserves_every_raw_key` and
    `test_needs_migration_is_readable_on_the_real_avatar_01_file` (renamed
    from a name that asserted a specific True/False) were fixed to treat
    that stamp as mutable external state rather than assuming the real
    file stays permanently unmigrated forever. See `test_persistence.py`.
  - **Cutover check run 2026-09-16 -- result: the portal still re-prompts
    on every relaunch.** See the updated "Stable app identity" bullet
    above for the full result and why it isn't fixable from this app's
    side (a GNOME/`xdg-desktop-portal-gnome` limitation, not specific to
    this app or this fix).

New mouth-alternation feature and real-avatar wiring, 2026-09-16, per the
owner's in-progress avatar-01 art drop (two new mouth shapes, `mouth-
open-mild-02.png` and `mouth-open-wide-02.png`, added to `for-assembly/`
alongside the existing set) -- the owner asked for the rig to be wired up
and the mouth/eye/action *system* enhanced to match what the art actually
supports, then to fine-tune it themselves from there:
  - **`rig.Sprite.variant` (new field) + `motion.sprite_alpha`'s
    `talk_variant`/`active_talk_variant`/`talk_variant_count` params +
    render.py's swap timer**: when more than one sprite shares the same
    nonzero `talk_state`, they now take turns showing at a configurable
    rate (`MotionConfig.mouth_variant_hz`, exposed in Settings as "Mouth
    alternate rate") instead of all trying to render at once. This is the
    "2 mild mouths that alternate during continuous speech" feature
    requested 2026-09-15 and deliberately deferred until real art existed
    to drive it -- it does now, for both the mild and wide bands. A
    `talk_state` with only one sprite in it (every rig before today,
    and still the common case) is completely unaffected -- the variant
    check is a no-op unless `talk_variant_count > 1`. New `Sprite.variant`
    field is exposed in the Editor's property panel (int, 0-9) so the
    owner can regroup/reassign which sprites alternate together without
    editing the file by hand. Persisted as a new `talkVariant` key
    (`persistence.py`) with no legacy counterpart -- defaults to 0
    ("no alternation") on any file that predates this.
  - **Real avatar-01 `.uc` file wired up** (not just the code): the
    owner's in-progress file had all 10 `for-assembly/` sprites added via
    the Editor's "Add…" button but left at every field's default (every
    `talk_state` was 0, meaning none of the 4 new/existing open-mouth
    shapes were gated to a talk band at all). Loaded and re-saved through
    `persistence.load_avatar`/`save_avatar` directly (the app's own code
    path, atomic write and backup included -- not hand-edited JSON) to:
    talk-gate the 5 mouths (closed=0, mild pair=1, wide pair=2, matching
    the exact convention already validated in the real, older 8-sprite
    `avatar-01.save`), assign variant 0/1 within each alternating pair,
    and reorder the sprite list to that same validated back-to-front
    order (hoody, head, shades, bling, hair, then the 5 mouths -- this
    format uses list order to break z-index ties, and every sprite here
    is z=0). Confirmed no `unicorn_cloak` process was running first (the
    owner had one open earlier this session while concurrently editing
    this exact file -- see the migration entry above -- so this checked
    fresh before touching it again). A `body-01.png` also existed in
    `for-assembly/` and was tried in an earlier pass of this edit, but
    the owner clarified it isn't wanted in this rig -- removed again via
    the same load/remove_sprite/save path, not left in place hidden.
  - **Asset bug found and flagged, not silently worked around**:
    `clothes-hoody-01.png` has no real transparency -- checked its alpha
    channel directly (not just eyeballing the rendered preview), and all
    four corners plus a full-image histogram show 100% of pixels at
    alpha=255. Every other sprite in the set is correctly mostly-
    transparent. Showing this layer as-is would paint the entire
    1672x941 canvas solid black, hiding every other layer and defeating
    the transparent-window OBS capture this whole app exists for. Left
    fully wired into the rig (position, z-order) but with
    `costume_layers` set to all-`False` (hidden in every costume slot)
    until it's re-exported with a real transparent background --
    flip it back on per-slot from the Editor once that's done.
  - **No eye states wired**: `for-assembly/` has no eye/blink art at all
    (only `shades-aviator-01.png`, which covers the eyes entirely) --
    3 candidate eye states (`eyes-closed-01`, `eyes-open-wide-01`,
    `eyes-squint-01`) exist only in the raw `src/` staging folder, not
    promoted to `for-assembly/`, and would be invisible behind the
    shades regardless. Not wired, on purpose -- there's nothing to wire
    yet, and inventing blink art or a squint band the owner hasn't asked
    for would be exactly the kind of unrequested feature-building this
    project is trying to avoid. `blink_state`'s existing 3-band mechanism
    already supports a squint band the moment real art exists for it.
  - **No "action" art exists yet** anywhere under `avatar-01/` (no wave/
    dance/etc. layers) -- the existing `toggle` field (per-sprite,
    hotkey-bindable, still unwired to any actual hotkey) and the 10-slot
    costume system are already in place for whenever that art shows up;
    nothing new was invented here without content to back it.
  - **Full in-app Help window** (`help_window.py`, new): a scrollable
    reference covering the three-window model, every hotkey, the full
    sprite-field glossary (including the new Variant field), the Editor
    workflow, the `.uc` file format and auto-upgrade behavior, and what
    each Settings group does. Opened from a new "Help" button next to
    Undo/Redo in the Editor; a single re-raised instance, not a new
    window per click.
  - Test coverage: `motion.py`'s variant gating (no-op defaults, gating
    within a band, band-0 immunity, edit-mode ghosting), an end-to-end
    `render.py` test that two mouths sharing a band actually alternate
    (and don't when the band's inactive, and don't when there's only one
    sprite in the band), `persistence.py` load/save/default round-trips
    for the new `variant` key, and Editor coverage for the Help
    button (singleton, not recreated per click) and the Variant property
    field.

Eyes hooked up, 2026-09-16, right after the above -- the owner fixed the
hoody transparency bug and dropped 3 eye sprites into `for-assembly/`
(`eyes-open-wide-01.png`, `eyes-squint-01.png`, and confusingly-named
`eyes-open-closed-01.png`, which actually depicts fully-shut eyes --
checked visually, not just the filename) in the same session:
  - **The variant mechanism from the mouth work above is now axis-
    generic, not talk-only**: `motion.sprite_alpha` gained
    `blink_variant`/`active_blink_variant`/`blink_variant_count`,
    mirroring the talk-axis params exactly, and render.py now runs two
    independent swap timers (`_talk_variant_*` and `_blink_variant_*`) off
    two independent config rates (`MotionConfig.mouth_variant_hz`,
    already existed, and new `eye_variant_hz`). `rig.Sprite.variant`
    itself didn't need a second field -- a given sprite is only ever
    gated by one nonzero axis in practice (a mouth has talk_state set and
    blink_state 0, an eye has the reverse), so the same field means
    "alternation slot within whichever axis actually gates this sprite."
    `eye_variant_hz` defaults low (0.15, roughly once every ~7s) on
    purpose -- unlike the mouth's flutter, an eye swap is meant to read
    as an occasional expression change (wide-open vs. squint), not a
    twitch. Renamed the persisted key from `talkVariant` to axis-neutral
    `variant` while it was still brand new (one turn old, one real file)
    rather than let a misleading name settle in -- `load_avatar` falls
    back to the old name so that one file doesn't lose the field.
  - **Real avatar-01 wiring**: `clothes-hoody-01.png`'s *embedded* bytes
    in the `.uc` file were still the old broken export -- this format
    embeds a copy of the image at add/replace time, it doesn't re-read
    the file path live, so the owner fixing the file on disk didn't
    automatically fix the already-saved sprite. Refreshed it (same as
    the Editor's Replace button would) and restored its costume-layers
    to all-visible now that it's actually transparent (confirmed: alpha
    histogram no longer 100% opaque). Added the 3 eye sprites: the two
    "open" shapes share `blink_state=1` with variants 0/1 so they
    alternate; the closed shape is `blink_state=2` (shown only mid-blink,
    the existing binary blink driver's other band) with only one sprite,
    so it just always shows during a blink, no alternation involved.
  - **Stacking order judgment call**: the eyes are placed *after* (in
    front of) `shades-aviator-01.png`, not in native face order behind
    it. Looked at the actual shades art: the aviator lenses are fully
    opaque and mirrored (a reflective galaxy pattern), not see-through --
    drawn in the head's native stacking position, an eye layer would sit
    permanently behind the lenses and never be visible, making the whole
    feature a no-op. Drawing eyes in front of the glasses isn't
    physically accurate but is a common stylized-rig cheat and is what
    actually makes blinking/expression visible on screen, which is
    presumably the entire point of the owner adding this art.
  - Test coverage mirrors the mouth-variant tests exactly, plus one
    checking the two axes' swap timers don't interfere with each other
    when both are alternating in the same frame.

Per-layer visibility toggle + real-avatar glasses/eyes swap, 2026-09-16,
immediately after the above -- the owner confirmed they'll only ever use
one of glasses or eyes at a time ("unless I make some pimp new glasses
you can see through"), which needs a plain manual show/hide switch, not
another talk/blink/costume gate:
  - **`rig.Sprite.hidden` (new field)**: an always-in-effect visibility
    override, independent of costume/talk/blink gating and unrelated to
    the existing `toggle` field (a hotkey-bound *name*, not a bool).
    `motion.sprite_alpha` checks it first, before any state gating --
    hidden wins regardless of what talk/blink/variant would otherwise
    show, ghosting to 0.2 in edit_mode same as every other gate.
    Persisted as a new `hidden` key, no legacy counterpart, defaults to
    False on load (every existing file stays fully visible).
  - **Editor sprite list gained a per-row eye-icon toggle**
    (`editor_window.py`): each row is now a small widget (an eye
    QToolButton + the layer's name as a clickable label) via
    `QListWidget.setItemWidget`, not a plain text item -- Qt has no
    built-in per-row icon-button, and this app has no icon set/font
    dependency yet (that's a v2 style-pass item), so `_eye_icon()` draws
    a minimal open/closed eye with QPainter rather than pulling in an
    icon library for one control. Clicking the eye toggles
    `sprite.hidden` immediately (undoable, like every other structural
    edit) and updates both the Editor canvas and the Render Window --
    the latter needs no rebuild/sync call, since it already reads
    `sprite.hidden` live every frame exactly like talk_state/blink_state.
    Clicking the name label still selects the sprite for the property
    panel, same as clicking used to before the row had two widgets in it
    -- a small `_LayerNameLabel` override was needed since
    `setItemWidget` replaces the list's own click-to-select handling for
    that row's whole rect.
  - **Real avatar-01 wiring**: `shades-aviator-01.png` set to
    `hidden=True` -- the eyes wired up moments earlier are the active
    choice for now; the shades stay fully in the rig (position,
    z-order, all costume slots) for whenever the owner wants to swap
    back or builds see-through lenses, just one click away in the
    Editor rather than re-adding the layer from scratch.

Remappable costume hotkeys + Editor origin guides, 2026-09-16, closing
out two of Milestone 4/5's open items -- **and dropping the third
(global hotkeys) entirely**, owner's call: "global hotkeys will mess
w/all sorts of stuff, bad idea":
  - **Global/background hotkeys are no longer a planned item, not just
    deferred.** Milestone 4 originally called for background-usable
    hotkeys (the actually-useful case while streaming, since the Render
    Window rarely has focus then); the owner explicitly rejected this --
    a global hotkey would fight with whatever else on the system already
    binds the same key (games, other overlays, DAW shortcuts), and that
    collision risk isn't worth it. `HotkeysConfig`'s docstring documents
    this as a decision, not a gap, so it doesn't get silently
    re-proposed later. Costume hotkeys remain focus-only.
  - **`config.HotkeysConfig` (new) + costume hotkeys are now remappable**:
    `costume_keys` is 10 `QKeySequence`-parseable strings (default
    "1".."9","0", identical to the old hardcoded behavior). Settings
    gained a "Hotkeys — costume switching" group with one
    `QKeySequenceEdit` per slot (capped at a single key, no chords --
    costume switching was never meant to need a modifier). `render.py`'s
    `keyPressEvent` resolves each configured string back to a plain
    `Qt.Key` fresh on every keypress via `_plain_key_from_sequence()`
    (verified empirically: `QKeySequence(text)[0]` returns a
    `QKeyCombination` in this PySide6 version, and `.key()` gives back
    exactly what `QKeyEvent.key()` returns -- checked in a throwaway
    script before committing to this, not assumed from docs), so a
    rebind in Settings takes effect immediately, no rebuild/reconnect,
    same live-config pattern as motion_config. Settings' own window
    needed a `QScrollArea` wrapper once this group pushed it past a
    comfortable fixed height.
  - **Editor canvas gained origin guides**: a dashed crosshair through
    scene (0, 0) -- where a root-level sprite's own Position of (0, 0)
    actually sits, given this view applies no centering offset (unlike
    the Render Window's root_item). Implemented as a `drawForeground()`
    override on a new `_EditorCanvasView` subclass rather than scene
    items, specifically so it survives `_rebuild_scene()`'s
    `scene.clear()` (called on every undo/redo and structural edit) with
    no recreate-it-every-time bookkeeping, and can never be accidentally
    selected or dragged like a real item could. Toggleable via a
    checkbox above the Sprites list, on by default per the owner's
    request ("with a toggle to turn them off").

**Phase 2 pulled forward, 2026-09-16: the v2 design-token port (Phase 2
Milestone 1), owner's call ("let's do the theme now before we carry
on").** Only this one milestone -- the rest of Phase 2 (control-panel
re-skin, live capture preview, performance pass, motion fine-tuning)
stays where it is in the plan, not silently expanded:
  - **New `theme.py`**, applied once in `__main__.py` via `theme.apply(app)`
    right after the `QApplication` is constructed. Hand-copies the actual
    hex/rem/px values out of `tokens/colors.css`, `tokens/typography.css`,
    and `tokens/spacing.css` into Python constants plus a generated QSS
    stylesheet -- the design system itself is React/JSX + CSS custom
    properties with no path into a Qt app, so this is a manual port, not
    an import; if the source tokens ever change, this file needs updating
    by eye, there's no automated sync.
  - **The three brand fonts (Anton, Space Grotesk, JetBrains Mono) aren't
    installed on this machine** -- confirmed with `fc-list` before doing
    anything else. Asked the owner whether to bundle the real files or
    fall back to the tokens' own documented fallback fonts; they chose
    bundling. Downloaded from Google Fonts' static CDN (the same source
    the design system's own `tokens/fonts.css` points at) as real `.ttf`
    files, not `.woff`/`.woff2` -- Google serves different formats based
    on User-Agent, and getting `.ttf` specifically (for guaranteed
    `QFontDatabase.addApplicationFont` compatibility, since Qt's cross-
    platform WOFF support is inconsistent) needed spoofing an old
    browser UA; verified the resulting files are genuinely TrueType
    (`file *.ttf`) and that Qt actually loads and registers all three
    families before treating this as done, not assumed from the
    successful download alone. Live under `assets/fonts/*.ttf`, loaded by
    `theme.load_fonts()`.
  - **The Render Window is deliberately excluded from all of this**, on
    purpose, not by omission: it must stay exactly as transparent/
    frameless as OBS needs it. Two independent guarantees, not just one:
    every QSS selector in `theme.py` targets a concrete widget class or
    an explicit `objectName` (`EditorWindow`, `SettingsWindow`) rather
    than a blanket `QWidget` rule, AND `render.py`'s `RenderWindow` never
    sets `Qt.WA_StyledBackground` (a plain `QWidget` subclass doesn't
    paint a stylesheet background at all without it -- confirmed this is
    the actual mechanism, not assumed). `EditorWindow`/`SettingsWindow`
    each opt in explicitly (`setObjectName` + `WA_StyledBackground`);
    `HelpWindow` needs neither, since `QDialog` already paints its
    stylesheet background natively. Regression-tested directly
    (`test_theme.py`): the generated stylesheet string is asserted to
    never contain a bare `QWidget {` rule, and a real `RenderWindow`
    built after `theme.apply()` is asserted to still have
    `WA_StyledBackground` off and `WA_TranslucentBackground` on.
  - **Knock-on fixes so the rest of the app doesn't look inconsistent
    with the new dark theme**: the Editor's canvas (`QGraphicsScene`)
    was defaulting to Qt's plain white background -- unrelated to
    render.py's transparent-for-OBS one, but jarring next to a dark
    theme everywhere else, so it's now a dark ink tone too. The sprite-
    list eye icon (added earlier this session) was hardcoded black,
    which would nearly vanish against the new dark list background --
    recolored to a light tone when visible, dimmed when hidden. The
    origin-guide crosshair's color was swapped for the exact brand
    magenta token instead of an approximate value chosen before the
    palette was ported.

**Move Up/Move Down were a silent no-op on every real avatar, fixed
2026-09-16** -- reported by the owner ("the move up/down buttons don't
seem to do anything"), confirmed against the real file before touching
any code:
  - **Root cause, two layers deep.** `AvatarRig.move_layer_up/down`
    worked by swapping two siblings' `z_index` values. Every sprite in
    every real avatar this app has ever touched leaves `z_index` at its
    default (0) and relies entirely on list order as the tie-break (see
    `sprites_in_stacking_order`) -- swapping two identical numbers (0
    with 0) is a complete no-op. Every existing test for this used
    hand-built rigs with deliberately distinct z_index values (0/1/2),
    which is exactly why this was never caught: it's not representative
    of any real content.
  - **The first fix attempt was itself wrong, caught before landing.**
    Making a tied swap move the *list position* instead of `z_index`
    seemed sufficient, but tracing it against `sprites_in_stacking_order`
    by hand showed it moved the sprite *backward* on "Move Up" -- the
    old `_siblings_by_z` helper (used only by move_layer_up/down) broke
    ties by ascending list index in the *opposite* direction from
    `sprites_in_stacking_order`'s own tie-break, an inconsistency that
    was invisible only because ties never used to change anything at
    all. Re-derived move_layer_up/down to rank siblings with the exact
    same sort key as `sprites_in_stacking_order` (`_siblings_front_to_back`,
    replacing `_siblings_by_z`), so the two can never disagree again --
    verified by hand-tracing both the tied and the original distinct-z
    cases before writing a single test, then confirming every existing
    distinct-z test still passed unchanged.
  - **The Render Window had a second, independent copy of the same
    class of bug.** `EditorWindow._move_layer`'s "no full rebuild needed"
    optimization only called `setZValue` on the two swapped items --
    correct when z_index actually differs, but Qt breaks equal-z ties by
    item *insertion order*, which a two-item property sync never
    touches. Even with the rig.py fix, the Render Window's visible
    stacking would have stayed silently wrong while the Editor's own
    list looked correct. Fixed by always doing a full
    `_rebuild_scene()`/`render_window.rebuild()` after a move, matching
    the pattern already used by `_on_parent_changed`/`_on_frames_changed`
    -- this is an occasional discrete click, not a per-frame hot path, so
    the correctness win costs nothing worth optimizing around.
  - Verified against the real `.uc` file directly (load, move a layer,
    confirm the order actually changed, discard -- never saved back,
    since reordering wasn't asked for, only fixing the button). New
    regression tests in `test_rig.py`/`test_editor_window.py` use tied-
    z-index rigs specifically, so this class of bug can't hide behind a
    distinct-z test fixture again.
  - **The owner had the app open while this was being fixed.** Nothing
    here touched their avatar file (verification was read-only, no
    save), but the running process still has the old code loaded --
    needs a restart to pick up the fix, same as every other code change
    this session.

**Full self-review pass, 2026-09-16, owner's request** ("go over all your
work and check for bugs/oversights") -- covering everything from the
mouth-variant work onward, not just the move-layer fix above. Five real
issues found and fixed, verified empirically rather than assumed, in
each case:
  - **Escape could be bound to a costume slot, silently disabling the
    only way to quit the Render Window.** `QKeySequenceEdit` does *not*
    treat Escape as "cancel this key capture" the way that's commonly
    assumed -- checked directly (`edit.keyPressEvent` with a synthetic
    Escape event), and it captures Escape like any other key. Since
    `RenderWindow.keyPressEvent` used to check costume keys before
    falling through to the Escape-quit check, a costume slot bound to
    Escape would catch the press first and `return` before quit ever
    ran -- confirmed the actual consequence with a small script
    (`active_costume` changed, `close()` never called) before writing
    the fix, not just reasoning about it. Fixed two ways: `render.py`
    now checks Escape first, unconditionally, before scanning costume
    keys (holds even against a hand-edited config.json); `settings_window.py`
    also rejects binding Escape in the UI itself and reverts the widget,
    so the owner gets immediate feedback instead of a silently-inert
    binding.
  - **An oversized `costume_keys` list could crash the render loop.**
    Unlike the old hardcoded 1-9/0 mapping (exactly 10 keys, always in
    range), the new remappable `costume_keys` has no length check --
    `rig.Sprite.costume_layers` does (`__post_init__` requires exactly
    `NUM_COSTUMES`), which is the actual asymmetry that makes this a
    real gap, not a hypothetical one: an 11th hand-edited entry could
    set `active_costume` past the end of every sprite's fixed-length
    `costume_layers` tuple, `IndexError`-ing the next frame in
    `_apply_to_scene`/`_sprite_currently_eligible` (below). Bounded both
    the read side (`render.py`'s `keyPressEvent`, the fix that actually
    prevents the crash) and the Settings UI (so it doesn't offer to bind
    a "Costume 11" that can never exist) to `[:NUM_COSTUMES]`.
  - **Variant alternation didn't account for costume/hidden visibility.**
    `talk_variant_count`/`blink_variant_count` counted every sprite in
    the matching band regardless of whether it could actually be shown
    right now. No real content exercises this today (every sprite is
    visible in every costume slot), but it's a real latent bug in
    already-shipped logic, not a hypothetical: hide one of two "mild"
    mouths via the eye icon, or give it a costume it's not in, and the
    one remaining eligible sprite would wrongly alternate on/off against
    a "rival" that was never visible, instead of showing continuously
    like a true 1-sprite band. Added `RenderWindow._sprite_currently_eligible`
    (excludes hidden and costume-inactive sprites) and required it in
    both variant-count computations.
  - **The v2 theme's `QDialog` selector was scoped too broadly.** Caught
    before it ever shipped to the owner: a bare `QDialog {...}` rule
    would style *every* `QDialog` in the app, including `QFileDialog`
    (Add/Replace/Save/Load) and `QMessageBox` (avatar_io.py's upgrade
    notice) -- both have plenty of internal widgets (tree views,
    breadcrumbs, native-look chrome) this stylesheet doesn't cover, and
    `QT_QPA_PLATFORMTHEME` isn't set on this machine (checked directly),
    so there was no guarantee Qt would hand these off to an unaffected
    native/portal picker instead of its own styleable widgets. Rescoped
    to `QDialog#HelpWindow` specifically -- the one `QDialog` subclass
    this app actually owns and fully styles -- with a regression test
    asserting the generated stylesheet never contains a bare `QDialog {`
    rule again.
  - **Editor color literals duplicated `theme.py`'s values instead of
    importing them.** The eye icon and origin-guide crosshair colors
    were hardcoded RGB tuples with a comment pointing at the matching
    `theme.py` constant -- exactly the kind of thing that silently drifts
    out of sync the next time the palette changes. Switched to importing
    and constructing `QColor(theme.PINK_WHITE)` etc. directly; nothing
    left to keep in sync by hand.
  - Also fixed stale documentation caught in the same pass, unrelated to
    behavior: `__main__.py`'s module docstring still claimed hotkeys/
    undo-redo/link-unlink were "still ahead", and this file's own top
    Status paragraph (immediately below the title) hadn't been refreshed
    since before most of today's work and still described costume
    hotkeys as fixed-1-9/0 and global hotkeys as an unstarted
    investigation rather than a rejected decision.
  - Two things checked and confirmed correct, not just assumed, while
    doing this pass: `QKeySequenceEdit.setMaximumSequenceLength(1)`
    actually caps capture at one key combination (tested with three
    rapid sequential presses); the Help window's inline `<style>` block
    is genuinely honored by Qt's rich-text engine (checked the actual
    rendered `QTextCharFormat` of the heading, not just that `setHtml`
    didn't raise).
  - 8 new regression tests added for the above (219 total, up from 211).

**Phase 2 Milestones 3 & 4 attempted unsupervised, 2026-09-16** ("knock
out everything u can without me... definitely add the profiling stuff
and when u do the live capture add a toggle") -- one real bug caused and
fixed along the way, one real bug found and fixed in `render.py`, and an
honest, incomplete result on the profiling side:
  - **Killed the owner's own running `unicorn_cloak` process while
    profiling.** Used `pgrep -f` to find "the process I just launched"
    by command-line pattern instead of tracking its exact PID -- picked
    up an unrelated, already-running instance (very likely the owner's
    own session from looking at the mouth-stacking bug) and killed it.
    Caught immediately from the process's own `etimes` (elapsed
    seconds) not matching a process started seconds earlier, disclosed
    immediately, owner said continue. Fixed the actual mistake, not just
    apologized for it: every process check from that point on tracks the
    exact PID from the launch itself (`echo $!` into a file, or the
    PID the script prints via `os.getpid()`), and existence checks use
    an anchored pattern (`^.venv/bin/python -m unicorn_cloak`) so they
    can't self-match this session's own shell wrapper either (a second,
    smaller version of the same class of mistake, caught before it
    caused anything -- an unanchored `pgrep -f "unicorn_cloak"` matches
    the literal text of its own command line).
  - **Real profiling, not assumed.** `ps -T` (per-thread CPU) plus `gdb
    -batch -ex "thread apply all bt"` (native backtraces -- `py-spy`,
    installed temporarily for this and removed after, only sees Python
    frames, not Qt's C++ internals) against a real, freshly-launched,
    exact-PID-tracked process. Found real, substantial CPU use (measured
    150-290%, varying run to run) concentrated in Qt's own global
    thread pool (`QThreadPool`, labeled "Thread (pooled)" by `ps`/`gdb`)
    -- not this app's own Python code, not the audio thread (measured
    separately at ~4%), not numpy/OpenBLAS (a real lead that was
    checked and ruled out: its thread pool exists but sits genuinely
    idle, confirmed via `ps -T` showing 0% on all of it). Isolated
    testing (Render Window alone, +Editor, +Settings, +mic, various
    combinations, some runs 25+ seconds long) never reproduced the
    high number in any *reduced* combination, only the real, full
    `python -m unicorn_cloak` entry point -- and even that varied
    significantly run to run (150%, 270%+ climbing, 290%+ climbing,
    120% settling, across separate genuine launches). **Confound found
    and disclosed rather than ignored:** the owner's own `unicorn-viz`
    (a separately-running, GPU-heavy OpenGL visualizer, confirmed via
    `ps aux` to have been running continuously at ~79-86% CPU the whole
    time) was active throughout every one of these tests and was never
    controlled for -- Wayland/GPU compositor contention between two
    GPU-drawing apps competing for the same iGPU is a real, plausible
    explanation for run-to-run variance that a dedicated investigation
    couldn't rule in or out without either closing unicorn-viz (not this
    session's call to make) or a proper system-level profiler
    (`perf`, not installed, would need a package install this session
    didn't have standing permission to do unsupervised).
  - **One concrete, verified fix landed regardless:** `render.py`'s
    `_apply_to_scene` was calling `item.setTransform()` with a fresh
    `QTransform` on *every* sprite, *every frame*, unconditionally --
    even though every sprite in the real avatar has
    `rotation_drag_strength=0` and `stretch_amount=0` (confirmed by
    checking the actual loaded rig, not assumed), meaning the resulting
    transform was mathematically identity 100% of the time. Now skipped
    entirely once a sprite's rotation/scale settle back to identity
    (`_SpriteRuntime.transform_is_identity`, `resetTransform()` only
    called on the transition back to identity, `setTransform()` only
    called when a sprite is actually rotating/stretching). Verified two
    ways: unit tests (identity sprites never get a non-identity
    transform; an actively rotating sprite still gets a real one; it
    correctly resets once rotation decays back to zero) and a controlled
    isolated-process CPU comparison (Render Window alone, real avatar,
    no other windows/mic -- ~15% settling before the fix, ~9-10%
    settling after, same machine, back to back). A real, measured
    improvement, reported at the scale it was actually measured at, not
    extrapolated to claim the full 150-290% problem is solved -- it
    likely isn't, given the isolated reduction is far smaller than the
    full-app variance observed.
  - **Live capture preview** (`settings_window.py`, new
    `_PreviewView(QGraphicsView)`): a second view onto the *same*
    `QGraphicsScene` the Render Window's own view already uses -- Qt
    keeps every view attached to one scene in sync automatically, so
    this needed no manual redraw loop, no second timer, and no pixel-
    copying; whatever repaints the real window repaints this thumbnail
    too, for free. Refits itself (`fitInView`, aspect-preserving) on its
    own resize and whenever shown. Added a "Show live preview" checkbox
    to Settings' Display group, per the owner's explicit request for a
    toggle -- **off by default**, specifically because this same session
    just found that extra live-repainting views have a real, non-zero
    CPU cost; deliberately not persisted to `config.json` (a per-session
    convenience, not a setting worth remembering across launches, unlike
    every other Display control).
  - 7 new regression tests (226 total, up from 219): the transform
    optimization's three cases, and the preview's default-hidden state,
    shared-scene identity, checkbox toggle, and non-persistence.

**Profiling continued with `perf`, 2026-09-16 -- owner's call: "performance
is critical," approved installing it** (`sudo dnf install -y perf`, a
system package, not pip -- confirmed the distinction when asked). This
time it actually found something conclusive:
  - **The `unicorn-viz` confound from the earlier session resolved
    itself** -- it had been running continuously (~79-86% CPU, a
    separate GPU-heavy OpenGL visualizer, confirmed via `ps aux`) through
    every test in the prior profiling pass; by the time `perf` was
    installed it was no longer running. Re-tested the full app several
    times with it gone: CPU still varies run to run (measured 53-115%,
    settling; earlier same-machine runs with `unicorn-viz` active hit
    150-290%), consistent with GPU/compositor contention between two
    simultaneously-drawing apps having been a real factor, not fully
    ruled in or out, just no longer confusing this round of numbers.
  - **`perf record -g --call-graph dwarf` + `perf report`, a real
    10-second sample of a genuinely fresh, exact-PID-tracked process
    (2672 samples) -- not gdb snapshots this time, an actual statistical
    profile.** Found something the earlier `gdb`-snapshot approach
    completely missed: **the audio thread ("unicorn-cloak-a") accounted
    for ~41% of all sampled CPU cycles**, with named, attributable
    symbols (`reduce_loop`, `FLOAT_add_X86_V3` inside numpy's
    `_multiarray_umath`) -- not Qt's thread pool at all in this run,
    which showed zero samples. gdb's one-shot backtraces earlier had
    been catching threads mid-wait far more often than mid-work, which
    in hindsight was always going to undersample whatever's actually
    hot; a real sampling profiler doesn't have that blind spot.
  - **Two real, measured, verified fixes in `audio.py`**, both run on
    the per-block audio callback (~47 times/second, forever, for the
    life of the app -- exactly the kind of hot, tiny, frequent call
    where numpy's generic-reduction overhead dominates over the actual
    arithmetic):
    1. `rms_volume`: `sqrt(dot(block, block) / n)` instead of
       `sqrt(mean(square(block, dtype=float64)))` -- avoids materializing
       a whole intermediate squared array and the unrequested float64
       upcast (this is a threshold-comparison volume meter, not a
       measurement needing that precision). Measured with `timeit`
       against a realistic 1024-sample block, mathematically identical
       result: **3.40us → 0.80us per call, 4.3x faster.**
    2. `downmix_to_mono` (new, extracted from an inline expression so
       it's independently testable): the 2-channel case now averages the
       two columns directly instead of `.mean(axis=1)` -- channel count
       is always exactly 1 or 2 here (`_run_one_connection` already caps
       it), so the generic N-dimensional reduction path was never
       actually needed. Measured, mathematically equivalent (verified
       against `.mean(axis=1)` directly in a test, not just spot-
       checked): **19.62us → 2.15us per call, 9.1x faster -- the single
       largest contributor found in the whole profile, bigger than
       rms_volume's own cost.**
  - **What wasn't touched, and why:** `_POLL_INTERVAL_S` (10ms poll
    interval bounding how long a read can block before re-checking
    `stop()`) was a candidate but not touched -- no profiler evidence
    specifically implicated the `stream.read_available` poll calls
    themselves (the hot symbols were all numpy, not a PortAudio/ctypes
    entry point), and loosening it trades away documented shutdown-
    responsiveness for a guess, not a measurement. The safety-critical
    `np.array(..., copy=True)` (the fix for the real heap-corruption
    segfault found earlier this project) was also left alone on
    purpose -- removing it would reintroduce a known, worse bug to chase
    a CPU number.
  - **Honest bottom line, not oversold:** the two audio.py fixes are
    real, proven, and directly address the single largest attributable
    cost `perf` actually found. Whether they (plus the earlier transform
    fix) fully explain every high full-app CPU reading across every run
    is not proven -- run-to-run variance is real on this machine even
    with the confound gone, and a live OBS streaming test (this
    milestone's other stated acceptance check) still hasn't happened.
    Not claiming "near-zero idle CPU" is reached; claiming two
    measured, real inefficiencies are gone.
  - 3 new regression tests for `downmix_to_mono` (229 total, up from
    226): mono passthrough, stereo averaging, and numerical equivalence
    against the `.mean(axis=1)` it replaced.

**New feature, 2026-09-16, not on any phase's plan -- owner's own
"special out-of-band issue"**: driving the avatar's mouth from a local
audio/video file instead of the live mic. Real motivating scenario, not
speculative: re-recording a video interview where the avatar stands in
for one participant, whose isolated audio track survived and should
drive the mouth, while a *different*, already-combined recording (both
participants, played back separately through OBS's own Media Source) is
what actually gets captured -- the two files need to play back roughly
together, hence the request for a file-based volume source alongside
the mic. Asked two clarifying questions before writing any code (file
format, playback control) rather than guessing -- answers: broad format
support needed (not just WAV), and a plain Play/Stop button, nothing
fancier.
  - **`audio.FilePlayback`** (new): decodes the chosen file with ffmpeg
    (`-re -i <path> -f f32le -ar 48000 -ac 1 pipe:1`, verified directly
    before writing any wrapper code -- generated a 2-second test tone,
    confirmed the exact planned command decodes it and that `-re` really
    paces the read to ~real playback time, not near-instant) and feeds
    the resulting blocks through the *exact same* `rms_volume` this app
    already uses for the mic, via the *exact same* `on_volume`/
    `on_error` callback contract `Microphone` already has -- new source,
    zero changes needed to the envelope-follower math downstream.
    **Never plays audio out loud, on purpose**: ffmpeg decodes straight
    to a pipe this process reads, never to a system audio sink, since
    the file that should actually be heard/recorded is the combined one,
    played separately -- doubling audio output would conflict with that.
    One-shot, not looping: reaching the end (or a decode failure) calls
    `on_finished()` once and stops, unlike `Microphone`'s automatic
    reconnect-on-failure -- a bad file isn't a transient condition worth
    retrying.
  - **`audio_manager.AudioManager`** (new): owns whichever source is
    currently active and forwards both through the same pair of Qt
    signals, so `__main__.py`'s envelope-follower code and Settings'
    UI don't need to know which one is live. Settings calls into it
    directly (`switch_to_microphone`/`switch_to_file`/`play_file`/
    `stop_file`), the same established pattern already used for
    `render_window.set_background`/`set_zoom` -- not a generic
    settings-changed signal. `__main__.py`'s old inline `_AudioBridge` +
    manual `Microphone` setup is gone, replaced by this.
  - **A real cross-thread bug caught in review before it shipped**: the
    first draft of `AudioManager._handle_file_finished` (triggered by
    `FilePlayback.on_finished`, which fires from *its own* background
    thread per audio.py's documented threading contract) mutated
    `self._file` directly from inside that callback -- a genuine
    cross-thread state mutation of a plain Python attribute, not just a
    Qt-safety issue, that could race a Qt-thread-side `play_file()`/
    `stop_file()` call landing at the same moment. Caught before writing
    a single test for it, not found by one. Fixed by routing
    `on_finished` through a private, `QueuedConnection`-only internal
    signal (`_file_finished_from_bg_thread`) so the actual `self._file =
    None` mutation only ever happens on the Qt thread, mirroring exactly
    why `_AudioBridge`/explicit `QueuedConnection` existed in the first
    place for `volume_measured`/`error_occurred`.
  - **A real UX bug caught by the test suite itself, not eyeballing**:
    picking "File" from the Source dropdown before choosing a specific
    file silently left the microphone running (the first version of
    `switch_to_file` only stopped the mic when a `file_path` was already
    set) -- the avatar would keep mouth-flapping from the mic the whole
    time the owner was in "File" mode but hadn't picked a file yet, the
    opposite of what selecting "File" should mean. Found by
    `test_switching_source_to_file_enables_browse_and_stops_the_microphone`
    failing, not by inspection. Fixed by making `switch_to_file`'s `path`
    argument optional -- calling it with none (from the dropdown change
    handler) still stops the mic immediately; calling it with a path
    (from Browse…) also records the file.
  - **Settings gained a new "Audio source" group**: a Source combo
    (Microphone/File), a file label + Browse… button (enabled only when
    Source is File), and a Play/Stop button (additionally only enabled
    once a file is actually chosen). `config.audio.source`/`file_path`
    persist across restarts even while Source is Microphone, so
    switching back to File doesn't lose the chosen path; whether a file
    is actually *playing* is deliberately not persisted (matches the
    live-preview toggle's precedent from earlier the same day -- a
    per-session action, not a setting).
  - Verified end-to-end against the real app's actual `settings.json`
    (via `load_state()`, not a synthetic Config) and a real ffmpeg-
    encoded MP3 test tone -- 95 volume readings over a 2-second clip, a
    plausible max value, zero errors -- and confirmed the run never
    wrote anything to the real `settings.json` on disk (only an in-
    memory `Config`, `save_state()` was never called), so nothing about
    this verification touched the owner's actual settings.
  - 19 new regression tests across three files (`test_audio.py`,
    the new `test_audio_manager.py`, `test_settings_window.py`) --
    including the two real bugs above, both caught by tests that were
    written to check the feature works, not written after the fact to
    reproduce a bug already found by hand. `_make_test_wav`/
    `needs_ffmpeg` moved into the shared `qt_helpers.py` (was about to
    be duplicated into a second test file) rather than copy-pasted.

**Two more new features, 2026-09-16, owner's request** ("let's do these
two real quick"): OBS mute awareness, and a visual tuning meter. Neither
is on any phase's plan -- both are owner-directed additions, like the
file-audio-source work just above.

**Mute awareness** -- "read the OBS mic mute state over obs-websocket...
force the mouth closed while muted. Otherwise the avatar talks while the
stream hears silence":
  - **`obsws-python` added as a real dependency** (not a diagnostic tool
    like `perf`/`py-spy` from the profiling work) -- a maintained
    obs-websocket v5 client, chosen over hand-rolling the protocol's
    SHA256 challenge/response auth handshake. `pyproject.toml` and
    `requirements.txt` both updated with the exact installed versions.
  - **`obs_link.ObsMuteWatcher`** (new, Qt-free, mirrors `audio.py`'s
    `Microphone`/`FilePlayback` shape exactly): fetches the configured
    input's *initial* mute state via a one-shot `ReqClient.get_input_mute`
    call (events only report *changes*, not the state at connect time),
    then subscribes to `InputMuteStateChanged` via `EventClient`,
    filtered to the configured input name. Reconnects automatically and
    indefinitely -- OBS not running, or its websocket server not being
    enabled yet, are both completely routine here (unlike `Microphone`'s
    mic-disconnect handling, there's no equivalent of "this is corrupt,
    stop retrying"). A wrong input name is treated differently on
    purpose: reported once via `on_error` with a clear message, not
    silently retried into an identical failure forever, since a typo
    isn't something more retries will fix.
  - **`obs_link_manager.ObsLinkManager`** (new, mirrors
    `audio_manager.AudioManager`'s shape): owns the watcher, starts/stops
    it based on `config.obs.enabled`, restarts it when connection
    settings change while enabled. Settings calls into it directly, the
    same established pattern as `render_window.set_background`/
    `audio_manager.switch_to_file`.
  - **`render.RenderWindow.set_muted()`/`effective_talk_level`**: every
    place that previously read `self.talk_level` directly (the mouth-
    shape alpha calc, the mouth-variant-count calc, and the speech-
    bounce retrigger check) now reads `effective_talk_level` instead,
    which is forced to 0 whenever muted, regardless of what the mic/file
    is actually saying. **Judgment call, documented rather than just
    made silently**: muting suppresses the bounce too, not just the
    mouth shape -- a bouncing-but-silent avatar would still visually
    read as "talking energetically," which defeats the point. `talk_level`
    itself is left untouched by muting, so unmuting instantly reflects
    whatever it already is without waiting for a fresh audio update.
  - **`config.ObsConfig`** (new): `enabled` (off by default -- turning
    it on with nothing configured would just be pointless retry noise),
    `host`/`port`/`input_name`, and `password` -- typed into the running
    app's Settings directly, never pre-filled or copied in from OBS's
    own config file by this app, and stored only in this app's own
    `settings.json`, which (like the rest of `unicorn-cloak/`) stays
    outside the parent `obs` repo's git tracking. Matches how OBS itself
    stores its own websocket password in plaintext in its own local
    config -- not over-engineered into a secrets vault for a hobby app,
    consistent with the existing convention on this exact machine for
    this exact kind of credential.
  - **Settings gained an "OBS mute awareness" group**: an enable
    checkbox, Host/Port/Password/Input name fields (password field uses
    `QLineEdit.EchoMode.Password`), and a live status label ("Not
    connected" / "Connected -- not muted" / "Connected -- muted").
  - **Verified against the owner's actual, live, running OBS instance**,
    not just mocks -- confirmed OBS was genuinely running first (`flatpak
    ps`, `lsof -i :4455`), then ran three throwaway scripts (deleted
    after use, never committed) that read the real obs-websocket
    password from OBS's own config file *at runtime* and used it
    in-memory only -- the actual password value was never printed,
    logged, or written into any file or message by this work, including
    this one. Results: (1) the raw `obsws-python` client connects,
    authenticates, and lists real inputs -- found the owner's actual mic
    input, `"blue mic"`; (2) `ObsMuteWatcher` itself connects, reports
    the real initial mute state (`False`), and stops cleanly; (3) an
    intentionally wrong input name against the real server produces
    exactly the designed `on_error` message. **Not verified live**: the
    event-stream path (an actual mute toggle in OBS triggering a live
    update) -- toggling the owner's real mic mute wasn't done unprompted
    out of caution about a visible action on their live session; that
    path is thoroughly unit-tested against a fake client built to match
    the real library's exact attribute names and callback shape (verified
    via reading `obsws-python`'s own source, not guessed), just not
    fired through the real server.
  - **A real, noisy-but-harmless finding, fixed on the spot**:
    `obsws-python` logs a full traceback to stderr on every connection
    failure and every request error via its own logger -- confirmed
    directly against the real server (a wrong-input-name test dumped
    three tracebacks to the terminal even though the error was already
    being handled and reported cleanly through `on_error`). Silenced via
    `logging.getLogger("obsws_python").setLevel(logging.CRITICAL)` in
    `obs_link.py`; re-verified the same test afterward with the noise
    gone and the `on_error` message still correct.

**Visual tuning meter** -- "a live level bar with the open and close
thresholds drawn on it, plus a measured audio-to-frame latency readout.
The owner was fighting responsiveness, so show it":
  - **`_LevelMeter`** (new, `settings_window.py`): a custom-painted
    widget at the top of the "Audio — mouth-shape envelope" group. Draws
    the live smoothed envelope as a filled bar, auto-scaled to
    `max(wide_open * 1.5, envelope, 0.01)` so it stays readable regardless
    of mic sensitivity, with all five thresholds (noise gate, mild/wide
    open and close) drawn as vertical marks read live from `config.audio`
    -- opens solid, closes dashed, so the hysteresis pairs are visually
    distinguishable, not just numerically different in the spinboxes
    below. Polls `render_window`'s plain `current_envelope`/
    `measured_latency_ms`/`talk_level`/`muted` attributes via a 20Hz
    `QTimer`, the same "read the live object directly" pattern
    `_PreviewView` already uses for its scene rather than a signal per
    audio sample.
  - **Latency is measured, not estimated, and honestly scoped**: from
    when a block is captured (`AudioManager._handle_volume_from_source`
    timestamps it, on whichever background thread -- mic or file -- is
    active) to when `__main__.py`'s `on_volume_on_qt_thread` finishes
    processing it on the Qt thread. Documented explicitly, in the code
    and in the Help window, what this number does *not* include: mic
    hardware/OS driver buffering before the block was even readable, and
    the render timer's own up-to-~16ms paint delay after this point --
    labeling it as more precise than it actually is would defeat the
    entire reason the owner asked for a real number instead of a guess.
  - `render.py` gained `set_envelope`/`set_measured_latency_ms`, plain
    telemetry setters alongside the existing `set_talk_level`/
    `set_muted`, called from the same `on_volume_on_qt_thread` call site.
  - 27 new regression tests across five files (two brand new --
    `test_obs_link.py`, `test_obs_link_manager.py`) -- 275 total, up
    from 248. The mute/bounce-suppression behavior in `render.py`, the
    watcher's initial-fetch/event/reconnect/wrong-input-name paths (all
    against a fake client verified to match the real library's actual
    attribute names), the manager's start/stop/restart logic, and the
    Settings UI's field wiring and status label -- all covered before
    ever touching the real OBS instance for the additional live
    verification above.

Also fixed 2026-09-15, from a persistence review — the round-trip claim in
this doc wasn't actually backed by a test that would catch a lossy
round-trip:
  - **`toggle` (a hotkey-bindable per-sprite visibility field) was
    dropped on every load and never written on save.** Not hypothetical:
    every sprite in the real `avatar-01` file has this key
    (`"toggle": "null"`, all currently unbound). `Sprite` never modeled
    it, so it silently vanished on any save through this app. Added to
    `Sprite` and wired through both directions of `persistence.py`. No
    hotkey behavior is built for it yet -- it just survives round-trips
    now.
  - **The round-trip test only compared 7 of ~19 fields**, which is
    exactly how the `toggle` bug went unnoticed. Replaced with (a) full
    `Sprite` dataclass equality sprite-by-sprite, and (b) a raw-JSON
    structural diff, load→save→reload, over every key of every sprite
    against the real `avatar-01` file -- (b) is what actually catches a
    field that never made it into the data model at all, which (a) can't.
  - **`load_avatar` would raise on a `costumeLayers` list of any length
    other than exactly 10**, because `Sprite.__post_init__`'s strict
    validation (correct for sprites this app constructs) was also being
    applied to whatever an external file happened to contain. Legacy
    pads a short list rather than crashing; `persistence.py` now
    normalizes (pads with `True`, truncates if long) before constructing
    the `Sprite`, so an older or hand-edited file loads instead of
    throwing.
  - **`save_avatar` wrote directly to the target path, non-atomically,
    with the app's *default* avatar path pointing at the owner's only
    master copy of that file** (not a working copy). Now matches
    `config.py`'s pattern: temp file + `os.replace`, plus one `.bak` copy
    of whatever was there immediately before the write.
All four have tests, including one that saves the same path twice and
confirms the `.bak` contains the version *before* the last write, not the
current one.

**Three more new features, 2026-09-16, owner's request** ("next: Envelope
record and replay... Hot reload... Costume snapshot export"). None of
these are on any phase's plan either -- all owner-directed additions, like
the file-audio-source work and the mute-awareness/tuning-meter pair above.

**Envelope record and replay** -- "capture ten seconds of mic envelope and
loop it so thresholds can be tuned without talking the whole time":
  - **`audio.EnvelopeRecorder`/`EnvelopeRecording`/`EnvelopeLoopPlayback`**
    (new, Qt-free, `audio.py`): the recorder is a plain, unthreaded
    `(elapsed_seconds, value)` collector -- `record()` is meant to be
    called inline from whatever's already delivering volume values, on
    whichever thread that already runs on, so it needs no thread or lock
    of its own. The player loops the recorded sequence forever, waiting
    the *actual* recorded gap between samples each time (not an even
    spacing), which is what preserves a real speech rhythm -- pauses,
    bursts, and all -- to tune attack/hold/release against, rather than
    smoothing it into an average. Same on_volume/on_error contract as
    `Microphone`/`FilePlayback`.
  - **What gets recorded is the *raw* per-block volume, not the
    already-smoothed envelope** -- a deliberate choice: feeding raw
    volume back through `update_speaking()` on every loop means changing
    attack/hold/release/thresholds *while the loop is playing* still
    changes the resulting mouth behavior in real time, exactly like
    talking live would. Recording the smoothed envelope instead would
    have baked in whatever settings were active during recording and
    made half the point of this feature (tuning against a live loop)
    moot.
  - **`AudioManager.start_recording_and_loop(duration_s=10.0)`**: records
    whatever's currently active (mic or file -- it doesn't care which,
    since `_handle_volume_from_source` feeds the recorder inline
    regardless of source), then automatically starts looping once the
    window closes. **`stop_loop()`** restores whichever source was active
    before recording started. The 10-second cutoff is a `QTimer.singleShot`
    on the Qt thread, not the recorder noticing its own deadline -- a
    plain elapsed-time check inside `record()` would only fire on the
    *next* incoming sample, which could arrive late or never near a real
    silence at the end of the window; the timer fires at exactly the
    requested duration regardless.
  - **A real ordering bug caught by a UI test, not by inspection**: the
    first draft emitted `recording_finished` *before* calling
    `_start_loop()`. `recording_finished` is a direct (non-queued)
    connection -- both fire on the Qt thread already, since the QTimer
    that triggers them was created there -- so Settings' listener ran
    *synchronously inside* the emit() call and read `is_looping` as still
    `False`, showing "Record 10s & loop" instead of "Stop loop" right
    after a successful recording. Found by
    `test_recording_completes_and_button_offers_stop_loop` failing, fixed
    by starting the loop first and emitting second.
  - **Settings gained a "Record 10s & loop" button** in the Audio source
    group: idle text "Record 10s & loop"; disables itself and counts down
    ("Recording… Ns") during the capture window; becomes "Stop loop" once
    looping (clicking it calls `stop_loop()` and snaps the Source combo
    back to whatever it already reads, since looping is a temporary
    override on top of Microphone/File, not a third peer entry in that
    dropdown). Switching Source manually while looping (or calling
    `switch_to_microphone`/`switch_to_file` directly) also stops the loop,
    so there's no way to end up with two sources fighting for the mouth.
  - 16 new regression tests across `test_audio.py`, `test_audio_manager.py`,
    `test_settings_window.py` -- including the ordering bug above, caught
    by the test written to check the feature works, not written after the
    fact to reproduce a bug already found by hand.

**Hot reload** -- "watch the save file and its source PNGs and reload on
change, so art iteration never needs a restart":
  - **`hot_reload.AssetWatcher`** (new, Qt-facing -- built on
    `QFileSystemWatcher`, whose signals already fire on the Qt thread, so
    unlike `audio.py`/`obs_link.py` there is no cross-thread marshaling
    needed here at all): watches the avatar's save file and every
    sprite's own source PNG path, debounced 200ms so one logical save
    (which can still produce more than one low-level write event) becomes
    one reload, not several.
  - **A real, well-known `QFileSystemWatcher` quirk worked around
    proactively, not found by a failure**: many editors and export tools
    replace a file via write-to-temp-then-rename rather than writing to
    it in place, which changes the file's inode and silently drops it
    from the watch after the *first* such save. `_emit_for_path`
    re-`addPath`s defensively after every change, verified with a test
    that does two separate temp-file-then-`Path.replace()` saves in a row
    and confirms both are caught, not just the first.
  - **`EditorWindow.refresh_after_external_change()`** (new): the same
    rebuild-scene/rebuild-list/clear-selection/render-window-rebuild
    sequence `_on_load()` already ran after a manual Load, factored out
    so hot reload (and any future external-change trigger) doesn't
    duplicate it. Deliberately does not push an undo snapshot -- an
    external file change on disk isn't an action this app's undo stack
    has any business reverting; the next hot-reload event would just pull
    the same file back in anyway.
  - **`__main__.py` wiring**: on the avatar file changing, reloads via
    the existing `load_avatar_with_upgrade` and re-points the sprite
    watch at whatever the reloaded file now actually contains (sprites
    can be added/removed/renamed by an external edit); on a single
    sprite's PNG changing, re-reads just that file's bytes into
    `sprite.image_data` in place -- the same mutation the Editor's own
    "Replace" button already does, just triggered automatically instead
    of by a click.
  - 14 new regression tests (`test_hot_reload.py`, new; three more in
    `test_editor_window.py`), including the inode-replace quirk above and
    a debounce test that fires five rapid writes and confirms exactly one
    reload signal.

**Costume snapshot export** -- "render any costume to a PNG at arbitrary
resolution for thumbnails and channel art. A few lines with QPainter":
  - **`snapshot.render_costume_snapshot`/`export_costume_snapshot`** (new
    module): builds a throwaway `QGraphicsScene` with no runtime/
    simulation state at all -- every sprite sits at its rest pose (no
    sway, drag, rotation, stretch, or bounce) -- reusing the same
    parent/child item-nesting `rig.py`'s contract describes for position
    composition, and the exact same `talk_level=0, blink_level=1,
    edit_mode=False` convention `editor_window.py`'s own static preview
    already uses for "what does this look like at rest," so a snapshot
    can never show a sprite the Editor itself wouldn't also show ghosted
    at rest. Only sprites in the requested costume slot, not hidden, and
    visible at rest show up. `export_costume_snapshot` optionally scales
    the result to an exact width/height (aspect-preserved, transparent-
    padded, centered) via `QPainter.drawImage`, matching the owner's own
    framing ("a few lines with QPainter").
  - **Editor gained an "Export Snapshot…" button**: prompts for width,
    height (`QInputDialog`), then a save path (`QFileDialog`), and
    exports the currently active costume.
  - 10 new regression tests (`test_snapshot.py`, new; two more in
    `test_editor_window.py`) covering hidden sprites, costume-slot
    filtering, mild/wide talk-variant exclusion at rest, parent/child
    position composition when the parent itself is invisible, and the
    exact-resolution export path.
  - 312 tests total, up from 275.

**Editor "artifacts" investigated, 2026-09-16** -- owner reported "all
the mouths off but the editor has some strange artifacts showing maybe
all of them w/like 2% opacity", then confirmed glasses (also hidden)
showed the same faint ghost, and that the Render Window never shows it.
That combination -- multiple, unrelated hidden sprites all faintly
visible, only in the Editor -- pointed straight at the *intentional*
edit-mode ghosting in `motion.sprite_alpha` (hidden, or gated off by the
current talk/blink preview state, renders at a low alpha in the Editor
specifically so the artist can see where a layer is; the Render Window
always renders the same sprite at true 0%), not a real rendering bug.
Confirmed by reading the code rather than assuming: this was working
exactly as designed since `editor_window.py`'s original build. The
owner found the existing 0.2 ghost too faint to read as "deliberate
outline" rather than "rendering glitch," and wanted it adjustable rather
than just explained:
  - **Ghost alpha bumped 0.2 → 0.4** in `motion.sprite_alpha` (both
    branches: explicitly-hidden sprites and sprites gated off by the
    current preview state share the same constant).
  - **New "Show hidden layers ghosted" checkbox** in the Editor
    (`editor_window.py`), on by default (preserves existing behavior).
    Unchecking it passes `edit_mode=False` into every
    `motion.sprite_alpha` call from `_apply_preview_opacity`, so hidden/
    gated-off sprites render at true 0% in the Editor too -- an exact
    match for what the Render Window already shows, for previewing
    without the ghost outlines.
  - 3 new regression tests in `test_editor_window.py`; 3 existing
    `test_motion.py`/`test_editor_window.py` assertions pinned to the old
    0.2 constant updated to 0.4. 315 tests total, up from 312.

**Settings spinbox Reset/Lock + scroll-safety, 2026-09-16, owner's
request**: "each of the little boxes in the settings window need reset &
lock buttons (lock because scrolling changes values and moves the window
and it's easy to miss and change a setting you didn't want to).. also
make it so u have to click in the field itself before you can scroll
change it rather than just when hovering over."
  - **`ScrollSafeSpinBox`/`ScrollSafeDoubleSpinBox`** (new,
    `settings_window.py`): override `wheelEvent` to ignore the wheel
    unless the field already has keyboard focus (i.e. was clicked into
    first) -- Qt's default QAbstractSpinBox reacts to the wheel on hover
    alone, which is exactly what made scrolling this long, scrollable
    window liable to silently change whatever field the cursor happened
    to be over. Every numeric field in Settings (all 17 built through
    `_add_double`/`_add_int`, plus `zoom` and `obs_port`, previously
    constructed inline) now uses one of these two instead of a plain
    `QSpinBox`/`QDoubleSpinBox`.
  - **`set_locked(bool)`** on the same classes: a second, stronger
    guarantee on top of focus-gating, for a value the owner wants to
    make hard to bump even deliberately. Overrides `stepBy()` (what
    wheel, arrow keys, and the spin buttons all funnel through in Qt) to
    no-op while locked, and additionally sets `setReadOnly(True)` since
    typing a value and pressing Enter bypasses `stepBy()` entirely (it
    goes through `interpretText()`/`setValue()` instead) -- verified
    both paths directly with a script driving real `QWheelEvent`s and
    `stepBy()` calls before writing it up, not assumed from the Qt docs.
  - **Every field gained a Reset button** (restores the field's actual
    dataclass default, read via `dataclasses.fields()` rather than
    hardcoded a second time) **and a Lock toggle** (checkable, disables
    Reset while checked -- "locked" means the value can't change through
    this UI at all until explicitly unlocked, not just "harder to
    change"). `theme.py` gained a `QSpinBox:read-only`/
    `QDoubleSpinBox:read-only` rule (muted text/background, reusing the
    existing `GREY_500`/`INK_850` tokens) so a locked field is visually
    obvious, not just functionally inert.
  - **A real rendering bug caught by an actual screenshot, not assumed
    to be fine**: the first version used ↺/🔓/🔒 as button labels.
    Grabbing a real rendered screenshot of the Settings window showed
    both as blank/garbled boxes -- this app's bundled "Space Grotesk"
    font has no glyph for either and Qt has no configured fallback font
    here. Replaced with plain text ("Reset"/"Lock"/"Locked"), matching
    every other button in this app (Play, Stop, Browse…, etc.), and
    re-screenshotted to confirm before calling it done. A second
    screenshot caught a follow-up sizing bug the same way: a fixed
    28-56px button width (sized for the symbols) clipped the plain-text
    labels; fixed by sizing the Lock button's minimum width off its own
    longer "Locked" state up front so it doesn't visibly resize the row
    the first time it's checked.
  - 12 new regression tests (`test_settings_window.py`): the focus-gated
    wheel behavior and lock's stepBy/wheel blocking directly against the
    new spinbox classes (real `QWheelEvent`s, not mocked), Reset
    restoring the true default, Lock disabling Reset and greying out the
    field, and that `zoom`/`obs_port` (the two special-cased inline
    fields) got wired up identically to the fields built through
    `_add_double`/`_add_int`. 321 tests total, up from 315.

**Real mouth-stacking bug root-caused and fixed, 2026-09-16, owner's
report**: "microphone is still blasting through the ceiling and my actual
mic gain is @ about 30%" plus "how does the program know which eyes/
mouths are open/closed etc? seems to be no indicator or ability to
directly set them." Investigated both before writing any code, not
assumed:
  - **Checked the real avatar file directly**: `mouth-closed-01.png` had
    `talk_state=0`. Per `axis_visible`, 0 means "always visible,
    regardless of talk level" -- so the closed mouth was rendering on
    *every* frame, not just at rest; mild/wide only ever drew on top of
    it. Confirmed with a pixel-level alpha diff (not assumed): ~15-17% of
    the closed mouth's opaque pixels, concentrated in a ~144x211px region
    at the lip corners, aren't covered by either open variant's opaque
    art -- exactly where it would visibly peek through.
  - **Checked the legacy PNGTuber-Plus Godot source** to rule out a
    mis-port before touching anything: legacy's own `talkBlink()` formula
    confirms `showTalk=0` really did mean "always visible" there too
    (verified by hand-decoding the lookup-table formula for all
    speaking/blink combinations) -- so this app's port of that specific
    semantic is faithful; the bug is that a real closed/mild/wide trio
    was authored assuming three individually-gated bands, which the
    2-value-plus-"always" model (0/1/2, legacy's own scheme) never
    supported for the "closed" member. This app's own 3-band talk_level
    (quiet/mild/wide) is already a deliberate enhancement over legacy's
    plain speaking-boolean; this is the model catching up for real
    trio-authored content.
  - **`motion.TALK_QUIET_ONLY` (new, value 3)**: a fourth, additive
    `talk_state` value meaning "visible only when talk_level == 0."
    Chosen over repurposing 0 itself specifically to avoid a breaking
    migration -- every existing non-mouth sprite (hair, hoody, shades,
    bling) in the real avatar already relies on 0 meaning "always show,"
    and there's no way to tell old data's intent apart automatically.
    `blink_state` gets no equivalent sentinel -- blink only has two real
    bands (open/blinking), both already representable via 1/2.
  - **A second, related bug caught while adding the sentinel**:
    `render.py`'s `_talk_variant_count` computed membership with a direct
    `talk_state == effective_talk_level` check, which would have
    silently excluded any future `TALK_QUIET_ONLY` sprite from ever
    sharing a variant-alternation pool (3 never equals an actual
    talk_level, which is always 0/1/2). Fixed by using
    `motion.axis_visible()` for the membership check instead of direct
    equality -- doesn't change behavior for existing states 1/2, only
    correctly extends to 3.
  - **Talk state / Blink state are now QComboBoxes, not raw-number
    QSpinBoxes**, in the Editor's property panel -- "Always visible",
    "Only when quiet" (talk axis only), "Only mild", "Only wide" /
    "Only eyes open", "Only mid-blink", each carrying its real int as
    `itemData` so the file format is unchanged. Owner's own words: "a
    didactic way to assign sprites to their actions" -- the raw 0-2
    numbers were exactly what made the original bug possible to author
    without noticing.
  - **New "Preview state" group** in the Editor (above the Sprites
    list): two more dropdowns (Talk level: Quiet/Mild/Wide; Blink state:
    Eyes open/Mid-blink) that force the canvas preview to whatever
    combination is picked, instead of the fixed rest pose
    (`talk_level=0, blink_level=1`) it was hardcoded to before. Directly
    closes the gap the owner named ("no indicator or ability to directly
    set them") and would have caught the original bug immediately, since
    the closed mouth would have visibly stayed on top at every preview
    level. Never affects the Render Window.
  - **The real avatar file itself was fixed**, not just the code: loaded
    it through this app's own `load_avatar_with_upgrade`, changed the
    closed mouth's `talk_state` from 0 to `TALK_QUIET_ONLY`, and saved it
    back through `save_avatar` (atomic write, automatic `.bak`) --
    verified no instance of the app was running first, so nothing could
    overwrite the fix with a stale in-memory copy, and reloaded
    afterward to confirm the value round-trips as 3, not 0. The 15-17%
    art coverage gap at the lip corners is now moot for correctness
    (mutual exclusion doesn't depend on it) but is still a known
    cosmetic imperfection if the owner ever wants to tighten the art.
  - 20 new/updated regression tests across `test_motion.py`,
    `test_editor_window.py`, `test_persistence.py` (the real-avatar-file
    test's `talk_state == 0` assertion was a pin on the *old, buggy*
    value -- updated to assert `TALK_QUIET_ONLY`, with a comment
    explaining why, not silently changed).

**Mic sensitivity/gain knob, 2026-09-16, same owner report**: PipeWire's
own volume for the owner's mic (`wpctl get-volume @DEFAULT_AUDIO_SOURCE@`)
read 0.81 at the time, not the ~30% the owner referenced -- checked
directly rather than guessed, and left unresolved which control the
owner was actually looking at (a mic's own physical gain dial, if it has
one, wouldn't show up in PipeWire at all). Rather than chase that further
remotely, added a control this app fully owns regardless of the answer:
  - **`AudioConfig.gain: float = 1.0`** (new) and
    `AudioManager._handle_volume_from_source` now multiplies every raw
    RMS value by it before anything downstream (the recorder, the level
    meter, `update_speaking`'s thresholds) ever sees it, clamped to
    [0, 1] so an aggressive gain can't make the level meter's own
    auto-scaling chase an unbounded number. Applied once, at the
    earliest point in the pipeline -- equivalent to the mic itself being
    that much louder or quieter, independent of whatever the OS mixer or
    a hardware knob is doing.
  - **New "Sensitivity" field** in Settings' audio group (first field,
    above Noise gate, since it scales everything below it), built
    through the same `_add_double` path as every other threshold -- gets
    Reset/Lock and scroll-safety for free, no special-casing needed.
  - 5 new regression tests (`test_audio_manager.py`, `test_settings_window.py`):
    gain multiplies correctly, gain=1.0 is a no-op, clamping at the top
    of the range, and the Settings field's default/Reset/Lock wiring.
  - 333 tests total, up from 321.

**Named groups, manual-driven expressions, and a sanity-check pass,
2026-09-17, owner's follow-up**: after the mouth-stacking fix landed, the
owner asked the sharper question underneath it -- "how in the world does
the app know which sprite is a mouth, which is an eye, which is open
which is closed? ... it's all just coincidence right now." Confirmed
directly (read `rig.Sprite`'s full field list): true, no `name`/`role`/
`group` field existed anywhere. A sprite "being a mouth" was entirely
incidental -- shared position, shared parent, and talk_state values that
happened not to collide, with nothing tying them together on purpose and
nothing to catch it when they were wrong (which is exactly how the
original bug shipped unnoticed). The owner also wanted more than 3 mouth
states ("mouth laughing"), confirmed two design decisions before building
anything: a manual on/off toggle (not audio detection) for a state like
"Laughing", and keep the existing 3 volume bands as-is rather than
redesigning them -- named grouping layers on top, it doesn't replace the
mechanism.
  - **`rig.Sprite` gained three fields**: `group_name`/`state_name`
    (both `str`, purely organizational -- e.g. group_name="Mouth",
    state_name="Closed"/"Laughing") and `manual_driven: bool`. All three
    default to `""`/`False`, so every file saved before today loads with
    identical behavior; `persistence.py` round-trips them as
    `groupName`/`stateName`/`manualDriven` (no legacy counterpart, same
    treatment as `variant`/`hidden` before them).
  - **`motion.sprite_alpha` gained `manual_driven`/`manual_active`**:
    when `manual_driven` is true, talk_state/blink_state and every
    `*_variant` parameter are ignored entirely -- visibility is exactly
    `manual_active`, a plain bool the caller computes by comparing the
    sprite's group_name/state_name against whatever's live-overridden.
    Deliberately kept `sprite_alpha` itself ignorant of "groups" as a
    concept -- it stays Qt-free and testable with plain bools, same as
    before.
  - **`render.RenderWindow.manual_overrides`/`set_manual_override()`**
    (new): a live `group_name -> state_name` dict, read every frame in
    `_apply_to_scene`. An absent entry means "not overridden" -- correct
    default is nothing showing until explicitly forced, not some
    fallback state. Also excluded manual_driven sprites from
    `_talk_variant_count`/`_blink_variant_count`'s membership checks,
    matching the same defensive pattern the TALK_QUIET_ONLY fix used.
  - **Editor property panel gained Group name / State name (editable
    combos, prefilled with whatever's already used in this rig -- State
    name's options scoped to the selected Group, cleared when the group
    changes) and a Manually driven checkbox** (disables Talk state/Blink
    state while checked -- verified with a real screenshot that disabled
    fields are actually visually distinguishable, see below).
  - **A real signal-wiring bug caught by a failing test, not
    inspection**: the first draft wired Group name's editable combo
    through `currentIndexChanged`, which only fires when picking an
    *existing* item from the dropdown list -- typing a brand-new group
    name (the whole point of an editable combo) never fired it at all,
    so State name never got rescoped and the change never wrote through.
    Verified empirically with a throwaway script before fixing: an
    editable QComboBox's `editTextChanged` fires in every case
    (selecting an existing item, typing new text, or setting existing
    text programmatically) where `currentIndexChanged` only fires for
    the first. Switched both Group name and State name to
    `editTextChanged`.
  - **Editor's "Preview state" extended**: "Force talk variant"/"Force
    blink variant" (0-9 spinboxes) pick which sprite shows when more
    than one shares a band -- the Editor's canvas has no running timer
    to alternate them on its own (see this module's own docstring:
    deliberately static), so without this a second variant (e.g. squint
    alongside wide-open eyes) was simply never previewable at all. Found
    because the owner reported exactly that: "blink preview is only
    showing 2/3 states (no squint state)." A new
    `_preview_variant_counts()` helper mirrors render.py's own
    `_talk_variant_count`/`_blink_variant_count` logic so
    `motion.sprite_alpha`'s variant-count>1 gating actually engages in
    the Editor too (previously it silently never did, since
    `talk_variant_count`/`blink_variant_count` were never passed in at
    all -- every sprite sharing a band just showed simultaneously,
    unfiltered). Also gained "Force expression", a canvas-only preview
    of a Manually-driven state, independent of Settings' real,
    live-affecting control below.
  - **Settings gained an "Expressions" group**: one checkable button per
    distinct (group_name, state_name) pair found among manual_driven
    sprites in the loaded rig (a placeholder explains how to define one
    if none exist yet). Checking a button calls
    `render_window.set_manual_override()` live; buttons sharing a group
    are mutually exclusive (checking one unchecks any other in the same
    group), matching `manual_overrides` being one value per group key.
    Not persisted to settings.json -- a live control, not a setting,
    same precedent as the live-preview toggle.
  - **A second real rendering bug caught by a screenshot, not assumed
    fine**: grabbed a real image of a checked vs. unchecked Expressions
    button and they were pixel-identical -- `theme.py` had no
    `QPushButton:checked` rule at all, so there was no way to tell an
    active expression override from an inactive one just by looking.
    Added one (filled magenta, matching the theme's existing "active"
    accent), re-screenshotted to confirm, and it incidentally also fixed
    the same missing visual cue on Settings' own Lock buttons (which
    already changed *text* on check but never color).
  - **`rig_lint.py`** (new module, Qt-free): `find_rig_issues(rig)` --
    heuristic sanity checks, not a hard validator. Buckets sprites by
    `group_name` when set, falling back to `parent_id` for older/
    ungrouped content (so the check still works on a rig that hasn't
    adopted Group name at all yet). Flags: incomplete exclusive-gating
    coverage on either axis (used states form a proper subset of the
    full gated set), two sprites sharing a state *and* the same Variant
    (would fight instead of alternate -- reuses the exact axis_visible-
    based membership logic the render.py variant-count fix established),
    a manual_driven sprite with no group/state set (can never be
    triggered), and inconsistent Talk/Blink/manual_driven settings
    across sprites sharing the same (group, state) label pair (likely
    copy-paste drift). Verified against the real, now-fixed avatar file
    end-to-end: zero issues found.
  - **Editor gained "Check for Issues…"**, next to Export Snapshot:
    runs `find_rig_issues` and reports results in a message box (a
    clean "No issues found." or each finding as a bullet).
  - 37 new regression tests across `test_rig_lint.py` (new),
    `test_motion.py`, `test_render.py`, `test_editor_window.py`,
    `test_settings_window.py`, `test_persistence.py`. 370 tests total,
    up from 333.

**Interface redesign: single Control Panel window, 2026-09-17, owner's
request** ("now we need to deal w/interface issues... firstly, do tell
why we have 3 windows please lol"). Answered honestly first: the docs
said "two-window architecture" (Render Window + one Control Panel) but
the app had actually drifted to three (Editor and Settings split apart
organically, never reconfirmed). The owner then gave a full list of
interface changes; two clarifying questions up front (what "level meter
always below the avatar" meant -- resolved as one canvas with an
Edit/Live-Preview toggle, live preview default; and quit-confirmation
behavior -- resolved as always-confirm, extra warning if unsaved) before
committing to the design, then delivered as one continuous pass with
screenshot checkpoints, per the owner's own preference.
  - **`editor_window.py`/`settings_window.py` deleted outright**, not
    kept as unused parallel classes -- everything they did now lives in
    **`control_panel_window.py`** (new, ~1700 lines, the single
    `ControlPanelWindow`) plus a new **`widgets.py`** (the genuinely
    reusable pieces: `ScrollSafeSpinBox`/`ScrollSafeDoubleSpinBox`,
    `LevelMeter`, `PreviewView`, `elide_path_middle`, and the new
    `CollapsibleSection`). `__main__.py` now constructs one window
    instead of two; every old test in `test_editor_window.py`/
    `test_settings_window.py` was either ported into the new
    `test_control_panel_window.py`/`test_widgets.py` or superseded by a
    more accurate replacement -- not left pointing at deleted code.
  - **Layout**: a canvas up top (Live Preview -- mirrors the real Render
    Window, reacts to actual mic/blink, read-only, the default -- or Edit
    Sprites -- the interactive drag-to-position canvas, driven by Preview
    state controls that appear above it only in this mode) with a level
    meter always directly below it in either mode; four tabs below that
    (Sprites, Behavior, Audio, Application, each holding at most 3
    `CollapsibleSection`s in a vertical `QSplitter` so every section is
    independently collapsible *and* resizable); a bottom bar that's never
    scrolled out of view (audio source controls on their own row with the
    chosen file's path shown underneath, middle-elided so the filename
    itself always stays intact; then Undo/Redo/Help/Save/Save As…/
    Load…/Export Snapshot…/Check for Issues…/Guide/Ghost/Quit).
  - **Grid replaces the old origin crosshair**: `GridCanvasView` draws a
    full grid at a configurable spacing (`ControlPanelConfig.grid_spacing_px`,
    default 100px, editable on the Application tab), plus the origin axes
    through (0, 0) still drawn brighter than the rest of the grid. Off by
    default, toggled with the **Guide** button -- a checkable
    `QPushButton`, not a checkbox with a paragraph-long label (owner's
    request); same treatment for **Ghost** (was "Show hidden layers
    ghosted"). Both default off now too (was on).
  - **Dirty-tracking, Save vs. Save As, and quit confirmation** (new
    behavior, not present before): `_dirty` is scoped to the avatar rig
    only -- every Settings-style field already autosaves into
    `settings.json` immediately, so there's nothing to lose there.
    **Save** writes to whatever file was last saved to or loaded from,
    no dialog; **Save As…** always prompts. `RenderWindow` gained
    `on_quit_requested`/`on_avatar_double_clicked` callback hooks (kept
    Qt-free of any Control Panel coupling -- `render.py` stays a dumb
    leaf widget) -- Escape and the new Quit button both route through
    the *same* `confirm_and_quit()`: always asks to confirm, and if the
    avatar has unsaved changes, offers Save/Discard/Cancel instead of
    just quitting silently, which is what happened before. Closing the
    Control Panel itself (the window, not the whole app) still does
    neither -- "Settings window can be closed, leaving avatar live" --
    and double-clicking the avatar in the Render Window reopens it.
  - **A real bug found by a real test, not assumed away**:
    `EditableSpriteItem.__init__`'s own `setPos()` call fires Qt's
    `itemChange(ItemPositionHasChanged)` exactly like a real drag would
    -- pre-existing in the code this was ported from, but with no
    observable effect until dirty-tracking existed to expose it: every
    `_rebuild_scene()` (including the very first one, at construction,
    and every Load/undo/redo/hot-reload after that) was marking the
    avatar dirty on its own, before any real edit -- the quit
    confirmation would have warned about unsaved changes literally every
    time, even right after opening the app. Fixed with a
    `_rebuilding_scene` guard flag around the scene-construction pass;
    `on_sprite_moved` (which `itemChange` calls) no-ops while it's set.
  - **Two more real rendering bugs, both found by grabbing and reading
    actual screenshots, not assumed correct**: (1) `CollapsibleSection`'s
    header is a `QPushButton`, and Qt treats a bare `&` in button text as
    a mnemonic marker -- "Position & Hierarchy" rendered as
    "Position_Hierarchy" until fixed by escaping to `&&` (Qt's own
    literal-ampersand escape). (2) `theme.py` had no `QPushButton:checked`
    rule at all -- a checked Expressions button was pixel-identical to an
    unchecked one in a real screenshot comparison. Added one (filled
    magenta, matching the theme's other "active" accent), which
    incidentally also fixed the same missing cue on the Reset/Lock
    fields' own Lock buttons (previously only a text change, no color).
  - **`ControlPanelConfig`** (new, in `config.py`): window geometry
    (`x`/`y`/`width`/`height`, clamped to the current screen's available
    height on show and on every resize -- "window vertical should never
    be larger than the screen height"), `active_tab`, `canvas_mode`,
    `show_origin_guides`, `show_hidden_ghosted`, `grid_spacing_px`, and
    `collapsed_sections` (a tuple of section titles) -- all round-tripped
    through `settings.json` so the Control Panel reopens exactly as it
    was left, per the owner's explicit request to remember "all
    settings/state/loaded avatar." The loaded avatar's path was already
    tracked (`config.avatar_path`); Save As/Load now keep it in sync
    (previously only the initial startup load used it).
  - New regression tests: `test_widgets.py` (new, 10 -- including the
    `&`-escaping regression) and `test_control_panel_window.py` (new,
    39 -- including the `_rebuilding_scene` dirty-tracking regression,
    Save/Save As/Load path-tracking, all five `confirm_and_quit()`
    branches, canvas-mode switching, grid/ghost toggling, and the
    elided-path source-file label), plus `test_render.py` (+6, the new
    quit/double-click hooks) and `test_theme.py` (updated for the merged
    window) -- net of the ~95 tests deleted with `test_editor_window.py`/
    `test_settings_window.py`. **314 tests total.**

No dependency on the `obs` repo's own rules beyond "lives here for now" —
this is a companion app, not an OBS config change, so none of CLAUDE.md's
live-tree/secrets/output-settings rules apply to it. It gets a line in the
root README's layout table since it's a new top-level directory; it does
not get its own git history yet.

**Interface redesign follow-up fixes, same day, 2026-09-17, all four found
by the owner testing the real build, not by review:**
  - **Theme selector still pointed at the deleted window names.**
    `theme.py`'s background rule read `QWidget#EditorWindow,
    QWidget#SettingsWindow` -- never updated when the merge renamed the
    class to `ControlPanelWindow`, so the whole window rendered with no
    background at all ("everything is still all white"). Fixed by
    updating the selector to `QWidget#ControlPanelWindow,
    QDialog#HelpWindow`.
  - **Canvas too small, settings pane too wide.** Two independent causes.
    (1) `QSplitter.setSizes()` doesn't reliably stick when called before
    the window has actually been shown -- verified with a synthetic
    reproduction (a pre-show `setSizes([600, 400])` on a 1000px splitter
    came back `[382, 254]`, nowhere near proportional). Fixed by moving
    the initial-sizes call into a `showEvent()` override, guarded by a
    one-time flag. (2) `minimumSizeHint()` on the right-hand pane was
    1021px, almost entirely driven by an 11-button single-row bottom
    action bar fighting the splitter for space. Fixed by splitting it
    into two rows (dropped the minimum to 518px), bumping the default
    window to 1600×880 (was 980×820), and weighting the splitter's
    stretch factors 3:2 toward the canvas. Verified end-to-end with real
    screenshots against the owner's actual avatar file (958/638px split).
  - **`ControlPanelConfig` never actually round-tripped through
    `settings.json`** -- diagnosed by the owner directly, down to the
    exact two-line fix ("Config.control_panel is populated correctly in
    memory, but save_state() never writes it to JSON and load_state()
    never reads it back... I confirmed this live"). `save_state()`/
    `load_state()` simply never mentioned the `control_panel` key. Fixed
    by wiring it into both, with the same tuple-normalization
    `collapsed_sections` already needed applied to the new
    `splitter_sizes` field too (added at the same time, to also persist
    the user's dragged splitter ratio). Two new regression tests added in
    `test_config.py` for the save→load round trip specifically, not just
    the in-memory capture that let this slip through 314 passing tests.
  - **Quit/save confirmation dialogs had invisible text** ("the save/quit
    dialogs have no text and the save one maybe not working correctly").
    Root cause, confirmed empirically (not assumed): an application-wide
    Qt stylesheet's descendant selectors (e.g. a scoped
    `#ControlPanelWindow QLabel` rule) match by the parent-child
    *ownership* tree, not the visual/layout tree -- so the existing
    blanket, unscoped `QLabel { color: PINK_WHITE; ... }` rule was always
    going to leak into any `QMessageBox`/`QInputDialog` built as
    `QMessageBox.warning(self, ...)`, since `self` is passed through as
    the Qt parent regardless of it being a separate top-level window.
    Scoping the label rule more tightly would *not* have fixed this --
    proved with a direct test before attempting a fix. The dialogs had no
    background of their own to match that light text, so on the owner's
    real (light-palette) GNOME session the message body was light text on
    a light background; it happened to look fine in this dev
    environment's own dark-default offscreen palette, which is why it
    wasn't caught here first. Fixed with an explicit `QMessageBox,
    QInputDialog { background-color: {INK_900}; }` rule. Verified two
    ways: real screenshots of both dialog types with clearly readable
    text, and `box.palette().color(box.backgroundRole()).name()`
    returning the exact `INK_900` hex after `ensurePolished()`. Two new
    regression tests added in `test_theme.py`. Deliberately did **not**
    extend the same fix to `QFileDialog` (Save As.../Load.../Export
    Snapshot's file picker) -- it has the identical leak but a much
    bigger internal widget tree (file list, tree view, breadcrumbs) that
    this stylesheet doesn't cover, so a background-only fix would look
    half-themed rather than actually fixed; flagged for the owner as an
    open question, not implemented unprompted.
    Separately traced the "save one maybe not working correctly" half of
    the report: read through `confirm_and_quit()`'s Save/Discard/Cancel
    branches and `_on_save()`, then live-tested the full Save-and-quit
    path end to end (construct a dirty panel, monkeypatch the warning
    dialog to return Save, call `confirm_and_quit()`) -- the file is
    written to disk, `_dirty` clears, and the app is allowed to quit, all
    correctly. No separate functional bug found; almost certainly just a
    byproduct of not being able to read which button did what before the
    text-visibility fix above.

**`QFileDialog` styling closed out, same day, 2026-09-17, owner's
request** ("yep, fix the thing please" -- the open question above).
Rather than a background-only fix, gave it the full treatment: its own
background, plus explicit rules for its internal `QLineEdit` (filename
entry), `QListView`/`QTreeView` (file listing and the favorites
sidebar -- true embedded child widgets, not a separate top-level window
like `QMessageBox`, so ordinary descendant selectors reach them with no
ownership-tree caveat needed), and `QHeaderView`/`::section` (Detail
View's column headers, including the empty trailing stretch section,
which needed its own base `QHeaderView` rule -- `::section` alone left
it a stray native-grey box). Verified with real screenshots in both
Detail View and List View, against the owner's actual home directory
listing -- consistent dark theme throughout, no half-themed native
widgets left. Two new regression tests in `test_theme.py`
(`test_stylesheet_fully_themes_qfiledialog`,
`test_filedialog_actually_gets_the_themed_background_color`). **323
tests total.**

**Quit-dialog-twice bug + Control Panel white-background/grid-theme pass,
2026-09-17, owner's report** ("killin' me w/the white background in the
settings section... use the neon cyber grid pattern style from
../ai-animated-video" plus "the quit dialog pops twice"). Two unrelated
bugs, both found by live-reproducing the reported behavior first, not
guessed at:
  - **Quit button asked to confirm twice.** Traced with a monkeypatched,
    call-counting `confirm_and_quit` and a real `app.exec()` run (not a
    direct call -- the bug only shows up through the real event loop):
    `_on_quit_clicked()` called `confirm_and_quit()` itself and *then*
    `QApplication.instance().quit()` -- but `quit()` sends a QCloseEvent
    to every remaining top-level window as part of normal Qt shutdown,
    which hit `RenderWindow.closeEvent`'s own `on_quit_requested()` call
    (wired to that same `confirm_and_quit`) a second time. Fixed by
    having the Quit button close the Render Window instead of confirming
    directly -- `confirm_and_quit()` now only ever runs from inside that
    one `closeEvent`, for both Escape and the Quit button. One new
    regression test (`test_quit_button_only_asks_to_confirm_once`),
    counting real calls through the same wiring `__main__.py` uses, not
    a direct call to `confirm_and_quit()` (which wouldn't have caught
    this at all).
  - **White backgrounds throughout the right-hand pane**, reproduced by
    forcing a plausible light default `QPalette` before constructing the
    real window (same technique as the dialog-text bug) rather than
    trusting this dev environment's own dark-default offscreen palette.
    Found three distinct unstyled containers, not one: the Live Preview
    canvas (`PreviewView` mirrors `render_window.scene`, whose own
    background mode is usually "transparent"/`NoBrush` -- correct for
    the real OBS-captured window, but with nothing else painting over it
    in this in-UI mirror, it fell through to the viewport's native white
    -- fixed with the view's own `setBackgroundBrush`, independent of
    the mirrored scene's); `QSplitter`/`QTabWidget::pane`/`QTabBar`
    (never styled at all, so their native paint won on a light palette,
    also making the Position & Hierarchy field labels unreadable --
    near-white text on a now-explained white background); and
    `QLineEdit` (used directly for the OBS host/password/input-name
    fields, and internally by every `QKeySequenceEdit` hotkey field,
    which delegates its actual paint to a real child `QLineEdit` the
    outer-widget rule never reached).
  - **Replaced the flat single-color window background with the actual
    "neon cyber grid"**, per the owner's request to match
    `../ai-animated-video`'s own design system (a sibling app on this
    machine, same Unicorn Tears/Viz brand) -- read its `globals.css`
    directly rather than guessing: a violet radial glow near the top
    plus two hairline repeating grids (magenta horizontal, cyan
    vertical) at 64px spacing. Qt stylesheets have no
    `repeating-linear-gradient` equivalent, so this is a `paintEvent`
    override on `ControlPanelWindow` instead (the same "draw it with
    QPainter" approach `GridCanvasView`'s own foreground grid already
    used) -- verified empirically first that `WA_StyledBackground`'s QSS
    fill still paints automatically before a custom `paintEvent`
    override runs, so `super().paintEvent(event)` plus manual drawing on
    top was safe, not a guess. Every container fix above was necessary
    groundwork for this to actually show through instead of being hidden
    behind native white again.
  - Verified end-to-end with real screenshots (forced light palette) of
    every tab -- Sprites, Behavior, Audio, Application -- plus both
    canvas modes; no white or half-themed native widgets left anywhere.
    Four new regression tests
    (`test_stylesheet_themes_splitters_tabs_and_lineedits`,
    `test_control_panel_window_paints_the_neon_grid_background`,
    `test_quit_button_only_asks_to_confirm_once`,
    `test_preview_view_has_a_solid_dark_background_brush`). **327 tests
    total.**

**Tab reorganization + grouped Layer List, 2026-09-17, owner's request**
("i'll try to keep these in smaller more easy to manage requests for you
now" -- the first of that series):
  - **State Assignment and Expressions moved from the Behavior tab to the
    Sprites tab**; **Position & Hierarchy and Animation moved from the
    Sprites tab to the Behavior tab**, the latter two starting collapsed.
    Sprites is now Layer List / State Assignment / Expressions (sprite
    *identity*); Behavior is now Motion / Position & Hierarchy /
    Animation (per-sprite *tuning*, alongside the avatar-wide Motion
    knobs). Sections are keyed by title in `self._sections`, so moving
    them between tabs needed no changes to persistence, undo, or any
    other cross-cutting code -- confirmed by the full suite passing
    unchanged (327/327).
  - The "start collapsed" half turned out to need a different fix than
    the obvious one: `CollapsibleSection(..., collapsed=True)` alone does
    nothing, because `_apply_persisted_ui_state()` unconditionally
    re-applies `config.control_panel.collapsed_sections` over top of it
    on every construction -- confirmed by screenshot (both sections
    still rendered expanded despite `collapsed=True`). Real fix:
    `ControlPanelConfig.collapsed_sections`'s own default now includes
    both titles. Caught before it shipped half-fixed: the owner had the
    app open against the *old* code during this session and closed it
    right as the fix landed, which wrote the *old* default
    (`collapsed_sections: []`) into their real `settings.json` --
    patched that file directly (via `json.load`/`json.dump`, not text
    substitution) to match, verified it still round-trips through the
    real `load_state()`.
  - Fixed three stale tooltip/help references the move broke: two Motion
    tooltips ("Mouth/Eye alternate rate") pointed at "the Sprites tab" to
    find Variant, which is now on this same Behavior tab; `help_window.py`
    had its own "Sprites tab" / "Behavior tab" sections describing the
    old split, plus a few older leftover "Settings'"/"the Editor's"
    references from before the original window merge that this reorg
    made newly relevant to fix alongside them.
  - **Layer List now shows a header + lighter background for
    grouped sprites** (owner's request, second half): sprites sharing a
    non-empty Group name (State Assignment's own field -- independent of
    parent/child hierarchy, e.g. three alternate mouth shapes are usually
    siblings, not nested) now get a small magenta, non-selectable header
    row printed at the start of each contiguous run, plus one extra
    indent level and an `INK_700` background (vs. the list's own
    `INK_800`) on the member rows themselves -- `WA_StyledBackground` set
    per-row, since a plain `QWidget` paints no background of its own
    otherwise. Verified with a real screenshot (a synthetic
    head/mouth-trio/eyes rig) showing "Mouth" and "Eyes" headers with
    their members clearly clustered underneath. Five new regression
    tests across `test_control_panel_window.py`
    (`test_layer_list_shows_a_header_row_for_a_shared_group_name`,
    `test_layer_list_header_row_is_not_selectable`,
    `test_layer_list_grouped_member_rows_get_a_lighter_background`,
    `test_layer_list_ungrouped_sprites_get_no_header`). **331 tests
    total.**

**settings.json versioning + tabbed Help dialog, 2026-09-17, owner's
request**:
  - **`settings.json` is now format-versioned**, mirroring
    `persistence.py`'s own `CURRENT_FORMAT_VERSION`/`needs_migration` for
    avatar files, which already existed -- this was the one major piece
    of app-owned persisted state without the same protection. Added
    `CURRENT_CONFIG_VERSION`/`__config_version__` (stamped by
    `save_state()`) and a `_CONFIG_MIGRATIONS` chain applied by
    `_migrate_raw_config()` before `_merge()` ever sees the loaded dict --
    empty for now (no structural change needed one yet, same as
    `CURRENT_FORMAT_VERSION`'s own introduction), but proven to actually
    work end-to-end with a synthetic registered migration in a test, not
    just a stamp nobody reads. Unlike avatar files, this is silent --
    `settings.json` is app-internal state the owner never hand-edits or
    sees a message about, unlike an avatar file. Also fixed
    `config.py`'s own module docstring, stale since the Editor/Settings
    merge (still described a `SettingsWindow` in `settings_window.py`,
    both deleted that day). Four new tests in `test_config.py`.
  - **Help window rebuilt as four tabs** (Overview / Usage / Sprites /
    Reference) instead of one long scroll -- owner's request: "a proper
    help dialog with overall usage methodology & tips... make it
    tabbed." Three tabs are genuinely new writing: Overview (app premise
    plus an explicitly placeholder "About me" paragraph, marked as such
    rather than invented), Usage (the actual end-to-end workflow --
    prepare art, build the rig, tag states, tune live, go live in OBS,
    iterate), and Sprites (practical art-prep tips -- consistent canvas
    size across layers, one full-canvas PNG per state rather than a
    patch, transparency, consistent linework across alternates, pivot
    points, sprite-sheet frame layout). The pre-existing exhaustive
    per-field reference (the original single-tab content) moves to a
    fourth **Reference** tab, word for word -- not discarded, since
    tooltips alone still don't cover what it does. Each tab is its own
    `QTextBrowser`/HTML document (Qt's rich-text engine only reads a
    `<style>` block from the document it's actually painting, not the
    app-wide QSS, so the brand `<style>` block is now factored into a
    shared `_STYLE` constant included in all four rather than copied by
    hand). Verified with real screenshots of all four tabs. Four new
    tests in `test_help_window.py`. **339 tests total.**

**Startup noise hidden unless debug mode, 2026-09-17, owner's request**
("i'm just kinda super anal about my own code's cleanliness... hide the
noise unless debug mode is set please" -- reacting to a real terminal
paste showing three unrelated warning lines on launch). Diagnosed each
line before touching anything: a `libssh.so.4`/`libfido2` ABI-mismatch
dlopen warning and a broken GIO module from an unrelated snap-installed
app are pure system/environment noise, nothing to do with this app's own
code; `qt.qpa.services: Failed to register with host portal` is Qt's own
portal-registration retry, and the exact already-investigated,
already-accepted GNOME/`xdg-desktop-portal-gnome` limitation this doc
already covers above (OBS re-prompting the picker on relaunch regardless
of app_id) -- not a new regression, not actionable from this app's side.
`__main__.py`'s `main()` now checks a new `UNICORN_CLOAK_DEBUG` env var
(separate from the existing, narrower `UNICORN_CLOAK_DEBUG_AUDIO`) before
doing anything else:
  - Sets `QT_LOGGING_RULES=qt.qpa.*=false` (must happen before
    `QApplication` exists to reliably cover a logging category's first
    use) -- silences the portal-registration line.
  - Wraps `QApplication(sys.argv)` construction itself in a new
    `_suppressed_native_stderr()` context manager, which redirects the
    process's real stderr file descriptor (not just Python's own
    `sys.stderr` object) to `/dev/null` for that one call -- the libssh/
    GIO lines are written by native code during Qt's platform-plugin
    loading, bypassing Python's stderr entirely, so nothing reachable
    from Qt's own logging or Python's `warnings`/`logging` modules could
    have caught them. Scoped tightly around just that one constructor
    call, not the whole process, so a real crash afterward still reaches
    the terminal.
  - `UNICORN_CLOAK_DEBUG=1` restores both. Verified live (not just in
    the offscreen test suite) with real `python -m unicorn_cloak` runs,
    piped to a log file with `PYTHONUNBUFFERED=1`: default run shows only
    the three expected startup lines (Loaded avatar/Window title/Press
    Escape), debug run shows the full original noise, proving the gate
    actually works both ways rather than just suppressing everything
    unconditionally.

**Collapsible-section splitter bugs, 2026-09-17, owner's request**
("all tabs: when all items collapse they jump to vertical center... they
should peg to the top" / "when expanding all, if that makes the column
longer than the window it changes the window size... instead it should
collapse something else and not change the window size"). Both
reproduced empirically first, with real geometry/size numbers, not
assumed from reading the code:
  - **Collapse-all "jumps to center"**: only reproduced starting from a
    tab that had previously been *expanded* first, not a fresh
    never-touched one -- `QSplitter` caches each pane's last-negotiated
    pixel size across calls, even after a child's sizePolicy/sizeHint
    changes underneath it, so collapsing every section right after
    expanding them left the splitter still holding each pane's old,
    larger allotment; each now-tiny collapsed header ended up centered
    within its own stale, oversized slot instead of pegged to the top of
    a freshly-sized one (confirmed via `splitter.geometry()`: y=9 on a
    fresh collapse, y=270 after a prior expand, same tab, same sections).
    Fixed with a `CollapsibleSection.collapsed_changed` signal (new,
    fires on *every* real state change, unlike the header QPushButton's
    own `toggled`, which `set_collapsed()` deliberately blocks to avoid
    a spurious emission during persisted-state restore) that
    `ControlPanelWindow` uses to force a fresh `splitter.setSizes(...)`
    after any change -- each collapsed pane's real `sizeHint()`, and
    `QWIDGETSIZE_MAX` for every expanded one, so Qt recomputes
    proportions from scratch instead of reusing stale ones.
  - **Expanding overflow grows the window**: confirmed the mechanism
    directly -- `panel.minimumSizeHint()` jumped from 756px to 943px tall
    after expanding every section on the Behavior tab, with nothing (no
    scroll area) absorbing that demand, so Qt grows the real top-level
    window to satisfy it. Rather than adding a scroll area (a bigger,
    riskier change than asked for), implemented exactly what the owner
    described: expanding a section now auto-collapses another section in
    the *same* splitter first if the new total no longer fits the space
    already available (measured via `splitter.height()` *before* Qt
    re-lays-out for the just-applied change, so it's still the old,
    un-grown figure) -- repeating if one collapse isn't enough, giving up
    rather than looping forever once nothing's left to collapse. Verified
    live: expanding Position & Hierarchy on the Behavior tab
    auto-collapses Motion, `minimumSizeHint()` stays exactly 756px both
    before and after, real screenshot confirms no window growth and
    correct top-pegged layout.
  - Two new regression tests in `test_control_panel_window.py`
    (`test_collapsing_every_section_stays_pegged_to_the_top_even_after_a_prior_expand`,
    `test_expanding_a_section_auto_collapses_a_sibling_instead_of_growing_the_window`).
    **341 tests total.**

**Follow-up: collapse-all still centered in one case, plus CLI not
exiting, 2026-09-17, owner's reports** ("stuff is still jumping to
center when collapsed, the behavior tab started all collapsed &
centered, all other behaved well until all were collapsed" / "the app
*seems* to be quitting properly but the cli launcher is not exiting").
Both re-reproduced empirically before changing anything, since the
previous round's fixes had already landed and clearly weren't the whole
story:
  - **Splitter centering, the real root cause this time**: the previous
    fix (resyncing each pane's own `sizes()`) addressed a real but
    *different* bug -- it didn't touch what was actually observed here.
    Traced with direct geometry printouts before vs. after switching to
    an affected tab: the per-tab *splitter widget itself* had correct
    internal pane proportions the whole time, but once every child
    collapses, the splitter's own effective `maximumHeight()` shrinks
    (children all move to `QSizePolicy.Maximum`), and a plain
    `QVBoxLayout` with no alignment set **centers** a child that can't
    grow to fill its allotted space rather than pegging it to the top --
    confirmed by the splitter's own geometry going from `y=9` to `y=270`
    depending only on whether the affected tab had actually been
    switched to yet (QTabWidget only does a real layout pass on the page
    that's actually visible, which is why "a fresh, never-shown tab"
    didn't reproduce it, but "started all collapsed" and "switched to
    it" both did). Fixed with one line per tab --
    `outer.setAlignment(splitter, Qt.AlignmentFlag.AlignTop)`, via a new
    `_add_tab_splitter()` helper used by all four `_build_*_tab()`
    methods -- which is a no-op whenever the splitter *can* fill the
    available height (any section expanded), so the normal, mostly-
    expanded case is untouched. One new regression test,
    specifically switching tabs after construction (not toggling live),
    since that's what the previous round's tests didn't cover:
    `test_a_tab_that_starts_fully_collapsed_from_persisted_config_stays_pegged_to_top`.
  - **CLI hang on quit**: reproduced the full quit flow end-to-end
    (`main()`, a simulated Quit-button click, `confirm_and_quit`) with
    real audio/OBS access stubbed out -- came back clean in 0.67s,
    proving the hang isn't in this app's own Qt/window shutdown code at
    all. Traced it to `sounddevice`'s own `atexit`-registered
    `_exit_handler()` (read directly, not assumed), which
    unconditionally calls PortAudio's global `Pa_Terminate()` during
    normal Python interpreter shutdown -- and that same file's own
    upstream comment admits outright that "portaudio hangs when calling
    close()" under some conditions. The owner's real trigger: OBS open
    at the same time, sharing the same mic on the same JACK graph
    (PipeWire's JACK-compat layer) -- multi-client JACK teardown
    contention is a known class of PortAudio hang, and it fires *after*
    this app's own already-correct `Microphone.stop()` cleanup
    (`stream.abort()`/`stream.close()`), not because of anything wrong
    with it. Fixed in the `if __name__ == "__main__":` block: flush
    stdout/stderr, then `os._exit(exit_code)` instead of `sys.exit()` --
    skips every registered `atexit` handler entirely (including
    sounddevice's), safe specifically because `on_quit()`
    (`app.aboutToQuit`) already ran and saved everything that matters
    *before* `app.exec()` even returns. Verified the mechanism live via
    a subprocess run of the real quit flow (`main()` returns, then the
    exact same flush+`os._exit()` sequence terminates the process
    immediately, confirmed by a line placed after it never printing) --
    the actual JACK/OBS-contention hang itself couldn't be reproduced in
    this sandbox (no real audio hardware here, and instructed not to
    touch the owner's live OBS session), so this fix is verified by
    mechanism and live smoke-test, not by reproducing the original hang
    symptom directly. **342 tests total** (no new test for the `os._exit`
    change itself -- it's `__main__`-guarded process-exit behavior,
    outside this suite's established in-process test pattern, and would
    need its own subprocess-spawning harness to test meaningfully).

**Over-eager auto-collapse fix + auto-expand assignment sections on
select, 2026-09-17, owner's reports** ("now you can only have one
section open at a time which is also not great... only force a single
unit to collapse if and when it would over-flow the window/panel
boundaries" / "when clicking on a sprite, it should auto-populate it's
state/expression assignments if it has any"):
  - **Auto-collapse was over-triggering.** Root cause, found by measuring
    real `minimumSizeHint()` numbers side by side rather than guessing:
    `_make_room_if_needed` measured "available space" as the *splitter's
    own* height, but that height itself shrinks (via the AlignTop fix
    from the previous round) whenever nothing inside it is expanded --
    so the very first expand from an all-or-mostly-collapsed tab read a
    stale, much-too-small budget and collapsed a sibling that was never
    actually needed, and each subsequent expand kept doing the same
    thing, leaving only ever one section open. Fixed by measuring against
    the tab *page*'s own height instead (assigned directly by
    QTabWidget, unaffected by the splitter's own size fluctuations).
    Verified with real numbers: Motion (361px) + Position & Hierarchy
    (253px) + collapsed Animation (34px) + handles (8px) = 656px against
    a genuine 633px budget -- correctly still collapses Motion first --
    but expanding a *second* section afterward (Animation, on top of an
    already-expanded Position & Hierarchy) no longer force-collapses
    anything, since both genuinely fit together once Motion's already
    out of the way. New regression test:
    `test_expanding_a_second_section_that_still_fits_does_not_force_further_collapses`.
  - **Selecting a sprite now auto-expands State Assignment/Expressions**
    when it actually has something tagged -- the fields themselves were
    already being populated silently either way
    (`_load_property_form`), but that's easy to miss if the section
    happens to be collapsed (including by this app's own auto-collapse
    behavior above). Only expands a section that has something to show
    for *that* sprite specifically: State Assignment opens whenever
    Group name is set at all, Expressions opens only when the sprite is
    also Manually driven with both Group name and State name set (i.e.
    it would actually show a toggle there) -- clicking a plain, untagged
    sprite (hair, body, etc.) leaves sections exactly as they were, not
    forcing them open for nothing. Two new regression tests
    (`test_selecting_a_tagged_manually_driven_sprite_expands_state_and_expressions`,
    `test_selecting_an_untagged_sprite_leaves_collapsed_sections_alone`).
    **345 tests total.**

**Committed to git + docs reorg + default avatar replaced, 2026-09-17,
owner's request** ("i have one or two more iterations... but for now..
let's replace our default model!... but first, it looks like you
haven't been committing on a regular basis, please make sure everything
is committed.. and move all the cloak related docs into
unicorn-cloak/docs/... when we're done i'll be moving it out to it's
own repo" + a follow-up: "wire that new model all up w/all the
behaviors, etc.."):
  - **Housekeeping first, as asked.** This folder had been untracked
    inside the `obs` repo the whole time (a deliberate earlier choice,
    documented in this file's own "Open questions" section) -- the
    owner's own git-conventions rule for `obs` ("commit and push at the
    end of every meaningful iteration, without waiting to be asked")
    was never actually being followed for anything under here. Moved
    `PLAN.md` to `docs/PLAN.md` (this file), added a local
    `.gitignore` (personal `settings.json`, `.pytest_cache/`,
    `*.egg-info/` -- `.venv/`/`__pycache__/`/`*.bak` were already
    covered by the parent repo's own root `.gitignore`), fixed every
    internal `PLAN.md` cross-reference to the new path, and committed
    the whole app in three commits (the app itself; the new default
    avatar, below; a small doc-link fix in the parent repo's own
    README.md/CLAUDE.md) -- then pushed, per that same standing
    convention.
  - **Default avatar replaced** with a new asset set the owner built,
    `assets/unicorn-demo/` (17 production PNG layers, each the same
    1216×1296 canvas per its own `README.txt`, plus two reference-only
    images) -- assembled into `unicorn-demo.uc` by a one-off build
    script (not committed -- see `persistence.save_avatar`/`rig.Sprite`
    directly for the actual shape) and set as `DEFAULT_AVATAR_PATH`.
    That constant was also made package-relative
    (`Path(__file__).resolve().parents[2] / "assets" / ...`, matching
    `DEFAULT_STATE_PATH`'s own existing pattern) instead of an absolute
    path under `/home/jj/projects/...` that only ever existed on this
    one machine -- worth fixing now specifically because this folder is
    headed for its own repo, where that path would have been dead on
    arrival for anyone else (or even this owner, post-move).
  - **Fully wired, not just swapped in as a flat image stack** (the
    owner's explicit follow-up ask) -- every layer got real
    Group/State/Talk/Blink tagging, not left blank the way the
    *previous* default avatar actually was (checked directly: its own
    `.save` file has `groupName`/`stateName` empty on every sprite,
    despite the app fully supporting them since 2026-09-16). Mouth
    (Group "Mouth"): Closed gated `TALK_QUIET_ONLY` ("Only when quiet",
    not `0`/"Always visible" -- the exact bug this value exists to
    prevent, per `motion.py`'s own docstring), two Slight Open and two
    Wide Open sprites as alternating Variant pairs. Eyes (Group "Eyes"):
    real ambiguity here, genuinely asked rather than guessed (four PNGs
    -- regular/open/squint/closed -- with no single obviously-correct
    mapping to the app's two-band blink model) -- owner's answer: Open +
    Squint alternate as the two "eyes open" Variants (confirmed this
    exactly matches both `motion.py`'s own docstring example *and* the
    previous default avatar's real `.save` content, `eyes-open-wide-01`
    paired with `eyes-squint-01`, found by reading it directly rather
    than assumed), Closed is the mid-blink frame, Regular became a
    Manually-driven expression instead. Hoodie/vest costume slots
    (slot 1/2) using the existing costume-layer system, matching the
    two alternate outfits the asset set actually provides -- hoodie
    default, matching the asset set's own `preview_hoodie.png`
    reference exactly; the bare-torso layer shows only under the vest.
    Verified zero `rig_lint` issues and with real renders of both
    costumes, quiet/wide talk states, the blink frame, and the manual
    expression -- not just "it loads without crashing."
  - `test_rig_lint.py`'s own end-to-end sanity test against "the real
    default avatar" now actually runs instead of skipping (the file is
    in the repo, not owner-machine-only) -- renamed and re-commented to
    match, since it was still named/worded around the *previous*
    default avatar's own now-superseded bug fix.

**Third avatar (bugged-out-nerd) built + eyes fix applied to both new
avatars, 2026-09-17, owner's request** ("i also have a whole new set of
assets for one we'll call 'bugged-out-nerd.uc'... land the uc file for
that one right there with its assets" -- landed at
`/home/jj/projects/bon/images/avatar-animated/`, personal content, not
in this repo, same treatment as avatar-01). Same asked-not-guessed
approach for its own genuine ambiguity (this asset set has *three*
open-eye candidates -- normal/wide/squint -- plus an asymmetric wink
that can only ever be manual): owner picked wide+squint as the automatic
pair, normal manual, mirroring the answer given for unicorn-demo.
  - **Both answers turned out wrong, and the owner caught it**: "we
    previously had the eyes just right... mostly open, squinted
    sometimes, blinked sometimes... that's not how they are now? you
    asked the same question for each but didn't get it right... our
    presently-loading-on-default model probably has it right, i don't
    think we've touched that one... and that was before we designed the
    'expressions' feature." "Presently loading" was the key clue: the
    owner's real `settings.json` still points at avatar-01 directly
    (`DEFAULT_AVATAR_PATH` is only the fallback when no path is already
    set, so swapping it to unicorn-demo never touched what their actual
    running app loads) -- confirmed avatar-01's own real `.uc` is
    genuinely untouched (only Group/State tags were added to it earlier
    today, never talk/blink/variant/manual values) and predates
    Expressions by definition: its Eyes group is just two automatic
    variants (wide + squint) alternating under "Only eyes open", *no*
    manual-only sprite at all. Both new avatars' question framing had a
    real flaw: pulling the plain, default-looking sprite (regular/
    normal) out to Manually-driven, keeping only the more exaggerated
    look (open/wide) in automatic rotation -- meaning the avatar never
    showed its plain resting look at all outside a manual trigger, only
    ever "excited" or "squinting". Fixed both by swapping which sprite
    is automatic vs. manual: the plain sprite (regular/normal) is now
    the Variant-0 automatic partner for Squint (matching avatar-01's own
    pairing shape), the more exaggerated one (open/wide) becomes the
    Manually-driven expression instead -- Expressions itself wasn't the
    mistake (the owner confirmed it's a real, intentionally-designed
    feature), just which sprite got assigned to it. Verified at the
    opacity level, not just visually, for both. Zero `rig_lint` issues
    on either file.
  - Also reported live in the same message, not yet resolved: the mic
    stopped driving the avatar with OBS open (previously worked), and
    quitting crashed the whole process --
    `Expression 'result' failed in 'src/hostapi/jack/pa_jack.c', line:
    1703`. Real PortAudio/JACK-hostapi crash, not a Python exception --
    see this file's own next entry once that's actually investigated,
    not guessed at from here.

**Quit-crash root-caused and fixed; mic-dropout investigated but not
conclusively resolved, 2026-09-17, same owner report.** Confirmed this
machine's actual audio setup first, not assumed: no real `jackd` running
-- `pipewire-jack-audio-connection-kit` provides `libjack.so.0` as a
PipeWire-backed JACK-compatible shim, and PortAudio's JACK hostapi device
list (`sd.query_hostapis()`) showed OBS's own nodes ("OBS", "OBS-Monitor")
sitting on the *same* graph as this app's own mic device -- confirming
the multi-client JACK contention theory from earlier today, not just
plausible-sounding guesswork.
  - **Root cause of the crash, and why the earlier `os._exit()` fix
    didn't cover it**: that fix only skips Python's `atexit` handlers
    (specifically `sounddevice`'s own, which calls `Pa_Terminate()`) --
    but this crash happens *before* that code ever runs, synchronously
    inside `Microphone.stop()`'s own `stream.abort()`/`stream.close()`
    calls, called from `on_quit()` while `app.exec()` is still running.
    A hard C-level assertion inside PortAudio's own JACK hostapi isn't a
    Python exception, so no `try`/`except` here could ever have caught
    it regardless of where it was placed.
  - **Fix**: `Microphone.stop()` gained an `abandon` parameter -- when
    True, skips the `stream.abort()`/`close()` calls entirely rather
    than attempting-and-ignoring-exceptions (never actually an option
    for a C-level abort). `AudioManager.shutdown()` is the *only* caller
    that passes `abandon=True`, since it's the only one always
    immediately followed by the whole process `os._exit()`ing -- every
    other caller (switching sources mid-session, the app continuing to
    run) still gets the real, full teardown, since those genuinely need
    the device released. Two new tests directly on `Microphone.stop()`
    proving the calls are actually skipped vs. actually made
    (`test_microphone_stop_abandon_skips_stream_teardown`,
    `test_microphone_stop_without_abandon_still_tears_down_the_stream`),
    plus one on `AudioManager` proving only `shutdown()` passes
    `abandon=True` while a live source switch does not
    (`test_shutdown_abandons_the_microphone_but_switching_sources_does_not`).
    Three existing hand-rolled `Microphone` test fakes needed their own
    `stop()` signature updated to accept the new keyword -- caught by the
    full suite, not missed.
  - **Mic-dropout, honestly unresolved**: checked for an obvious
    lingering cause -- no stale `unicorn_cloak` process, no obviously
    stuck PipeWire node (the real mic source showed `SUSPENDED`, i.e.
    idle, not stuck) -- found nothing conclusive. Best working theory,
    not confirmed: a previous crash-corrupted JACK client registration
    for this app's own stream, which the crash fix above should prevent
    from recurring, but this is a hypothesis to be confirmed by the
    owner actually re-testing with OBS open, not a verified fix in its
    own right. Could not reproduce the live multi-client contention
    condition in this environment to test more conclusively.

**Scale feature added to Position & Hierarchy, 2026-09-17, owner's
request** ("to make it up to me, you can add scale features to the
positioning section...w/a lock toggle (on by default) that scales x & y
maintaining proportions"). `Sprite` gained `scale_x`/`scale_y` (default
1.0) as a *static, authored* size multiplier -- distinct from the
existing `stretch_amount`, which is *reactive* and always returns to 1.0
at rest. The two combine multiplicatively in `render.py`'s transform
(`combined_scale = sprite.scale * runtime.scale`), so a permanently
resized layer still squashes/stretches normally around its own new size.
UI: two spinboxes plus a checkable "🔗 Lock proportions" button (checked
by default, following the existing Guide/Ghost checkable-QPushButton
convention rather than a QCheckBox) in the Positioning section -- when
locked, dragging either spinbox writes the same value to the other via
`blockSignals` to avoid feedback loops. The lock state persists in
`ControlPanelConfig.scale_lock_proportions` like the other UI toggles.
Persisted as `scaleX`/`scaleY` in the `.uc`/`.save` JSON, with old files
defaulting both to 1.0 on load. New regression tests across all four
layers: `Sprite` defaults (`test_rig.py`), save/load round-trip
(`test_persistence.py`), the combined static+reactive transform math
(`test_render.py`), and the lock-toggle linking + config round-trip
(`test_control_panel_window.py`). Full suite green at 359 tests.

Also answered the owner's Position-vs-Offset question (asked in the same
message): per `rig.py`'s own transform-hierarchy docstring, Position is
the pivot point that parenting/rotation/stretch center on, while Offset
shifts the artwork away from that pivot *without* moving the pivot
itself -- they only produce visibly different results once a sprite also
rotates or stretches reactively and needs a pivot away from its own
visual center (e.g. a limb hinging at a joint). None of the three real
avatars built so far exercise that combination, which is exactly why
Offset has looked redundant with Position in practice. Recommendation
given to the owner: keep it in the data model/persistence for backward
compatibility and future reactive-limb work, but it's a legitimate
candidate to hide from the UI by default if it stays unused.

---

## 0. What we're actually replacing

Read in full before drafting this: `main_scenes/main.gd`, `autoload/global.gd`,
`autoload/saving.gd`, `autoload/defaultAvatarData.gd`, `main_scenes/ControlPanel.gd`,
`main_scenes/MicInputSelect.gd`, `main_scenes/EditControls.gd`,
`ui_scenes/VolumeBar.gd`, `project.godot`. ~2,600 lines of GDScript across 24
files, Godot 4.1.2, per-pixel-transparent viewport (`window/size/transparent=true`,
`per_pixel_transparency/allowed=true`).

**Feature inventory (reference for what this kind of tool needs to do —
not a checklist to match; see "goal" above):**

- **Window/capture:** borderless, per-pixel-transparent, resizable window;
  size persisted across launches. Control-panel chrome auto-hides on OS
  focus-loss (`NOTIFICATION_APPLICATION_FOCUS_OUT`) so OBS's window capture
  only ever sees the avatar, never the editor UI — this is the load-bearing
  trick that makes a single window work for both editing and streaming.
- **Rig model:** a tree of sprite nodes, each with: position, offset,
  z-index, drag speed (spring-lag "follow" motion when a parent moves),
  rotational drag + min/max rotation limits, idle sway (independent x/y
  sine frequency + amplitude), sprite-sheet frame count + animation speed,
  stretch amount, an "ignore bounce" flag, and a "clipped" flag.
  Parent→child linking drives secondary motion (e.g. hair follows head).
- **State-driven visibility, not just poses:** each sprite carries a
  talk-state (0/1/2, mouth shapes), a blink-state (0/1/2, eye shapes), and
  an 8–10 slot "costume layer" bitmask — the same physical sprite tree
  produces different visible outfits depending on which costume number is
  active.
- **Reactive motion:** a single "speaking" boolean (volume above a smoothed
  sensitivity threshold) drives a vertical bounce-and-settle impulse
  (velocity + gravity, not a canned animation). Blinking is an independent
  randomized timer (interval × chance-per-tick).
- **Audio:** live microphone capture, device enumeration/selection,
  volume + sensitivity sliders, and a **periodic forced mic
  reconnect** (`secondsToMicReset`, default 180s) — clearly a workaround for
  a driver/stream issue, not a feature; v1 should root-cause this instead of
  blindly porting the timer.
- **Costume switching:** 10 number-key hotkeys, remappable, no other input
  path in practice (Stream Deck support exists in the source via the
  `godot-streamdeck-addon` but — confirmed with the owner — no physical
  Stream Deck exists on this machine, so it's legacy dead weight, not a
  parity requirement).
- **Editor tools:** add / replace / duplicate / link (reparent) / unlink
  sprite; file-picker-driven import; a sprite list panel with per-sprite
  visibility toggles; on-canvas origin/alignment guide lines; zoom
  (ctrl+scroll); a scrolling toast/log of recent actions ("pushed
  updates"). No undo/redo anywhere in the original.
- **Persistence:** avatars save as a JSON blob that embeds each sprite's
  PNG bytes (base64) alongside its rig metadata — self-contained and
  portable, not just a set of file-path references. Separate app-level
  settings file (window size, last avatar, sliders, hotkeys, FPS cap,
  background color, texture filtering, bounce/gravity constants). A
  hardcoded default avatar ships in `autoload/defaultAvatarData.gd` — not
  carried forward; see the Default avatar decision below.
- **Naming/quality debt worth naming explicitly**, since it's the reason
  this plan exists: a UI-protection group is literally named `"penis"`, a
  dead-input signal is named `fatfuckingballs`, `swapMode()` doesn't say
  which modes, and several booleans/flags (`clipped`, `toggle`,
  `ignoreBounce`) are undocumented and only inferable from call sites.
  None of this carries forward.

---

## Guiding principles for all three phases

1. **User-facing vocabulary stays familiar** (avatar, sprite/layer, costume,
   hotkey) — owner already thinks in these terms from the legacy tool.
   "Proper terminology" means clean, documented *code* (module names,
   function names, a written data model), not renaming concepts the owner
   already knows.
2. **No scope creep per phase.** v1 does not get its final look. v2 does
   not get new rig capabilities beyond what fine-tuning requires. Each
   phase has an explicit non-goals list below.
3. **Root-cause, don't port, workarounds.** Anything in the legacy app that
   looks like a workaround for a bug (the mic-reset timer is the clearest
   example) gets investigated, not copied.
4. **Everything stays capturable by OBS exactly the way things are captured
   today** — a window/portal source, no OBS-side reconfiguration required
   beyond possibly re-picking the window once at cutover.
5. **Take the family conventions from `unicorn-viz`** (same owner, same
   machine, same OBS-adjacent Python-on-Linux problem space): TOML config,
   `pyproject.toml` + pinned `requirements.txt`, a real `tests/` directory,
   its own `CLAUDE.md` once this becomes a real working area, `sounddevice`
   + `numpy`/`scipy` for audio capture/FFT (same libraries it already uses
   — not a code dependency between the two projects, just the same proven
   approach on this exact machine).

---

## Architecture decisions (locked in for v1)

| Decision | Choice | Why |
|---|---|---|
| Language/runtime | Python 3.11+ | Owner's call; matches `unicorn-viz` on this machine. |
| Render-window toolkit | **PySide6 (Qt6)** | Owner's call over pywebview. Qt has proven per-pixel-transparent, frameless windows on Wayland/GNOME, and `QGraphicsScene`/`QPainter` is a good fit for a layered-sprite compositor with per-item transforms and animation. |
| Control-panel toolkit | PySide6 as well, in v1 | One toolkit, one codebase, lowest v1 risk. Re-skinned in v2 (see below) — not rebuilt in a different framework. |
| Stream Deck | **Dropped for v1.** No hardware exists. Revisit only if the owner acquires one; `python-elgato-streamdeck` exists if/when that happens. | Confirmed with owner. |
| Audio capture | `sounddevice` + `numpy` (mirrors `unicorn-viz`'s proven approach on this machine) | Avoids reinventing device enumeration/FFT plumbing that's already solved and tested next door. |
| Config format | TOML (`config.toml`, mirrors `unicorn-viz`) | Human-editable, diffable, consistent with the sibling project. |
| Avatar save format | JSON, self-contained (embedded PNG bytes + rig metadata), same shape as the legacy `.save` format | Not a legacy-compatibility feature — the owner's real starting content (`unicorn-tears-avatar-01-hoody-hair-aviator-bling.save`) already exists in exactly this shape, so the loader has to speak it regardless. Cleanly typed via dataclasses on read instead of loose dicts. |
| Window model | **Confirmed: two windows.** A permanently-transparent **Render Window** (the only thing OBS ever targets) and a separate **Control Panel** window that never needs to hide itself. | Owner approved. More robust than the legacy focus-loss-hide trick; costs one OBS source re-pick at first launch. |
| Default avatar | `/home/jj/projects/unicorn-tears/images/animated-avatar/avatar-01/unicorn-tears-avatar-01-hoody-hair-aviator-bling.save` — the owner's real DJ-persona rig (hoody, spiky hair, aviator shades, bling, 3 mouth states), loaded directly from that path, not copied into `unicorn-cloak/`. | Nothing from PNGTuber-Plus's own bundled default (the little creature in `defaultAvatarData.gd`) carries forward — confirmed dropped entirely. Referencing the file in place matches the "media stays where it is" convention already used in the `obs` repo; revisit only if the owner wants it copied in for portability. |

---

## Phase 1 (v1) — Rewrite

**Goal:** a clean, fully-working app that's *better and unique*, not a
clone. The legacy feature inventory above is a starting reference for
what an avatar-overlay tool needs to do, not a spec to match — dropped as
an explicit target 2026-09-15 (owner's call: "our goal is really *better*
and *unique*"). Plain/functional UI is fine for this phase. OBS reads it
the same way it reads the current app.

**Non-goals:** brand styling, animation polish, plugin architecture,
packaging/distribution, anything from v2/v3.

### Milestones

1. **[DONE 2026-09-15] Spike: de-risk the transparent window before
   building anything on top of it.** A bare PySide6 window with `Qt.FramelessWindowHint` +
   `WA_TranslucentBackground`, one test sprite, added as an OBS window
   capture source on this exact machine (Fedora 44, GNOME/Wayland,
   PipeWire portal). Confirm: true per-pixel alpha in the captured frame,
   acceptable idle CPU, and how the portal picker behaves for this window
   (expect the "pick this window" prompt once, same caveat that applies to
   any new capture source per CLAUDE.md's screen-capture note). This
   milestone gates everything else — if Qt transparency doesn't hold up
   here, we stop and re-decide the toolkit before writing rig code.
2. **Rig model + renderer.** Dataclasses for the sprite tree (position,
   offset, z, drag speed, rotational drag/limits, sway freq/amp, frames,
   anim speed, stretch, talk-state, blink-state, costume mask). Pure
   functions for the motion math (bounce/gravity, sway, drag-follow,
   blink timer) with unit tests — this math was previously buried in
   `_process()` callbacks with no tests at all.
3. **Audio reactivity.** Device enumeration/selection, volume + smoothed
   sensitivity, threshold-crossing speak/stop events. Investigate the
   actual cause of the legacy 180s mic-reset workaround (likely a
   `sounddevice`/PortAudio stream that silently stalls) and either fix it
   properly or, if a periodic reconnect genuinely is the correct mitigation
   for a real driver quirk, document why with a comment — not silently
   copy the number.
4. **[DONE 2026-09-16] Costume + hotkeys.** 10 remappable costume
   hotkeys, no Stream Deck. **Global** (works-while-another-app-has-focus)
   hotkeys were explicitly dropped, not deferred — owner's call: too
   likely to collide with whatever else already claims the same key
   system-wide. Costume hotkeys are focus-only and remappable from
   Settings (see PLAN.md's dated entry).
5. **Editor UI.** Add/replace/duplicate/link/unlink [DONE], sprite list
   with visibility toggles [DONE 2026-09-16] and origin guides
   [DONE 2026-09-16], undo/redo [DONE — cheap to include, painful to
   retrofit, a real usability gap in the original]. **Still open:**
   canvas zoom/pan, multi-select, and an action-log toast panel — see
   the top status paragraph, last refreshed 2026-09-18.
6. **[DONE 2026-09-16] Persistence.** Save/load in the self-contained JSON shape described
   above. No legacy-avatar migration tool — nothing from PNGTuber-Plus is
   being carried forward. Ship
   `unicorn-tears-avatar-01-hoody-hair-aviator-bling.save` as the bundled
   default and prove the loader round-trips it exactly (load → re-save →
   diff). Note while testing: this rig currently has no blink-state
   sprites (`showBlink` is 0 on every layer — `eyes-closed-01.png` etc.
   exist in `src/` but aren't wired into the save yet) and all 10 costume
   slots are identical (`costumeLayers` is `[1]*10` on every layer, and
   the alternate clothing in `src/` — jacket, vest, tux, visor — isn't
   assigned to a slot). Both are content gaps in the source file, not
   bugs in the loader; don't chase them as regressions.
7. **[DONE 2026-09-16] Cutover check.** Render Window captures cleanly
   as an OBS window/portal source with the avatar-01 rig live -- owner's
   own words, "render capture is super clean." The portal
   re-pick-on-relaunch behavior was also checked (see the Wayland/portal
   entries above) and turned out to be an ordinary, unfixable-from-here
   GNOME portal limitation, not a capture-quality problem. Owner
   confirmed PNGTuber-Plus deprecation is final: "this is hot garbage!
   ... done & dusted." `~/Repos/pngtuber-plus` and the Godot install are
   left on disk, untouched, not deleted (removal wasn't asked for) --
   see `decisions/0001-avatar-lipsync-tooling.md` (moved here 2026-09-18
   from the parent `obs` repo's `docs/decisions/0004-...`) and the `obs`
   repo's own `README.md` changelog for the parent-repo side of this
   record.

---

## Phase 2 (v2) — GUI overhaul, style, optimization, fine-tuning

**Goal:** looks and feels like a real Unicorn Tears / Unicorn Viz family
product, runs efficiently enough to leave on for an entire stream without
thinking about it, motion feels tuned rather than default.

**Style source:** `/home/jj/projects/unicorn-tears/claude-design-system`.
That system is React/JSX + CSS custom properties (`tokens/colors.css`,
`tokens/typography.css`, `tokens/spacing.css`) — it can't be imported
directly into a Qt app. v2 **ports the tokens**, not the components: pull
the actual hex values, type ramp (`Anton` display / `Space Grotesk` UI /
`JetBrains Mono` for anything HUD-like — hotkey tables, the action log),
and spacing scale out of those CSS files into a generated QSS stylesheet +
a small set of custom-painted Qt widgets for the things CSS can't do
(neon glow strokes, the magenta→violet→cyan gradient on primary
actions/dividers). This keeps the two apps visually related without
depending on a web stack.

**Non-goals:** new rig capabilities beyond what "fine-tuning" motion
requires; plugin architecture; its own repo/packaging (that's v3).

### Milestones

1. **[DONE 2026-09-16] Design token port.** Colors/type/spacing → QSS + a small `theme.py`.
   See PLAN.md's dated entry for what's actually covered and what's
   deliberately excluded (the Render Window).
2. **[Partially done] Control panel re-skin.** Grouped sections
   [DONE, already true since Settings/Editor were first built --
   `QGroupBox` per section] and a keyboard-shortcut reference view
   [DONE via the Help window, added 2026-09-16]. **Not done, and
   deliberately not attempted unsupervised 2026-09-16:** numeric fields
   alongside sliders (Settings is numeric-only today, no sliders exist
   at all -- adding a slider next to all 16+ tunables is a real UX/visual
   judgment call, not something to guess at without the owner looking at
   it) and drag-and-drop layer reordering (Move Up/Move Down already
   work correctly as of the 2026-09-16 bugfix; real drag-and-drop is
   riskier to get right blind, since QListWidget's built-in reorder mode
   is known to interact awkwardly with the custom per-row eye-icon
   widgets already in place -- also flagged for a visual check, not
   attempted speculatively).
3. **[DONE 2026-09-16] Live capture preview.** A thumbnail in the
   control panel showing exactly what the Render Window currently looks
   like, with an explicit on/off toggle (owner's request). See the dated
   entry below for how it's actually implemented (shares the Render
   Window's own `QGraphicsScene` -- no manual redraw loop).
4. **[Investigated 2026-09-16 in two passes, three real fixes landed,
   not fully closed] Performance pass.** See the two dated entries
   below (the first with `gdb`/`ps -T`, the second with a proper `perf`
   sampling profile the owner approved installing) for the full
   investigation, including a real live bug caused and fixed while
   profiling. Three concrete, measured, verified fixes landed: redundant
   per-frame `QTransform` calls on sprites that never rotate/stretch
   (render.py), and two numpy inefficiencies in the audio thread's
   per-block processing that `perf` proved were the actual largest
   costs (`rms_volume` 4.3x faster, the stereo-to-mono downmix 9.1x
   faster -- both measured, both mathematically identical results).
   **Still not claiming "near-zero idle CPU"** -- full-app CPU varies
   run to run even with a confound (a separately-running GPU-heavy
   visualizer) removed, and "confirm no frame drops in a real OBS test
   stream" still needs the owner; not attempted.
5. **[Audited 2026-09-16, effectively already done] Motion fine-tuning.**
   Checked every constant actually exercised by real content against
   what's exposed in Settings -- bounce strength/gravity/retrigger,
   blink speed/chance, mouth wobble freq/amp, and both variant-
   alternation rates are all already live-tunable. The remaining
   hardcoded constants in motion.py (rotation lerp factor, stretch blend
   factor, the blink timer's base-420-ticks constant) belong to
   rotation_drag_strength/stretch_amount, which no real sprite currently
   uses at all (confirmed while profiling, see below) -- exposing UI
   controls for a feature nothing uses yet would be speculative, not
   fine-tuning; left alone on purpose, matching this project's own
   standing "don't build for hypothetical requirements" rule.

---

## Phase 3 (v3) — World-class / production grade

**Goal:** the version worth open-sourcing next to `unicorn-viz`, if the
owner wants to go that far.

**Candidate scope (owner picks which of these actually matter before this
phase starts — this list is intentionally broader than one phase should
be):**

- ~~Better mouth-shape driver~~ — **done in Phase 1, 2026-09-15**, pulled
  forward: the avatar-01 art already has closed/mild/wide mouths and the
  owner wanted it working now, not in Phase 3. `audio.py`'s
  `update_speaking` is a proper RMS envelope follower (attack/hold/release
  in ms, a noise gate, independent open/close thresholds per band for
  hysteresis) driving a 3-level `talk_level`; `motion.axis_visible` reads
  it as an exact-band match rather than the old legacy binary
  active/inactive rule. All of it is live-tunable in the Settings window.
  Also added while in there: a periodic bounce re-trigger while
  `talk_level > 0` (continuous speech keeps the avatar bobbing instead of
  one impulse that settles), and an extra idle wobble on any sprite with
  a nonzero `talk_state` (any mouth-shape layer).
- **Input parity with `unicorn-viz`.** OSC and/or MIDI control surface
  using the same `python-osc` approach already proven there, so one
  control surface can drive both apps.
- **Alternate capture path.** An optional OBS Browser Source render mode
  (serve the render surface over local HTTP/WebSocket) as a fallback for
  setups where window/portal capture is inconvenient — this is the
  "browser-source instead of a native plugin" middle ground discussed
  earlier, and is a much smaller lift than a compiled OBS plugin.
- **Extensibility.** A drop-in style plugin model for new motion "drivers"
  or mouth-shape strategies, mirroring `unicorn-viz`'s own drop-in
  architecture.
- **Packaging & distribution.** PyInstaller/Briefcase build, versioned
  releases, and — only at this point — its own git repository, README,
  license, and CI, separate from this `obs` repo.
- **Test/docs/community polish** if it's going public: full test suite,
  contribution guide, accessibility pass.
- **Lock the shipped default avatar once it's finalized.** Owner, 2026-09-17,
  after seeing `unicorn-demo.uc` running: "this is the official app
  mascot!" -- once the owner is "done done" tweaking it, make the shipped
  default read-only in the app (Save As still works, plain Save onto the
  bundled file does not). Deliberately not done yet -- the owner is still
  hand-editing it directly (see the same date's hair-position tweak) and
  explicitly said this is a "when I'm done" step, not a now step.
- **Post-FX drop-in.** Owner, 2026-09-17: "put on our todo list - post fx
  drop-in (i'll do that around release time)." A plugin-style slot for
  post-processing visual effects on the rendered avatar (glow, chromatic
  aberration, etc. -- distinct from the Extensibility bullet above, which
  is about new *motion* drivers, not a rendering pass). Owner's own item
  to build, timed for around release -- nothing to design or implement
  here yet.
- **Independent costume toggles.** Owner, 2026-09-17, when asked to pick
  between "one look at a time" (built, see that day's dated entry) and
  independent per-hotkey on/off toggles that can combine freely (e.g. a
  hat and glasses toggled separately, at the same time): "do one look at
  a time, put combinations on later list." Bigger change than it sounds --
  replaces the single mutually-exclusive `active_costume` index with
  several simultaneously-active toggle states, and needs converting the 2
  real avatars that already use costumes (unicorn-demo, bugged-out-nerd)
  to whatever the new format ends up being.

**Zoom moved to Position & Hierarchy; image/video backgrounds added,
2026-09-17, owner's requests.** Two separate asks in the same session:

- "i think we should move zoom to the position panel" -- Zoom (a
  whole-avatar scale, `config.window.zoom`) moved from the Application
  tab's Display group into the Behavior tab's Position & Hierarchy
  section, in its own `QFormLayout` above the per-sprite fields.
  Deliberately kept out of `self.property_form`/`self._per_sprite_widgets`
  -- it's global, not tied to whichever sprite is selected, and must not
  get reloaded or disabled when switching sprites.
- "add, on the application/background feature... ability to add an image
  or video? should be easy to do the image, video might require weighty
  depends?" -- turned out video needed no extra dependency at all: PySide6
  already bundles its own self-contained FFmpeg-based Qt Multimedia
  backend (`libffmpegmediaplugin.so`, confirmed present in this project's
  own `.venv`), so `QMediaPlayer` + `QGraphicsVideoItem` work out of the
  box with zero new entries in `pyproject.toml`. Verified end-to-end with
  a real `ffmpeg`-generated test clip, not just import checks: it decodes
  and loops correctly under this same offscreen/headless setup.
  - `WindowConfig` gained `background_image_path`/`background_video_path`
    (separate fields, not one shared path, so switching the Background
    combo back and forth doesn't forget whichever file was chosen for the
    *other* mode) -- `background` itself gained `"image"`/`"video"` as
    two more values alongside the existing solid colors/transparent.
  - `render.py`: an image renders as a `QGraphicsPixmapItem` scaled to
    exactly fill the scene rect (a plain background brush can't be
    scaled); a video renders via `QGraphicsVideoItem` + a looping,
    force-muted `QMediaPlayer` (`QAudioOutput.setMuted(True)` -- this is a
    silent visual loop, same "never plays its own sound" rule as the
    audio-file playback path in `audio_manager.py`, regardless of the
    file's own audio track). Both sit at a fixed, far-negative `zValue`
    (`BACKGROUND_MEDIA_ITEM_Z = -100_000`) so they always stay behind
    every sprite without needing per-avatar tuning. A decode failure
    (`QMediaPlayer.errorOccurred`) or a bad image path both fall back to
    transparent, logged not raised -- consistent with how the rest of the
    app treats a bad settings.json value, and specifically because a
    missing codec on someone else's machine is a real possibility this
    app shouldn't crash over.
  - UI: Background combo gained "Image" and "Video" entries; a Browse…
    button and an elided file-path label (reusing the same
    `elide_path_middle` helper as the audio file picker) appear only in
    those two modes.
  - New regression tests across `render.py` (pixmap scaling math, muted/
    looping player construction, bad-path fallback, path persisting
    across a mode switch), `config.py` (save/load round-trip), and
    `control_panel_window.py` (Browse wiring, visibility toggling). Full
    suite green at 371 tests.

**Editor drag-to-scale/rotate; costume swap verified; Expressions
suppression bug fixed, 2026-09-17 -- owner's "three things...then we can
pretty much call it a wrap" list.**

- **Drag-to-scale/rotate on the edit canvas.** Drag-to-*move* already
  existed (`EditableSpriteItem`'s `ItemIsMovable`); this adds real corner
  and rotate handles, not just the Position & Hierarchy spinboxes. New
  `Sprite.rotation_deg` (static, authored -- same relationship to the
  existing reactive `rotation_drag_strength` as `scale_x/y` has to
  `stretch_amount`), persisted as `rotationDeg`, combined with the
  reactive rotation in `render.py` by addition (`sprite.rotation_deg +
  degrees(rt.rotation_rad)`) the same way scale combines by
  multiplication. A "Rotation (deg)" spinbox added to Position &
  Hierarchy alongside Scale.
  - `EditableSpriteItem` gained 4 corner handles + 1 rotate handle
    (drawn in `paint()`, replacing Qt's own dashed selection rect via the
    standard "paint with `State_Selected` cleared" pattern), hit-tested
    in local item coordinates. Key finding verified empirically before
    trusting it: a mouse event's `.pos()` on a `QGraphicsItem` is already
    inverse-mapped through the item's *current* transform, so the new
    absolute scale/rotation can be computed directly from the live mouse
    position every move event -- no incremental delta-tracking needed,
    and it stays correct even mid-rotation (confirmed with a throwaway
    scene script, not assumed from docs). Corner-drag scaling reuses the
    existing Scale-lock toggle (`scale_lock`) rather than a second lock
    concept, and clamps to positive-only scale (dragging past the origin
    no longer flips the sprite, matching the spinbox's own 0.01-100.0
    range). Found and fixed while wiring this up:
    `QGraphicsPixmapItem.boundingRect()` pads the pixmap rect by half a
    unit on every side (confirmed empirically -- a 100x100 pixmap at
    offset (-50,-50) reports as `(-50.5,-50.5,101,101)`), which silently
    threw off every corner-handle position and scale calculation until
    `_pixmap_rect()` was rewritten to build the rect directly from
    `offset()`/`pixmap().size()` instead of trusting `boundingRect()`.
  - Verified with a real rendered screenshot of the edit canvas (not
    just unit tests) that the handles actually draw where expected.
  - New regression tests: `rig`/`persistence`/`render` coverage for
    `rotation_deg` mirroring the existing scale tests, plus direct tests
    of `_handle_at`/`_drag_handle` (called as plain methods with a
    `QPointF`, not simulated through real Qt mouse events -- simpler and
    just as valid, since Qt's own event dispatch is what's responsible
    for turning a real mouse event into that same local `QPointF` in the
    first place).
- **Costume swap (hoodie -> vest) -- already fully wired, verified not
  rebuilt.** Owner asked to "wire up the costumes... swap hoody [both
  parts!] for vest and costume hotkeys," but this was already done in the
  original unicorn-demo build (see "Replace default avatar with
  unicorn-demo, fully wired" above): slot 0 shows both hoodie layers and
  hides the vest + bare-torso layer, slot 1 is the reverse, and costume
  hotkeys are generic (any avatar's `costume_layers` "just works" once
  authored). Confirmed live via direct simulation before reporting it
  back rather than assuming the commit message was still accurate, and
  pinned down with a new end-to-end regression test against the real
  shipped file (`test_the_real_default_avatars_costume_slots_swap_hoodie_for_vest`)
  so a future costumeLayers edit can't silently break it.
- **Expressions: a real suppression bug found and fixed, not just
  "wired."** `motion.sprite_alpha` decides each sprite's visibility
  independently and has no notion of "groups" (deliberate, per its own
  docstring) -- which meant turning on unicorn-demo's one existing
  expression ("Eyes: Open") while the automatic blink system had
  "Regular" showing left *both* eye sprites drawn opaque on top of each
  other. Confirmed with a direct opacity dump before touching any code,
  not assumed. Fixed in `render.py`'s `_apply_to_scene` (not
  `sprite_alpha`, to keep that function's own Qt/group-agnostic design
  intact): a non-manual sprite is now also force-hidden whenever its own
  `group_name` has an active override elsewhere, routed through the
  existing `hidden` parameter rather than a new one since it's exactly
  the same "always wins, ghosted in edit mode" treatment. Regression test
  extends the existing `test_manual_override_shows_only_the_matching_sprite`
  to also assert the automatic sibling's opacity (it wasn't being checked
  at all before, despite the automatic sibling already being right there
  in the test's own rig). How to actually use an expression, for the
  owner: Behavior tab -> Expressions section has one toggle button per
  tagged (Group, State) pair -- click to force it live on the real Render
  Window (and therefore OBS), click again to release it back to
  automatic. No hotkey binding exists for these yet (only costumes have
  one) -- flagged to the owner as an open question, not assumed either
  way.

**Costume/Expression hotkeys redesigned around explicit sprite-pair
assignments; Expression hotkeys added, 2026-09-17, owner's follow-up.**
Owner, on seeing the old numbered costume-hotkey list: "are the costume
hotkeys labeled with what they do? when i went in there i just saw a list
of numbers." Owner's proposed fix, generalized to Expressions too: a
number list where each slot has explicit dropdown-picked assignments
instead of an opaque index into a raw `costumeLayers` bitmask. Confirmed
with the owner up front which of two structurally different models to
build -- "one look at a time" (today's single mutually-exclusive
`active_costume` index, just a friendlier editor) vs. "independent
toggles" (any number of costumes on/off at once, a bigger change touching
all 3 real avatars' saved data) -- owner picked the former, deferring the
latter ("put combinations on later list", logged in Phase 3's candidate
list below).

- **New `AvatarRig.costume_assignments`/`expression_hotkeys`** (both
  `list[list[tuple]]`, one inner list per hotkey slot) are a pure
  *authoring* layer on top of the existing, unchanged
  `costume_layers`/`active_costume` engine -- adding a costume pair
  writes straight through to both sprites' `costume_layers` via the new
  `AvatarRig.assign_costume_pair`/`remove_costume_pair`, so rendering
  itself never needs to know this list exists and a file saved before
  this feature existed keeps working unmodified. Persisted as two new
  rig-level (not per-sprite) JSON keys, `__costume_assignments__`/
  `__expression_hotkeys__`.
- **A real semantic bug found and fixed before it shipped**: the first
  implementation of `assign_costume_pair` had hide/show backwards --
  `hide_id`'s sprite (meant to read "hidden by default, shown while this
  costume is active", per the owner's own wording) was being set to
  *hidden*, not shown, at the target slot, and `show_id` the reverse.
  Caught by working through the exact real migration this same entry
  describes below (unicorn-demo's already-correct real data has the
  vest/body layers visible *only* in slot 1) rather than trusting the
  first pass -- the bug would have made every new costume assignment
  backwards from what its own UI labels/tooltips said. Fixed in
  `rig.py`, with test assertions corrected to match.
- **UI**: the Application tab's "Hotkeys" section is now "Hotkeys —
  Costumes & Expressions" -- one number list per feature, each slot a
  dynamic set of rows (two sprite dropdowns for Costumes, one Expression
  dropdown for Expressions) plus a "+ Add" button. A row only becomes a
  real, saved assignment once fully filled in; clearing any part of an
  already-committed row removes it -- generalizes the owner's own
  described deletion gesture ("not assigning to first box but assigning
  the second box will simply remove the item") to "any incomplete row
  isn't a real assignment," which also covers clearing the *other* box,
  not just the first. Dropdown options and displayed rows fully rebuild
  from the rig's own data at the end of `_rebuild_scene()` -- one
  integration point covers load, undo/redo, and add/remove/duplicate
  sprite, since they all already funnel through it.
  - Found and fixed while building this: this section's own content (up
    to 20 slots' worth of dropdown rows) made the *whole panel's* minimum
    size balloon when expanded by default, since a `QTabWidget`'s overall
    minimum size is driven by its largest page regardless of which tab is
    active -- added to `ControlPanelConfig.collapsed_sections`' own
    default tuple (matching "Position & Hierarchy"/"Animation"'s existing
    entries) rather than left expanded.
  - `costume_assignments`/`expression_hotkeys` ride along in the same
    undo/redo snapshot as the sprite list now (`_snapshot`/`_restore`
    extended, `deepcopy` since they're lists of lists of tuples) --
    otherwise undoing a change that happens to revert a sprite's
    `costume_layers` would leave the assignment list stale, showing a row
    that no longer matches what the sprites actually do.
- **Expression hotkeys are Shift+1..Shift+9,Shift+0**, fixed (not
  user-remappable, unlike costume keys) and scoped to the *Control Panel*
  window, not the Render Window -- deliberately different from how
  costume hotkeys work, since Expressions are already configured and
  toggled entirely through Control Panel buttons today. Implemented as
  `QShortcut`s that `.click()` the exact same Expression buttons the
  Behavior tab's Expressions section already has (not a second,
  parallel toggle implementation), so a hotkey press and a real click
  always stay in sync automatically, including the existing "only one
  state per group" exclusivity.
- **Content migration**: unicorn-demo's and bugged-out-nerd's real,
  already-correct hoodie/vest and plaid/camo costume swaps existed only
  as raw `costumeLayers` data with no `costume_assignments` describing
  them, which would have shown as empty rows in the new editor despite
  already working. Backfilled both real files via
  `AvatarRig.assign_costume_pair` itself (not hand-edited JSON) and
  verified byte-for-byte that `costumeLayers` came out unchanged -- this
  only adds the new authoring metadata, never touches what's actually
  rendered. avatar-01 was checked too and has no costume-layer usage at
  all (predates the Expressions-era swap pattern), so nothing to migrate
  there.
- Full suite green at 409 tests, including new coverage across
  `rig.py`/`persistence.py`/`control_panel_window.py` for both editors,
  the undo/redo extension, the hide/show semantics themselves, and the
  Shift+number shortcut wiring.

**Costumes split into two columns; new Help "Hotkeys" tab; doc audit,
2026-09-17, owner's immediate follow-up.** "That made the window too
large vertical and it doesn't fit on screen, let's change the costumes
area to two columns of five costumes each" -- the 10-slot Costumes list
(each with its own multi-row swap editor) was still too tall as one
column even collapsed by default. Split into two `QVBoxLayout`s of 5
slots side by side inside a `QHBoxLayout`; Expressions (also 10 slots)
left as a single column for now since only Costumes was asked for, but
it has the identical height problem and is a likely next ask.

Also: "add a 'hotkeys' tab to the help menu and make sure all the
tooltips are up to date and none are missing." Audited every interactive
widget in `control_panel_window.py` (`QPushButton`/`QComboBox`/spinbox/
`QLineEdit`/`QKeySequenceEdit` construction sites) against a nearby
`setToolTip()` call -- all already covered, nothing missing there. The
real gap was in `help_window.py`'s prose, several tabs behind this
session's actual feature set:

- New `HOTKEYS_HTML` tab (Overview, Usage, Sprites, **Hotkeys**,
  Reference) -- the single source of truth for every keyboard/mouse
  shortcut and how to configure what each one does. Reference's own old
  one-paragraph "Hotkeys" section was cut down to a one-line pointer here
  rather than kept as a second, driftable copy.
- Flagged prominently, not just mentioned in passing: Expression hotkeys
  (Shift+number) only fire while the *Control Panel* has focus, not the
  Render Window -- a real, deliberate difference from costume hotkeys
  (see that feature's own dated entry for why: they click the Control
  Panel's own Expression buttons directly, to guarantee they can never
  drift out of sync with them). The Usage tab's "Go live" step used to
  say "the Control Panel can stay closed" unconditionally, which is now
  only true for costumes -- corrected there too, not just in the new tab.
- Reference tab's stale content fixed to match everything else built
  this session: "Costume layers" no longer says "needs a file edit for
  now" (it's the new editor); "Expressions" section now mentions the
  hotkey binding; "Position & Hierarchy" now covers Rotation/Scale/the
  Lock-proportions toggle/drag-to-scale-rotate on the canvas; "Application
  tab" now describes Background's Image/Video modes and Zoom's move to
  Behavior, and the renamed "Hotkeys — Costumes & Expressions" section.
- New/updated tests in `test_help_window.py` (tab count/order shifted to
  5, Reference's own content-check index updated, two new tests on the
  Hotkeys tab's content including the Control-Panel-focus caveat
  specifically, so it can't silently regress out of the docs again).
- Full suite green at 411 tests.

**Costumes/Expressions moved to their own tabs, immediately right of
Sprites, 2026-09-17, owner's immediate follow-up on seeing a screenshot.**
"That's horrible lmao... let's put costumes & expressions each in their
own tabs immediately to the right of the sprites tab." Two-columns-of-
five inside one collapsed Application-tab section was still an awkward
squeeze (see screenshot in that turn: cramped, key-capture boxes reading
"Press shortcut" mid-edit). New tab order: Sprites, **Costumes**,
**Expressions**, Behavior, Audio, Application.

- Each new tab wraps its grid in a `QScrollArea` (new to this app --
  `theme.py` already had an unused rule for it) instead of the previous
  "start collapsed" workaround. Verified directly, not assumed:
  `panel.minimumSizeHint()` measured byte-identical switched to the
  Sprites tab vs. the Costumes tab (622×702 either way) -- a
  `QScrollArea`'s own size hint doesn't grow with its content the way a
  plain nested layout's does, which is what actually caused the previous
  "every tab got taller" bug in the first place (`QTabWidget` sizes
  itself to its single largest page, and it doesn't matter which tab is
  currently showing). This also meant the sections no longer need to
  start collapsed by default -- removed "Hotkeys — Costumes &
  Expressions" from `ControlPanelConfig.collapsed_sections`' default
  without replacing it with the two new titles.
- Applied the two-column layout to Expressions too, proactively, not
  just Costumes as literally asked -- identical height problem, and the
  owner has asked for symmetric treatment between these two features at
  every step so far ("expressions could work the same way").
- Test fallout, all mechanical: `test_panel_has_exactly_four_tabs`
  renamed/updated to the new 6-tab order; several Behavior-tab tests that
  hardcoded `tabs.setCurrentIndex(1)` (assuming Behavior was tab index 1)
  switched to a new `_switch_to_tab(panel, name)` test helper that looks
  up the index by title instead, so tab reordering can't silently break
  them like this again; the stale "starts collapsed" test for the old
  section deleted outright (the section no longer exists).
- Help window's Hotkeys/Reference tabs updated to point at the new
  **Costumes**/**Expressions** tabs instead of "Application tab's
  Hotkeys section" everywhere that phrase appeared. Also caught and
  fixed a pre-existing, unrelated inaccuracy while in there: Reference
  said Expressions lived on "the Behavior tab" -- it's actually the
  Sprites tab (moved there in an earlier session, per that section's own
  comment in `control_panel_window.py`; the help text just never caught
  up).
- Full suite green at 410 tests.

**Costumes/Expressions single-column fix; Layer List given real room;
one-character settings.json repair, 2026-09-17, owner's screenshots of
the actual running app.** Two "this is horrible" reports, each with a
real screenshot -- diagnosed by reproducing against the owner's own real
avatar and real settings.json (a synthetic 4-sprite test rig at a
deliberately wide 1060px window had NOT caught either bug; only matching
the owner's real, narrower panel width and real long sprite filenames
did).

- **Root cause of the broken-looking Costumes/Expressions tabs**: the
  two-column layout put two full sprite-name dropdowns side by side per
  row (e.g. "clothes_hoodie_front.png (5)"), which needed more width than
  a realistic (non-maximized) panel actually has -- forcing an ugly
  *horizontal* scrollbar on top of the intended vertical one. Fixed two
  ways: (1) dropped back to a single column entirely -- the two-column
  idea only ever existed to save vertical space for the old, collapsed-
  by-default Application-tab section, and the `QScrollArea` from the same
  day's earlier fix already handles unlimited vertical content on its
  own, so columns weren't buying anything anymore; (2) capped every
  sprite/Expression dropdown's own natural width
  (`setSizeAdjustPolicy(AdjustToMinimumContentsLengthWithIcon)` +
  `setMinimumContentsLength(14)`) so a single long name can't blow out
  even a single-column row -- it elides instead, full text still visible
  via the open dropdown or hover tooltip.
- Verified visually against the real app afterward (`theme.apply()` +
  the real default avatar + the owner's actual narrow panel width, not
  the earlier synthetic repro) -- no horizontal scrollbar, no visual
  corruption, full sprite names readable.
- Caught two more stale "Behavior tab's Expressions" tooltip references
  while re-verifying (Sprites tab, not Behavior -- same mistake as the
  Help window text fixed earlier the same day) and fixed those too.
- **Layer List was cramped** ("super cramped @ around 2.75 [lines]") --
  it had no explicit minimum height, so it only ever got whatever
  leftover space State Assignment/Expressions didn't need on the same
  splitter. Given an explicit `setMinimumHeight()` sized to 10 rows
  (measured empirically against the real list/real theme: 25px/row).
- **"The one expression we already have set up is not showing here"**
  -- not a bug: the Sprites tab's own Expressions section (the original
  toggle-button UI) still shows "Eyes: Open" exactly as before: the new
  Expressions *tab* only lists hotkey *bindings*, and nothing has bound
  "Eyes: Open" to a Shift+number slot yet. Genuinely easy to conflate
  now that two different "Expressions" UIs exist a tab apart from each
  other -- Help text updated to spell out the distinction explicitly
  rather than assume it's obvious.
- Also found and fixed in passing, unrelated to the layout bug: the
  owner's own real `settings.json` had an empty string for costume slot
  1's key (`costume_keys[0] == ""`, rendering as "Press shortcut"
  instead of "1") -- likely an accidental clear from earlier
  interaction. One-character repair, not a code change (the field is
  gitignored, personal machine state).
- Full suite green at 410 tests.

**Costume row still overflowed at a narrower stress-tested width;
Costumes/Expressions tabs renamed to disambiguate from an existing
Sprites-tab section, 2026-09-17, same-day follow-up.**

- Stress-testing the just-fixed single-column layout at a narrower panel
  width than the owner's own screenshot (820px, then 650px total window)
  still showed a horizontal scrollbar -- capping each dropdown's own
  width (`setMinimumContentsLength`) reduced the problem but didn't
  eliminate it, since Hide and Show still shared one row. Fixed for real
  this time by stacking Hide above Show instead of side by side, so
  each dropdown only ever competes with its own short label for width,
  never with a sibling dropdown -- verified clean (no scrollbar) all the
  way down to 479px of panel width, well past anything the owner's real
  screenshots showed.
- Owner: "i thought the expressions TAB was about assigning expressions
  and the one in the sprites tab would fire them?" -- their model was
  basically right (Sprites tab defines *and* fires; the tab only
  *binds* a hotkey to something already defined), but "Expressions"
  naming two different UI locations a tab apart from each other was a
  real, avoidable point of confusion, not something to argue past.
  Renamed the tab labels to **Costume Hotkeys**/**Expression Hotkeys**
  (CollapsibleSection titles inside each tab, and the Sprites tab's own
  "Expressions" section, both left alone -- only the bare tab-bar labels
  were ambiguous) and added an explicit "two different Expressions, a
  tab apart" paragraph to the Help window's Hotkeys tab spelling out the
  define/fire vs. bind distinction, rather than leaving it implicit.
- Full suite green at 410 tests.

**Costume/Expression Hotkeys tabs rebuilt a third time on QListWidget,
2026-09-17, same-day follow-up.** Owner, with fresh real screenshots:
"dude ur just not nailin' this lol.. ugly, no alignment, cropping,
WHIIIIITE." The QScrollArea-based fix (same day, earlier entry) still
showed real corruption in the owner's own actual themed app -- patches
of the wrong (light) background color, misaligned/overlapping rows --
that this session could not reproduce with a from-scratch isolated
QScrollArea+theme repro, meaning it was something about that exact
nested combination (CollapsibleSection body -> QScrollArea -> plain
QWidget content -> per-slot QVBoxLayouts), not a generic, confidently-
fixable Qt gotcha. Rather than keep guessing at QScrollArea internals
this session couldn't reliably reproduce, switched to the technique the
Sprites tab's own Layer List already uses successfully in this exact
app/theme/tab context: `QListWidget` + `setItemWidget`.

- First pass at this (one `QListWidgetItem` per *slot*, holding a
  variable-length inner layout of swap/force rows) hit a second, more
  subtle bug, caught before it shipped by measuring rather than
  eyeballing: a `QListWidgetItem`'s size hint does not reliably refresh
  when its embedded widget gains a child afterward, even after
  `updateGeometry()`/`layout().activate()` -- confirmed with real
  `sizeHint()` printouts showing a stale, too-small value after adding a
  row. Fixed by matching Layer List's own granularity exactly: one
  `QListWidgetItem` *per swap/force row*, plus one static header item and
  one static "+ Add" item per slot -- adding/removing a row means
  adding/removing a whole list item (a plain, native, well-supported
  QListWidget operation, inserted immediately before that slot's "+ Add"
  item) rather than ever resizing one in place.
- Verified this time with real measurements, not just a screenshot at
  one window size: printed every item's actual `sizeHint()` after adding
  three rows to a slot and confirmed each new row is its own correctly-
  sized item; scrolled the real `QListWidget` (native scrollbar, not a
  `QScrollArea`) and confirmed clean rendering at both ends of the list;
  re-ran the narrow-panel stress test (650px) from the previous QScrollArea
  fix and confirmed no white patches, no overlap, no cropping there
  either. `minimumSizeHint()` is no longer byte-identical switching tabs
  (`QListWidget` carries a small built-in minimum a `QScrollArea` didn't,
  ~70px) but stays flat regardless of content -- nowhere near the
  hundreds-of-pixels-per-slot growth that started this whole chain of
  fixes.
- `_costume_rows`/`_expression_hotkey_rows` (the row *widgets* --
  `row.hide_combo` etc., what the rest of this app already reads) are
  unchanged; only their container went from "layout position" to "list
  item", tracked in parallel by the new `_costume_row_items`/
  `_expression_row_items`.
- Full suite green at 410 tests, all pre-existing costume/expression
  tests passing unmodified -- confirms the swap was contained to how rows
  are *displayed*, not how they're read or how the underlying data works.

**Real root cause of the empty-space bug finally found: a mislabeled
`setAlignment` from three days-worth of comments back, 2026-09-17, same-
day follow-up.** The white/cropping corruption from the QScrollArea
attempts was gone (owner confirmed, screenshot clean) -- but the new
QListWidget-based tabs left "sooo much room" empty below a tiny list on
their own. Root-caused by measurement, not another guess: printed the
actual widget hierarchy's geometry top to bottom and found the *splitter*
itself stuck at ~244px inside a ~677px-tall page, even after manually
calling `setSizes()` with a huge value -- meaning the constraint was
above the splitter's own children entirely.

Tracked it to `_add_tab_splitter`'s `outer.setAlignment(splitter,
Qt.AlignmentFlag.AlignTop)`, added earlier the same day for a *different*
bug (all-collapsed sections centering instead of pegging to the top).
That fix's own comment claimed AlignTop "is a no-op whenever the splitter
can fill the available height" -- confirmed by direct, isolated testing
to be simply **wrong**: `QLayout::setAlignment()` on an item overrides
that item's size policy entirely for the layout's main axis, permanently
capping it to its own `sizeHint()` and aligning within whatever's left,
regardless of whether the widget's policy is Expanding. It was never a
no-op; it just happened not to matter for every earlier multi-section tab
(their sections' combined sizeHints already summed to nearly the whole
window). A one-section tab with modest content (exactly what Costume/
Expression Hotkeys are) was the first case where the difference actually
showed up.

Fix: `_update_splitter_top_alignment(splitter)` computes this
dynamically -- `AlignTop` only while *every* section in that splitter is
actually collapsed (the case the original fix targeted), plain `Qt.
AlignmentFlag(0)` (Qt's own default, fill-the-cell behavior) the moment
anything is expanded. Called once at construction and again on every
`collapsed_changed` (the same signal `_resync_tab_splitter_sizes` already
listens to), so it can never go stale relative to a section's real state.
Verified two ways: (1) the specific splitter/page/list heights from the
bug report, confirmed with the fix in place (splitter grew from 244px to
659px in a 677px page); (2) reverted the fix and confirmed the exact
existing regression tests for the *original* all-collapsed-centering bug
still pass unmodified -- this didn't just trade one bug for the other.
New regression test
(`test_a_single_expanded_section_fills_the_tab_instead_of_leaving_it_mostly_empty`)
added and confirmed it actually fails against the pre-fix code (235 vs.
required ~530), not just written to pass.

An earlier, now-removed attempt at this same turn added a resync call to
`_on_tab_changed` on the theory that a not-yet-shown tab's page had stale
geometry the one time `showEvent()` resyncs every splitter. Measured
directly and found the *alignment* fix alone was sufficient without it
(same 659px either way) -- removed rather than leave unexplained,
unneeded defensive code sitting next to the real fix.

---

## Open questions / liberties taken (flag if any of these are wrong)

- Confirmed by owner: two-window split (yes), default avatar is
  `avatar-01` (not the legacy creature — PNGTuber-Plus's own default,
  its Godot source, and its "migrate the legacy avatar forward" idea are
  all dropped, nothing from that app carries into this one).
- Assumed the `avatar-01` save should be read from
  `/home/jj/projects/unicorn-tears/images/animated-avatar/avatar-01/` in
  place rather than copied into `unicorn-cloak/`. If the owner later
  wants this app self-contained (e.g. before any v3 packaging/distribution
  step), that's a one-line path change, not a redesign.
- Assumed "we'll not worry about its own repo for now" means this folder
  stays uncommitted/untracked-as-a-unit inside `obs` until v3 packaging,
  and that's fine per CLAUDE.md's git rules since nothing here touches the
  live OBS tree.
- **The three Wayland/portal questions from earlier 2026-09-16 are now
  all resolved** (see that date's entries above for the full reasoning
  and each verified outcome) -- kept here as a record, not an open list:
  1. Super+drag repositioning: **works**, verified on the owner's actual
     4-monitor GNOME/Wayland session.
  2. Minimizing the Render Window while OBS captures it: **does not**
     blank or freeze the capture, contrary to the prediction.
  3. The cutover check: **fails** -- OBS still re-prompts the portal
     picker on every relaunch of either the app or OBS, regardless of
     the stable `app_id`/`applicationName`. Per the owner, this matches
     ordinary behavior for "every other window most of the time" in OBS
     on this machine -- a GNOME/`xdg-desktop-portal-gnome` limitation,
     not something fixable from this app's side. Re-selecting the
     Render Window source after a relaunch is just expected, ongoing
     behavior on this setup, not a defect to keep chasing.
