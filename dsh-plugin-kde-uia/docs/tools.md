# Tools and CLI

Two front ends share one Python client:

- **DSH tools** (`kde_uia_*`) — what the agent sees. Registered through
  `defineTool` from `@deepseek-ai/dsh-tools`, so schemas are validated exactly like built-in tools.
- **CLI** (`kde-uia …`) — the same operations from a shell, for humans, scripts and tests.

Exit codes of the CLI and of `python -m kde_uia ops`: `0` ok, `1` coded failure, `2` usage error,
`124` wait timeout.

## Tools

| Tool | Effect | Client op |
|---|---|---|
| `kde_uia_doctor` | capability report (transport, client, AT-SPI, window backend, input, screenshots) | `doctor` |
| `kde_uia_windows` | list windows from AT-SPI + KWin/X11 (titles, apps, ids, geometry) | `windows` |
| `kde_uia_tree` | indented element tree of one window/element with roles, names, values, actions, refs | `tree` |
| `kde_uia_find` | find elements by role/name/text/states/attributes, scoped to a window | `find` |
| `kde_uia_info` | one element's properties, states, actions, geometry, parent chain | `info` |
| `kde_uia_click` | click an element (a11y action first, pointer fallback); `dry_run` available | `click` |
| `kde_uia_keys` | key combination (`ctrl+l`, `Enter`, `ALT+F4`, …) | `press` |
| `kde_uia_type` | type text into the focused (or referenced) widget, optional `submit` | `type` |
| `kde_uia_set_value` | set a value via the Value or editable-text interface | `set` |
| `kde_uia_scroll` | wheel over an element or at x/y | `scroll` |
| `kde_uia_wait_for` | poll until an element appears / a window appears or closes | `wait` |
| `kde_uia_screenshot` | capture desktop, window or element to PNG | `screenshot` |
| `kde_uia_activate` | activate/close/minimize/maximize/move/resize a window | `activate`, `window` |

Mutating (absent with `readOnly: true`): `click`, `keys`, `type`, `set_value`, `scroll`, `activate`.

### Common arguments

- `ref` — an element reference such as `uia:1:kwrite:1/0/2` from `tree`/`find`.
- `selector` (or flat `role`/`text`/`name`/`states`/`window`/`app`/`window_id`) — a condition tree;
  all present conditions must match. `match` is `contains` (default, case-insensitive), `exact`
  or `regex`; `case_sensitive` makes them case-sensitive.
- `dry_run` (click/type) — report the resolved target and point without touching the desktop.

### Refs

```
uia:1:<application>:<child-index-path>[:<instance>]
      ^            ^                     ^ D-Bus instance suffix, only when two apps share a name
      |            `0/1/3` = walk child 0, then 1, then 3 from the application root
      `dolphin`, `kwrite`, ... (AT-SPI application name)
```

A ref is resolved statelessly: the application is looked up again and the path is walked. If a
node disappeared the call fails with `INVALID_REF` and a hint to re-take the ref. Refs are meant
to be used immediately after they are obtained.

## CLI

```
kde-uia doctor                     capability report with fixes
kde-uia env [--json]               environment and backend facts
kde-uia windows [--all]            list windows
kde-uia active-window              the active window
kde-uia focused                    the element with keyboard focus
kde-uia tree --window Dolphin [--depth 6] [--max-nodes 300] [--extents]
kde-uia find --role push-button --text Save [--window Dolphin] [--match exact] [--state focusable]
kde-uia info --ref uia:1:kwrite:1/0
kde-uia activate --window Dolphin [--id 0x3a00007]
kde-uia window close --window Dolphin      # close|minimize|maximize|restore|move|resize
kde-uia click --text Save --role push-button [--strategy atspi|xdotool|kdotool] [--dry-run]
kde-uia press ctrl+l                       # or: press Return --repeat 3
kde-uia type "trash:///" --submit          # or: type hello --ref uia:1:kwrite:1/1
kde-uia scroll --ref uia:1:dolphin:2 --direction down --amount 5
kde-uia set --ref uia:1:kwrite:1/1 "new value"
kde-uia toggle --role check box --text "Show hidden files"
kde-uia focus --ref uia:1:kwrite:1/1
kde-uia expand --ref uia:1:dolphin:0/2
kde-uia wait --for window --window Dolphin --timeout 15
kde-uia wait --for gone --ref uia:1:dolphin:0/9
kde-uia screenshot --window Dolphin -o /tmp/dolphin.png [--strategy kwin|spectacle|grim|import|xwd|portal]
kde-uia open "kwrite /tmp/a.txt" --window a.txt --screenshot /tmp/a.png
kde-uia ops <op> --args '<json>' [--result PATH]     # machine protocol (see docs/protocol.md)
```

Global flags: `--backend auto|kwin|x11|atspi`, `--input auto|atspi|xdotool|kdotool|dbus|dry-run`,
`--screenshot-strategy auto|kwin|spectacle|grim|import|xwd|portal|drm`, `--timeout SECONDS`
(AT-SPI call timeout), `--allow-xdotool-on-wayland`, `--quiet`, `--json`.

## Input strategies

| Strategy | Needs | Notes |
|---|---|---|
| `auto` | — | tries AT-SPI action, then xdotool (X11), then kdotool (Wayland) |
| `atspi` | — | toolkit-native: `click`/`activate` actions, editable-text insertion; no pointer movement |
| `xdotool` | `xdotool`, X11 | moves the real pointer; types Unicode character by character |
| `kdotool` | `kdotool` | KWin fake-input on Wayland |
| `dbus` | `xclip`/`xsel` or `wl-copy` | clipboard + paste, last resort for typing |
| `dry-run` | — | records the intent, changes nothing |

## Screenshot strategies

| Strategy | Needs | Prompts |
|---|---|---|
| `kwin` | KWin | no — reads the compositor's shadow buffer |
| `spectacle` | `spectacle` | no (`--background`) |
| `grim` | `grim` | no |
| `import` / `xwd` | ImageMagick / x11-apps | no |
| `portal` | any D-Bus tool | **yes** — the desktop shows its own consent dialog |
| `drm` | read access to `/dev/fb0` | never tried automatically |

## Error codes

`USAGE`, `NO_DISPLAY`, `NO_GUI_CONTEXT`, `UNSUPPORTED_PLATFORM`, `ATSPI_UNAVAILABLE`,
`ATSPI_TIMEOUT`, `ATSPI_ERROR`, `ACCESSIBILITY_DISABLED`, `BUSY`, `NOT_FOUND`, `AMBIGUOUS`,
`INVALID_REF`, `NOT_ACTIONABLE`, `NO_WINDOW`, `BACKEND_UNAVAILABLE`, `DRM_DENIED`,
`SCREENSHOT_FAILED`, `INPUT_FAILED`, `INPUT_DENIED`, `TIMEOUT`, `INTERNAL`.

Transport-level codes added by the plugin: `CONFIG` (bad plugin configuration),
`TRANSPORT_INCOMPLETE` (the Linux side produced no JSON answer), `ABORTED` (the tool call was
cancelled).
