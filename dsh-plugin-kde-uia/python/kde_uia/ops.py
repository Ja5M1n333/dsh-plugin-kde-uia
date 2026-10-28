"""The command implementations behind the CLI and the DSH tools.

Each function is a thin, cancellable orchestration over :mod:`kde_uia.session`:

* it validates arguments and raises coded :class:`~kde_uia.errors.KdeUiaError`
  subclasses (never prints);
* it returns plain JSON-serialisable dictionaries;
* it accepts an optional ``ProgressReporter`` for human-facing stderr output
  in the CLI.

Sub-commands are also reachable as ``python -m kde_uia ops <name> ...`` by
the DSH plugin.
"""

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import env as env_mod
from .errors import (
    BackendUnavailableError,
    InputError,
    InvalidRefError,
    KdeUiaError,
    NoDisplayError,
    NotFoundError,
    NotActionableError,
    UsageError,
)
from .refs import parse_ref
from .selector import Selector
from .session import DesktopSession, Options
from .wait import wait_for


@dataclass
class Progress:
    """Optional stderr channel for the CLI (silent for tools)."""

    enabled: bool = False

    def note(self, message: str) -> None:
        if self.enabled:
            import sys

            print(message, file=sys.stderr, flush=True)


def _as_int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise UsageError(f"{name} must be an integer, got {value!r}") from exc


def _resolve_target(session: DesktopSession, args: dict[str, Any]) -> tuple[Any, Selector]:
    """Resolve an element target: explicit ref wins, else the selector + window scope."""
    selector = Selector.from_dict(args.get("selector"))
    if args.get("window") or args.get("app") or args.get("window_id"):
        # Ad-hoc scope fused onto the selector when callers pass flat options.
        fused = {**selector.to_dict(), "window": args.get("window"), "app": args.get("app"), "window_id": args.get("window_id")}
        selector = Selector.from_dict(fused)
    ref = args.get("ref")
    if ref:
        return session.tree.resolve_ref(str(ref)), selector
    if selector.is_empty:
        raise UsageError(
            "an action needs a target: pass `ref`, or a selector (role/name/text/states), optionally scoped by window",
            hint='Examples: {"ref": "uia:1:kwrite:1/0/2"} or {"selector": {"role": "push-button", "name": "Save", "window": "Untitled"}}',
        )
    return session.tree.resolve_element(selector=selector), selector


def _window_of(session: DesktopSession, element: Any) -> dict[str, Any] | None:
    """Best window description for an element (KWin frame when possible)."""
    wm = None
    try:
        wm = session.window_backend()
    except KdeUiaError:
        wm = None
    title, app = None, None
    node = element
    for candidate in [element, *element.ancestors()]:
        role = candidate.role_name()
        if role in ("frame", "dialog", "alert", "window", "file chooser"):
            title, app = candidate.name(), candidate.app_root().name()
            break
    if wm is None:
        return {"title": title, "app": app, "backend": "atspi"}
    try:
        active = wm.active()
    except KdeUiaError:
        active = None
    if active and title and (active.get("caption") or "").startswith(title[:20]):
        return {"title": active.get("caption"), "app": active.get("resourceClass"), "id": active.get("id"),
                "frame": active.get("frame"), "backend": wm.__class__.__name__.replace("Backend", "").lower()}
    return {"title": title, "app": app, "backend": "atspi"}


