# 0001 — Avatar lip-sync: PNGTuber-Plus, built from source

**Status:** Superseded 2026-09-15, deprecation finalized 2026-09-16 — see notes at bottom · **Date:** 2026-09-15

**Moved 2026-09-18** from the parent `obs` repo's `docs/decisions/0004-avatar-lipsync-tooling.md`
to this file, renumbered as `unicorn-cloak`'s own first decision record —
this project's docs are consolidating here ahead of its planned move to
its own repo (see `../PLAN.md`'s "Committed to git + docs reorg" entry
for the first, incomplete pass at this). Content and history below are
unchanged from the original.

## Context

Owner wants a local, mic-driven cartoon avatar (mouth moves when they talk)
to use as an OBS source. Considered:

1. **VTube Studio + Live2D** — the industry-standard rig (full expression
   sets, head tilt, physics), but Windows/Mac only; Linux support is
   unofficial, running through Wine/Proton. On this machine (Iris Xe
   iGPU, no NVENC, Wayland) that compatibility layer is a real latency and
   stability risk, working against "smoothest, most natural."
2. **PNGTuber-Plus** ([kaiakairos/PNGTuber-Plus](https://github.com/kaiakairos/PNGTuber-Plus)) —
   open source (Unlicense/public domain), Godot 4.1 project with native
   Linux support (ships a Linux build of its one native GDExtension
   component). Mic-volume-driven mouth states plus idle motion (blink,
   sway, bounce, jiggle) via the engine, not hand-animated. No camera or
   face tracking needed.

No official GitHub release exists for this project (source only); the
author distributes built binaries via itch.io. Building from source with
the Godot engine was chosen over sourcing the itch.io binary so the exact
version in use is pinned and reproducible from this repo's records, and so
no unverified third-party binary is run on this machine.

## Decision

- Use **PNGTuber-Plus**, not VTube Studio.
- Clone the source to `~/Repos/pngtuber-plus` (a sibling repo, not nested
  inside `obs` — it's third-party software this setup depends on, not
  OBS configuration) and run it via the Godot engine rather than the
  itch.io binary.
- Pinned commit: `3173b213681152eb7fca55c63e757cfc42d2eb44` (tag `1.4.5`,
  2024-03-26 — the latest on `master` as of 2026-09-15).
- Run via **Godot 4.7.2** (Flathub `org.godotengine.Godot`) even though the
  project targets the 4.1 feature set — no Godot 4.1 build is available on
  Flathub, and Godot's GDExtension ABI is intended to stay
  forward-compatible within the 4.x line. The project's one native
  component already ships a Linux `.so`, so no engine-version rebuild of
  that piece should be needed. **If the project fails to open or run
  correctly under 4.7.2, fall back to the itch.io pre-built binary
  instead of chasing an older Godot version.**
- Project uses the **GL Compatibility** rendering feature set, which suits
  this machine's Intel Iris Xe iGPU (lighter than the Vulkan
  Forward+ renderer OBS itself would otherwise compete with for GPU time).

## Alternatives

- VTube Studio/Live2D — rejected for this machine, see above. Revisit if
  the owner later runs a Windows/Mac capture box for streaming.
- itch.io pre-built binary — rejected as the first attempt in favor of a
  pinned source build; remains the documented fallback.

## Consequences

- A new local dependency (`~/Repos/pngtuber-plus`) exists outside this
  repo's scope; `obs`'s docs record the integration (how it feeds into an
  OBS window-capture source) but not the tool's own source or art.
- Avatar art is created and imported through PNGTuber-Plus's own UI (art
  is embedded into its save file, not read from a folder of PNGs at
  runtime) — the owner is producing that art separately.
- No OBS scene work happens until the owner has usable art; setup here
  covers getting the tool installed and running with its default
  placeholder avatar.

## Superseded 2026-09-15

While tuning it, found the mouth open→closed decay is a fixed rate
hard-coded in `autoload/global.gd` (`lerp(volumeSensitivity, 0.0, delta*2)`)
with no exposed setting — a real ceiling on how responsive it can be made
at normal talking pace, even with both threshold sliders maxed. Owner
decided to build a custom lip-sync avatar tool from scratch instead of
working around this — a full 3-phase replacement plan ("Unicorn Cloak",
Python/PySide6) already exists at `../PLAN.md`.
`~/Repos/pngtuber-plus` is left in place (untouched, not deleted) as the
reference implementation the plan is replacing.

## Deprecation finalized 2026-09-16

Unicorn Cloak (`../PLAN.md`) now runs end-to-end against the
owner's real avatar and mic on this machine — owner's own words on the
Render Window's OBS capture: "super clean." Owner confirmed PNGTuber-Plus
is fully deprecated, not just superseded-in-plan: "this is hot garbage!
... i forgot about it yesterday, done & dusted." `~/Repos/pngtuber-plus`
and the Godot install remain on disk, untouched, per this record's
original "left in place, not deleted" policy — removing them was not
asked for and hasn't been done. `../avatar-lipsync-setup.md` (the
setup doc for the now-deprecated tool) is marked superseded to match.
