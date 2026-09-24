"""
The in-app Help window: tabbed (added 2026-09-17, owner's request: "a
proper help dialog with overall usage methodology & tips") since a
single long scroll doesn't separate "what is this and why does it exist"
from "how do I actually use it" from "here's every field, in detail" --
three different questions a reader arrives with at different points, not
one long document to skim through regardless of which one they have.

<b>Overview</b> (premise + a placeholder "About me" -- real bio text
still needed from the owner) and <b>Usage</b> (the actual end-to-end
methodology: prepare art, build the rig, tag states, tune live, go live
in OBS) are genuinely new content, not extracted from anywhere. <b>Sprites</b>
is new practical art-prep advice (canvas size, alignment, transparency,
consistent line weight across alternate states) -- general guidance for
*making* the PNGs this app consumes, distinct from the Sprites tab's own
in-app field reference. <b>Hotkeys</b> (added 2026-09-17, owner's
request, once Expression hotkeys and the costume/Expression assignment
editor existed and the old one-paragraph mention inside Reference wasn't
enough room to explain them properly) is the single source of truth for
every keyboard/mouse shortcut and how to configure what each one does --
Reference's own old "Hotkeys" section was cut down to a one-line pointer
here rather than kept as a second, driftable copy. <b>Reference</b> is
every word of the original, single-tab Help window (updated in place as
features change, not left frozen) -- the exhaustive per-field/per-section
reference tooltips alone don't cover (see control_panel_window.py's own
tooltips, which this expands on rather than duplicates verbatim). No live
data of its own anywhere in this file -- if a concept's exact numbers or
ranges change, update the text here to match.

Styled by theme.py -- needs only `setObjectName("HelpWindow")`, not
ControlPanelWindow's `WA_StyledBackground`, since QDialog paints its
stylesheet background natively (a plain QWidget doesn't). The
objectName is what scopes theme.py's rule to just this dialog rather than
every QDialog in the app, including QFileDialog/QMessageBox -- see
theme.py's module docstring. The embedded `QTabWidget`/`QTabBar` pick up
theme.py's own (unscoped) rules for those automatically, same as the
Control Panel's own tabs. A couple of brand touches (Anton for headings,
JetBrains Mono for inline `<code>`) are inline in each tab's own HTML via
_STYLE below instead, verified against Qt's actual rendered output (not
assumed): Qt's rich-text engine reads a `<style>` block inside the HTML
itself, but not the app-wide QSS, for content rendered inside a
QTextBrowser's document -- so every tab needs its own copy, not one
shared app-wide rule.
"""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QPushButton, QTabWidget, QTextBrowser, QVBoxLayout

_STYLE = """
<style>
h2 { font-family: 'Anton'; color: #ff2bd6; letter-spacing: 1px; }
h3 { color: #19e3ff; }
code { font-family: 'JetBrains Mono'; color: #bd83ff; }
b { color: #ffffff; }
i { color: #c9bdda; }
</style>
"""

OVERVIEW_HTML = (
    _STYLE
    + """
<h2>Unicorn Cloak</h2>

<h3>About me</h3>
<p><i>Placeholder -- a short paragraph about who's behind Unicorn Cloak
and why it exists will go here.</i></p>

<h3>What this is</h3>
<p>Unicorn Cloak is a PNGTuber-style avatar app: a layered PNG rig that
reacts live to your microphone (mouth shapes) and a random timer (eye
blinks), rendered in a plain borderless window that OBS captures as a
source -- the same basic idea as PNGTuber-Plus, built from scratch in
Python/PySide6 rather than continuing on that app's own Godot codebase.
"Better and unique" was the goal from the start, not feature parity for
its own sake.</p>

<h3>Why it exists</h3>
<p>The direct motivation was PNGTuber-Plus's lip-sync: a single fixed-rate
decay that left the mouth visibly lagging shut about 0.7 seconds after
speech actually stopped, with no way to tune it. This app's mouth is
driven by a real envelope follower instead -- separate open/close
thresholds per loudness band (hysteresis, so it doesn't flicker right at
one boundary) plus tunable Attack/Hold/Release timing, all adjustable
live while you talk, with a level meter showing exactly where your voice
sits against those thresholds. Everything downstream of that same
motivation followed from actually using the thing: OBS mute-awareness (so
the avatar doesn't keep "talking" while the stream itself is muted), a
proper multi-costume/hotkey system, undo/redo, and a single Control Panel
window instead of hunting across several.</p>
"""
)

