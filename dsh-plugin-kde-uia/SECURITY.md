# Security

This document is the security statement for **dsh-plugin-kde-uia**. It covers the threat
model, what the plugin can and cannot do, the permissions it needs, what data it touches, and
how to report a problem. It is written for people installing the plugin on a machine they
control or administer.

> **A student's side project.** This plugin was written together with an AI agent on a
> student's school computer, originally for personal use on the author's own Nyarch Linux +
> KDE desktop, and it has not been verified on a real KDE session yet. The safeguards below
> describe what the code *is designed* to do rather than what has been proven to do it. If
> that uncertainty matters for your situation, waiting a while or holding off is a reasonable
> choice. The software is provided "AS IS", without warranty of any kind, and the author is
> not liable for any damage caused by its use (see [LICENSE](LICENSE)).

## Threat model

The plugin gives an **agent** the ability to operate a **KDE desktop session** on a machine
you name. The interesting attacker model is therefore:

1. **A manipulated or misbehaving agent.** An agent (or a prompt-injected page it read) could ask
   the tools to click or type in any application of that session — send a message, delete a
   file, change a setting. The plugin does not decide whether a click is wise; like a user's
   hands, it executes.
2. **An attacker who can already reach the transport.** Someone who can run `wsl`/`ssh` commands
   on the DSH host already controls that host. The plugin adds no new way to reach the Linux
   side beyond the fixed commands below.
3. **A hostile application on the Linux desktop.** AT-SPI is an IPC surface owned by the session
   user; an application that already runs as the same user can also talk to it. The plugin does
   not widen that surface (it opens no ports and registers no services).

What is **out of scope**: protecting the desktop from its own logged-in user, sandboxing the
applications being automated, or preventing MITM on an `ssh` connection you configured without
host-key checks. Use `BatchMode=yes` (the plugin always adds it) and proper known-hosts.

## What the plugin can do

| Capability | Why it exists |
|---|---|
| Read window titles, element trees, roles, names, values, states | to locate targets |
| Click, double-click, scroll | to operate the GUI |
| Type text, press key combinations | to fill forms and send shortcuts |
| Activate, move, resize, minimize, close windows | window management |
| Capture the screen or a window as PNG | visual confirmation for the agent/user |

That is equivalent to a desktop user's keyboard and mouse. It is **not** equivalent to root.

## What it cannot do (by construction)

- **No elevation.** The plugin never invokes `sudo`, `pkexec`, `su`, or any setuid helper. The
  Python client and every backend run with the desktop user's privileges.
- **No arbitrary shell.** Calls do not pass a caller-built shell string:
  - the transport builds an *argv* and quotes each element itself;
  - arguments are serialised to JSON and transported base64-encoded, so no quoting rule can
    reinterpret them;
  - the receiving side runs exactly one fixed wrapper (`bash -lc` of that argv in WSL, the
    remote user's shell in SSH), using the same route DSH's own bash tool uses;
  - typed text goes to the *application* through synthetic input, never to a shell.
- **No network.** No telemetry, no update checks, no external endpoints. The only outbound
  traffic is the transport you configured (`wsl.exe`, `ssh`).
- **No device access that needs extra permission.** Reading `/dev/fb0` is documented but never
  attempted automatically.
- **No silent installation or config edits.** The plugin writes only the files listed under
  *Data handling*.

## Permissions and setup changes

| Item | Effect |
|---|---|
| `dsh plugin add` | adds one dependency + one row (`tool-kde-uia`) to the profile |
| `mklink`/`Get-ChildItem` of `python/` | copies the client into the Linux environment (by you, with `cp`) |
| KWin script | installs `~/.local/share/kwin/scripts/kde-uia-window-probe.js` and loads it in the running KWin (user scope, removable by deleting the file) |
| AT-SPI access | reads the accessibility bus of your own session (no prompt) |
| Synthetic input | moves the pointer / types in the focused window (the user sees it) |
| Screenshot | captures the screen to a file path you name |

## Data handling

Files the plugin/client may create:

- `<client>/.runtime/args.json`, `result.json` — the current call's request/answer; deleted at
  the end of every call (on interruption they remain until the next call overwrites them).
- `/tmp/kde-uia/seq`, `result-<n>.json` — the KWin script bridge; contain the last operation
  name and its answer (window titles, geometry).
- `~/.local/share/kwin/scripts/kde-uia-window-probe.js` — the KWin script.
- PNG files only where `kde_uia_screenshot` asked for them.

Data leaves the machine only through the configured transport (wsl/ssh) and only as tool
arguments/results on the DSH side, where DSH's own session storage rules apply. The plugin
adds **no** telemetry: it does not call DSH's telemetry, logs tool arguments verbatim in DSH's
session log (that is DSH's behaviour), and never sends anything itself.

## Safeguards you can turn on

- `readOnly: true` — registers only `kde_uia_doctor`, `kde_uia_windows`, `kde_uia_tree`,
  `kde_uia_find`, `kde_uia_info`, `kde_uia_wait_for`, `kde_uia_screenshot`: no clicks, typing,
  keys, scroll or window mutation. Use it for audit/observe deployments.
- Run the client in a **dedicated WSL distro or SSH account** whose GUI session is the one the
  agent may touch, not your primary workstation session.
- Use `kde_uia_find`/`kde_uia_tree` in `dry_run` workflows first (`kde_uia_click` accepts
  `dry_run: true` and reports the target and point without clicking).
- Keep DSH's approval policy for tools in a mode you trust; the plugin adds no approval prompt
  of its own (it is bound by DSH's tool pipeline like any other tool).

## Reporting a vulnerability

Please report privately before opening a public issue:

- Open a **private security advisory** on the plugin repository (GitHub → Security →
  "Report a vulnerability"), or
- Email the maintainer listed in `package.json`/the repository with subject
  `[dsh-plugin-kde-uia security]`.

Include the version (`kde_uia_doctor` prints it), DSH version, the transport used (wsl/ssh/local),
and a reproduction. For the response policy see [MAINTENANCE.md](MAINTENANCE.md): issues are
always read, but this is a student-maintained project without an on-call schedule. Security
reports are handled first whenever the maintainer is available; credit is given on request.

**This plugin must never be able to do any of the following** — report it immediately if it can:

- elevate privileges (`sudo`, `pkexec`, setuid) or run as root;
- execute a shell command supplied by the model or by a web page;
- send data to any network endpoint;
- delete or modify files outside the documented scratch locations
  (`<client>/.runtime/`, `/tmp/kde-uia/`, the KWin script file, and screenshot paths you name);
- perform a state-changing desktop action when `readOnly: true` is configured or when called with
  `dry_run: true`.

Because this plugin can control a desktop, please treat "an agent can be tricked into clicking"
as a design fact rather than a vulnerability; report it if a tool can do something *beyond* the
described capability (for example, execute a shell command crafted by the model).