# ======================================================================
# Discovery
# ======================================================================
def env_info(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    from .input import available_backends
    from .screenshot import ScreenshotService

    environment = env_mod.detect_environment()
    info = environment.to_dict()
    info["input"] = available_backends()
    info["screenshots"] = ScreenshotService().available()
    info["guiContext"] = env_mod.has_gui_context()
    try:
        from .window_backends import KwinBackend, X11Backend

        backends = {}
        try:
            KwinBackend().ensure_loaded()
            backends["kwin"] = "ok"
        except KdeUiaError as exc:
            backends["kwin"] = f"unavailable: {exc.message}"
        try:
            X11Backend()
            backends["x11"] = "ok"
        except KdeUiaError as exc:
            backends["x11"] = f"unavailable: {exc.message}"
        info["windowBackends"] = backends
    except KdeUiaError:
        pass
    return info


def diagnose(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    """Run every capability check and report what works, with hints."""
    checks: list[dict[str, Any]] = []

    def check(name: str, fn: Callable[[], tuple[str, str]]) -> None:
        try:
            status, detail = fn()
            checks.append({"check": name, "status": status, "detail": detail})
        except KdeUiaError as exc:
            checks.append({"check": name, "status": "fail", "detail": exc.message, "code": exc.code, "hint": exc.hint})
        except Exception as exc:  # noqa: BLE001 - diagnosis must not crash
            checks.append({"check": name, "status": "fail", "detail": f"{type(exc).__name__}: {exc}"})

    def display() -> tuple[str, str]:
        if not env_mod.has_gui_context():
            raise NoDisplayError("neither DISPLAY nor WAYLAND_DISPLAY is set", hint="See the plugin runtime notes.")
        env = env_mod.detect_environment(probe_atspi=False)
        return "ok", f"{env.desktop} / {env.session_type} / display={env.display or env.wayland_display}"

    def atspi() -> tuple[str, str]:
        conn = session.conn
        desktop = conn.dispatch()
        apps = desktop.child_count() if desktop is not None else 0
        return "ok", f"atspi initialised; {apps} registered applications"

    def windows() -> tuple[str, str]:
        windows = session.tree.windows()
        return "ok", f"{len(windows)} accessible windows"

    def wm() -> tuple[str, str]:
        backend = session.window_backend()
        if backend is None:
            return "skip", "window backend disabled by --backend atspi"
        listing = backend.windows()
        return "ok", f"{type(backend).__name__}: {len(listing)} windows"

    def input_probe() -> tuple[str, str]:
        from .input import available_backends

        available = available_backends()
        ready = [k for k, v in available.items() if v and k != "waylandSession"]
        if not ready:
            raise BackendUnavailableError("no input backend available")
        return "ok", "available: " + ", ".join(ready)

    def shot() -> tuple[str, str]:
        from .screenshot import ScreenshotService

        available = ScreenshotService(timeout=15).available()
        ready = [k for k, v in available.items() if v]
        if not ready:
            raise BackendUnavailableError("no screenshot backend available")
        return "ok", "available: " + ", ".join(ready)

    check("display", display)
    check("atspi", atspi)
    check("window-tree", windows)
    check("window-backend", wm)
    check("input", input_probe)
    check("screenshot", shot)

    failed = [c for c in checks if c["status"] == "fail"]
    return {"ok": not failed, "checks": checks,
            "hint": None if not failed else "Fix the failing checks above; each names the code and the next step."}


def list_windows(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    include_hidden = bool(args.get("include_hidden"))
    selector = Selector.from_dict(args.get("selector"))
    windows: list[dict[str, Any]] = []
    error: str | None = None
    try:
        for info in session.tree.windows(include_hidden=include_hidden):
            windows.append({**info.to_dict(), "source": "atspi"})
    except KdeUiaError as exc:
        error = exc.message
        for app in session.tree.applications():
            _ = app
            break
    backend = None
    try:
        backend = session.window_backend()
    except KdeUiaError as exc:
        if not windows:
            error = (error or "") + f"; window backend: {exc.message}"
    if backend is not None:
        try:
            for row in backend.windows():
                windows.append({
                    "title": row.get("caption", ""),
                    "app": row.get("resourceClass", ""),
                    "role": "frame",
                    "id": row.get("id"),
                    "frame": row.get("frame"),
                    "active": bool(row.get("active")),
                    "minimized": bool(row.get("minimized")),
                    "desktop": row.get("desktop"),
                    "pid": row.get("pid"),
                    "source": "kwin" if type(backend).__name__.startswith("Kwin") else "x11",
                })
        except KdeUiaError as exc:
            error = (error or "") + f"; {exc.message}"
    out = []
    for row in windows:
        if selector.app and selector.app.casefold() not in (row.get("app") or "").casefold():
            continue
        if selector.window is not None and not selector._match_value(row.get("title") or "", selector.window):
            continue
        out.append(row)
    result: dict[str, Any] = {"windows": out, "count": len(out)}
    if error:
        result["degraded"] = True
        result["degradedReason"] = error
    elif not out:
        result["hint"] = ("No windows reported. Is accessibility enabled for the applications "
                          "(KDE System Settings > Accessibility), or are they starting?")
    return result


def active_window(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    try:
        backend = session.window_backend()
    except KdeUiaError:
        backend = None
    row: dict[str, Any] | None = None
    if backend is not None:
        row = backend.active()
    if row:
        return {"active": True, "source": "wm", "window": {
            "id": row.get("id"), "title": row.get("caption"), "app": row.get("resourceClass"),
            "frame": row.get("frame"), "minimized": row.get("minimized"),
        }}
    try:
        info = session.tree.active_window()
        return {"active": True, "source": "atspi", "window": info.to_dict()}
    except KdeUiaError as exc:
        raise NotFoundError(str(exc), hint=exc.hint,
                            details={"windowBackendError": exc.message if backend is None else "n/a"}) from exc


def focused(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    element = session.tree.focused()
    if element is None:
        raise NotFoundError("no element has keyboard focus", hint="Click into the target window, or activate it first.")
    details = element.match_summary()
    chain = []
    for ancestor in [element, *element.ancestors()]:
        chain.append(f"{ancestor.role_name()} {ancestor.name()!r}".strip())
        if len(chain) >= 6:
            break
    details["path"] = list(reversed(chain))
    details["value"] = element.text_or_value()
    return details


# ======================================================================
# Tree and element queries
# ======================================================================
def tree(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    from .tree import TreeRenderOptions, render_tree

    selector = Selector.from_dict(args.get("selector"))
    if args.get("window"):
        selector = Selector.from_dict({**selector.to_dict(), "window": args["window"]})
    if args.get("app"):
        selector = Selector.from_dict({**selector.to_dict(), "app": args["app"]})
    if args.get("ref"):
        root = session.tree.resolve_ref(str(args["ref"]))
        window = _window_of(session, root)
    else:
        info = session.tree.resolve_window(selector)
        root = info.element
        window = info.to_dict()
    options = TreeRenderOptions(
        max_depth=_as_int(args.get("depth", 4), "depth"),
        max_nodes=_as_int(args.get("max_nodes", args.get("maxNodes", 200)), "max_nodes"),
        include_extents=bool(args.get("include_extents")),
        include_refs=not bool(args.get("no_refs")),
    )
    rendered = render_tree(session.tree, root, options)
    return {"window": window, "text": rendered.text, "nodes": rendered.nodes,
            "truncated": rendered.truncated, "rootRef": root.ref(),
            "hint": "Re-run with depth>=6 or a ref to see deeper subtrees." if rendered.truncated else None}


def find(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    selector = Selector.from_dict(args.get("selector"))
    refs = args.get("refs") or []
    if not selector.is_empty and refs:
        raise UsageError("find takes either a selector or refs, not both")
    if refs:
        results = []
        failures = []
        for ref in refs:
            try:
                element = session.tree.resolve_ref(str(ref))
            except KdeUiaError as exc:
                failures.append({"ref": ref, "error": exc.to_dict()})
                continue
            results.append({**element.match_summary(), "value": element.text_or_value()})
        return {"ref": str(results[0]["ref"]) if len(results) == 1 else None,
                "found": bool(results) and not failures, "elements": results, "failures": failures}
    if selector.is_empty:
        raise UsageError(
            "find needs a selector",
            hint='Example: {"selector": {"role": "push-button", "name": "Save"}} or {"text": "Save"}',
        )
    found = session.tree.find(selector)
    elements = [{**e.match_summary(), "value": e.text_or_value()} for e in found]
    result = {
        "ref": elements[0]["ref"] if len(elements) == 1 else None,
        "found": bool(elements),
        "count": len(elements),
        "elements": elements,
        "selector": selector.to_dict(),
    }
    if not elements:
        result["hint"] = "No match. Inspect the window with `tree` and match roles/names as they appear there."
    elif len(elements) > 1:
        result["hint"] = "Several matches; take one ref or add conditions (states, description, window)."
    return result


def element_info(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    element, _ = _resolve_target(session, args)
    details: dict[str, Any] = {
        "ref": element.ref(),
        "role": element.role_name(),
        "name": element.name(),
        "description": element.description(),
        "value": element.text_or_value(),
        "app": element.app_name(),
        "backendId": element.backend_id(),
        "extents": _rect(element.extents()),
        "states": element.states(),
        "actions": element.actions(),
        "attributes": element.attributes(),
        "interfaces": element.role_supported_interfaces(),
        "children": element.child_count(),
    }
    chain = []
    node = element
    for _ in range(8):
        if node is None:
            break
        chain.append(f"{node.role_name()} {node.name()!r}".strip())
        node = node.parent
    details["path"] = list(reversed(chain))
    window = _window_of(session, element)
    if window:
        details["window"] = window
    return details


def _rect(rect: tuple[int, int, int, int] | None) -> dict[str, int] | None:
    if rect is None:
        return None
    x, y, w, h = rect
    return {"x": x, "y": y, "width": w, "height": h}


# ======================================================================
# Activation
# ======================================================================
def activate_window(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    selector = Selector.from_dict(args.get("selector"))
    for key in ("window", "app", "window_id"):
        if args.get(key):
            selector = Selector.from_dict({**selector.to_dict(), key: args[key]})
    window_id = args.get("id")
    target: dict[str, Any] | None = None
    backend = None
    try:
        backend = session.window_backend()
    except KdeUiaError:
        backend = None
    if window_id and backend is not None:
        target = backend.info(str(window_id))
    elif backend is not None:
        rows = backend.windows()
        need = (selector.window or "").casefold()
        matches = [r for r in rows if not need or need in (r.get("caption") or "").casefold()]
        if selector.app:
            matches = [r for r in matches if selector.app.casefold() in (r.get("resourceClass") or "").casefold()]
        if not matches:
            listing = ", ".join(repr(r.get("caption")) for r in rows[:10])
            raise NotFoundError(f"no window matched ({selector.scope_text()})", hint=f"Open windows: {listing}.")
        if len(matches) > 1:
            listing = ", ".join(f"{r.get('caption')!r} ({r.get('id')})" for r in matches[:10])
            raise UsageError(f"{len(matches)} windows matched: {listing}", hint="Narrow with app= or pass id.")
        target = matches[0]
    if backend is not None and target is not None:
        target = backend.act("activate", str(target.get("id")))
        wait_for(lambda: (backend.active() or {}).get("id") == target.get("id"),
                 timeout=min(session.options.wait_timeout, 5.0), what="window activation")
        return {"activated": True, "source": "wm", "window": {k: target.get(k) for k in ("id", "caption", "resourceClass", "frame")}}
    # Fall back to an accessibility action on the frame itself.
    info = session.tree.resolve_window(selector)
    if info.element.do_action("activate") or info.element.do_action("click"):
        return {"activated": True, "source": "atspi", "window": info.to_dict()}
    raise NotActionableError(
        "the window has no way to be activated: no window backend and no AT-SPI activate action",
        hint="Install kdotool (Wayland) or xdotool/wmctrl (X11), or activate it by clicking its titlebar.",
    )


def window_action(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    op = args.get("op")
    if op not in ("close", "minimize", "maximize", "restore", "move", "resize"):
        raise UsageError(f"unknown window op {op!r}", hint="close | minimize | maximize | restore | move | resize")
    selector = Selector.from_dict({"window": args.get("window"), "app": args.get("app")})
    window_id = args.get("id")
    backend = session.window_backend()
    if backend is None:
        raise BackendUnavailableError("window actions need a window backend", hint="Drop --backend atspi.")
    if window_id:
        info = backend.info(str(window_id))
    else:
        info = _match_backend_window(backend, selector)
    params: list[Any] = []
    if op in ("move",):
        params = [_as_int(args.get("x", 0), "x"), _as_int(args.get("y", 0), "y")]
    elif op in ("resize",):
        params = [_as_int(args.get("width", 0), "width"), _as_int(args.get("height", 0), "height")]
    result = backend.act(op, str(info.get("id")), params)
    return {"ok": True, "op": op, "window": result if isinstance(result, dict) else info}


def _match_backend_window(backend: Any, selector: Selector) -> dict[str, Any]:
    rows = backend.windows()
    matches = [r for r in rows if not selector.window or selector._match_value(r.get("caption") or "", selector.window)]
    if selector.app:
        matches = [r for r in matches if selector.app.casefold() in (r.get("resourceClass") or "").casefold()]
    if not matches:
        raise NotFoundError(f"no window matched ({selector.scope_text()})",
                            hint=", ".join(repr(r.get("caption")) for r in rows[:10]))
    if len(matches) > 1:
        raise UsageError(f"{len(matches)} windows matched", hint="Pass an exact id.")
    return matches[0]


def click(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    element, _ = _resolve_target(session, args)
    rect = element.extents()
    if args.get("x") is not None or args.get("y") is not None:
        point = (_as_int(args.get("x", 0), "x"), _as_int(args.get("y", 0), "y"))
    elif rect is not None:
        point = session.screen_map().element_center(_rect(rect) or {}, region=str(args.get("region", "client")))
    else:
        raise NotActionableError(
            "the element reports no on-screen geometry; it may be hidden or unmapped",
            hint="Scroll/lift it into view or pass explicit x/y.",
        )
    button = str(args.get("button", "left"))
    clicks = _as_int(args.get("clicks", 1), "clicks")
    strategy = str(args.get("strategy", session.options.input_strategy))
    if strategy == "atspi":
        from .input import _atspi_click

        if not _atspi_click(element):
            raise NotActionableError(
                "the element exposes no click/activate/toggle action",
                hint=f"Actions available: {', '.join(element.actions()) or 'none'}. Use --strategy xdotool to click by position.",
            )
        return {"ok": True, "backend": "atspi", "ref": element.ref(), "x": point[0], "y": point[1]}
    service = session.input()
    service.strategy = strategy if strategy != "auto" else session.options.input_strategy
    service.dry_run = bool(args.get("dry_run", False))
    result = service.click(point[0], point[1], button=button, clicks=clicks, element=element if service.strategy == "auto" else None)
    result.details["ref"] = element.ref()
    return {"ok": True, **result.to_dict()}


def press_key(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    key = args.get("key")
    if not key:
        raise UsageError("press needs `key`", hint="Example: CTRL+Shift+t, Enter, F5, Alt+F4.")
    service = session.input()
    service.dry_run = bool(args.get("dry_run", False))
    result = service.press(str(key), repeat=_as_int(args.get("repeat", 1), "repeat"))
    return {"ok": True, **result.to_dict()}


def type_text(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    text = args.get("text")
    if not isinstance(text, str) or text == "":
        raise UsageError("type needs non-empty `text`")
    element = None
    if args.get("ref"):
        element = session.tree.resolve_ref(str(args["ref"]))
    elif args.get("target"):
        element, _ = _resolve_target(session, args)
    if element is not None and not args.get("no_focus"):
        try:
            if element.acc.grab_focus():
                time.sleep(0.05)
        except Exception:
            pass
    service = session.input()
    service.dry_run = bool(args.get("dry_run", False))
    result = service.type_text(text, element=element, submit=bool(args.get("submit")),
                               interval_ms=_as_int(args.get("interval_ms", 0), "interval_ms"))
    if element is not None:
        result.details["ref"] = element.ref()
    return {"ok": True, **result.to_dict()}


def scroll(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    element = None
    if args.get("ref"):
        element = session.tree.resolve_ref(str(args["ref"]))
    elif args.get("target") or args.get("selector"):
        element, _ = _resolve_target(session, args)
    if args.get("x") is not None and args.get("y") is not None:
        point = (_as_int(args["x"], "x"), _as_int(args["y"], "y"))
    elif element is not None and element.extents() is not None:
        point = session.screen_map().element_center(_rect(element.extents()) or {})
    else:
        raise UsageError("scroll needs a target element or explicit x/y")
    service = session.input()
    service.dry_run = bool(args.get("dry_run", False))
    result = service.scroll(point[0], point[1], direction=str(args.get("direction", "down")),
                            amount=_as_int(args.get("amount", 3), "amount"))
    return {"ok": True, **result.to_dict()}


def set_value(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    element, _ = _resolve_target(session, args)
    value = args.get("value")
    if value is None:
        raise UsageError("set needs `value`")
    acc = element.acc
    # Range values (sliders, spin boxes) -> Value interface.
    try:
        float(value)
        is_number = True
    except (TypeError, ValueError):
        is_number = False
    if is_number:
        try:
            if acc.set_current_value(float(value), True):
                return {"ok": True, "interface": "value", "ref": element.ref(), "value": element.value()}
        except Exception:
            pass
    text_value = str(value)
    try:
        current = acc.get_text()
    except Exception:
        current = None
    if isinstance(current, str):
        start = 0
        end = int(acc.get_character_count() or len(current))
        try:
            if end > 0 and not acc.delete_text(start, end, True):
                raise RuntimeError("delete_text refused")
            if not acc.insert_text(start, text_value, len(text_value), True):
                raise RuntimeError("insert_text refused")
            return {"ok": True, "interface": "editable_text", "ref": element.ref(), "value": acc.get_text()}
        except Exception as exc:
            last_error = str(exc)
    else:
        last_error = "no editable-text interface"
    detail = element.actions()
    raise NotActionableError(
        f"the element does not expose a settable value ({last_error})",
        hint=f"Interfaces: {', '.join(element.role_supported_interfaces()) or 'unknown'}; actions: {', '.join(detail) or 'none'}. "
             f"Try click/type, or the value's spin buttons.",
    )


def toggle(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    element, _ = _resolve_target(session, args)
    desired = args.get("state")
    if desired is not None:
        desired = bool(desired)
    before = element.state("checked") or element.state("pressed") or element.state("selected")
    if args.get("dry_run"):
        return {"ok": True, "dryRun": True, "before": before, "desired": desired}
    if desired is not None and before == desired:
        return {"ok": True, "changed": False, "state": before, "ref": element.ref()}
    if not (element.do_action("click") or element.do_action("toggle")):
        raise NotActionableError(
            "the element has no toggle/click action",
            hint=f"Actions: {', '.join(element.actions()) or 'none'}. Click it by position instead.",
        )
    after = element.state("checked") or element.state("pressed") or element.state("selected")
    return {"ok": True, "changed": after != before, "before": before, "state": after, "ref": element.ref()}


def focus_element(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    element, _ = _resolve_target(session, args)
    ok = element.acc.grab_focus()
    if not ok:
        if element.do_action("focus"):
            ok = True
    if not ok:
        rect = element.extents()
        if rect is not None:
            point = session.screen_map().element_center(_rect(rect) or {})
            session.input().click(point[0], point[1], element=element)
            ok = True
    return {"ok": bool(ok), "ref": element.ref(), "focused": bool(element.state("focused"))}


def expand(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    element, _ = _resolve_target(session, args)
    if element.do_action("expand"):
        return {"ok": True, "expanded": element.state("expanded"), "ref": element.ref()}
    raise NotActionableError("the element has no expand action",
                             hint=f"Actions: {', '.join(element.actions()) or 'none'}.")


def select_text(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    element, _ = _resolve_target(session, args)
    acc = element.acc
    try:
        text = acc.get_text()
    except Exception:
        text = ""
    if not isinstance(text, str):
        raise NotActionableError("the element exposes no text interface")
    needle = args.get("text")
    if needle is None:
        start, end = 0, len(text)
    else:
        index = text.find(str(needle))
        if index < 0:
            raise NotFoundError(f"text {needle!r} is not in the element", hint=f"Element text: {text[:200]!r}")
        start, end = index, index + len(str(needle))
    _ = (start, end)
    # AT-SPI text selection needs Text.add_selection; not exposed by every toolkit.
    raise NotActionableError(
        "text selection is not implemented for this toolkit (AT-SPI Text.add_selection is not in the PyGObject binding)",
        hint="Use press-key CTRL+a in a focused field, or click/drag coordinates instead.",
    )


# ======================================================================
# Waiting and observation
# ======================================================================
def wait(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    kind = str(args.get("for", "element"))
    timeout = float(args.get("timeout", session.options.wait_timeout))
    interval = float(args.get("interval", session.options.poll_interval))
    started = time.monotonic()
    if kind == "element":
        raw_selector = args.get("selector")
        if raw_selector is None and args.get("text"):
            raw_selector = {"text": args["text"]}
        selector = Selector.from_dict(raw_selector)
        if selector.is_empty:
            raise UsageError("wait --for element needs a selector")
        element = wait_for(lambda: (session.tree.find(selector) or [None])[0], timeout=timeout,
                           interval=interval, what=f"an element matching {selector.describe()}")
        return {"met": True, "elapsed": round(time.monotonic() - started, 3), "element": element.match_summary()}
    if kind == "gone":
        if not args.get("ref"):
            raise UsageError("wait --for gone needs a ref")
        ref = str(args["ref"])
        wait_for(lambda: _ref_missing(session, ref), timeout=timeout, interval=interval, what=f"element {ref} to disappear")
        return {"met": True, "elapsed": round(time.monotonic() - started, 3), "gone": ref}
    if kind in ("window", "window-gone"):
        selector = Selector.from_dict({"window": args.get("window"), "app": args.get("app")})
        if not selector.window and not selector.app:
            raise UsageError("wait --for window needs --window and/or --app")
        if kind == "window":
            info = wait_for(lambda: _first(session.tree.find_windows(selector)),
                            timeout=timeout, interval=interval, what=f"window {selector.scope_text()}")
            return {"met": True, "elapsed": round(time.monotonic() - started, 3), "window": info.to_dict()}
        wait_for(lambda: not session.tree.find_windows(selector), timeout=timeout, interval=interval,
                 what=f"window {selector.scope_text()} to close")
        return {"met": True, "elapsed": round(time.monotonic() - started, 3), "closed": selector.scope_text()}
    if kind == "idle":
        wait_for(lambda: session.tree.focused() is not None, timeout=timeout, interval=interval, what="keyboard focus")
        return {"met": True, "elapsed": round(time.monotonic() - started, 3)}
    raise UsageError(f"unknown wait target {kind!r}", hint="element | gone | window | window-gone")


def _first(items: list[Any]) -> Any | None:
    return items[0] if items else None


def _ref_missing(session: DesktopSession, ref: str) -> bool:
    try:
        session.tree.resolve_ref(ref)
    except KdeUiaError:
        return True
    return False


def screenshot(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    service = session.screenshots()
    if args.get("strategy"):
        service.strategy = str(args["strategy"])
    out = Path(str(args.get("output") or "")).expanduser() if args.get("output") else Path(
        tempfile.gettempdir()) / f"kde-uia-{int(time.time() * 1000)}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    layout = session.screen_map()
    if args.get("window") or args.get("app") or args.get("id"):
        backend = session.window_backend()
        selector = Selector.from_dict({"window": args.get("window"), "app": args.get("app")})
        row = backend.info(str(args["id"])) if args.get("id") else _match_backend_window(backend, selector)
        capture = service.capture_window(out, window=row, layout=layout)
    elif args.get("ref"):
        element = session.tree.resolve_ref(str(args["ref"]))
        rect = element.extents()
        if rect is None:
            raise NotFoundError("the element has no geometry (hidden?)")
        if backend_ok(session):
            from .screenshot import crop_capture

            full = service.capture_screen(out.with_name(out.stem + "-screen.png"), layout=layout)
            capture = crop_capture(full, out, _rect(rect) or {}, layout=layout)
        else:
            capture = service.capture_screen(out, layout=layout)
    else:
        capture = service.capture_screen(out, layout=layout)
    if capture.width <= 0 or capture.height <= 0:
        raise KdeUiaError("the capture is not a decodable PNG", code="SCREENSHOT_FAILED")
    result = capture.to_dict()
    result["layout"] = layout.to_dict()
    return result


def backend_ok(session: DesktopSession) -> bool:
    try:
        return session.window_backend() is not None
    except KdeUiaError:
        return False


def inspect_screenshot(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(args.get("path") or ""))
    if not path.is_file():
        raise UsageError(f"no screenshot at {path}")
    from .screenshot import image_size

    width, height = image_size(path)
    layout = session.screen_map()
    from .screens import infer_scale

    scale = infer_scale((width, height), layout)
    return {"path": str(path), "width": width, "height": height, "scale": scale, "layout": layout.to_dict()}


# ======================================================================
# Composite actions
# ======================================================================
def open_(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    import shlex
    import subprocess

    command = args.get("command")
    if not command:
        raise UsageError("open needs `command`", hint="Example: open --command dolphins or open --command \"kwrite /tmp/a.txt\"")
    argv = shlex.split(str(command))
    if not argv:
        raise UsageError("empty command")
    try:
        proc = subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise NotFoundError(f"executable not found: {argv[0]}", hint="Check that the KDE application is installed.") from exc
    result: dict[str, Any] = {"ok": True, "pid": proc.pid, "command": argv}
    if args.get("window") or args.get("app"):
        selector = Selector.from_dict({"window": args.get("window"), "app": args.get("app")})
        try:
            info = wait_for(lambda: _first(session.tree.find_windows(selector)),
                            timeout=float(args.get("timeout", 20.0)), what=f"window {selector.scope_text()}")
            result["window"] = info.to_dict()
        except KdeUiaError as exc:
            result["ok"] = False
            result["windowError"] = exc.to_dict()
    if args.get("screenshot"):
        shot = screenshot(session, {"output": args.get("screenshot")})
        result["screenshot"] = shot
    return result


def app_activate(session: DesktopSession, args: dict[str, Any]) -> dict[str, Any]:
    app = args.get("app")
    if not app:
        raise UsageError("app-activate needs `app`")
    candidates = [w for w in session.tree.windows() if app.casefold() in w.app.casefold()]
    if candidates:
        return activate_window(session, {"window": candidates[0].title, "app": app})
    raise NotFoundError(f"application {app!r} has no accessible window", hint="Start it first (open --command), or pass --window.")


# ======================================================================
# Registry used by the CLI and by ``python -m kde_uia ops <name>``
# ======================================================================
OPS: dict[str, Callable[[DesktopSession, dict[str, Any]], dict[str, Any]]] = {
    "env": env_info,
    "doctor": diagnose,
    "windows": list_windows,
    "active-window": active_window,
    "focused": focused,
    "tree": tree,
    "find": find,
    "info": element_info,
    "activate": activate_window,
    "window": window_action,
    "click": click,
    "press": press_key,
    "type": type_text,
    "scroll": scroll,
    "set": set_value,
    "toggle": toggle,
    "focus": focus_element,
    "expand": expand,
    "wait": wait,
    "screenshot": screenshot,
    "screenshot-info": inspect_screenshot,
    "open": open_,
}

READ_ONLY_OPS = frozenset({"env", "doctor", "windows", "active-window", "focused", "tree", "find", "info",
                           "screenshot", "screenshot-info"})
