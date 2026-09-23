# Unicorn Cloak

A from-scratch, PySide6 replacement for **PNGTuber-Plus**: a mic-reactive,
layered-sprite avatar overlay window that OBS captures as a window/portal
source. Two windows — a permanently-transparent **Render Window** (the
only thing OBS ever targets) and a **Control Panel** for building the rig,
tuning motion/audio, and going live.

Split out 2026-09-19 into its own repo from the [`obs`](https://github.com/iDoMeteor/obs-config)
repo (jj's OBS Studio management repo), where it started life as a
companion app. History from that period is preserved here via a
subdirectory rewrite; `obs`'s own git log still has the combined
pre-split history for context.

## Status

See [`docs/PLAN.md`](docs/PLAN.md) for current status, the full feature
history, and what's still open — its top section is a refreshed snapshot,
kept current; everything below that is a dated build log.

## Running it

```
cd unicorn-cloak
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m unicorn_cloak
```

Escape (or the Control Panel's Quit button) quits, with a confirmation
and an extra warning if the avatar has unsaved changes. Set
`UNICORN_CLOAK_DEBUG=1` to see startup diagnostics normally hidden as
environment noise (see `docs/PLAN.md`'s "Startup noise hidden" entry).

## Tests

```
.venv/bin/pytest
```

Qt runs headless via `QT_QPA_PLATFORM=offscreen` (set automatically by
`tests/conftest.py`). 530 tests as of 2026-09-23.

## Layout

```
docs/            plan/status doc, decision records, superseded setup notes
src/unicorn_cloak/   the app (rig, renderer, audio, control panel, persistence)
assets/          bundled default avatar art (unicorn-demo)
tests/           pytest suite, one file per module
spike/           throwaway scripts from early de-risking work
```

## Docs

- [`docs/PLAN.md`](docs/PLAN.md) — plan, status, full build log
- [`docs/decisions/`](docs/decisions/) — short decision records, numbered `NNNN-slug.md`
- [`docs/avatar-lipsync-setup.md`](docs/avatar-lipsync-setup.md) — the superseded PNGTuber-Plus setup this app replaced
