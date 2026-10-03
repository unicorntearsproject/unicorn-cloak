# Unicorn Cloak — Installation Plan

**Status:** proposed, 2026-10-02. Nothing in this plan is built yet.
**Source:** adapted from unicorn-viz's installer work
(`../unicorn-viz/tools/install*`, `tools/install/`, `tools/launchers/`,
`tools/packaging/`, and `docs/planning/installers.md`). The goal is to use the
same methods here, so both apps install, update and uninstall the same way.

Today the only way to run Unicorn Cloak is a dev checkout (`python3 -m venv
.venv && pip install -e ".[dev]"`, then `python -m unicorn_cloak`). This plan
takes it to a one-line install with a menu entry and icon, then signed native
packages, then Windows.

---

## 1. Methods adopted from unicorn-viz

The ask was to use all of unicorn-viz's methods. Each one is listed here, so
nothing is silently dropped. The few that don't apply say why.

| # | unicorn-viz method | Here | Notes |
|---|--------------------|------|-------|
| M1 | **Shared shell library** (`tools/install/lib.sh`) used by both the dev installer and the public one-liner: logging, an `ERR` trap that prints the failing line, `die`, `run` that honors `--dry-run`, `sudo` only when not root, `curl` fetch with retry | **Adopt** | Prefix `uc_` instead of `uv_` |
| M2 | **Distro detection** from `/etc/os-release` `ID` and `ID_LIKE` → apt / dnf / pacman families, with a clear manual-install message for anything else | **Adopt** | Package sets in §4 |
| M3 | **Bundled python-build-standalone runtime** by default (`fetch_runtime.sh`: pinned version, checksum-verified, prints only the interpreter path on stdout); `--system-python` to opt out | **Adopt** | Pin a CPython 3.14.x **GIL** build to match the dev pin (3.14.6). unicorn-viz's free-threaded `ft` flavor is not needed: PySide6 has no cp314t wheels and this app gains nothing from it |
| M4 | **Venv + pip install of the project** from the bundled runtime (`--prefer-binary`, pip and wheel upgraded first) | **Adopt** | Pins from `requirements.txt`, then `pip install .` |
| M5 | **Dev installer from a clone** (`tools/install_linux.sh`: `--python`, `--system-python`, `--no-deps`, `--dry-run`) | **Adopt** | |
| M6 | **Public curl-to-bash one-liner** (`install.sh`): `--prefix`, `--version`, `--channel`, `--no-deps`, `--no-desktop`, `--system`, `--uninstall`, `--dry-run` | **Adopt** | §6 |
| M7 | **Installer hardening:** `set -Eeuo pipefail`, ERR and cleanup traps, refuse root unless `--system`, `curl -fsSL --retry 3 --retry-delay 2`, no `eval`, no `curl \| sudo bash`, one `sudo -v`, idempotent re-run upgrades in place | **Adopt** | |
| M8 | **Desktop integration:** canonical `.desktop`, hicolor icon ladder, a `~/.local/bin` *wrapper script* (not a bare symlink) that exports the app root, `update-desktop-database` / `gtk-update-icon-cache` best-effort, warning if `~/.local/bin` isn't on PATH | **Adopt** | The `.desktop` basename **must** be `unicorn-cloak.desktop`, see §5 |
| M9 | **Uninstaller** (`tools/install/uninstall_linux.sh`, `install.sh --uninstall`): remove prefix, wrapper, `.desktop`, icons, refresh caches | **Adopt** | Never deletes user settings or avatars (§3) |
| M10 | **App-root env var** (`UNICORNVIZ_APP_ROOT`) so a pip-installed package finds assets that live outside site-packages | **Adopt** | `UNICORN_CLOAK_APP_ROOT`, see P3 |
| M11 | **Curated payload by allowlist** (`stage_payload.sh`): ship only the package, runtime assets and pip metadata — never `.git`, venvs, logs, `settings.json`, `notes`, `spike/` | **Adopt** | |
| M12 | **`manifest.json` as the single source of truth** for latest version and artifact URLs (stable / prerelease channels; merged, never overwritten; `manifest.py update/show`) | **Adopt** | Required here, not just nice: the repo is **private**, so a raw-GitHub one-liner can't work (§6) |
| M13 | **Self-hosted object storage** (Cloudflare R2, zero egress) behind a vanity URL; build host decoupled from distribution host; `release.sh --s3-url --endpoint-url` sync | **Adopt** | Host and domain are an owner decision (§12) |
| M14 | **`git tag vX.Y.Z` for provenance**, with tag and commit SHA stamped into every artifact | **Adopt** | |
| M15 | **`release.sh`**: one command builds, stages and optionally publishes `<dest>/<version>/…` plus a merged `manifest.json` | **Adopt** | |
| M16 | **`SHA256SUMS` + detached GPG `.asc`**; public key committed as `docs/release-key.asc` and on keys.openpgp.org; `sha256sum -c` always, `gpg --verify` when available | **Adopt** | |
| M17 | **Native `.deb` / `.rpm` via fpm** (`build_native.sh`): FHS layout under `/opt/<app>` with a bundled runtime, postinst cache refresh, prerm cleanup, `dpkg-sig` / `rpm --addsign` | **Adopt** | §7 |
| M18 | **Windows PowerShell installer** (`install_windows.ps1` with `-Skip*` switches), **`.bat` wrapper**, and a **WinForms GUI installer** (`install_windows_gui.ps1`) | **Adopt** | §8, phase 6 |
| M19 | **Windows portable zip**, cross-built on any host (`build_windows_portable.sh`: PBS Windows runtime, `pip --platform --target`, `.cmd` launcher setting the app root, `--self-test`) | **Adopt** | |
| M20 | **Inno Setup `.exe`**: per-user or per-machine, Start-menu and desktop entries, Apps & Features uninstaller | **Adopt** | After the portable zip works |
| M21 | **Signing gated on CI secrets:** an unset secret means an unsigned artifact plus a loud WARN, never a failed release (signtool OV/EV, later Apple codesign/notarytool) | **Adopt** | |
| M22 | **★1–★5 quality rubric per channel** (exists → clean-room → self-contained → automated and verified → trusted and discoverable), with a "solo-dev escape hatch" for unsigned ★5 | **Adopt** | §10 |
| M23 | **CI and QA:** shellcheck as a hard gate; nightly clean-container install smoke asserting `<app> --help` / `--self-test`; local builds aren't clean-room | **Adopt** | §9 |
| M24 | **Launcher `--self-test`** flag | **Adopt** | P5 |
| M25 | **Distro ffmpeg fallback** (Fedora: try `ffmpeg` from RPM Fusion, else warn with the enable command) | **Adopt** | ffmpeg is optional here (File playback only), so warn, never fail |
| M26 | **Flatpak / Snap** (Flathub / Snap Store) | **Defer** | Sandbox risks are real for this app: JACK/PipeWire capture, the Wayland portal identity OBS relies on, and localhost obs-websocket. Evaluate after ★4 on native channels |
| M27 | **macOS** unsigned `.dmg` + Homebrew tap; notarization deferred | **Defer** | No Mac hardware or test path yet; same deferral unicorn-viz took |
| M28 | Prebuilt **cp314t wheelhouse** + trust file (`fetch_wheelhouse.sh`, `wheelhouse-*.sha256`) | **N/A** | Only exists because PyPI lacks free-threaded wheels for unicorn-viz's GPU/MIDI deps. Every dependency here has normal PyPI wheels. Revisit only if a dependency loses wheels |
| M29 | **Drop-in dependency manager** (`dropins install`, per-drop-in requirements, `--no-deps` package exceptions, CPU-only torch preinstall) | **N/A** | Unicorn Cloak has no plugin or drop-in system |

