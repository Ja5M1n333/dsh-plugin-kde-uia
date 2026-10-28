# JSON protocol (plugin ⇄ Python client)

The plugin never calls Python APIs directly; it runs one command per tool call and reads one
JSON document back. The contract is deliberately tiny so the client can be tested, replaced or
called from other languages.

## Command shape

Inside the Linux environment the plugin runs (as a single script, each element quoted by the
plugin, arguments base64-encoded):

```bash
mkdir -p <client>/.runtime
printf '%s' '<base64 JSON args>' | base64 -d > file://<client>/.runtime/args.json
PYTHONPATH=<client> python3 -m kde_uia ops <op> \
    --args-file file://<client>/.runtime/args.json \
    --result    file://<client>/.runtime/result.json
cat file://<client>/.runtime/result.json 2>/dev/null
rm -f file://<client>/.runtime/args.json file://<client>/.runtime/result.json
```

- `<client>` is the directory holding the `kde_uia` package (default `/opt/dsh/kde-uia`).
- `--result` makes the client write the answer atomically to that path **as well as** stdout, so
  a truncated pipe never loses the answer.
- `python3 -m kde_uia ops …` works for any parser-safe file URI, including WSL paths such as
  `file:///mnt/c/…`.

You can replay any tool call by hand:

```bash
python3 -m kde_uia ops windows --args '{}'
python3 -m kde_uia ops click --args '{"ref":"uia:1:kwrite:1/0/2","dry_run":true}'
```

## Answer document

Success:

```json
{ "ok": true, "result": { "windows": [ … ], "count": 1 } }
```

Failure:

```json
{
  "ok": false,
  "error": {
    "code": "NOT_FOUND",
    "message": "no element matched text~='Save' (scope: all application windows)",
    "hint": "Run `kde-uia tree --window <title>` to inspect the window's elements.",
    "details": { "attempts": 1 }
  }
}
```

- `code` is one of the stable codes in `docs/tools.md#error-codes`.
- `hint` is written for an agent: it names the next step.
- Exit status: `0` for `ok: true`, `1` for coded failures, `2` for usage errors (bad JSON, unknown
  op), `124` for a `wait` timeout. The document is authoritative; the exit status is a convenience.
- Unexpected exceptions never leak a traceback to the model: they become
  `{"ok":false,"error":{"code":"INTERNAL", …}}` (set `KDE_UIA_DEBUG=1` to see it on stderr).

## Operations

| op | arguments | result |
|---|---|---|
| `env` | `{}` | environment/capability facts (no desktop contact) |
| `doctor` | `{}` | `{ ok, checks: [{check, status, detail, hint?}] }` |
| `windows` | `{ include_hidden?, selector? }` | `{ windows: [{title, app, role, ref, id?, frame?, active?, source}], count }` |
| `active-window` | `{}` | `{ active, source, window }` |
| `focused` | `{}` | element summary + `path` + `value` |
| `tree` | `{ selector?/window/app/window_id, ref?, depth?, max_nodes?, include_extents? }` | `{ window, text, nodes, truncated, rootRef }` |
| `find` | `{ selector }` or `{ refs: [...] }` | `{ ref, found, count, elements: [{ref, role, name, app, window, extents, actions, value}] }` |
| `info` | `{ selector? , ref? }` | `{ ref, role, name, description, value, states, actions, attributes, interfaces, extents, path, window }` |
| `activate` | `{ window?, app?, id?, selector? }` | `{ activated, source, window }` |
| `window` | `{ op: close\|minimize\|maximize\|restore\|move\|resize, window/app/id, x,y,width,height }` | `{ ok, op, window }` |
| `click` | `{ selector?/ref?, x?, y?, button?, clicks?, strategy?, dry_run? }` | `{ ok, backend, x, y, ref }` |
| `press` | `{ key, repeat? }` | `{ ok, backend, combo, repeat }` |
| `type` | `{ text, ref?, submit?, interval_ms?, dry_run? }` | `{ ok, backend, text }` |
| `set` | `{ value, selector?/ref? }` | `{ ok, interface, value, ref }` |
| `toggle` | `{ selector?/ref?, state? }` | `{ ok, changed, before, state }` |
| `scroll` | `{ selector?/ref? | x,y, direction?, amount? }` | `{ ok, backend, x, y }` |
| `focus` | `{ selector?/ref? }` | `{ ok, focused }` |
| `expand` | `{ selector?/ref? }` | `{ ok, expanded }` |
| `wait` | `{ for: element\|gone\|window\|window-gone, selector?, ref?, timeout?, interval? }` | `{ met, elapsed, element?/window?/gone }` |
| `screenshot` | `{ output?, window?/app?/id?/ref?, strategy? }` | `{ path, strategy, width, height, scale, layout }` |
| `open` | `{ command, window?/app?, screenshot? , timeout? }` | `{ ok, pid, window?, screenshot? }` |

Selectors are documented in `docs/tools.md#common-arguments`.

## Environment overrides

The client reads these from the environment (the plugin sets none; use them when calling it by
hand): `KDE_UIA_BACKEND` (`auto|kwin|x11|atspi`), `KDE_UIA_INPUT`, `KDE_UIA_SCREENSHOT`,
`KDE_UIA_ALLOW_XDOTOOL_ON_WAYLAND`, `KDE_UIA_SKIP_A11Y_CHECK`, `KDE_UIA_DEBUG`.
