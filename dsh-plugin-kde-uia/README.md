# dsh-plugin-kde-uia

**Windows UI Automation–style control of a Linux KDE Plasma desktop for DeepSeek Harness agents.**

> A small side project a student put together in the time left over from classes. It has not
> been tested on a real KDE desktop yet — if you decide to try it, a quick look at its current
> maturity first would be a good idea.
> Details: [A few things to know before use](#a-few-things-to-know-before-use).

[English](README.md) | [中文](README.zh.md) · [Security](SECURITY.md) · [Maintenance](MAINTENANCE.md) · [Changelog](CHANGELOG.md) · [Tools](docs/tools.md) · [Architecture](docs/architecture.md) · [Protocol](docs/protocol.md) · [Arch Linux guide](docs/arch-linux.md)

---

## About the author

- The author is a student, so time at the computer is limited between classes and homework.
  Updates will come slowly, and a late reply simply means there was no spare time — thanks
  for your patience.
- The code was written together with a DeepSeek Harness (DSH) agent. The author is still
  learning the AT-SPI and KWin scripting internals, so if anything looks shaky, a pointer from
  someone more experienced would be very welcome.
- Issues are read and answered when possible, but neither speed nor a schedule can be
  promised. For a quick start, the troubleshooting section below plus the output of
  `kde_uia_doctor` already cover most common causes.
- If this plugin turns out to be useful to you, that will make the author's day. Pull requests
  and notes about your setup are very welcome too.

> In one line: **written together with an AI, maintained by a student in between classes —
> thank you for understanding m(_ _)m**

### A few things to know before use

- It was built on the author's **school computer**, originally just for personal use on the
  author's own machine (**Nyarch Linux + KDE**). Putting it on GitHub is mostly to keep a copy
  and maybe help someone with a similar need.
- It has not run on a real KDE desktop yet, so small problems are likely; in an extreme case,
  an action on the UI could reach something you would rather not have touched. Reading
  [SECURITY.md](SECURITY.md) and the status section below before trying it would help you
  judge for yourself.
- If its current maturity does not fit your needs, or you are not comfortable with the
  possible risks, **holding off (or not using it at all) is a perfectly understandable
  choice** — the author will respect that.
- Forking and modifying are welcome (the MIT licence allows it anyway); just using it on a
  production system or a primary machine is not recommended. A VM or a dedicated user session
  is a safer place to try it.
- Should something go wrong, the author may not have the ability to fix the consequences and
  cannot take responsibility for them (the LICENSE says the same). Keeping a backup of
  important data is a good idea.

> In one line: **a small tool a student built on a school computer for personal use —
> whether and how to use it is best judged by your own situation.**

### Current status: first field test on a real Plasma 6 desktop (v0.1.1)

On 2026-10-31 this plugin ran against a live KDE Plasma 6.8.2 Wayland session for the first
time. The full environment, raw output, reproduction commands and known failures are in
[FIELD-TEST.md](../FIELD-TEST.md). Summary:

- ✅ `kde_uia_doctor` passes all six checks; window listing, element trees, `find` and `info` work.
- ✅ Semantic clicks through accessibility actions work (the widget's `checked` state was read
  back before and after to confirm the toggle).
- ✅ Screenshots work (spectacle); window activate / minimize / close / resize work (kdotool,
  XWayland windows).
- ❌ **Keyboard input (`kde_uia_keys` / `kde_uia_type`) does not work on native Wayland:** the
  call reports success, but the event never reaches the application. This is not a
  configuration mistake — every unprivileged input path is closed on that machine (details
  below).

### Why 0.1.0 did not work out of the box (fixed in 0.1.1)

The 0.1.0 Python client was written from documentation and had **ten real defects**; any one
of them was enough to break tree reading or clicks (PyGObject method names, a KWin scripting
bridge that Plasma 6 cannot drive, scoped searches that never matched, refs colliding between
two instances of one app, and more). The fixes live in `kde-uia/src/kde_uia/compat.py` and
apply automatically when the client is imported; each one is explained in the
[CHANGELOG](CHANGELOG.md#011--2026-10-31). Set `KDE_UIA_NO_PATCHES=1` to compare against the
original behaviour.

### Known limit: keyboard input under Wayland

Every input path the plugin ships is closed on that machine:

- XTest (`xdotool`) is a no-op under native Wayland;
- `kdotool` 0.3.0 has no `key` / `click` / `type` subcommands;
- KWin 6.8.2 does not run scripts (`loadScript` returns an id and `isScriptLoaded` says true,
  yet the script never executes);
- `Atspi.generate_keyboard_event()` returns success, but KWin drops the event.

The workable alternatives all need the machine owner's consent, so none is enabled by
default: **`ydotool`** (AUR, `/dev/uinput`, `input` group plus a running `ydotoold`) or the
**XDG Remote Desktop portal** (`RemoteDesktop`, which asks you for permission in a dialog).
Until then, prefer the keyboard-free tools: `kde_uia_click`, `kde_uia_set_value`.


---

## What it does

DeepSeek Harness on Windows has no way to "see" or "touch" a KDE desktop — not the one on
this machine, not the one inside WSL. This plugin adds that in the shape Windows
developers already know from **UI Automation (UIA)**:

| UIA concept | this plugin / client |
|---|---|
| `AutomationElement.RootElement` + `TreeWalker` | `kde_uia_windows`, `kde_uia_tree` |
| `FindFirst` / `FindAll` + conditions | `kde_uia_find` (role / name / text / states / attributes) |
| `RuntimeId` | `uia:1:<app>:<child-index-path>` references |
| `InvokePattern`, `TogglePattern` | `kde_uia_click` (runs the accessibility action first) |
| `ValuePattern` | `kde_uia_set_value`, `kde_uia_type` |
| `WindowPattern` | `kde_uia_activate` (activate/close/minimize/maximize/move/resize) |
| synthetic keyboard & mouse | `kde_uia_keys`, `kde_uia_type`, `kde_uia_click`, `kde_uia_scroll` |
| screen capture | `kde_uia_screenshot` |

Under the hood it drives the **AT-SPI2 accessibility bus** (the Linux equivalent of the UIA
provider model) for element trees and semantic actions, **KWin scripting** for window
management on Wayland *and* X11, and **X11 tools** (xdotool/wmctrl) or **kdotool** for
pointer and keyboard input.

It focuses on one real problem and does it end to end: *let an agent operate a KDE
application by accessible name instead of blind coordinates and OCR screenshots.*

## Requirements

**Primary target: Arch Linux + KDE Plasma 6** (Wayland or X11). Other distributions work
too — the package names differ, see the table below.

| Where | Need |
|---|---|
| DSH host | any OS; on a Linux desktop this is just the same machine (`runtime: local`); on Windows the desktop is reached through **WSL** or **SSH** |
| Linux desktop | KDE Plasma 5.x or 6.x (Wayland or X11), logged-in user session |
| Python | 3.9+ with **PyGObject** and the **libatspi typelib** (system packages, never pip) |
| Accessibility | enabled in the session (`org.a11y.Status.IsEnabled = true`) |
| Window control | `qdbus6` + `kwriteconfig6` (KWin scripting), or `xdotool` + `wmctrl` (X11) |
| Input (optional) | `xdotool` (X11) and/or `kdotool` (Wayland) |
| Screenshots (optional) | `spectacle` (Plasma) or `grim`/`import`; the XDG portal is used only when asked |

Arch Linux (one line, verified package names):

```bash
sudo pacman -S python-gobject at-spi2-core qt6-tools kconfig xdotool wmctrl spectacle
# optional for Wayland input — kdotool is AUR-only, there is no official package:
yay -S kdotool
```

`kconfig` is the easy one to miss: without it the KWin scripting bridge cannot hand its
commands over, and the plugin falls back to the weaker X11/AT-SPI backend. Full walkthrough
with a verification checklist: [docs/arch-linux.md](docs/arch-linux.md).

Debian/Ubuntu/KDE neon:

```bash
sudo apt install python3-gi gir1.2-atspi-2.0 at-spi2-core qdbus-qt6 kconfig-cli xdotool wmctrl spectacle
```

Fedora: `sudo dnf install python3-gobject at-spi2-core qt6-qttools kf6-kconfig xdotool wmctrl spectacle`

## Install

### 1. Install the Python client inside the Linux environment

The plugin ships a self-contained copy of the client under `python/`. One `cp` installs it
(`/opt/dsh/kde-uia` is the default location the plugin probes first):

```bash
# inside the Linux desktop / WSL distro
sudo mkdir -p /opt/dsh
sudo cp -r <path-to-plugin>/python /opt/dsh/kde-uia
sudo chown -R "$USER" /opt/dsh/kde-uia

PYTHONPATH=/opt/dsh/kde-uia python3 -m kde_uia doctor
```

`doctor` prints one line per capability (display, AT-SPI, window backend, input, screenshots)
with a concrete fix for every failed check. Nothing is started by it.

From a Windows DSH host, the same check through WSL:

```powershell
wsl -e bash -lc "PYTHONPATH=/opt/dsh/kde-uia python3 -m kde_uia doctor"
```

### 2. Install the plugin into the DSH profile

Any of these works; each only adds the plugin, nothing else changes:

```bash
# a) from a local checkout
dsh plugin --profile desktop add file:<abs-path>/dsh-plugin-kde-uia

# b) inside the plugin directory
cd dsh-plugin-kde-uia && dsh plugin --profile desktop add .

# c) an archive
dsh plugin --profile desktop add ./dsh-plugin-kde-uia-0.1.0.tgz
```

The package's `package.json` carries `dsh.bundle.patch: ./cordis.patch.yml`; the DSH plugin
manager reads that field to know how the package contributes rows.

### 3. Choose a runtime (only needed for SSH or custom paths)

The default `runtime: auto` already works for **WSL on Windows** and for a **Linux DSH host**.
Override it in your profile's `cordis.patch.yml`
(`$DSH_HOME/profiles/desktop/cordis.patch.yml`):

```yaml
# Reach a KDE desktop on another machine, through Windows OpenSSH:
- id: tool-kde-uia
  config:
    runtime: ssh
    sshHost: user@kde-box
    remotePath: /opt/dsh/kde-uia       # where step 1 copied the client
    # sshIdentity: C:\Users\me\.ssh\id_ed25519

# Or a specific WSL distribution (e.g. one with a graphical session):
- id: tool-kde-uia
  config:
    runtime: wsl
    wslDistribution: Ubuntu-24.04
    remotePath: /opt/dsh/kde-uia

# Read-only deployments: no click/type/keys/scroll/activate tools at all
- id: tool-kde-uia
  config:
    readOnly: true
```

| Config | Default | Meaning |
|---|---|---|
| `runtime` | `auto` | `auto` \| `wsl` \| `ssh` \| `local` |
| `wslDistribution` | `''` | WSL distro, empty = default |
| `remotePath` | `''` | client directory inside Linux; empty = probe `/opt/dsh/kde-uia`, then the checkout |
| `remotePython` | `python3` | interpreter inside Linux (must have PyGObject; the Windows Python is never used) |
| `wslCommand` | `''` | explicit `wsl.exe` path |
| `sshHost` | `''` | `user@host` when `runtime: ssh` |
| `sshIdentity` | `''` | private key (a Windows path is converted for WSL) |
| `sshOptions` | `[]` | extra `ssh -o` options |
| `timeoutMs` | `120000` | per-call budget |
| `readOnly` | `false` | register only the read tools |
| `doctorOnLoad` | `true` | run the offline probe once when the plugin mounts and log the result |
| `executable` | `''` | advanced: launch `kde_uia` through this command (e.g. a wrapper script) instead of the bundled Python |

Unknown keys are ignored, so a newer README can describe a key an older install does not
implement yet; a wrongly typed value fails at load with a message naming the key.

After changing the profile, DSH reloads it (HMR) or restart DSH. The agent can then call
`kde_uia_doctor` to see exactly what works.

## Usage: the agent's loop

```
kde_uia_windows                         -> { "Dolphin" [dolphin] id 0x03a00007 active? }
kde_uia_tree   { "window": "Dolphin" }  -> tool bar 'mainToolBar'
                                           push button 'New Tab' actions=click uia:1:dolphin:0/1/0
                                           entry 'Path' value="/home/me"        uia:1:dolphin:0/3
kde_uia_find   { "text": "New Tab", "actionable": "button", "window": "Dolphin" }
kde_uia_click  { "ref": "uia:1:dolphin:0/1/0" }
kde_uia_keys   { "key": "ctrl+l" }
kde_uia_type   { "text": "trash:///", "submit": true }
kde_uia_wait_for { "selector": { "text": "Trash", "window": "Dolphin" }, "timeout_s": 5 }
kde_uia_screenshot { "window": "Dolphin", "output": "/tmp/dolphin.png" }
```

`kde_uia_tree` is the map; `kde_uia_click`/`kde_uia_activate` take refs. Refs are *paths*, so
re-run `tree`/`find` after the window changed — the plugin surfaces `INVALID_REF` with that
advice instead of failing silently.

The same client is usable outside DSH (scripts, CI, other harnesses):

```bash
export PYTHONPATH=/opt/dsh/kde-uia
kde-uia windows
kde-uia tree --window Dolphin --depth 5
kde-uia click --text "Save" --role push-button
kde-uia screenshot --window Dolphin -o /tmp/dolphin.png
```

The plugin also ships its own operator CLI, which uses exactly the same transport as the tools
(handy on the DSH host when nothing is loaded yet or you want to verify a deployment):

```bash
node dsh-plugin-kde-uia/lib/cli.js doctor --runtime wsl --remote-path /opt/dsh/kde-uia
node dsh-plugin-kde-uia/lib/cli.js windows
node dsh-plugin-kde-uia/lib/cli.js call kde_uia_find --json '{"text":"Save","window":"Dolphin"}'
```

See [docs/tools.md](docs/tools.md) for every tool and CLI command, and
[docs/protocol.md](docs/protocol.md) for the JSON protocol the plugin speaks.

## DSH compatibility

| Package version | DSH runtime | Status |
|---|---|---|
| 0.1.0 | `@deepseek-ai/dsh` **0.2.0-rc.2** (Desktop 44 / `primary-runtime` `0.2.0-rc.2`) | developed and tested against |
| — | `0.2.0-rc.*` other than rc.2 | expected, not exercised |
| — | any other version | unsupported; DSH refuses to load incompatible peers |

`package.json` declares **exact** peer versions (`"0.2.0-rc.2"`) on purpose: the plugin is
built on the documented extension points (`ctx.tools.register`, `defineTool`, `dsh.bundle.patch`,
`ctx.shell`) and DSH is still pre-stable, so a range would promise more than release notes can
keep. If DSH updates:

1. try enabling the plugin — DSH reports the incompatible peer before importing it;
2. if it loads and `node --test "tests/**/*.test.js"` passes (the suite compiles every tool with
   the *real* `defineTool` from your installed DSH), the update is very likely fine;
3. otherwise pin the plugin back (`dsh plugin --profile desktop add dsh-plugin-kde-uia@0.1.0`).

Compatibility-relevant changes are always listed under **Compatibility** in
[CHANGELOG.md](CHANGELOG.md).

## Security

Short version; details in [SECURITY.md](SECURITY.md).

- **What it can do:** the plugin can click, type and press keys in whatever KDE session the
  transport reaches, i.e. everything the logged-in desktop user can do in their GUI. Treat it
  like a remote-control tool, not like a read-only observer.
- **No new privileges:** it never uses `sudo`, never runs as root, never elevates. It talks to
  the session bus and the a11y bus as the desktop user.
- **No arbitrary shell:** tool arguments travel as JSON (base64) to a fixed command; the
  plugin always submits a fixed `bash -lc` wrapper of an argv it quotes itself, never a
  caller-built shell string. Text typed into applications is application data, not shell.
- **No network:** no telemetry, no endpoints, no uploads. The only outbound traffic is your
  own `ssh`/`wsl` transport if you configure it.
- **Read-only switch:** `readOnly: true` removes every mutating tool from the agent.
- **Data on disk:** `/opt/dsh/kde-uia/.runtime/` (per-call argument/result files, removed after
  each call), `/tmp/kde-uia/` (KWin script bridge), `~/.local/share/kwin/scripts/kde-uia-window-probe.js`
  (the KWin probe script) and any PNG you ask `kde_uia_screenshot` to save.

## Known limitations

Honest list — these are current constraints, not a roadmap.

- **AT-SPI coverage is per toolkit.** Qt/KDE apps expose a rich tree. Apps that do not enable
  accessibility (some Electron/Java/xterm builds, `GTK` apps with `GTK_MODULES` disabled) show up
  as a single node; text fields sometimes lack an editable-text interface and are typed into
  with synthetic keys instead.
- **Refs are paths, not hashes.** Any widget insertion/removal invalidates refs taken earlier;
  the error says so. Match by `text`/`role` for long workflows.
- **Wayland input:** `xdotool` only sees XWayland windows. On Wayland install `kdotool`
  (KWin scripting) or use the `atspi` strategy; `kde_uia_doctor` reports what is available.
- **Screenshots:** `kwin` (shadow buffer) and `spectacle` are per-window without prompts; the
  XDG portal shows its own consent dialog each time and is never used automatically.
- **No DRM/`/dev/fb0` fallback.** Reading the framebuffer directly would need device
  permissions; it is documented but not executed automatically.
- **Windows host paths:** SSH from a Windows DSH needs `remotePath` set explicitly (the plugin
  cannot guess where your checkout landed on the remote host); WSL paths are converted
  automatically (`C:\x` → `/mnt/c/x`).
- **One desktop at a time.** The runtime targets a single session/distro/host per profile.
- **No event streaming yet.** The client polls (`kde_uia_wait_for`); AT-SPI's event stream is
  used by the client internally only for name/role caches.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `kde_uia_doctor` says *client not reachable* | Step 1: copy `python/` into `/opt/dsh/kde-uia` in WSL/SSH; check `wsl -e bash -lc "echo $PATH"` |
| `ATSPI_UNAVAILABLE` | `sudo apt install python3-gi gir1.2-atspi-2.0 at-spi2-core`; run as the desktop user |
| `ACCESSIBILITY_DISABLED` | Enable accessibility (KDE System Settings → Accessibility) then restart the target app |
| Windows appear without windows | The application is not exposing a tree; check `kde_uia_tree --depth 1` |
| *No window backend* | `sudo apt install qdbus6` (KWin scripting) or `xdotool wmctrl` (X11) |
| Click does nothing on Wayland | Install `kdotool`, or pass `"strategy": "atspi"` to `kde_uia_click` |
| Screenshot fails everywhere | `sudo apt install spectacle` (Plasma) or `grim` (other Wayland) |
| DSH refuses to load the plugin | DSH version mismatch — see [DSH compatibility](#dsh-compatibility) |

## Development

```bash
# Node side (tool declarations, runtime, plugin, docs) — no DSH install needed:
cd dsh-plugin-kde-uia
npm run setup:test                      # optional: use your installed DSH's real modules
                                         #   (DSH_APP_ASAR=<…>\resources\app.asar)
node --test "tests/**/*.test.js"        # 45 tests; compiles every tool with the *real*
                                         # defineTool, or a strict DS L mock when none is found
node scripts/smoke-dsh-load.mjs C:\HARNESS\resources\app.asar
                                         # real-host gate: cordis shape, defineTool, JSON-Schema
                                         # validator and argument validation from DSH itself
KDE_UIA_SMOKE_WSL=1 node --test tests/integration.test.js
                                         # live wsl.exe → python client transport check

# Python side (library + CLI):
cd ../kde-uia && PYTHONPATH=src python3 -m unittest discover -s tests   # 46 tests
bash scripts/dev-smoke.sh                # import + doctor + ops protocol on this machine

# everything at once:
bash dsh-plugin-kde-uia/scripts/run-all-tests.sh   # (works in WSL; see header for Windows)

# keep the vendored client in sync before committing:
bash scripts/sync-python.sh && bash scripts/sync-python.sh --check
```

The Python client lives in [`kde-uia/`](kde-uia) (it is also installable on its own with
`pip install ./kde-uia`); `dsh-plugin-kde-uia/python/` is a byte-identical vendored copy so the
plugin installs with a single `cp`.

## License

MIT — see [LICENSE](LICENSE).
