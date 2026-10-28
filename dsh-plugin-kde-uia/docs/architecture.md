# Architecture

```
DeepSeek Harness (Windows / macOS / Linux)
├── profile: desktop
│   └── cordis.patch.yml row: tool-kde-uia
│         └── dsh-plugin-kde-uia (Node, zero dependencies)
│               ├── lib/index.js     cordis plugin: apply(), dispose(), Config
│               ├── lib/tools.js     13 defineTool declarations (schema + renderer)
│               └── lib/runtime.js   transport (wsl | ssh | local) + JSON protocol
│
│        transport:  wsl.exe --exec bash -lc '<argv>'     (Windows → WSL)
│                    pwsh … ssh.exe … 'bash -lc <argv>'   (Windows → SSH)
│                    bash -lc '<argv>'                    (Linux host)
▼
Linux desktop session (KDE Plasma)
└── kde_uia python client (vendored in python/, installed at /opt/dsh/kde-uia)
      ├── ops.py / ops_cli.py    one JSON operation per process: {"ok":…}
      ├── tree.py / element.py   AT-SPI accessibles, traversal, find, refs
      ├── window_backends.py     KWin scripting (D-Bus) + X11 (wmctrl/xdotool)
      ├── input.py               AT-SPI actions, xdotool, kdotool, clipboard
      ├── screenshot.py          KWin shadow buffer, spectacle, grim, import, xwd, portal
      ├── screens.py             logical ↔ device pixel mapping (HiDPI)
      └── selector.py / keys.py  condition trees, key-combination parsing
```

## Why the work happens in Python, not in Node

DSH on Windows cannot open the Linux session bus or the accessibility bus, and on Linux the
AT-SPI client is only practical through PyGObject (`libatspi`'s C API with a running GLib
main loop). So the plugin keeps the Node side deliberately small and *host-agnostic* — it only
declares tools and transports calls — while everything touching the desktop lives in one
Python package that runs inside the Linux session. The same package is a standalone library and
CLI, so the automation can be tested and used without DSH.

## Call path of one tool call

1. The model calls `kde_uia_click { "ref": … }`; `defineTool` validates the arguments against
   the declared schema.
2. `lib/tools.js` maps it to the client op `click` and the client's argument object.
3. `lib/runtime.js` serialises the arguments to JSON, base64-encodes them into the script, and
   submits `wsl.exe … --exec bash -lc "<fixed script>"` through DSH's shell seam (`ctx.shell`)
   with `exec.signal` for cancellation and `timeoutMs` as the budget.
4. The script writes the decoded arguments to `file://<client>/.runtime/args.json`, runs
   `python3 -m kde_uia ops click --args-file … --result …`, prints the result document, and
   removes both files.
5. `parseDocument` picks the last JSON document out of the output; `ok: false` becomes a tool
   `Error` whose message carries the client's message and hint.
6. The renderer turns the value into the text the model reads.

## Client internal design notes

- **Serialised AT-SPI calls.** libatspi runs one blocking loop; the client funnels every call
  through a single worker with a timeout, so a wedged application becomes `ATSPI_TIMEOUT`
  instead of a hang, and concurrent calls get `BUSY`.
- **Stateless refs.** A ref is `application + child-index path`; resolving it re-walks the tree.
  This trades stability for simplicity and process independence (each CLI call is a new process).
- **KWin scripting bridge.** Plasma offers no per-call "run this JS now" D-Bus method, so the
  client loads a small KWin script that reads its arguments from the script's own KConfig
  section (`readConfig`), writes one JSON answer per call, and watches `configChanged`. That
  makes each CLI process independent while keeping one long-lived script.
- **Coordinate model.** AT-SPI and KWin report logical compositor pixels; captures are device
  pixels (output `devicePixelRatio`). `screens.py` converts between them for clicks and crops.
- **Fail-loud errors.** Every failure is a coded error with a hint; the plugin surfaces both.

## Testing strategy

| Layer | Tests | Needs |
|---|---|---|
| Python logic (refs, selectors, keys, screens, wait, protocol) | `kde-uia/tests/test_pure.py` | nothing |
| Python tree behaviour | same file, in-memory fake AT-SPI tree | nothing |
| Node tool declarations | `dsh-plugin-kde-uia/tests/tools.test.js` | the real `defineTool` when a DSH install/probe copy is present, else a strict mock |
| Node transport & protocol | `tests/runtime.test.js` | nothing (argv capture) |
| Plugin wiring | `tests/plugin.test.js` | nothing (fake ctx/tools/shell) |
| Docs contract | `tests/docs.test.js` | nothing |

What is *not* covered by automated tests here: a real Plasma session (needs a desktop, KWin and
the AT-SPI bus). `kde_uia_doctor`, `scripts/probe-contract.sh` and the manual loop in the README
are the acceptance path for that environment.