---

## 2. Install layout

| What | Per-user (default) | System (`--system` / `.deb` / `.rpm`) |
|------|--------------------|---------------------------------------|
| App root (payload, runtime, venv) | `~/.local/share/unicorn-cloak/` | `/opt/unicorn-cloak/` |
| Bundled runtime | `<root>/runtime/python/` | same |
| Venv | `<root>/venv/` | same |
| Launcher | `~/.local/bin/unicorn-cloak` (wrapper) | `/usr/bin/unicorn-cloak` |
| Desktop entry | `~/.local/share/applications/unicorn-cloak.desktop` | `/usr/share/applications/` |
| Icons | `~/.local/share/icons/hicolor/<N>x<N>/apps/unicorn-cloak.png` | `/usr/share/icons/hicolor/…` |
| **User settings** | `~/.config/unicorn-cloak/settings.json` | same (always per user) |
| **User avatars** | `~/.local/share/unicorn-cloak-data/avatars/` | same (always per user) |

User data (settings, avatars, `.bak` files) **never lives under the app
root**. Upgrades and uninstalls can then replace or remove the root without
touching anything the owner made. User avatars sit in a sibling directory
for exactly this reason; the paths should come from Qt's
`QStandardPaths` (`AppConfigLocation` / `AppDataLocation`) so Windows and macOS
get correct locations for free.