USAGE_HTML = (
    _STYLE
    + """
<h2>Usage</h2>
<p>The overall workflow, start to finish -- each step links to the
Reference tab's own section for the details.</p>

<h3>1. Prepare your art</h3>
<p>Before touching this app: get your layered PNGs ready. See the
Sprites tab for concrete tips -- canvas size, alignment, and what to
export as separate layers vs. one image.</p>

<h3>2. Build the rig</h3>
<p>On the Sprites tab's Layer List: <b>Add…</b> each PNG as its own
sprite. Set Parent/Position/Offset/Z-index (Behavior tab) so everything
sits where it should and stacks correctly. Use the Edit-mode canvas
(drag to reposition, grid + origin axes for alignment) rather than typing
numbers blind.</p>

<h3>3. Tag mouth and eye states</h3>
<p>For each mouth shape: Group name "Mouth", a State name
("Closed"/"Mild"/"Wide"), and the matching Talk state. For each eye
state: Group name "Eyes", State name, and Blink state. This is what
makes "only one mouth shape shows at a time" actually work, instead of
every shape just sitting on top of each other. Use <b>Preview state</b>
(above the canvas) to check each combination without talking or waiting
for a real blink, and <b>Check for Issues…</b> to catch an incomplete
trio or a state with nothing tagged to it.</p>

<h3>4. Tune it live</h3>
<p>Talk into your mic while watching the Audio tab's Envelope section and
the level meter below the canvas -- adjust the open/close thresholds and
Attack/Hold/Release until the mouth feels responsive but doesn't flicker.
Use <b>Record 10s &amp; loop</b> to tune against a repeating sample of
your own real speech instead of talking continuously. Tune Motion
(bounce, blink timing, wobble) the same way, watching the Live Preview
canvas.</p>

<h3>5. Go live</h3>
<p>Add the Render Window as an OBS Window Capture (or portal Screen
Capture) source, matched by its title. Leave Background as Transparent
unless you're chroma-keying (or set an Image/Video instead). Save the
avatar, then use the costume hotkeys while actually streaming -- the
Control Panel can stay closed for these (double-click the avatar to
bring it back) so it never ends up in frame. Expression hotkeys
(Shift+number) are the one exception: they need the Control Panel itself
open and focused, since they're wired to its own Expression buttons --
keep it open somewhere outside any OBS capture if you plan to use them
live. See the <b>Hotkeys</b> tab for the full list.</p>

<h3>6. Iterate</h3>
<p>Hot reload picks up a re-saved avatar file or a re-exported sprite PNG
automatically, live, no restart -- keep your art tool and Unicorn Cloak
open side by side while refining. Reset/Lock (every numeric field) makes
it safe to experiment without losing a value you'd already tuned.</p>
"""
)

SPRITES_TIPS_HTML = (
    _STYLE
    + """
<h2>Sprites: art-prep tips</h2>
<p>General advice for making the PNGs this app consumes -- not specific
to any one art tool.</p>

<h3>Canvas size</h3>
<p>Give every layer of the same avatar the exact same canvas size, with
the subject in the same place on that canvas across all of them (e.g.
every mouth shape drawn on an identical full-head canvas, not cropped
tight to just the mouth). Position and Offset become simple, predictable
numbers instead of per-layer guesswork, and swapping between states never
causes a visible jump.</p>

<h3>One state, one full layer</h3>
<p>Export each mouth shape and each eye state as its own complete,
full-canvas PNG -- not a small patch meant to overlay on top of a base
layer. This app shows exactly one sprite per active state (see Talk
state/Blink state in the Reference tab); a "patch" approach needs a
separate always-visible base layer underneath and is much easier to
misalign.</p>

<h3>Transparency</h3>
<p>Export with a real alpha channel, fully transparent outside the
subject -- no white or checkerboard background baked in. Watch for
anti-aliased edge pixels that are only partially transparent; a hard
edge with no halo reads more cleanly once composited over your scene.</p>

<h3>Consistent linework across alternates</h3>
<p>Keep line weight, shading, and lighting consistent across every
alternate state in the same group (e.g. all three mouth shapes, or both
eye states). A shape that's drawn noticeably differently from its
siblings "pops" when it swaps in, even if the pose itself is correct.</p>

<h3>Pivot points</h3>
<p>Decide where each sprite's pivot should be (usually its parent
attachment point) and keep art consistent about where that point sits on
the canvas, layer to layer. Use Offset to correct a pivot after the fact
rather than nudging the art around on canvas -- keeps Position meaningful
as "where this sprite's pivot sits," not entangled with per-layer art
placement quirks.</p>

<h3>Sprite-sheet animation</h3>
<p>If a layer animates (Frames &gt; 1, Reference tab), lay every frame out
in one horizontal strip, each frame the same width. This app slices it
into equal-width columns -- an inconsistent frame width will misalign the
later frames.</p>

<h3>Check alignment before wiring behavior</h3>
<p>Add a sprite, look at it against the Edit-mode canvas's grid and
origin axes (Guide button) before setting up its Talk/Blink state --
confirming it's positioned and sized correctly is much easier to spot
against a fixed reference than after several more layers are stacked on
top of it.</p>
"""
)

