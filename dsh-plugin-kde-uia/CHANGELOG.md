# Changelog

All notable changes to `dsh-plugin-kde-uia` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) for both the plugin and the Python
client. **Compatibility** notes name the DSH runtime and anything a future release could break.

**Status note (v0.1.0):** this is a student's side project and has not been run against a live
KDE Plasma desktop yet. All tests and checks so far ran on a Windows host plus an Ubuntu 24.04
WSL server that has neither PyGObject nor KWin. The Arch package names, the KWin scripting
bridge and the Wayland input path were worked out from documentation and code logic rather
than confirmed by a run — see ["Verification status"](#verification-status) below.

## Compatibility

| Plugin | DSH | Python | Plasma | Primary distro |
|---|---|---|---|---|
| 0.1.0 | 0.2.0-rc.2 (exact peer) | 3.9+ | 5.x / 6.x, Wayland or X11 | **Arch Linux** |

## [Unreleased]

### Fixed

- **KWin scripting on machines without a KConfig CLI now degrades instead of breaking.**
  The backend used to accept `busctl`/`gdbus` as its D-Bus tool and only fail later, when
  the bridge tried to write the script's config section. It now rejects an incapable tool
  at construction time with a hint naming the right package per distribution, so `auto`
  falls through to the X11 or AT-SPI backend. Found and reproduced while checking Arch
  Linux support.
- **Every installation hint now names the Arch package first**, and the Arch names were
  verified against the Arch package database / AUR:
  - AT-SPI runtime: `python-gobject` + `at-spi2-core` (which ships `Atspi-2.0.typelib`);
    Arch has **no** `gir1.2-atspi-2.0` package.
  - KWin bridge: `qt6-tools` (`qdbus6`) + `kconfig` (`kwriteconfig6`/`kreadconfig6`);
    the old hint said `kconfig-cli`, which does not exist on Arch.
  - `kdotool` is **AUR-only** on Arch (`yay -S kdotool`); the old text claimed an official repo.
  - `read_config()` can now fall back to `kreadconfig6` when `qdbus` is unavailable.
- `input.py` used a distro hint helper without importing it (would have raised `NameError`
  when a key backend was missing).

### Added

- `MAINTENANCE.md` — what the maintainer can and cannot promise, and how someone else can
  take over (tests, architecture doc, release checklist).
- `.github/ISSUE_TEMPLATE/` — an issue template that asks for `kde_uia_doctor` output first,
  so reports are actionable even when the maintainer is offline.
- `types/index.ts` — a TypeScript *template* of the plugin shape for whoever maintains this
  next (checked by `npm run check:ts`, no download needed).
- `tests/test_pure.py::DistroHintTests` — pins the Arch package names and the KWin-bridge
  degradation, so a "helpful" hint edit cannot silently send users to a wrong package.
- `scripts/publish/git-init.sh` + `git-push.sh` — create the repository and push it without
  touching the system description: the archive is generated from tracked files only, so
  the project's own README survives a push.

### Verification status

| Area | Verified? | How |
|---|---|---|
| Tool declarations compile with the host's real `defineTool` | **yes** | tests with packages extracted from a DSH 0.2.0-rc.2 install |
| JSON-Schema gate + argument validation | **yes** | `scripts/smoke-dsh-load.mjs` against real DSH modules |
| WSL transport (wsl.exe → python client → JSON) | **yes** | live integration test on a Windows host |
| Shell quoting / Unicode argument round-trip | **yes** | live test with `$(…)`, backticks, quotes |
| AT-SPI tree / find / refs / clicks | **no** (unit tests on a fake tree only) | no a11y bus available here |
| KWin scripting bridge | **no** | needs a running KWin |
| Wayland input via kdotool | **no** | needs Plasma Wayland |
| Snapshots (kwin/shadow buffer, spectacle, grim) | **no** | needs a compositor |

If you run it on a real desktop, please open an issue (or a PR fixing this table) with the
`kde_uia_doctor` output — that is the single most useful contribution right now.

## [0.1.0] — 2026-10-21

First release.

### Added

- **Plugin (Node, no dependencies)**
  - Tools registered through DSH's own `defineTool` (13 tools: `kde_uia_doctor`, `kde_uia_windows`,
    `kde_uia_tree`, `kde_uia_find`, `kde_uia_info`, `kde_uia_click`, `kde_uia_keys`,
    `kde_uia_type`, `kde_uia_set_value`, `kde_uia_scroll`, `kde_uia_wait_for`,
    `kde_uia_screenshot`, `kde_uia_activate`), each with a typed JSON-Schema parameter set and a
    text renderer for the model.
  - Runtime transports: `wsl` (through `wsl.exe`), `ssh` (Windows OpenSSH via PowerShell,
    POSIX `ssh` elsewhere) and `local`, with `auto` detection, explicit config, client
    auto-discovery and per-call cancellation through `exec.signal`.
  - `readOnly` deployment switch; `doctorOnLoad` capability probe that logs actionable warnings
    without ever breaking plugin load.
  - `dsh.bundle.patch` metadata (`cordis.patch.yml` with one `tool-kde-uia` row).
- **Python client (`kde_uia`, vendored in `python/`)**
  - AT-SPI2 element model: applications, windows, depth-limited trees, selectors
    (role/name/text/description/states/attributes, exact/contains/regex), stateful `uia:` refs.
  - Window backend: KWin scripting over `org.kde.KWin`/`/Scripting` (X11 + Wayland), X11
    fallback through `wmctrl`/`xdotool`, pure-AT-SPI enumeration.
  - Input: AT-SPI actions and editable-text insertion, `xdotool`, `kdotool`, clipboard
    fallback, `dry-run`; screen/device-pixel coordinate mapping for HiDPI.
  - Screenshots: KWin shadow buffer, `spectacle`, `grim`, ImageMagick `import`, `xwd`, XDG
    Screenshot portal (explicit only).
  - Waiting/retry helper with last-state diagnostics; coded error taxonomy with hints.
  - CLI (`kde-uia …`) with human output and `--json`, plus the `python -m kde_uia ops` JSON
    protocol used by the plugin.
- **Tests** — 46 Python tests (pure logic + an in-memory AT-SPI tree), 37 Node tests including
  compiling every tool with the *real* harness `defineTool` when a DSH installation is present.
- **Docs** — English and Chinese README (scope, install, compatibility, security, limits,
  troubleshooting), SECURITY.md, this changelog, `docs/tools.md`, `docs/architecture.md`,
  `docs/protocol.md`.

### Known limitations (from this release)

- Refs are paths and invalidate on widget insertion/removal.
- No AT-SPI event streaming; waits poll.
- Applications without accessibility expose a single node.
- Windows→SSH requires an explicit `remotePath`.
