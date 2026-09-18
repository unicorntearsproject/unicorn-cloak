# Avatar lip-sync setup (PNGTuber-Plus) — SUPERSEDED

**Owner:** jj · **Status:** superseded 2026-09-16 · **Last updated:** 2026-09-18

**Moved 2026-09-18** from the parent `obs` repo's `docs/avatar-lipsync-setup.md`
into `unicorn-cloak/docs/` — this project's docs are consolidating here
ahead of its planned move to its own repo. Content below is unchanged
from the original except for path fixes made necessary by the move.

**PNGTuber-Plus is deprecated.** The owner replaced it with a from-scratch
Python/PySide6 app, **Unicorn Cloak** (`PLAN.md`), which now
runs end-to-end against the real avatar and mic and captures cleanly in
OBS. Run it with `cd unicorn-cloak && .venv/bin/python -m unicorn_cloak`;
see `PLAN.md` for everything else (current status, open
items, how the rig/editor/settings work). `~/Repos/pngtuber-plus` and the
Godot install are left on disk, untouched, not deleted (see
`decisions/0001-avatar-lipsync-tooling.md`'s deprecation note).

The rest of this doc is kept as a historical record of the superseded
PNGTuber-Plus setup — not a current how-to.

---

Tool choice and reasoning: `decisions/0001-avatar-lipsync-tooling.md`.
Progress and remaining steps at the time: the parent `obs` repo's
`docs/todos-current.md` (now historical — this line, and the "Remaining
steps" section below, describe PNGTuber-Plus's own now-abandoned setup,
not anything still tracked).

## What's installed

| Item | Detail |
|------|--------|
| Engine | Godot 4.7.2 (Flathub `org.godotengine.Godot`) |
| App source | `~/Repos/pngtuber-plus`, cloned from [kaiakairos/PNGTuber-Plus](https://github.com/kaiakairos/PNGTuber-Plus), pinned at commit `3173b213681152eb7fca55c63e757cfc42d2eb44` (tag `1.4.5`) |
| Licence | Unlicense (public domain) |
| Renderer | GL Compatibility (the project's own feature set, `config/features` in `project.godot`) — confirmed initializing correctly on this machine's Intel Iris Xe iGPU via OpenGL 4.6 / Mesa |

Verified 2026-09-15: headless asset import completes clean (76 assets, no
fatal errors — one non-fatal shader-compiler warning logged and safely
ignored by Godot). App launches on the real desktop session and stays
running (confirmed process alive, rendering).

## Running it

```
flatpak run org.godotengine.Godot --path ~/Repos/pngtuber-plus
```

This opens the Godot editor with the project, which is how this app is
normally run (it isn't exported to a standalone binary here — see the ADR
for why a source build was chosen over the itch.io binary). If that
changes (e.g. an export is made for convenience), update this doc.

## How art gets in

PNGTuber-Plus does **not** read a folder of PNG files at runtime. Layers
are imported through its own UI and embedded (base64) into its save file
format (see `autoload/defaultAvatar.save` for the default placeholder
avatar's structure). So: owner creates PNG layers separately (see the
tips already given — matched canvas size/position across states, mouth
open/closed at minimum, a blink layer, optionally a second talking
variant), then imports them inside the app.

## Remaining steps (tracked in `docs/todos-current.md`)

1. Confirm mic input selection picks up the Blue Yeti
   (`alsa_input.usb-Generic_Blue_Microphones_2035BAB06RZ8-00.analog-stereo`,
   the parent `obs` repo's `docs/environment.md`) via the app's built-in
   mic-select control.
2. Owner imports their art once ready.
3. Tune the volume-trigger threshold against real mic levels.
4. Add the running app as a window-capture source in the OBS collection
   it'll be used in (same `pipewire-window-capture-source` pattern already
   used throughout `Unicorn Tears` — no new OBS plugin needed for this
   part).