HOTKEYS_HTML = (
    _STYLE
    + """
<h2>Hotkeys</h2>

<h3>Render Window (needs keyboard focus there)</h3>
<ul>
<li><b>1-9, 0</b> — switch costume slot. Remappable per slot from the
<b>Costume Hotkeys</b> tab (click a slot's key-capture box, press the key
you want). Avoid Escape and avoid reusing the same key on two slots —
only the first matching slot fires.</li>
<li><b>Escape</b> — quit the app, with confirmation (not remappable).</li>
</ul>
<p>Costume switching only fires here while the <b>Render Window</b>
itself has keyboard focus, on purpose: a global variant (usable while OBS
or another app has focus, which would otherwise be the actually-useful
case while streaming) was considered and rejected -- it would risk
colliding with whatever else on the system already claims the same keys
(games, other overlays, DAW shortcuts), and that's not a trade worth
making.</p>

<h3>Control Panel (needs keyboard focus there instead)</h3>
<ul>
<li><b>1-9, 0</b> — switch costume slot, same remappable keys as the
Render Window above. Added 2026-09-19 so costume and Expression hotkeys
work from the same window instead of needing two different ones focused
at two different times.</li>
<li><b>Shift+1</b> through <b>Shift+9</b>, <b>Shift+0</b> — toggle an
Expression on/off. Fixed, not remappable (unlike costume keys).</li>
<li><b>Ctrl+Z</b> / <b>Ctrl+Shift+Z</b> — undo/redo.</li>
<li><b>Ctrl+S</b> Save, <b>Ctrl+Shift+S</b> Save As…, <b>Ctrl+O</b>
Load….</li>
<li><b>Delete</b> — delete the selected sprite; <b>Ctrl+D</b> — duplicate
it.</li>
<li><b>Arrow keys</b> — nudge the selected sprite 1 px
(<b>Shift</b>+arrow: 10 px). Does nothing to a locked sprite. A run of
nudges undoes in one step, same as typing into the Position fields.</li>
</ul>
<p>Delete, Ctrl+D and the arrow keys stand down while a text field,
combo box or number field has focus (so Delete still erases a
character there); the arrow keys also stand down while the Layer List has
focus, so they keep moving its selection instead.</p>
<p>Both hotkey types are skipped here while a text field, combo box, or
key-capture box has focus, so typing into one (including remapping a
costume key itself) never gets hijacked by a matching digit press.
Expression hotkeys work by clicking the exact same buttons the Sprites
tab's Expressions section already has, so they still only fire while the
<i>Control Panel</i> window has focus and is open -- if you plan to use
them live, keep the Control Panel open somewhere off to the side, outside
whatever OBS is actually capturing.</p>
<p><b>Two different "Expressions," a tab apart -- not the same thing:</b>
the Sprites tab's Expressions section is where an expression actually
gets <i>defined</i> (tag a sprite Manually driven with a Group/State
name) and where you can always <i>fire</i> it with a plain click, no
hotkey required. The Expression Hotkeys tab doesn't define or fire
anything new by itself -- it only <i>binds</i> an already-defined
expression to a Shift+number key, by clicking that exact same button for
you. An expression you haven't bound to a hotkey yet still works fine
from the Sprites tab; it just won't show up as a row here until you
explicitly add it.</p>

<h3>Setting up what a costume hotkey does</h3>
<p>The <b>Costume Hotkeys</b> tab, immediately right of Sprites -- a
scrolling list of all 10 slots. Each slot has:</p>
<ul>
<li>Its own remappable key-capture box (see above).</li>
<li>Zero or more <b>Show / Hide</b> sprite-pair rows. Pick a sprite in
<b>Show</b> -- it's hidden everywhere else and this hotkey shows it. Pick
a sprite in <b>Hide</b> -- it's shown everywhere else and this hotkey
hides it. Click <b>+ Add swap</b> for another row under the same slot to
swap several sprites at once (e.g. both halves of a hoodie for a vest,
under one hotkey), or the row's own <b>−</b> button to remove it and put
both its sprites back to normal (visible everywhere).</li>
</ul>
<p>A row only takes effect once both boxes are filled in -- clearing one
back to "—" just leaves it incomplete, it doesn't remove the row; use
<b>−</b> for that. This is purely a friendlier way to author what used to
need a raw file edit (each sprite's own "Costume layers"); nothing about
how costumes actually render changed.</p>

<h3>Setting up what an Expression hotkey does</h3>
<p>The <b>Expression Hotkeys</b> tab, right of Costume Hotkeys -- same
scrolling, ten-slot layout. Each Shift+number slot has zero or more
<b>Force</b> rows -- pick an Expression (any Manually-driven Group
name/State name pair; tag one on the Sprites tab first if none exist
yet, or use the Sprites tab's own Expressions section, which lists
exactly the same
pairs as plain toggle buttons if you just want to force one live without
a hotkey). Add more than one row to
force several groups together as one combined expression (e.g. a mouth
shape and an eye shape at once). Use the row's own <b>−</b> button to
remove it, same as costumes.</p>

<h3>Mouse (Edit-mode canvas)</h3>
<p>Select a sprite (click it on the canvas or in the Sprites list) to see
its handles -- a boxed square at each corner to scale, and one floating
above it to rotate. Not shown at all, and not draggable, on a sprite
that's locked (see "Lock Position" below):</p>
<ul>
<li>Drag the sprite itself to move it (updates Position live).</li>
<li>Drag a corner handle to scale it independently on X/Y.</li>
<li>Drag the handle floating above it to rotate it.</li>
</ul>
<p>All three write straight into that sprite's Position/Scale/Rotation
fields, live -- the property panel and the canvas always stay in sync
with each other, whichever one you just used.</p>
<p>Scroll the mouse wheel over the canvas to zoom the <i>view</i> in and
out, centered on the cursor -- a "look closer while editing" aid only.
It never changes the avatar's own Scale/Rotation/Zoom fields or
anything saved, and resets the next time the canvas re-fits (resizing
the window, loading a different avatar, or switching back from Live
Preview). Live Preview doesn't zoom on scroll -- it always shows the
avatar at its real Render Window size.</p>
<p>Hold <b>Ctrl</b> and drag to pan the view -- takes priority over the
usual click-to-select/drag-to-move-a-sprite behavior, even if the drag
starts on top of a sprite, so it's always available once zoomed in far
enough that part of the avatar is off-screen.</p>
"""
)

