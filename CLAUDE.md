---
applyTo: "**"
---

# Unicorn Cloak — Agent Rules & Operating Standards

This file governs all AI-assisted work in `~/Repos/unicorn-cloak`. Read it in
full before touching code or docs. Status and history live in
`docs/PLAN.md` (top section is a refreshed snapshot; everything below is a
dated build log); design choices live in `docs/decisions/`.

Split out 2026-09-19 from the `obs` repo, where this app started as a
companion project — see the README for that history. It is now a fully
independent repo with its own private GitHub remote
(`origin`, `iDoMeteor/unicorn-cloak`); none of the OBS-management rules
from that repo's `CLAUDE.md` apply here except where this file says so.

---

## Project Identity

**unicorn-cloak** is a from-scratch PySide6 replacement for
**PNGTuber-Plus**: a mic-reactive, layered-sprite avatar overlay window
that OBS captures as a window/portal source. Two windows — a
permanently-transparent **Render Window** (the only thing OBS ever
targets, deliberately excluded from all app theming) and a **Control
Panel** for building the rig, tuning motion/audio, and going live.

Explicitly **not chasing legacy-parity** with PNGTuber-Plus's behavior or
quirks — the goal is *better and unique*, not a faithful port. Don't
reintroduce PNGTuber-Plus's design just because that's "how it worked
there."

**Platform.** Python 3.11+ (dev pinned to 3.14.6, see `requirements.txt`),
PySide6/Qt, developed on Fedora 44/Wayland. Qt runs headless in tests via
`QT_QPA_PLATFORM=offscreen` (set in `tests/conftest.py`) — don't remove
that or tests will try to open real windows in CI-like environments.

---

## Repository Layout

```
CLAUDE.md          this file
README.md          entry point: what this is, how to run it, layout
docs/              canonical documentation (docs/README.md is the index)
  PLAN.md          plan, current status, full dated build log
  decisions/       short decision records (NNNN-slug.md), numbered from 0001
  avatar-lipsync-setup.md   superseded: the PNGTuber-Plus setup this replaced
src/unicorn_cloak/ the app: rig, renderer, audio, control panel, persistence
assets/            bundled default avatar art (unicorn-demo)
tests/             pytest suite, one file per module
spike/             throwaway scripts from early de-risking work
```

New top-level directories require a line in this table.

---

## Secrets & Local State (Hard Rule)

This app has no cloud credentials today, but treat local machine state the
same way secrets are treated: it never enters git.

- `settings.json` (window geometry, selected audio device, etc.) is
  gitignored — it's per-machine, not project state.
- `*.bak` files (settings backups, and `persistence.py`'s automatic
  version-upgrade-and-backup copies of `.uc`/`.save` avatar files) are
  gitignored — they're generated, not authored.
- If a future feature adds any real credential (a streaming service token,
  an API key), it follows the same rule the `obs` repo uses: never in a
  commit, a doc, a log excerpt, or a chat message; add the pattern to
  `.gitignore` immediately.

---

## Testing (Hard Rule)

- Every module under `src/unicorn_cloak/` gets a matching
  `tests/test_<module>.py`. This project has a track record of real bugs
  caught by these tests (or a dedicated review pass) — a bounce-retrigger
  physics bug, a scene-rebuild crash, a silently no-op Move Up/Move Down,
  an Escape-hijack hotkey bug — treat the suite as load-bearing, not
  decorative.
- Run `.venv/bin/pytest` before calling any change done. Qt tests need the
  `qapp` fixture from `tests/conftest.py`, not a raw `QApplication()`.
- When a performance fix is claimed, back it with a real measurement (a
  `perf` sampling profile or equivalent), not intuition — see PLAN.md's
  4.3x/9.1x audio-thread fixes for the standard this project holds itself
  to. Don't claim "near-zero" or similar without the number behind it.

---

## Documentation SOP

- Canonical docs live under `docs/`; `docs/README.md` is the index and
  every doc must be linked from it.
- Root-level markdown is reserved for `README.md` and `CLAUDE.md`. Planning
  notes, decision records, and superseded setup docs go under `docs/`.
- `docs/PLAN.md`'s top section is a living, refreshed snapshot of current
  status — keep it current when a milestone or notable fix lands.
  Everything below that line is an append-only dated build log: add to it,
  don't rewrite past entries (if a past entry turns out wrong, correct it
  by adding a new dated note, the way the transform-hierarchy bugs section
  already does, not by silently editing history).