---

## 3. Phase 0 — Make the app installable (code prerequisites)

None of the installers can work until these land. They are code changes in
`src/unicorn_cloak/`, each with tests, per CLAUDE.md.

- **P1. Console entry point.** Add `[project.scripts] unicorn-cloak =
  "unicorn_cloak.__main__:run"`, where `run()` does exactly what the
  `if __name__ == "__main__"` block does today: `main()`, flush,
  **`os._exit(code)`**. A console script calls the function directly, so
  without this the PortAudio atexit hang documented in `__main__.py`
  (2026-09-17) comes back for every installed user. Keep `python -m
  unicorn_cloak` working through the same `run()`.
- **P2. Move settings out of the repo root.** `config.DEFAULT_STATE_PATH` is
  `Path(__file__).parents[2] / "settings.json"`. Installed, that points
  inside the venv's `lib/` directory. Switch to the XDG config dir (§2),
  overridable with `UNICORN_CLOAK_CONFIG`. **Migration:** on first launch,
  if the new path doesn't exist but the old repo-root `settings.json` does,
  copy it over once, keeping the old file and its `.bak`. A dev checkout
  keeps working unchanged, since the env var or the migration covers it.
- **P3. Assets and the default avatar.**
  - Declare `src/unicorn_cloak/assets/fonts/*` as package data in
    `pyproject.toml`. Today they're only found because the dev install is
    editable.
  - `DEFAULT_AVATAR_PATH` also resolves via `parents[2]` to
    `assets/unicorn-demo/`, outside the package. Ship the demo avatar in
    the payload, located via `UNICORN_CLOAK_APP_ROOT` (the M10 pattern,
    with the repo root as fallback for dev).
  - **On first run, copy the demo avatar into the user avatars dir and open
    that copy.** The shipped file is read-only under `/opt`, would be
    overwritten by every upgrade, and is the owner's master copy
    (CLAUDE.md), so Save must never write into the install tree.
- **P4. App icon.** No icon exists yet. Needs a square master, at least
  512×512 and ideally SVG. **This is owner art (§12).** Generate the 48 / 64 /
  128 / 256 / 512 PNG ladder at release time (`magick`), and also set it as
  the window icon in-app (`QApplication.setWindowIcon`).
- **P5. `--version` and `--self-test` flags** in `run()`:
  - `--version` prints the version and the stamped tag and commit.
  - `--self-test` runs headless (`QT_QPA_PLATFORM=offscreen`): import
    PySide6 and Qt Multimedia, load the bundled demo avatar, list audio
    devices without opening a stream, check for `ffmpeg` (warn only), then
    exit 0/1. This is what every installer's final step and the nightly CI
    smoke run.
- **P6. Version source of truth.** `pyproject.toml`'s `version` (currently
  `0.0.1`) is the source. `release.sh` refuses to run unless `git describe`
  shows a matching `vX.Y.Z` tag on a clean tree. Write `_build_info.py`
  (tag and commit) into the staged payload only, never into the repo.
