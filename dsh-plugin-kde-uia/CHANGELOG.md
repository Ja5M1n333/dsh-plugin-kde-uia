# Changelog

All notable changes to `dsh-plugin-kde-uia` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) for both the plugin and the Python
client. **Compatibility** notes name the DSH runtime and anything a future release could break.

**Status note (v0.1.1):** the plugin now runs on a live KDE Plasma desktop. The first field
test (Plasma 6.8.2 / Wayland / Arch, 2026-10-31) found ten defects in the 0.1.0 client; all
are fixed here. It also showed that **keyboard input cannot be delivered on this kind of
Wayland session** — see ["Keyboard input: known limit"](#keyboard-input-known-limit) and
[FIELD-TEST.md](../FIELD-TEST.md).

## Compatibility

| Plugin | DSH | Python | Plasma | Primary distro |
|---|---|---|---|---|
| 0.1.3 | 0.2.0-rc.2 (exact peer) | 3.9+ | 5.x / 6.x, Wayland or X11 | **Arch Linux** |
| 0.1.2 | 0.2.0-rc.2 (exact peer) | 3.9+ | 5.x / 6.x, Wayland or X11 | Arch Linux |
| 0.1.1 | 0.2.0-rc.2 (exact peer) | 3.9+ | 5.x / 6.x, Wayland or X11 | Arch Linux |
| 0.1.0 | 0.2.0-rc.2 (exact peer) | 3.9+ | 5.x / 6.x, Wayland or X11 | Arch Linux |

## [0.1.3] — 2026-10-31

Found while using the plugin on a real task: reading the account usage page
(`platform.deepseek.com/usage`) without a screenshot.

### Added

- **`tree-text` client op.** Reads the accessible text of every node under a
  window, selector or ref, de-duplicated and depth-limited, and returns it as
  plain lines. This is the operation that makes "read the window" possible: on
  the usage page a single call returned 57 lines including `充值余额 ¥5.97`,
  `累计消费金额 ¥99.27`, `API 请求次数 3,920` and `Tokens 546,407,414`.
- `kde_uia_tree` gained `include_text: true`, which appends each node's text to
  its line (web documents keep their content in `section` nodes whose text is
  invisible to a plain tree).

### What this fixes in practice

A web page's real content is **not** in the `document web` node — that node
exposes a single placeholder character. It lives in descendant `section`
nodes, readable only through the Text interface, which 0.1.2 started using but
no operation surfaced. 0.1.3 surfaces it.

### Notes for future readers of this file

- `document web` alone is never enough to read a page; walk down to `section`.
- Keyboard input is still subject to the input method: typing a URL with a
  Chinese IME active produces Chinese characters. Switch to a plain keyboard
  layout first, or use clipboard paste.

## [0.1.2] — 2026-10-31

Second field test: now driven entirely by the agent through the registered
`kde_uia_*` tools rather than the CLI. All changes are additive; nothing in
0.1.1 changes behaviour on a machine without the new inputs.

### Fixed

- **`kde_uia_activate` always failed** with `unknown op 'window-op'`. The tool
  layer sent its internal `window-op` sentinel to the client verbatim; the
  client knows only `activate` and `window` (with an `op`). `lib/tools.js` now
  translates it (`windowOp()`), and a regression test asserts the sentinel can
  never travel to the client again.
- **All text reads returned an empty string.** `TextCapability` called
  `self._a.get_text(start, end)`; in PyGObject the accessor's `get_text()`
  takes no arguments and hands back the accessible, while the real reader is
  `Atspi.Text.get_text(accessible, start, end)`. Every `text` value in a tree,
  `find` or `info` result was blank because of this — including a terminal's
  contents, which is what makes output verifiable without a screenshot.

### Added

- **`ydotool` input backend.** On a Wayland session where XTest is inert,
  kdotool has no input commands and the compositor drops AT-SPI synthetic
  events, key presses could not be delivered at all. When a `ydotoold` socket
  exists (`$YDOTOOL_SOCKET`, else `$XDG_RUNTIME_DIR/.ydotool_socket`), keys,
  typing and pointer clicks now go through `ydotool` first, then AT-SPI, then
  the tool fallbacks. Machines without it keep the 0.1.1 order unchanged.
- `compat.X11_TO_KEYCODE` / `MODIFIER_KEYCODES` / `ydotool_sequence()`: X
  keysym -> Linux input-event key code, so `CTRL+Shift+t` becomes
  `29:1 42:1 20:1 20:0 42:0 29:0`. Unknown keys raise `UsageError` so the next
  backend is tried instead of sending a wrong event.
- Typing through `ydotool` uses `-d 40 -H 40`: the 20 ms defaults dropped
  characters (`echo` arrived as `keco`) when the focused client was busy.

### Verified on the test machine (Arch, Plasma 6.8.2, Wayland)

| Check | Result |
|---|---|
| `kde_uia_doctor` | six checks green |
| `kde_uia_windows` / `tree` / `find` / `info` | works; Firefox tabs, Konsole toolbar, dialog structures readable |
| `kde_uia_activate` | works after the `window-op` fix |
| `kde_uia_screenshot` | works (spectacle) |
| `kde_uia_type` / `kde_uia_keys` via `ydotool` | `echo lag-test-one` typed and executed verbatim |
| Page body text of a web page | **not available**: Firefox exposes 4 placeholder characters through `document web` |
| Terminal contents | **partial**: Konsole reports 7181 characters but only serves ~2591, so the newest lines cannot be read |

### Requirements for the keyboard path

```
yay -S ydotool                        # AUR
# /dev/uinput must be writable by the user (ACL or the `input` group)
ydotoold --socket-path=$XDG_RUNTIME_DIR/.ydotool_socket --socket-perm=0600
```

## [0.1.1] — 2026-10-31

First release that has been verified on a real KDE Plasma desktop. Both the plugin and the
bundled Python client move to 0.1.1; the client's fixes are in `kde-uia/src/kde_uia/compat.py`
and apply on import (`KDE_UIA_NO_PATCHES=1` opts out).

### Fixed — plugin never activated in DSH 0.2.0-rc.2

Enabling the plugin in DSH failed with:

```
tool-kde-uia (dsh-plugin-kde-uia): TypeError: Cannot read properties of undefined (reading 'validate')
```

Two independent causes, both fixed:

- **`Config` was a plain JSON-Schema object.** DSH validates every plugin through cordis'
  Standard Schema bridge (`runtime.Config['~standard'].validate`), which a bare JSON Schema
  does not provide. `Config` is now built with `@deepseek-ai/schemastery` (the schema library
  every built-in DSH plugin uses) and declares that dependency. A test now asserts the
  `~standard` contract so this cannot silently regress.
- **`apply()` returned an object.** Cordis treats a returned value as a setup promise and
  rejects non-thenable-shaped results; the returned `{ dispose, info }` broke activation.
  Tool teardown now registers through `ctx.effect()`, which is the cordis lifecycle hook, and
  `apply()` returns nothing.

Verified with the real loader: the entry imports, the config validates, and all 13
`kde_uia_*` tools register (`registered 13 tools via local Linux session`), with the on-load
probe reporting `desktop automation ready`.

### Fixed — defects found on a live Plasma 6.8.2 / Wayland session

Each item names the failed call, the real API, and the user-visible symptom it caused.

1. **`doctor` crashed on the AT-SPI check.** `ops.diagnose` called `desktop.child_count()`;
   PyGObject spells it `get_child_count()`. Symptom: `AttributeError` in the `atspi` row.
2. **No window ever counted as visible.** `AtspiElement.state_set()` called
   `self.acc.get_state_set()`; PyGObject exposes `self.acc.states`. Every state read returned
   `False`, so `showing` was always false and `windows`/`tree` came back empty.
3. **State names never resolved.** `_state_type()` looked up `StateType.STATE_SHOWING`;
   PyGObject's members have no `STATE_` prefix (`StateType.SHOWING`). All state checks raised
   and were swallowed as `False`.
4. **Actions were invisible.** `ActionCapability` used `get_action_count()` and
   `do_action(0, name)`; the real API is `get_n_actions()` and `do_action(index)`. No element
   reported an action and every semantic click failed.
5. **The KWin scripting bridge cannot work on Plasma 6.** `/KWin` exports no
   `org.kde.KConfig`, and KWin 6.8.2 answers `isScriptLoaded` with `true` while never executing
   the script. A `kdotool` backend replaces it for listing, activate, minimize, close and resize.
6. **Qt reported garbage values.** `get_current_value()` returned an uninitialised double
   (`6.9e-310`) for widgets without a value; only roles that carry a value are read now.
7. **Scoped searches never matched.** `find_windows` applied the element `role`/`name` to the
   window frame, so `{"window": …, "role": "push button"}` failed before the tree was walked.
8. **Refs collided between instances.** `_ref_path` dropped the application index, so two
   Gwenview windows both produced `uia:1:gwenview:0`. A ref now carries an `instance` suffix
   (the numeric application index when PyGObject exposes no path suffix), and resolving prefers
   that index. Refs without an instance keep the 0.1.0 shape.
9. **Screenshots failed on the spectacle path.** `_require_png()` was called with two
   arguments; `import` was invoked without `-silent` and waited for a file name on stdin.
10. **Nothing registered as an AT-SPI client.** Children were never preloaded, so toolkit trees
    stayed shallow.

### Added

- `kde-uia/src/kde_uia/compat.py` — the compatibility layer, documented defect by defect,
  verified on Arch / Plasma 6.8.2 / Wayland / Python 3.14 / PyGObject 3.58.1.
- `compat.py` adds a synthetic-input path on top of AT-SPI: `Atspi.generate_keyboard_event`
  and `generate_mouse_event` are tried before xdotool/kdotool, because kdotool 0.3.0 ships no
  input commands and XTest is inert under Wayland.
- [FIELD-TEST.md](../FIELD-TEST.md) — the field-test report: environment, raw output,
  reproduction commands, and what did not pass.
- `install.sh` at the repository root — installs the client to `/opt/dsh/kde-uia` and places
  the package in the DSH desktop profile without touching the running application.
- `kde-uia/tests/test_compat.py` — 19 regression tests that fake the AT-SPI surface with the
  names **PyGObject really provides** (`states`, `get_n_actions()`, `do_action(index)`, no
  `path_suffix()`), so the ten defects above cannot silently come back. The client suite now has 69 tests.

### Changed

- `kde_uia_doctor`'s `window-backend` row now reports `KdotoolBackend` when kdotool answers;
  the `kwin` backend stays selectable with `--backend kwin`.

### Keyboard input: known limit

**`kde_uia_keys` and `kde_uia_type` cannot deliver keystrokes on a native Wayland session where
the compositor does not act on AT-SPI synthetic events.** On the test machine every
unprivileged path was closed:

| Path | Result |
|---|---|
| XTest (`xdotool`) | no-op under native Wayland |
| `kdotool` 0.3.0 | ships no `key` / `click` / `type` commands |
| KWin scripting bridge | KWin 6.8.2 never runs the script |
| `Atspi.generate_keyboard_event` | returns `True`, event dropped by KWin |

The supported fixes need the machine owner's decision and are **not** enabled automatically:
**`ydotool`** (AUR, `/dev/uinput`, `input` group, `ydotoold` running) or the **XDG Remote
Desktop portal** (`RemoteDesktop`, grants input after a user prompt). Pointer actions through
accessibility actions, `set_value`, and screenshots do not depend on this path.

### Verification status (v0.1.1)

| Area | Verified? | How |
|---|---|---|
| Tool declarations compile with the host's real `defineTool` | **yes** | tests against a DSH 0.2.0-rc.2 install |
| JSON-Schema gate + argument validation | **yes** | `scripts/smoke-dsh-load.mjs` |
| WSL transport (wsl.exe → python client → JSON) | **yes** (0.1.0; not re-run in 0.1.1) | live test on a Windows host |
| AT-SPI element tree / find / refs | **yes** | live Plasma 6.8.2 session |
| Semantic click (accessibility action) + state read-back | **yes** | live session, Gwenview toggle |
| Window listing / activate / minimize / resize | **yes** (XWayland windows) | live session, kdotool backend |
| Screenshots (spectacle) | **yes** | live session |
| Keyboard / typing | **no** | live session: events are dropped (see above) |
| Plasma 5, X11 sessions, other distros | **no** | — |

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
