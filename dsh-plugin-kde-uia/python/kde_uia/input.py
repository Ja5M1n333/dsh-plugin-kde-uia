"""Synthetic input: focus windows, click, type, key combinations, scroll.

Backend order, each reached only when the previous one cannot run:

1. ``atispi`` - AT-SPI ``grab_focus`` + ``do_action("click")`` plus
   ``editable-text`` insertion.  Toolkit-native: it does not move the real
   pointer and works on Wayland and in nested sessions, but only for widgets
   that expose the interfaces.
2. ``xdotool`` - WarpPointer + XTest on X11.  Moves the real pointer and
   types character by character via a dynamically mapped keysym, which
   handles Unicode without touching the clipboard.
3. ``kdotool`` - KWin scripting under Wayland: ``mousemove``/``click``/
   ``type``/``key``.  Injects through KDE's fake-input protocols.
4. ``dbus`` - clipboard + ``Ctrl+V`` or AT-SPI text insertion, as the last
   resort for typing (e.g. for tools that do not inject argv-safe Unicode).
5. ``dry-run`` - records the intent, moves nothing.  Explicit opt-in for
   agents that only want to plan a click.

Every backend reports ``dryRun: true`` when no effect happened.  Moving the
real pointer is a shared resource, so callers that click should be prepared
for the pointer to be left where it was put.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable

from . import keys as keys_mod
from .atspi_client import package_hint
from .errors import BackendUnavailableError, InputError, KdeUiaError, UsageError

TEXT_BACKENDS = ("atspi", "xdotool", "kdotool", "dbus")
POINTER_BACKENDS = ("atspi", "xdotool", "kdotool")
BUTTONS = {"left": 1, "middle": 2, "right": 3}


@dataclass
class InputResult:
    backend: str
    kind: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"backend": self.backend, "kind": self.kind, **self.details}


def _have(tool: str) -> bool:
    return shutil.which(tool) is not None


def _run(argv: list[str], *, timeout: float = 10.0, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, input=stdin, check=False)
    except subprocess.TimeoutExpired:
        raise InputError(f"{argv[0]} did not finish within {timeout:g}s", hint="Retry; the input backend may be stuck.") from None
    except OSError as exc:
        raise InputError(f"cannot run {argv[0]}: {exc}") from exc


def available_backends() -> dict[str, bool]:
    wayland = bool(os.environ.get("WAYLAND_DISPLAY")) and not os.environ.get("DISPLAY")
    return {
        "atspi": True,  # capability probe happens on first use
        "xdotool": _have("xdotool") and bool(os.environ.get("DISPLAY")),
        "kdotool": _have("kdotool"),
        "dbus": _have("wl-copy") and _have("wtype") or _have("xclip") or _have("xsel"),
        "waylandSession": wayland,
    }


class InputService:
    """Dispatches one input intent across the enabled backends."""

    def __init__(self, *, strategy: str = "auto", dry_run: bool = False, allow_xdotool_on_wayland: bool = False) -> None:
        if strategy not in ("auto", *TEXT_BACKENDS, "dry-run"):
            raise UsageError(f"unknown input strategy {strategy!r}", hint=f"auto | {' | '.join(TEXT_BACKENDS)} | dry-run")
        self.strategy = strategy
        self.dry_run = dry_run or strategy == "dry-run"
        self.allow_xdotool_on_wayland = allow_xdotool_on_wayland

    # --------------------------------------------------------------- pointer
    def click(self, x: int, y: int, *, button: str = "left", clicks: int = 1, element: Any = None) -> InputResult:
        if button not in BUTTONS:
            raise UsageError(f"button must be one of {', '.join(BUTTONS)}")
        if clicks < 1:
            raise UsageError("clicks must be >= 1")
        if self.dry_run:
            return InputResult("dry-run", "click", {"x": x, "y": y, "button": button, "clicks": clicks})
        errors = []
        for backend in self._pointer_order():
            try:
                if backend == "atspi" and element is not None:
                    if _atspi_click(element):
                        return InputResult("atspi", "click", {"x": x, "y": y, "button": button, "clicks": clicks})
                    errors.append("atspi: element exposes no click action")
                elif backend == "xdotool":
                    _xdotool_click(x, y, button, clicks)
                    return InputResult("xdotool", "click", {"x": x, "y": y, "button": button, "clicks": clicks})
                elif backend == "kdotool":
                    _kdotool_click(x, y, button, clicks)
                    return InputResult("kdotool", "click", {"x": x, "y": y, "button": button, "clicks": clicks})
            except KdeUiaError as exc:
                errors.append(f"{backend}: {exc.message}")
        raise InputError(
            "no pointer backend could click: " + "; ".join(errors),
            hint="On X11 install xdotool; on Wayland install kdotool (KWin scripting). "
                 "Pass --strategy atspi to click via accessibility actions instead.",
        )

    def _pointer_order(self) -> list[str]:
        if self.strategy != "auto":
            return [self.strategy]
        wayland_only = bool(os.environ.get("WAYLAND_DISPLAY")) and not self.allow_xdotool_on_wayland
        order = ["atspi"]
        if not wayland_only:
            order.append("xdotool")
        order.append("kdotool")
        return order

    # ----------------------------------------------------------------- text
    def type_text(self, text: str, *, element: Any = None, submit: bool = False, interval_ms: int = 0) -> InputResult:
        if not isinstance(text, str) or text == "":
            raise UsageError("type needs non-empty text")
        if self.dry_run:
            return InputResult("dry-run", "type", {"text": _preview(text), "submit": submit})
        errors = []
        for backend in self._text_order():
            try:
                if backend == "atspi":
                    if element is None or not _atspi_insert_text(element, text):
                        errors.append("atspi: element exposes no editable-text interface")
                        continue
                    result = InputResult("atspi", "type", {"text": _preview(text)})
                elif backend == "xdotool":
                    _xdotool_type(text, interval_ms)
                    result = InputResult("xdotool", "type", {"text": _preview(text)})
                elif backend == "kdotool":
                    _kdotool_type(text, interval_ms)
                    result = InputResult("kdotool", "type", {"text": _preview(text)})
                elif backend == "dbus":
                    _clipboard_paste(text)
                    result = InputResult("dbus", "type", {"text": _preview(text), "via": "clipboard+paste"})
                else:  # pragma: no cover - guarded by _text_order
                    continue
                if submit:
                    self.press("Return")
                return result
            except KdeUiaError as exc:
                errors.append(f"{backend}: {exc.message}")
        raise InputError(
            "no text backend could type: " + "; ".join(errors),
            hint="Install xdotool (X11) or kdotool (Wayland). For a focused editable field, "
                 "pass its ref so the atspi strategy can insert text directly.",
        )

    def _text_order(self) -> list[str]:
        if self.strategy != "auto":
            return [self.strategy]
        wayland_only = bool(os.environ.get("WAYLAND_DISPLAY")) and not self.allow_xdotool_on_wayland
        order = ["atspi"]
        if not wayland_only:
            order.append("xdotool")
        order += ["kdotool", "dbus"]
        return order

    # ----------------------------------------------------------------- keys
    def press(self, combo: str, *, repeat: int = 1) -> InputResult:
        if repeat < 1:
            raise UsageError("repeat must be >= 1")
        if combo == "RETURN":
            combo = "Return"
        if self.dry_run:
            return InputResult("dry-run", "key", {"combo": combo, "repeat": repeat})
        errors = []
        for backend in self._key_order():
            try:
                if backend == "xdotool":
                    _xdotool_key(combo, repeat)
                elif backend == "kdotool":
                    _kdotool_key(combo, repeat)
                else:
                    continue
                return InputResult(backend, "key", {"combo": combo, "repeat": repeat})
            except KdeUiaError as exc:
                errors.append(f"{backend}: {exc.message}")
        raise InputError(
            "no key backend could press the combination: " + "; ".join(errors),
            hint=(
                f"The combination received by the client was {combo!r}. "
                "Install xdotool (X11) or kdotool (Wayland); keys use names like Return, ctrl+l, ALT+F4."
            ),
        )

    def _key_order(self) -> list[str]:
        if self.strategy != "auto":
            return [self.strategy]
        wayland_only = bool(os.environ.get("WAYLAND_DISPLAY")) and not self.allow_xdotool_on_wayland
        order = [] if wayland_only else ["xdotool"]
        return order + ["kdotool"]

    # --------------------------------------------------------------- scroll
    def scroll(self, x: int, y: int, *, direction: str = "down", amount: int = 3) -> InputResult:
        if direction not in ("up", "down", "left", "right"):
            raise UsageError("scroll direction must be up/down/left/right")
        if self.dry_run:
            return InputResult("dry-run", "scroll", {"x": x, "y": y, "direction": direction, "amount": amount})
        errors = []
        buttons = {"up": 4, "down": 5, "left": 6, "right": 7}
        for backend in self._pointer_order():
            try:
                if backend == "xdotool":
                    _run(["xdotool", "mousemove", str(x), str(y)])
                    for _ in range(amount):
                        _run(["xdotool", "click", str(buttons[direction])])
                elif backend == "kdotool":
                    _run(["kdotool", "mousemove", str(x), str(y)])
                    for _ in range(amount):
                        _run(["kdotool", "click", str(buttons[direction])])
                elif backend == "atspi":
                    errors.append("atspi: no scroll interface (use xdotool/kdotool)")
                    continue
                return InputResult(backend, "scroll", {"x": x, "y": y, "direction": direction, "amount": amount})
            except KdeUiaError as exc:
                errors.append(f"{backend}: {exc.message}")
        raise InputError("no backend could scroll: " + "; ".join(errors))


# --------------------------------------------------------------- AT-SPI side
def _atspi_click(element: Any) -> bool:
    actions = [a.lower() for a in element.actions()]
    preferred = [a for a in ("click", "press", "activate", "toggle") if a in actions]
    for name in preferred:
        if element.do_action(name):
            return True
    return False


def _atspi_insert_text(element: Any, text: str) -> bool:
    acc = element.acc
    try:
        current = acc.get_text()
    except Exception:
        return False
    if not isinstance(current, str):
        return False
    try:
        length = int(acc.get_character_count() or 0)
    except Exception:
        length = len(current)
    try:
        if not acc.grab_focus():
            return False
    except Exception:
        return False
    offset = length
    try:
        offset = int(acc.get_caret_offset())
    except Exception:
        offset = length
    try:
        if not acc.set_caret_offset(offset, True):
            offset = length
        return bool(acc.insert_text(offset, text, len(text), True))
    except Exception:
        return False


# --------------------------------------------------------------- xdotool side
def _xdotool_click(x: int, y: int, button: str, clicks: int) -> None:
    tool = shutil.which("xdotool")
    if tool is None:
        raise BackendUnavailableError("xdotool is not installed", hint=package_hint("xdotool"))
    args = [tool, "mousemove", str(x), str(y), "click", "--repeat", str(clicks), str(BUTTONS[button])]
    proc = _run(args)
    if proc.returncode != 0:
        raise InputError(f"xdotool click failed: {proc.stderr.strip() or proc.returncode}")


def _xdotool_type(text: str, interval_ms: int) -> None:
    tool = shutil.which("xdotool")
    if tool is None:
        raise BackendUnavailableError("xdotool is not installed", hint=package_hint("xdotool"))
    args = [tool, "type", "--clearmodifiers", "--delay", str(max(0, interval_ms))]
    proc = _run([*args, "--", text], timeout=max(15.0, len(text) / 20))
    if proc.returncode != 0:
        raise InputError(f"xdotool type failed: {proc.stderr.strip() or proc.returncode}")


def _xdotool_key(combo: str, repeat: int) -> None:
    tool = shutil.which("xdotool")
    if tool is None:
        raise BackendUnavailableError("xdotool is not installed", hint=package_hint("xdotool"))
    modifiers, key = keys_mod.parse_combo(combo)
    spec = keys_mod.format_combo(modifiers, key)
    proc = _run([tool, "key", "--clearmodifiers", "--repeat", str(repeat), spec])
    if proc.returncode != 0:
        raise InputError(f"xdotool key {spec} failed: {proc.stderr.strip() or proc.returncode}")


# --------------------------------------------------------------- kdotool side
def _kdotool() -> str:
    tool = shutil.which("kdotool")
    if tool is None:
        raise BackendUnavailableError("kdotool is not installed", hint=package_hint("kdotool"))
    return tool


def _kdotool_click(x: int, y: int, button: str, clicks: int) -> None:
    tool = _kdotool()
    _run([tool, "mousemove", str(x), str(y)])
    proc = _run([tool, "click", "--repeat", str(clicks), str(BUTTONS[button])])
    if proc.returncode != 0:
        raise InputError(f"kdotool click failed: {proc.stderr.strip() or proc.returncode}")


def _kdotool_type(text: str, interval_ms: int) -> None:
    tool = _kdotool()
    proc = _run([tool, "type", "--delay", str(max(0, interval_ms)), "--", text], timeout=max(15.0, len(text) / 20))
    if proc.returncode != 0:
        raise InputError(f"kdotool type failed: {proc.stderr.strip() or proc.returncode}")


def _kdotool_key(combo: str, repeat: int) -> None:
    tool = _kdotool()
    for _ in range(repeat):
        proc = _run([tool, "key", combo])
        if proc.returncode != 0:
            raise InputError(f"kdotool key {combo} failed: {proc.stderr.strip() or proc.returncode}")


# --------------------------------------------------------------- clipboard
def _clipboard_paste(text: str) -> None:
    wl_copy = shutil.which("wl-copy")
    if wl_copy and os.environ.get("WAYLAND_DISPLAY"):
        proc = _run([wl_copy], stdin=text)
        if proc.returncode != 0:
            raise InputError("wl-copy failed")
    else:
        xclip = shutil.which("xclip") or shutil.which("xsel")
        if xclip is None:
            raise BackendUnavailableError("clipboard paste needs xclip/xsel (X11) or wl-copy (Wayland)")
        argv = [xclip, "-selection", "clipboard"] if xclip.endswith("xclip") else [xclip, "--input", "--clipboard"]
        proc = _run(argv, stdin=text)
        if proc.returncode != 0:
            raise InputError("clipboard copy failed")
    time.sleep(0.05)
    _xdotool_key("ctrl+v", 1) if os.environ.get("DISPLAY") else _kdotool_key("ctrl+v", 1)


def _preview(text: str, limit: int = 80) -> str:
    flat = text.replace("\n", "\\n")
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def with_retry(fn: Callable[[], Any], *, attempts: int = 3, delay: float = 0.2) -> Any:
    """Retry transient input failures (a window that is still opening, for instance)."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except KdeUiaError as exc:
            last = exc
            time.sleep(delay * (attempt + 1))
    assert last is not None
    raise last