- **P7. LICENSE.** There is no LICENSE file and no `license` in
  `pyproject.toml`. Package metadata (fpm, Inno Setup, manifests) needs one.
  **Owner decision (§12).**
- **P8. Optional `[project.optional-dependencies]`:** keep `dev = ["pytest"]`.
  Installers never install dev extras.

---

## 4. Phase 1 — Dev installer from a clone (★1→★3 for contributors)

Files:
```
tools/install/lib.sh            shared library (M1, M2, M7, M8, M9)
tools/install_linux.sh          thin wrapper for clones (M5)
tools/install/uninstall_linux.sh
tools/packaging/fetch_runtime.sh   pinned PBS CPython 3.14.x GIL, sha256-verified (M3)
tools/launchers/linux/unicorn-cloak.sh   run from a clone: prefers .venv, else python3 -m
```

`tools/install_linux.sh [--system-python] [--python BIN] [--no-deps]
[--dry-run]` follows unicorn-viz's flow: system deps → provision the runtime
into `.venv-runtime/` → build `.venv` from it → `pip install -r
requirements.txt` → `pip install -e ".[dev]"` (editable for contributors) →
`unicorn-cloak --self-test`.

**System packages** (runtime only; Python comes from the bundled runtime).
These names are from memory and **must be confirmed in clean containers**
in phase 8 before release:

| Family | Packages | Why |
|--------|----------|-----|
| dnf (Fedora/RHEL) | `portaudio` `pipewire-jack-audio-connection-kit` `libxkbcommon-x11` `xcb-util-cursor` `mesa-libEGL` `fontconfig`; `ffmpeg` (RPM Fusion) else `ffmpeg-free`, warn only | sounddevice needs the system PortAudio on Linux. **`audio.py` deliberately excludes raw ALSA devices and relies on PipeWire's JACK shim**, so without pipewire-jack the device list comes up empty. The Qt 6.5+ xcb plugin needs `libxcb-cursor` |
| apt (Debian/Ubuntu) | `libportaudio2` `pipewire-jack` `libxkbcommon-x11-0` `libxcb-cursor0` `libegl1` `libfontconfig1` `ffmpeg` | same |
| pacman (Arch) | `portaudio` `pipewire-jack` `libxkbcommon-x11` `xcb-util-cursor` `ffmpeg` | same |