REFERENCE_HTML = (
    _STYLE
    + """
<h2>Unicorn Cloak — Reference</h2>

<h3>The two windows</h3>
<ul>
<li><b>Render Window</b> — the plain, borderless window with your avatar
in it. This is the only window OBS should ever capture (Window Capture or
a portal Screen Capture source, matched by its title, "Unicorn Cloak").
Press <b>Escape</b> to quit the whole app -- always asks you to confirm
first, with an extra warning if the avatar has unsaved changes.
<b>Double-click the avatar</b> to re-open the Control Panel if you've
closed it.</li>
<li><b>Control Panel</b> — everything else: building/arranging the
avatar, live-tuning the mic-reactive mouth and motion, OBS integration,
and app settings. One single window (merged from what used to be two
separate Editor/Settings windows) -- never captured by OBS. Closing it
does <i>not</i> quit the app or ask for confirmation; the avatar stays
live in the Render Window until you double-click it to bring the Control
Panel back.</li>
</ul>

<h3>The Control Panel, at a glance</h3>
<ul>
<li><b>Canvas</b> (top) — two buttons, <b>Live Preview</b> and <b>Edit
Sprites</b>, switch between two views of the avatar (the active one is
highlighted): Live Preview mirrors the real Render Window (reacts to
your actual mic and blinking, read-only) and is the default; Edit
Sprites is the interactive canvas -- drag a sprite to move it, driven by
the Preview state controls that appear above it instead of live audio.
Edit Sprites also shows two more buttons, <b>Reset Size</b> and
<b>Reset Rotation</b>, which reset the selected sprite's Scale X/Y back
to 1.0 or Rotation back to 0° -- both disabled with nothing selected,
and both undoable like any other edit. A level meter is always shown
just below the canvas, in either mode.</li>
<li><b>Tabs</b> (middle) — Sprites, Costume Hotkeys, Expression Hotkeys,
Behavior, Audio, and Application. Each tab is made of a few sections you
can collapse (click the header) or resize (drag the divider between
them) independently.</li>
<li><b>Bottom bar</b> (always visible, never scrolled away) — a
clickable file-playback timeline (File source only, once something's
actually been played), then audio source controls on their own row
(Source/Play/Browse…/Record, with the chosen file's path shown just
below, shortened from the middle if it's long), then Undo/Redo/Help/
Save/Save As…/Load…/Export Snapshot…/Check for Issues…/Guide/Ghost/
<b>Mute mouth</b>/Quit. <b>Mute mouth</b> forces the mouth closed
manually — independent of OBS mute, for a cough or an aside without
touching OBS at all. Click it again to let the mouth follow the
mic/audio source again.</li>
</ul>

<h3>Hotkeys</h3>
<p>See the <b>Hotkeys</b> tab for the full list and how to set up what
each one actually does.</p>

<h3>Sprite concepts</h3>
<p>Every layer in the avatar is a "sprite" — an image plus the rules
below. Hover any field on the Sprites/Behavior tabs for the short
version; this is the long version.</p>
<ul>
<li><b>Position / Offset</b> — Position is where this sprite sits,
relative to its parent (or the avatar's own center, for a root-level
sprite). Offset shifts where the <i>image</i> is drawn without moving the
sprite's own pivot point — it mainly matters once rotation or stretch is
involved. If your art is pre-aligned on a shared canvas (every layer the
same pixel dimensions, subject already in the right spot), both should
normally stay at (0, 0).</li>
<li><b>Z-index</b> — stacking order, but only among this sprite's own
siblings (same parent) — it does not compare across different parents.
Higher draws in front. A negative value draws behind this sprite's own
parent (e.g. a hair-back layer meant to peek out from behind the head).</li>
<li><b>Parent</b> — attaching a sprite to another makes it inherit that
parent's position, rotation, and stretch automatically. Combined with its
own Drag speed (not yet in the property panel — edit the file directly
for now), a child can lag behind a moving parent, e.g. hair trailing a
head's bounce.</li>
<li><b>Group name / State name</b> (added 2026-09-16) — purely
organizational: ties sprites together as belonging to the same named
slot, e.g. Group name "Mouth" with State name "Closed"/"Open a
little"/"Open wide"/"Laughing". Neither field changes what shows on its
own — they exist so a set of sprites is tied together on purpose,
instead of only coincidentally sharing numbers and overlapping positions
(which is exactly what let a real bug ship unnoticed — see Talk state,
below). State name's dropdown is scoped to whatever's already used
within the currently-selected Group name, editable so you can type a new
one. "Check for Issues…" (below) reads these two fields to warn about
likely mistakes.</li>
<li><b>Manually driven</b> — when checked, Talk state/Blink state below
are ignored entirely for this sprite. It shows only when its Group
name's live override is forced to exactly its State name — via the
Sprites tab's "Expressions" section (for the real Render Window and OBS)
or the canvas's own "Force expression" preview control (canvas-only).
For a named expression like "Laughing" that isn't tied to mic volume or
blinking at all — nothing shows until an override is explicitly
activated.</li>
<li><b>Talk state</b> — a dropdown: "Always visible" (use for anything
that isn't a mouth), "Only when quiet", "Only mild", or "Only wide". For a
real closed/mild/wide mouth trio, give each of the three shapes its own
exclusive option so only one ever shows at a time. "Always visible" is
<i>not</i> "shown while quiet" — it means exactly what it says, shown
regardless of talk level, which is why a real mouth trio needs "Only when
quiet" for its closed shape rather than "Always visible" (a real bug,
fixed 2026-09-16: a closed mouth set to "Always visible" rendered on
every frame no matter what, and peeked out from behind the mild/wide
shapes wherever their art didn't fully cover it). Ignored entirely when
Manually driven is checked.</li>
<li><b>Blink state</b> — same idea as Talk state, but driven by the
random blink timer instead of the mic: "Always visible", "Only eyes
open", or "Only mid-blink". Since this avatar's shades are fully opaque,
eye sprites are drawn <i>in front of</i> the shades layer (not in
realistic behind-the-glasses order) so blinking is actually visible.
Ignored entirely when Manually driven is checked.</li>
<li><b>Preview state</b> (above the Sprites list) — forces the Edit-mode
canvas to show sprites as if the mic were at a chosen talk level, or the
avatar were in a chosen blink state, so you can check exactly which
sprites show under which condition without talking into the mic or
waiting for a real blink. "Force talk variant" / "Force blink variant"
pick which sprite shows when more than one shares the same band (e.g.
squint vs. wide-open eyes, both "eyes open") — the canvas has no running
timer to alternate them on its own. "Force expression" previews a
Manually-driven state the same way. None of this ever affects the Render
Window, which always uses the real, live state.</li>
<li><b>Variant</b> — when more than one sprite shares the same nonzero
state on whichever axis gates it (two "mild" mouths on Talk state, or two
"eyes open" shapes like wide-open/squint on Blink state), Variant says
which alternation slot each one is in (0, 1, 2...). They'll take turns
showing while that state stays active — mouths at the Behavior tab's
"Mouth alternate rate" (a flutter, for continuous talking), eyes at the much
slower "Eye alternate rate" (an occasional expression change, not a
twitch). A state with only one sprite in it ignores Variant entirely; it
just always shows.</li>
<li><b>Frames / Anim speed</b> — for a simple sprite-sheet animation:
Frames is how many equal-width horizontal slices the image is cut into
(1 = a plain static image), Anim speed is how many frames per second it
plays through, looping. The Edit-mode canvas always shows frame 0 — it's
a static preview, not a live one.</li>
<li><b>Clipped</b> — masks this sprite's children to its own opaque
shape, not just its rectangle (edit the file directly for now; not yet a
field anywhere in this UI). Useful for something that should only ever
show up inside a silhouette.</li>
<li><b>Costume layers</b> — which of the 10 costume slots (see the
<b>Hotkeys</b> tab) this sprite appears in. Every sprite defaults to
"every slot" until a costume-hotkey assignment hides it from one. Set
this up from the <b>Costume Hotkeys</b> tab, not here directly — pick two
sprites (one hidden by default and shown by this slot, one shown by
default and hidden by this slot) and both sprites' Costume layers update
automatically.</li>
<li><b>Toggle</b> — a hotkey-bindable per-sprite visibility flag, carried
over from the file format. Nothing reads it yet (no hotkey wiring
exists), but it survives save/load untouched, so it's safe to leave set
if a file already has it.</li>
<li><b>Hidden</b> (the eye icon, not a Sprites-tab field) — a manual
show/hide switch for a layer, always in effect regardless of costume,
talk, or blink state. Every layer starts visible (open eye). Click a
layer's eye icon in the Sprites list to hide it (closed eye) — useful
for two alternatives that should never show together, e.g. glasses vs.
bare eyes. Clicking a layer's name still selects it for the property
fields, same as before. On the Edit-mode canvas specifically, a hidden
layer (and anything else not visible in the current talk/blink Preview
state) still shows faintly at 40% opacity by default — a ghost outline
so you can see where it is while you work — but it is <i>always</i> at
true 0% (fully invisible) in the Render Window and in OBS. See the
<b>Ghost</b> button below to turn this off.</li>
</ul>

<h3>Sprites tab</h3>
<ul>
<li><b>Layer List</b> section — <b>Add…</b> brings in a new sprite layer
from a PNG file (or drag one or more PNGs from your file manager straight
onto the canvas or the Layer List -- a multi-file drop undoes in one
step); <b>Replace…</b> swaps the selected sprite's image for a
different file, keeping every other setting as-is; <b>Duplicate</b>
copies the selected sprite, nudged slightly; <b>Delete</b> removes it
(children are kept, reparented to the root level); <b>Move Up / Move
Down</b> steps it toward the front/back among its siblings. The Sprites
list itself is always ordered front-to-back with parent/child
indentation; each row has an eye icon to show/hide that layer (see
Hidden, below) and a padlock icon to lock its Position/Rotation/Scale
(see "Lock Position" below -- same lock, either toggles both). Drag a
sprite directly on the Edit-mode canvas to move it (updates Position
live); clicking a sprite (on the canvas or in the list) selects it.</li>
<li><b>State Assignment</b> section — the selected sprite's Group
name/State name/Manually driven/Talk state/Blink state (see Sprite
concepts above).</li>
<li><b>Expressions</b> section — one toggle button per Manually-driven
Group name/State name pair defined just above (e.g. "Mouth: Laughing").
Clicking one forces every sprite tagged with that exact pair to show,
live, on the real Render Window and in OBS -- click it again to turn it
off. Only one state per group can be forced at a time; picking a
different button in the same group automatically turns the previous one
off. If nothing shows here, no sprite has been marked Manually driven
yet. The <i>currently forced state</i> isn't saved across restarts --
it's a live control, not a setting -- but you can bind any of these
buttons to a Shift+number hotkey from the <b>Expression Hotkeys</b> tab
(see the <b>Hotkeys</b> tab for the full explanation), which <i>is</i>
saved.</li>
</ul>

<h3>Canvas controls</h3>
<ul>
<li>The Edit-mode canvas shows a grid by default spaced at whatever the
Application tab's "Grid spacing (px)" is set to, plus dashed axes through
(0, 0) — where a root-level sprite's own Position of (0, 0) sits. Toggle
the whole thing with the <b>Guide</b> button in the bottom bar.</li>
<li><b>Ghost</b> (bottom bar) — on Edit-mode canvas only. Hidden layers
and anything not visible in the current Preview state show at 40%
opacity so you can see where they are; this never affects the Render
Window or OBS, which always show them at true 0%. Off by default.</li>
<li><b>Save</b> — writes the avatar to whatever file it was last saved
to or loaded from, no dialog. <b>Save As…</b> always asks where to save.
<b>Load…</b> reads a <code>.uc</code> or <code>.save</code> file,
replacing everything currently open (including undo history).
<b>Recent</b> (next to Load) re-opens one of the last five avatars you
had open. Each avatar also reopens in whichever costume it was last
showing — remembered per avatar in this app's own settings, not in the
avatar file, so switching costumes live never marks the avatar as
having unsaved changes.</li>
<li><b>Export Snapshot…</b> — renders the currently active costume at
rest (mouth closed, eyes open, no motion) to a PNG at whatever
resolution you choose, for thumbnails or channel art. Pick a width and
height, then a save location.</li>
<li><b>Hot reload</b> — the avatar's save file and every sprite's own
source PNG are watched automatically. Re-saving the file from outside
this app, or re-exporting a sprite's PNG over the same path, reloads it
live — no restart needed while iterating on art.</li>
<li><b>Check for Issues…</b> — scans every sprite's Talk state/Blink
state/Group name/State name/Manually driven assignment for likely
mistakes: an incomplete trio (sprites use exclusive gating on an axis but
one of the three bands has no sprite at all), two sprites that would
fight instead of alternate (same state <i>and</i> the same Variant), a
Manually driven sprite with no Group/State name set (can never be
triggered), and inconsistent labeling (sprites sharing a Group/State name
pair with different settings). It's a heuristic sanity check, not a hard
validator — a clean result means nothing obvious looks wrong, not that
the rig is guaranteed correct. Results open in their own window that
stays open alongside the Control Panel: click an issue to select the
sprite it's about (click it again to step through several).</li>
</ul>

<h3>File format: .uc</h3>
<p>New saves use the <code>.uc</code> extension ("Unicorn Cloak"). Older
<code>.save</code> files (from before this naming, or from PNGTuber-Plus's
own format, which this app reads directly) still load fine — the JSON
shape is unchanged, only the conventional extension is new. Opening a
file saved by an older version of this app upgrades it automatically:
you'll see a one-time message telling you it happened, and a
<code>.bak</code> copy of the pre-upgrade file is kept. Every save (of any
file) keeps one rolling <code>.bak</code> of whatever was there
immediately before it (replaced by the next save), <i>plus</i> a
timestamped copy in the same folder
(<code>yourfile.uc.20260923-173012-123456.bak</code>) — the last 10 of
those are kept, older ones pruned automatically, so a couple of bad saves
in a row can still be undone by hand. Saves are atomic, too (a crash or
power loss mid-save can't corrupt the file on disk).</p>

<h3>Reset / Lock</h3>
<p>Every numeric field across every tab has both. <b>Reset</b> restores
that field's built-in default value. <b>Lock</b> makes the field
immutable until you click it again -- scrolling, arrow keys, the spin
buttons, and typing all do nothing while locked (it visibly greys out).
This exists because the mouse wheel changes whichever field it happens
to be over, not just the one you clicked into, when you scroll a long
section -- Lock is a way to make sure a value you've carefully tuned
can't be bumped by an accidental scroll. Separately from Lock, every
field also requires an actual click into it before the wheel does
anything at all -- just hovering over it while scrolling is not enough
to change it.</p>

<h3>Behavior tab</h3>
<ul>
<li><b>Motion</b> section — the avatar-wide speech bounce (strength,
gravity, how often it re-triggers while you keep talking), the random
blink timer (speed and odds), the idle mouth wobble, and the mouth/eye
alternate rates (see Variant below).</li>
<li><b>Position &amp; Hierarchy</b> / <b>Animation</b> sections
(collapsed by default) — <b>Zoom</b> (whole-avatar, not per-sprite —
scales everything around its own center, regardless of which sprite, if
any, is selected) at the top, then the selected sprite's
Position/Offset/Z-index/Parent (a dropdown of every other sprite, plus
"None (root)")/Rotation/Scale, its own "Lock Position" toggle, and its
Frames/Anim speed/Variant. Rotation and Scale are static/authored values
— a permanent tilt or resize — independent of the reactive drag-rotation
and squash/stretch in the Motion section above, which apply on top of
them. <b>Lock Position</b> prevents Position/Rotation/Scale from being
changed at all -- by these fields or by dragging on the canvas --
everything else (Offset, Z-index, Parent, Frames/Anim speed/Variant,
State Assignment...) stays editable regardless; same lock as the
padlock icon next to this sprite in the Sprites tab's Layer List, either
toggles both. You can also drag a selected, unlocked sprite directly on
the Edit-mode canvas: its own body to move it, a corner handle to scale
it independently on X/Y, or the handle above it to rotate.</li>
</ul>

<h3>Audio tab</h3>
<ul>
<li><b>Envelope</b> section — <b>Sensitivity</b> (a multiplier on the raw
measured volume, independent of your OS's mic volume or a mic's own
physical gain knob -- for when those don't line up with what the level
meter is actually showing; 1.0 = no change) and the volume thresholds and
timing that decide when the mouth is quiet/mild/wide. Each band has
separate open/close thresholds (hysteresis) so it doesn't flicker right
at one boundary value; Attack/Hold/Release shape how snappy the reaction
feels and how long the mouth stays open between syllables during
continuous speech. The level meter above the canvas shows these
thresholds as marks (solid for "open", dashed for "close") plus a
measured audio-to-frame latency reading -- it measures from audio
capture to this app receiving it, not including mic hardware/driver
buffering before that or the Render Window's own render timer (up to
~16ms) after it. <b>Calibrate noise gate</b> (below the fields) samples 3
seconds of whatever's currently active while you stay quiet, then sets
Noise gate to about 1.5x the loudest ambient sample it measured -- a
quick starting point, not a replacement for fine-tuning by ear
afterward.</li>
<li><b>OBS mute awareness</b> section — reads a named OBS input's mute
state live, over obs-websocket, and forces the mouth fully closed while
it's muted -- so the avatar doesn't keep "talking" while the stream
hears silence. Turn it on, fill in Host/Port/Password (from OBS's own
Settings → WebSocket Server Settings → Show Connect Info) and Input name
(must match an OBS source exactly, case-sensitive -- check OBS's own
Sources/Mixer list). The status line updates live. OBS not running, or
the input name being wrong, are both handled gracefully -- the former
just keeps quietly retrying; the latter shows a clear one-time message
saying so.</li>
</ul>

<h3>File-playback timeline (bottom bar)</h3>
<p>A clickable/draggable bar directly above the Source row, with a
"m:ss / m:ss" clock beside it -- only visible while <b>File</b> is the
active source and a file has actually been played at least once (its
total length isn't known before then; see below). Click anywhere on it,
or drag and release, to jump playback to that point -- like scrubbing in
an ordinary media player. Under the hood this restarts decoding from the
new position (the same mechanism <b>Rewind</b> uses to jump back to
0:00), since this app's playback has no true pause/resume mid-file. The
total shown is probed fresh each time you press Play -- if it ever reads
"--:--" instead of a real number, ffprobe (bundled with ffmpeg on most
systems) isn't installed; playback and the elapsed-time half of the
clock still work fine either way.</p>

<h3>Audio source (bottom bar)</h3>
<p>What actually drives the mouth, always visible at the bottom of the
window. <b>Microphone</b> is the normal setup. <b>Desktop audio</b> drives
the mouth from whatever's actually playing out your speakers instead of a
mic -- a game, a video, music -- using the same Device dropdown described
below. It needs an explicit device chosen: unlike Microphone, it never
silently falls back to "whatever's first available," since on a typical
PipeWire/JACK setup that fallback is a real physical mic, not a desktop
loopback -- pick one from the Device dropdown, or you'll see a clear error
instead of the avatar quietly lip-syncing to your voice. <b>File</b> plays
a local audio or video file through this app instead, silently -- it never
plays the file's sound out loud, it only extracts its volume to drive the
mouth, at the file's own real-time pace. Built for re-recording something
where the avatar needs to be driven by one participant's isolated track
while a *different*, already-combined recording is what actually gets
captured (e.g. play the combined track separately through an OBS Media
Source while this decodes the isolated one). Pick a file with Browse…,
then click Play/Stop -- there's no auto-play, and no exact frame-sync
with whatever else you start playing; click both close together by hand.
The chosen file's path is shown just below the row, shortened from the
middle if it's long (e.g. <code>/home/jj/…/recording.mp3</code>), always
keeping the filename itself intact. <b>Record 10s &amp; loop</b> captures
ten seconds of whatever's currently active (mic, desktop audio, or file)
and then loops it continuously, so the Audio tab's thresholds can be
tuned against a real speech rhythm without talking the whole time. Click
it again (or pick a different source) to stop the loop and go back to
what was active before recording started.</p>

<h3>Device dropdown (bottom bar)</h3>
<p>Which capture device feeds the mouth, shown just below the Audio
source row -- only meaningful for Microphone and Desktop Audio (grayed
out on File, which doesn't use a capture device at all). Remembered
separately per source, so switching between Microphone and Desktop Audio
keeps each one's own choice. "System default" picks automatically for
Microphone; Desktop Audio has no such automatic pick (see above) -- choose
a real device from the list. A "Now capturing: …" label next to the row
shows the device this app actually opened, once one is; if that doesn't
match what you expected, it's worth double-checking the dropdown's
selection. Click <b>Refresh</b> after plugging in a new mic or headphones
-- this app has no way to notice that on its own.</p>

<h3>Application tab</h3>
<ul>
<li><b>Display &amp; Canvas</b> section — Background: Transparent (normal
OBS use), a solid color (chroma-keying/previewing), or an Image/Video of
your own choosing (Browse… appears once selected; video loops
continuously and is always silent, regardless of its own audio track).
<b>Render Window size</b>: pick a preset (1280×720, 1920×1080, 1080×1080)
or "Custom", with Width/Height fields below it -- match whatever OBS
source size you're capturing at. Changes apply immediately to the real
Render Window, not just on next launch; editing Width/Height by hand
switches the preset dropdown to "Custom" on its own, and typing in a
preset's exact values switches it back. Also Grid spacing (px): how far
apart the Edit-mode canvas's grid lines are, toggled on/off with the
Guide button in the bottom bar. (Zoom lives on the Behavior tab's
Position &amp; Hierarchy section instead, since it's saved with the
avatar, not app-wide like everything else here — see Behavior tab
below.)</li>
</ul>
<p>Costume/Expression hotkey setup moved to its own <b>Costume
Hotkeys</b>/<b>Expression Hotkeys</b> tabs, immediately right of Sprites
-- see the <b>Hotkeys</b> tab for the full explanation.</p>
<p>Every field has a tooltip with the short version of its own
explanation — hover anything you're unsure about.</p>
"""
)


class HelpWindow(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Unicorn Cloak — Help")
        # theme.py scopes its dialog background rule to this name
        # specifically, not a blanket QDialog selector -- see its module
        # docstring for why (QFileDialog/QMessageBox get their own,
        # separate type-scoped rules instead, not this one).
        self.setObjectName("HelpWindow")
        self.resize(760, 820)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._make_browser(OVERVIEW_HTML), "Overview")
        tabs.addTab(self._make_browser(USAGE_HTML), "Usage")
        tabs.addTab(self._make_browser(SPRITES_TIPS_HTML), "Sprites")
        tabs.addTab(self._make_browser(HOTKEYS_HTML), "Hotkeys")
        tabs.addTab(self._make_browser(REFERENCE_HTML), "Reference")
        layout.addWidget(tabs)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    @staticmethod
    def _make_browser(html: str) -> QTextBrowser:
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(html)
        return browser