- Decision records live in `docs/decisions/NNNN-slug.md` with `Status`,
  `Date`, `Context`, `Decision`, `Alternatives`, `Consequences`. Numbering
  is local to this repo, starting at `0001`. Reverted decisions stay in
  place, marked superseded — never delete or renumber.
- Do not create new `.md` files for routine changes; update the existing
  doc (PLAN.md for status, the relevant decision record for a reversed
  choice).

---

## Git Conventions

- **Commit (and push) after every substantial amount of work, without
  waiting to be asked** — a feature, a bug fix, a documentation update.
  Not every single file edit, and never mid-edit or before a claim (a
  perf fix, a bug fix) has been validated by running the tests. This
  repo now carries the same override the `obs` repo uses, reversing the
  earlier "only commit when asked" default.
- After pushing, confirm local `main` is actually in sync with
  `origin/main` (`git status`/`git log` — no unpushed commits, no
  divergence) before considering the iteration done, so the local
  checkout a dev works from is never quietly behind what's on GitHub.
- Commit with an imperative, ≤72-char subject and a body that says *why*,
  matching the existing log's style (`git log --oneline` for examples).
- Never commit `settings.json`, `*.bak` files, `.venv/`, `__pycache__/`, or
  anything under `.pytest_cache/`/`*.egg-info/` — `.gitignore` covers
  these; if a new generated-artifact pattern shows up, add it there rather
  than relying on a parent repo's `.gitignore` (there isn't one anymore).
- **Git History Safety (Hard Stop):** never detach `HEAD`, never `git
  rebase`, `git cherry-pick`, `git reset --hard`, or any force-push,
  without the owner explicitly asking for that specific operation. Stop
  and report the blocker and safe alternatives instead.

---

## Agent Autonomy — Tool Execution

No permission needed for:

- Reading anything: `cat`, `grep`, `find`, `ls`, `git status/log/diff`,
  running the test suite, running the app.
- Writing inside this repo (code, tests, docs) as part of an agreed task.
- Committing and pushing to `origin` after a substantial amount of
  validated work (see Git Conventions above) — no longer gated behind
  asking first.

Permission **is required** before:

- Installing, updating, or removing a dependency (`pyproject.toml`,
  `requirements.txt`).
- Any destructive git operation (see Git History Safety above).
- Deleting or overwriting `assets/unicorn-demo/` (the owner's authored
  demo avatar) or any file outside this repo.

---

## Sub-Agents (Hard Rule)

- Do not spawn sub-agents (the `Agent` tool, or equivalent task-delegation
  tools) for routine work in this repo — reading files, grepping,
  targeted investigation, making edits, running tests. Do that work
  directly, in the main conversation, so it stays visible and easy to
  follow along with in real time.
- Sub-agents are for genuinely long-running background tasks only —
  something the owner explicitly wants kicked off to run independently
  while other work continues, not a default way to parallelize or
  offload exploration.
- When in doubt, don't delegate — ask first rather than reaching for a
  sub-agent as a shortcut.

---

## What the Agent Should NOT Do

- Do not chase PNGTuber-Plus parity as a goal in itself (see Project
  Identity above) — the owner dropped that target 2026-09-15.
- Do not add global hotkeys for costume/expression switching — the owner
  rejected them outright (collision risk with other system hotkeys);
  focus-only is a deliberate decision, not an oversight.
- Do not apply `theme.py`'s QSS styling to the Render Window — it must
  stay visually untouched since OBS captures it directly.
- Do not claim a performance improvement without a measurement.
- Do not create new top-level directories without adding them to the
  Repository Layout table above.
- Do not create new `.md` files for routine changes.

---

## Preferred Tools

| Purpose | Tool | Notes |
|---------|------|-------|
| Tests | `pytest` via `.venv/bin/pytest` | Headless Qt (`QT_QPA_PLATFORM=offscreen`), see `tests/conftest.py` |
| Env/deps | `.venv` + `pip install -e ".[dev]"` | Pin changes in `requirements.txt` with the validation note (Python version, OS, date) already there |
| JSON edits (`.uc`/`.save` avatar files) | Python `json`, never text substitution | These are hand-editable but app-owned; prefer going through `persistence.py`/the app itself when testing a real fix |

---

## Owner Interaction Notes

- The owner iterates against real screenshots and the running app, not
  just code review — expect follow-up rounds on any UI change.
- When a bug report can't be fully resolved (missing art, an ambiguous
  spec), finish everything else, state exactly what's blocked and why in
  `docs/PLAN.md`'s build log, and let the owner decide rather than
  guessing.