The installer's last check: if `--self-test` reports zero usable input
devices, print a pointed message ("install the PipeWire JACK shim:
`<pkg>`") instead of letting the owner find out from an empty dropdown.

---

## 5. Phase 2 — Desktop integration

One canonical file, shipped by every Linux channel (M8):

```ini
[Desktop Entry]
Version=1.0
Type=Application
Name=Unicorn Cloak
GenericName=Avatar Overlay
Comment=Mic-reactive layered-sprite avatar for OBS
Exec=unicorn-cloak %U
Icon=unicorn-cloak
Terminal=false
Categories=AudioVideo;Video;
Keywords=pngtuber;vtuber;avatar;obs;stream;overlay;
StartupNotify=true
StartupWMClass=unicorn-cloak
```

- **Basename must be exactly `unicorn-cloak.desktop`.** `__main__.py` calls
  `setDesktopFileName("unicorn-cloak")` (`render.APP_ID`). On Wayland that is
  the app_id the compositor, and xdg-desktop-portal's screencast
  restore-token matching (what lets OBS skip the picker on relaunch), tie
  back to a desktop entry. An installed `.desktop` with a different name
  breaks that link. Verify it as part of the phase 8 checks (the
  PLAN.md cutover check).
- The per-user wrapper `~/.local/bin/unicorn-cloak` exports
  `UNICORN_CLOAK_APP_ROOT=<prefix>` and runs `<prefix>/venv/bin/unicorn-cloak "$@"`.
  Use a wrapper rather than a symlink (unicorn-viz's reasoning).
- Remove the dev-only launcher's hardcoded-path `.desktop` pattern: the
  unicorn-viz repo still has one with `/home/j/...` baked in. Generate
  entries instead of committing machine paths.

---

## 6. Phase 3 + 4 — Release pipeline and the public one-liner

**Release (`tools/packaging/release.sh`, M11–M16):**
1. Preconditions: clean tree, `vX.Y.Z` tag at HEAD matching `pyproject.toml`,
   test suite green.
2. `stage_payload.sh --dest build/payload`, allowlist only: `src/unicorn_cloak/`
   (with `assets/fonts`), `assets/unicorn-demo/` (art, `.uc`, README — not
   `master_reference.png` unless the owner wants it shipped), `pyproject.toml`,
   `requirements.txt`, `README.md`, `LICENSE`, `_build_info.py`.
3. Produce `<dest>/<version>/unicorn-cloak-<version>.tar.gz` and later the
   `.deb` / `.rpm`, then `SHA256SUMS` and `SHA256SUMS.asc`.
4. `manifest.py update` merges `<dest>/manifest.json` (channels `stable` /
   `prerelease`; schema shared with unicorn-viz so one tool serves both).
5. Optional `--s3-url … --endpoint-url …` sync to R2.

**One-liner (`install.sh` at the repo root, M6/M7/M12):**
```bash
curl -fsSL https://<host>/unicorn-cloak/install.sh | bash
curl -fsSL https://<host>/unicorn-cloak/install.sh | bash -s -- --channel prerelease
```
Because the GitHub repo is **private**, `install.sh` itself, the manifest and
all artifacts are served from the distribution host. Nothing reads from
GitHub at install time.

Flow:
1. refuse root (unless `--system`) → detect distro → system deps
2. read the manifest → pick version or channel → download tarball and `SHA256SUMS`
3. `sha256sum -c`, then `gpg --verify` if `gpg` and the key are present
4. provision the bundled runtime → venv → `pip install .`
5. desktop integration → `unicorn-cloak --self-test` → summary (version,
   paths, how to launch, how to uninstall)

**Re-running upgrades in place:** the app root is rebuilt; `~/.config` and
the user data dir are never touched (§2).

---

## 7. Phase 5 — Native `.deb` / `.rpm` (M17)

- `tools/packaging/build_native.sh` runs fpm inside a target-distro container
  (`fedora:44`, `debian:13`, `ubuntu:24.04`). Fedora is first, since it's the
  owner's platform.
- `/opt/unicorn-cloak/{runtime,venv,payload}` with the bundled runtime and
  shebangs rewritten to `/opt/unicorn-cloak/venv/bin/python`;
  `/usr/bin/unicorn-cloak` is a wrapper that sets the app root.
- Declared runtime dependencies are the §4 system packages; ffmpeg is
  *Recommends* / weak, never *Requires*.
- postinst runs `update-desktop-database` and `gtk-update-icon-cache`; prerm
  removes the wrapper only if it's ours.
- Sign with `rpm --addsign` / `dpkg-sig` using the release key.
- Publish to the same `<version>/` directory; manifest artifact keys
  `rpm-x86_64` / `deb-amd64`. A dnf/apt repository is post-v1.

---

## 8. Phase 6 — Windows (M18–M21)

Order: **portable zip first** (it can be built on Linux), then the PowerShell
installer, then Inno Setup.

- `build_windows_portable.sh`: PBS Windows CPython, dependencies
  cross-installed with `pip --platform win_amd64 --only-binary=:all:
  --target`, `unicorn-cloak.cmd` setting the app root,
  `UnicornCloak-Portable-<version>-win-x64.zip`. Must be **verified on real
  Windows** (double-click, then `unicorn-cloak.cmd --self-test`).
- `tools/install_windows.ps1` (`-SkipFfmpeg`, `-SkipShortcuts`, per-user
  `%LocalAppData%\Programs\UnicornCloak`, Start-menu shortcut via
  `WScript.Shell`), a `.bat` wrapper, and `install_windows_gui.ps1` (WinForms).
- Then Inno Setup `UnicornCloak-Setup-<version>.exe`, signed with signtool when
  the cert secret exists (M21).

**Windows-specific risks to resolve before ★2:**
- `audio.py`'s device filtering is written around Linux (it excludes ALSA
  and expects the JACK shim). On Windows, PortAudio exposes the same device
  under MME, DirectSound, WASAPI and WDM-KS, so the dropdown will be full of
  duplicates. Needs a Windows host-API preference (WASAPI) in `audio.py`.
- **Desktop Audio has no "monitor" device on Windows** without WASAPI
  loopback, which needs explicit support.
- The Render Window's transparency must be checked with OBS's Windows
  Window Capture and Game Capture.
- `os._exit` and the PortAudio teardown behave differently there; re-verify
  that quitting is clean.

---

## 9. Phase 8 — CI and QA (M22–M24)

- **Lint:** `shellcheck` on every `tools/**/*.sh` and `install.sh` (fail on
  warnings); PSScriptAnalyzer on `*.ps1`.
- **Unit:** the existing `.venv/bin/pytest`, plus tests for P1–P6
  (entry-point `os._exit`, XDG path and migration, first-run avatar copy,
  `--self-test` exit codes).
- **Installer dry runs in CI:** `install.sh --dry-run` and
  `tools/install_linux.sh --dry-run` on each distro family.
- **Nightly clean-container smoke** (Fedora, Debian, Ubuntu, Arch): run the
  real one-liner against a staging manifest, then `unicorn-cloak --version`,
  then `unicorn-cloak --self-test`, then `install.sh --uninstall`, then
  assert no leftovers outside the user data dirs.
- **Manual release checklist** (the owner's real machine, per CLAUDE.md's
  "iterates against the running app"): menu entry and icon appear; OBS
  captures the Render Window transparently; OBS skips the portal picker on
  relaunch; the mic and Desktop Audio device lists are populated; quitting
  doesn't hang the terminal.

---

## 10. Channel scorecard targets (M22)

| Channel | v1 target | ★5 path |
|---------|-----------|---------|
| Dev installer (clone) | ★3 | n/a (contributors) |
| `install.sh` one-liner | ★4 | GPG-signed sums + vanity URL |
| `.rpm` (Fedora) | ★4 | signed + dnf repo (post-v1) |
| `.deb` | ★3 | signed + apt repo (post-v1) |
| Windows portable / `.exe` | ★2 → ★3 | OV cert via signtool (gated secret) |
| macOS / Flatpak / Snap | — | deferred (M26, M27) |

---

## 11. Milestones

| Milestone | Contents | Exit criteria |
|-----------|----------|---------------|
| **I0** | Phase 0 (P1–P8) | `pip install .` into a fresh venv + `unicorn-cloak --self-test` passes; dev checkout unaffected; tests green |
| **I1** | Phase 1 + 2 (dev installer, desktop entry, uninstall) | Fresh Fedora 44 container → `tools/install_linux.sh` → menu entry, launches, uninstall leaves only user data |
| **I2** | Phase 3 + 4 (payload, release, manifest, one-liner) | One-liner installs from a local or staging manifest and `--self-test` passes; checksums verified |
| **I3** | Phase 5 (`.rpm` then `.deb`) | `dnf install ./unicorn-cloak-*.rpm` on clean Fedora works end to end |
| **I4** | Phase 8 (CI + nightly smoke) | Green nightly across distro containers |
| **I5** | Phase 6 (Windows) | Portable zip + `--self-test` verified on real Windows; device-list dedupe done |

I0 is the only milestone that changes app code, and the rest depend on it.

---

## 12. Open questions for the owner

1. **Distribution host and URL.** Reuse unicorn-viz's R2 bucket and domain
   under a `/unicorn-cloak/` prefix, or a separate one?
2. **Release key.** Reuse unicorn-viz's release key (`docs/release-key.asc`
   there) or create a dedicated one?
3. **License** (P7). Which license?
4. **Icon art** (P4). Derive from the unicorn-demo avatar, or new art?
5. **Ship the demo avatar?** It's what a fresh install opens with, so the
   plan assumes yes, minus `master_reference.png`.
6. **Windows timing.** In v1 scope, or after Linux ★4?
7. **Display name.** "Unicorn Cloak" for menus and the Windows Start menu.
   Confirm.
