"""CLI implementation for the ``kde-uia`` command.

Design rules:

* Human-facing messages go to **stderr**, results to **stdout** (``--json``
  prints the machine-readable document on stdout only).
* Exit status: ``0`` ok, ``1`` coded failure, ``2`` usage error, ``124``
  wait timeout (``kde-uia wait``), so shell scripts can branch on it.
* Errors print ``error: <message>`` plus ``code:`` and ``hint:`` lines.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .errors import KdeUiaError, UsageError
from .ops import OPS
from .session import DesktopSession, Options

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_TIMEOUT = 124

EXAMPLES = """examples:
  kde-uia doctor                                    check the whole stack
  kde-uia windows                                   list accessible windows
  kde-uia tree --window Dolphin --depth 5           dump a window's element tree
  kde-uia find --role push-button --text "Save"     find elements
  kde-uia click --text "Save" --role push-button    click by accessible name
  kde-uia press CTRL+Shift+t                        key combination
  kde-uia type "hello" --submit                     type text + Enter
  kde-uia wait --for window --app dolphin --timeout 15
  kde-uia screenshot --window Dolphin -o /tmp/d.png
  kde-uia ops windows --args '{}' --result /tmp/out.json    (plugin protocol)
"""


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="print the JSON result document on stdout")
    parser.add_argument("--backend", choices=("auto", "kwin", "x11", "atspi"), default="auto",
                        help="window backend (default: auto)")
    parser.add_argument("--input", choices=("auto", "atspi", "xdotool", "kdotool", "dbus", "dry-run"),
                        default="auto", help="input strategy (default: auto)")
    parser.add_argument("--screenshot-strategy", choices=("auto", "kwin", "spectacle", "grim", "import", "xwd", "portal", "drm"),
                        default="auto", help="screenshot strategy (default: auto)")
    parser.add_argument("--timeout", type=float, default=None, help="AT-SPI call timeout in seconds (default 10)")
    parser.add_argument("--allow-xdotool-on-wayland", action="store_true",
                        help="permit xdotool on a Wayland session (it only sees XWayland windows)")
    parser.add_argument("--quiet", action="store_true", help="suppress informational stderr output")
    parser.add_argument("-V", "--version", action="version", version=f"kde-uia {__version__}")


def _add_selector(parser: argparse.ArgumentParser, *, scope: bool = True) -> None:
    parser.add_argument("--role", help="element role, e.g. push-button, entry, text, list item")
    parser.add_argument("--name", help="accessible name (exact unless --match is used)")
    parser.add_argument("--text", help="shorthand: match name OR value")
    parser.add_argument("--description", help="accessible description")
    parser.add_argument("--match", choices=("exact", "contains", "regex"), default="contains",
                        help="how text options compare (default: contains, case-insensitive)")
    parser.add_argument("--case", action="store_true", help="case-sensitive matching")
    parser.add_argument("--state", action="append", default=[], metavar="STATE[=false]",
                        help="required state, repeatable (e.g. --state focusable --state enabled)")
    parser.add_argument("--attribute", action="append", default=[], metavar="KEY=VALUE",
                        help="required accessible attribute, repeatable")
    parser.add_argument("--depth", type=int, default=None, help="search depth limit")
    parser.add_argument("--limit", type=int, default=50, help="maximum matches (default 50)")
    if scope:
        parser.add_argument("--window", help="restrict to one window (title contains)")
        parser.add_argument("--app", help="restrict to one application name")
        parser.add_argument("--window-id", dest="window_id", help="restrict to one window id (KWin/X11)")
    parser.add_argument("--ref", help="address the element directly by its uia: ref")
    parser.add_argument("--selector", help="JSON selector document (overrides the flags above)")


def _selector_from_args(ns: argparse.Namespace) -> dict[str, Any] | None:
    if getattr(ns, "selector", None):
        return json.loads(ns.selector)
    data: dict[str, Any] = {}
    for key in ("role", "name", "text", "description"):
        value = getattr(ns, key, None)
        if value is not None:
            data[key] = value
    if getattr(ns, "match", "contains") != "contains":
        data["match"] = ns.match
    if getattr(ns, "case", False):
        data["case"] = True
    states: dict[str, bool] = {}
    for item in getattr(ns, "state", []) or []:
        name, _, raw = item.partition("=")
        states[name.strip()] = raw.strip().lower() not in ("false", "0", "no")
    if states:
        data["states"] = states
    attributes: dict[str, str] = {}
    for item in getattr(ns, "attribute", []) or []:
        key, sep, value = item.partition("=")
        if not sep:
            raise UsageError(f"--attribute expects KEY=VALUE, got {item!r}")
        attributes[key.strip()] = value
    if attributes:
        data["attributes"] = attributes
    if getattr(ns, "depth", None) is not None:
        data["depth"] = ns.depth
    if getattr(ns, "limit", None):
        data["limit"] = ns.limit
    for key in ("window", "app", "window_id"):
        value = getattr(ns, key, None)
        if value:
            data[key] = value
    if not data:
        return None
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kde-uia",
        description="Windows-UI-Automation-style desktop automation for Linux, KDE Plasma first.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_common(parser)
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    def command(name: str, help_text: str) -> argparse.ArgumentParser:
        child = sub.add_parser(name, help=help_text)
        return child

    command("doctor", "check display, AT-SPI, window backend, input and screenshot capabilities")
    command("env", "print environment and capability facts")
    command("version", "print the version")

    p = command("windows", "list windows (AT-SPI + KWin/X11)")
    p.add_argument("--all", action="store_true", help="include hidden/iconified windows")

    command("active-window", "describe the active window")
    command("focused", "describe the focused element")

    p = command("tree", "print a window (or an element) as an indented element tree")
    _add_selector(p)
    p.add_argument("--max-nodes", type=int, default=200, help="node budget (default 200)")
    p.add_argument("--extents", action="store_true", help="append on-screen rectangles")
    p.add_argument("--no-refs", action="store_true", help="omit uia: refs")

    p = command("find", "find elements by selector")
    _add_selector(p)
    p.add_argument("--refs", action="append", help="check that references are still alive (repeatable)")

    p = command("info", "describe one element")
    _add_selector(p)

    p = command("activate", "activate a window")
    _add_selector(p)
    p.add_argument("--id", help="window id from `kde-uia windows`")

    p = command("window", "close/minimize/maximize/move/resize a window")
    p.add_argument("op", choices=("close", "minimize", "maximize", "restore", "move", "resize"))
    p.add_argument("--window", help="window title (contains)")
    p.add_argument("--app", help="application name (contains)")
    p.add_argument("--id", help="window id")
    p.add_argument("--x", type=int, help="x for move")
    p.add_argument("--y", type=int, help="y for move")
    p.add_argument("--width", type=int, help="width for resize")
    p.add_argument("--height", type=int, help="height for resize")

    p = command("click", "click an element (or x,y) with an accessibility action or the pointer")
    _add_selector(p)
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.add_argument("--button", choices=("left", "middle", "right"), default="left")
    p.add_argument("--clicks", type=int, default=1)
    p.add_argument("--region", choices=("client", "frame"), default="client")
    p.add_argument("--strategy", choices=("auto", "atspi", "xdotool", "kdotool", "dbus"), default="auto")
    p.add_argument("--dry-run", action="store_true")

    p = command("press", "press a key or key combination")
    p.add_argument("key", help="e.g. Return, ctrl+l, Ctrl+Shift+t, F5, Alt+F4")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--dry-run", action="store_true")

    p = command("type", "type text into the focused (or referenced) widget")
    p.add_argument("text")
    _add_selector(p)
    p.add_argument("--submit", action="store_true", help="press Return afterwards")
    p.add_argument("--interval-ms", type=int, default=0)
    p.add_argument("--no-focus", action="store_true", help="do not focus the element first")
    p.add_argument("--dry-run", action="store_true")

    p = command("scroll", "scroll with the wheel at a point or over an element")
    _add_selector(p)
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.add_argument("--direction", choices=("up", "down", "left", "right"), default="down")
    p.add_argument("--amount", type=int, default=3)
    p.add_argument("--dry-run", action="store_true")

    p = command("set", "set an element value (Value or editable-text interface)")
    _add_selector(p)
    p.add_argument("value")

    p = command("toggle", "toggle a check/radio/press button")
    _add_selector(p)
    p.add_argument("--to", choices=("on", "off", "true", "false"), help="desired state")
    p.add_argument("--dry-run", action="store_true")

    p = command("focus", "give an element keyboard focus")
    _add_selector(p)

    p = command("expand", "expand a combo/menu item")
    _add_selector(p)

    p = command("wait", "wait until an element/window appears, disappears or gets focus")
    p.add_argument("--for", dest="for_", default="element",
                   choices=("element", "gone", "window", "window-gone", "idle"), help="what to wait for")
    _add_selector(p)
    p.add_argument("--interval", type=float, default=None, help="poll interval seconds (default 0.25)")

    p = command("screenshot", "capture the desktop, a window or an element (PNG)")
    p.add_argument("-o", "--output", help="PNG path (default: a temp file)")
    p.add_argument("--window", help="window title (contains)")
    p.add_argument("--app", help="application name")
    p.add_argument("--id", help="window id")
    p.add_argument("--ref", help="element reference to crop around")
    p.add_argument("--strategy", choices=("auto", "kwin", "spectacle", "grim", "import", "xwd", "portal", "drm"),
                   default=None)

    p = command("open", "launch an application, optionally wait for its window and screenshot it")
    p.add_argument("command", help="command line to start, e.g. 'kwrite /tmp/a.txt'")
    p.add_argument("--window", help="window title to wait for")
    p.add_argument("--app", help="application name to wait for")
    p.add_argument("--screenshot", help="save a screenshot of the window to this path")

    p = command("ops", "run one JSON operation (plugin/automation protocol)")
    p.add_argument("op", choices=sorted(OPS))
    p.add_argument("--args", default="{}", help="JSON argument object")
    p.add_argument("--result", help="also write the JSON answer to this path")

    return parser


def _session(ns: argparse.Namespace) -> DesktopSession:
    return DesktopSession(Options(
        window_backend=ns.backend,
        input_strategy=ns.input,
        screenshot_strategy=ns.screenshot_strategy,
        atspi_timeout=ns.timeout or 10.0,
        wait_timeout=10.0,
        dry_run=getattr(ns, "dry_run", False),
    ))


def _dispatch(ns: argparse.Namespace, session: DesktopSession) -> dict[str, Any]:
    command = ns.command
    if command in ("version",):
        return {"version": __version__}
    if command == "ops":
        op_args = json.loads(ns.args)
        result = OPS[ns.op](session, op_args)
        if ns.result:
            Path(ns.result).write_text(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=1), encoding="utf-8")
        return result
    selector = _selector_from_args(ns) if hasattr(ns, "role") else None
    if command == "windows":
        return OPS["windows"](session, {"include_hidden": ns.all, "selector": selector})
    if command == "tree":
        return OPS["tree"](session, {"selector": selector, "ref": ns.ref, "depth": ns.depth if ns.depth is not None else 4,
                                     "max_nodes": ns.max_nodes, "include_extents": ns.extents, "no_refs": ns.no_refs,
                                     "window": ns.window, "app": ns.app})
    if command == "find":
        return OPS["find"](session, {"selector": selector, "refs": ns.refs})
    if command == "info":
        return OPS["info"](session, {"selector": selector, "ref": ns.ref})
    if command == "activate":
        return OPS["activate"](session, {"selector": selector, "id": ns.id, "window": ns.window, "app": ns.app})
    if command == "window":
        return OPS["window"](session, {"op": ns.op, "window": ns.window, "app": ns.app, "id": ns.id,
                                       "x": ns.x, "y": ns.y, "width": ns.width, "height": ns.height})
    if command == "click":
        return OPS["click"](session, {"selector": selector, "ref": ns.ref, "x": ns.x, "y": ns.y, "button": ns.button,
                                      "clicks": ns.clicks, "region": ns.region, "strategy": ns.strategy,
                                      "dry_run": ns.dry_run, "window": ns.window, "app": ns.app})
    if command == "press":
        return OPS["press"](session, {"key": ns.key, "repeat": ns.repeat, "dry_run": ns.dry_run})
    if command == "type":
        return OPS["type"](session, {"text": ns.text, "ref": ns.ref, "target": selector, "submit": ns.submit,
                                     "interval_ms": ns.interval_ms, "no_focus": ns.no_focus, "dry_run": ns.dry_run})
    if command == "scroll":
        return OPS["scroll"](session, {"selector": selector, "ref": ns.ref, "target": selector, "x": ns.x, "y": ns.y,
                                       "direction": ns.direction, "amount": ns.amount, "dry_run": ns.dry_run})
    if command == "set":
        return OPS["set"](session, {"selector": selector, "ref": ns.ref, "value": ns.value})
    if command == "toggle":
        desired = None if ns.to is None else ns.to in ("on", "true")
        return OPS["toggle"](session, {"selector": selector, "ref": ns.ref, "state": desired, "dry_run": ns.dry_run})
    if command == "focus":
        return OPS["focus"](session, {"selector": selector, "ref": ns.ref})
    if command == "expand":
        return OPS["expand"](session, {"selector": selector, "ref": ns.ref})
    if command == "wait":
        return OPS["wait"](session, {"for": ns.for_, "selector": selector, "ref": ns.ref,
                                     "window": ns.window, "app": ns.app, "interval": ns.interval,
                                     "timeout": ns.timeout or 10.0})
    if command == "screenshot":
        return OPS["screenshot"](session, {"output": ns.output, "window": ns.window, "app": ns.app, "id": ns.id,
                                           "ref": ns.ref, "strategy": ns.strategy})
    if command == "open":
        return OPS["open"](session, {"command": ns.command, "window": ns.window, "app": ns.app,
                                     "screenshot": ns.screenshot})
    if command in ("doctor", "env"):
        return OPS[command](session, {})
    if command in ("active-window", "focused"):
        return OPS[command](session, {})
    raise UsageError(f"unknown command {command!r}")


def _human(ns: argparse.Namespace, result: dict[str, Any]) -> None:
    """Readable output on stdout for the common commands."""
    command = ns.command
    if command == "version":
        print(f"kde-uia {result['version']}")
        return
    if command == "windows":
        rows = result.get("windows", [])
        if not rows:
            print("(no windows)")
        for row in rows:
            title = (row.get("title") or "").rstrip()
            app = row.get("app") or ""
            frame = row.get("frame") or row.get("extents") or {}
            geo = f"{frame.get('width', '?')}x{frame.get('height', '?')}+{frame.get('x', '?')}+{frame.get('y', '?')}" if frame else "?"
            flag = "*" if row.get("active") else " "
            print(f"{flag} {row.get('id') or row.get('ref'):>10}  {geo:<16} {app:<18} {title}")
        return
    if command == "tree":
        print(result.get("text", ""))
        return
    if command == "find":
        elements = result.get("elements", [])
        for element in elements:
            rect = element.get("extents") or {}
            where = f"@{rect.get('x')},{rect.get('y')} {rect.get('width')}x{rect.get('height')}" if rect else ""
            print(f"{element['role']:<20} {element['name']!r:<40} {where:<24} {element['ref']}")
        if not elements:
            print("(no matches)")
        return
    if command == "doctor":
        for check in result.get("checks", []):
            mark = {"ok": "+", "fail": "x", "skip": "-"}.get(check["status"], "?")
            print(f"[{mark}] {check['check']:<16} {check['detail']}")
            if check.get("hint"):
                print(f"    hint: {check['hint']}")
        return
    if command == "screenshot":
        print(result.get("path"))
        return
    if command == "wait":
        print(f"met after {result.get('elapsed')}s")
        return
    if command in ("type", "press", "click", "scroll", "toggle", "focus", "expand", "window"):
        backend = result.get("backend") or result.get("source") or result.get("op")
        print(f"ok ({backend})" if backend else "ok")
        return
    if command in ("active-window", "focused", "info"):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        ns = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    if not getattr(ns, "command", None):
        parser.print_help()
        return EXIT_USAGE
    session = _session(ns)
    try:
        result = _dispatch(ns, session)
    except KdeUiaError as exc:
        if getattr(ns, "json", False):
            print(json.dumps({"ok": False, "error": exc.to_dict()}, ensure_ascii=False, indent=1))
        else:
            print(f"error: {exc.message}", file=sys.stderr)
            print(f"code: {exc.code}", file=sys.stderr)
            if exc.hint:
                print(f"hint: {exc.hint}", file=sys.stderr)
        if exc.code == "USAGE":
            return EXIT_USAGE
        if exc.code == "TIMEOUT":
            return EXIT_TIMEOUT
        return EXIT_ERROR
    except KeyboardInterrupt:
        return 130
    finally:
        session.close()
    if getattr(ns, "json", False):
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=1))
    else:
        _human(ns, result)
    return EXIT_OK


def _install_sigterm() -> None:
    def handler(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handler)


if __name__ == "__main__":  # pragma: no cover
    _install_sigterm()
    sys.exit(main())
