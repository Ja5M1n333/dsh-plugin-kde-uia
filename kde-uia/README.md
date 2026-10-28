# kde-uia

Windows UI Automation–style desktop automation for Linux, **KDE Plasma first**.
AT-SPI2 element trees and semantic actions, KWin scripting for windows, X11/kdotool
for synthetic input, multi-backend screenshots. Zero pip dependencies, one JSON
operation per process.

This package is the engine behind the DeepSeek Harness plugin
[`dsh-plugin-kde-uia`](../dsh-plugin-kde-uia) (which ships a vendored copy under
`python/`), and it works on its own as a library and a CLI.

## Install

System packages (Debian/Ubuntu/KDE neon):

```bash
sudo apt install python3-gi gir1.2-atspi-2.0 at-spi2-core qdbus6 xdotool wmctrl spectacle
```

The client itself needs no pip dependencies:

```bash
pip install .            # or: PYTHONPATH=src python3 -m kde_uia …
```

## Use

```bash
kde-uia doctor                       # what works here, with fixes
kde-uia windows
kde-uia tree --window Dolphin --depth 5
kde-uia find --role push-button --text "New Tab"
kde-uia click --ref uia:1:dolphin:0/1/0
kde-uia press ctrl+l
kde-uia type "trash:///" --submit
kde-uia wait --for window --window Trash --timeout 10
kde-uia screenshot --window Trash -o /tmp/trash.png
```

Library:

```python
from kde_uia import Client, Selector

with Client() as ui:
    window = ui.window(window="Dolphin")
    field = ui.find_first(Selector(text="Filter", window=window.title))
    ui.type("report", target=field, submit=True)
```

Machine protocol (used by the DSH plugin):

```bash
python3 -m kde_uia ops windows --args '{}' --result /tmp/out.json
```

Full command list: `docs/tools.md` in the plugin package · subprocess protocol:
`docs/protocol.md`.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests    # 46 tests, no desktop needed
bash scripts/dev-smoke.sh                               # import + doctor + ops protocol here
```

## Notes

- Refs (`uia:1:<app>:<path>`) are stateless paths; re-take them after a window changes.
- On Wayland install `kdotool` for pointer/keyboard input (or use `--strategy atspi`).
- `doctor` names the exact package to install for every failing capability.

MIT.
