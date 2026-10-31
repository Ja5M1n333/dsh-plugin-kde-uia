"""Plasma 6 / PyGObject compatibility layer for the ``kde_uia`` client.

**Why this module exists.** The 0.1.0 client was written on Windows and only
ever loaded against a WSL server without a desktop, so a handful of calls were
shaped from documentation rather than from a run.  The first real Plasma 6
session (Arch, KWin 6.8.2, Wayland, the distro's Python 3.14 + PyGObject) found
ten real defects.  Fixing them here rather than inside each module keeps the
change reviewable and the rest of the client untouched; every patch is
documented below with the failure it repairs and is safe to apply repeatedly.

``kde_uia/__init__.py`` calls :func:`install_patches` on import, so every entry
point (``python -m kde_uia ...``, the DSH plugin's ops calls, the ``kde-uia``
CLI) gets the same behaviour.  Set ``KDE_UIA_NO_PATCHES=1`` to opt out, and
``KDE_UIA_PATCH_DEBUG=1`` to trace a patch that fails to apply (a patch that
raises is skipped so it can never break the client).

Verified on
-----------

* Arch Linux, KDE Plasma 6.8.2 on Wayland (XWayland at ``:1``)
* Python 3.14.8, PyGObject 3.58.1, at-spi2-core 2.62.1, kdotool 0.3.0

What each patch repairs
-----------------------

1. ``ops.diagnose`` calls ``desktop.child_count()`` on a raw
   ``Atspi.Accessible``; PyGObject spells it ``get_child_count()``.
2. ``AtspiElement.state_set()`` calls ``self.acc.get_state_set()``; PyGObject
   exposes ``self.acc.states``.  Every state read returned ``False``, so no
   window ever passed the ``showing`` test and the tree looked empty.
3. The window backend drives a KWin script bridge that cannot work on this
   build: Plasma 6's ``/KWin`` exports no ``org.kde.KConfig``, and KWin 6.8.2
   answers ``isScriptLoaded`` with true while never executing the script.  A
   ``kdotool`` backend takes its place: it lists every window (Wayland clients
   included) and can activate, minimize, close and resize them.
4. Qt answers ``get_current_value()`` with an uninitialised double
   (``6.9e-310``) for widgets that have no value, so the tree printed garbage.
5. ``TreeSession.find_windows`` applies the element ``role``/``name`` to the
   window frame, so every scoped search ("push buttons inside Gwenview")
   failed before the tree was ever walked.
6. ``_ref_path`` drops the application index, so two Gwenview windows both
   produced ``uia:1:gwenview:0`` and every ref was ambiguous.
7. AT-SPI was used without registering as a client, so children were never
   preloaded and toolkit trees stayed shallow.
8. ``ActionCapability`` uses ``get_action_count()`` and ``do_action(0, name)``;
   PyGObject spells them ``get_n_actions()`` and ``do_action(index)``, so no
   element ever reported or ran an action.
9. ``_require_png`` is called with two arguments in the spectacle path, and
   ``import`` needs ``-silent``; both made screenshots fail.
10. Key presses and pointer clicks only went through ``xdotool``/``kdotool``.
    kdotool 0.3.0 has no ``key``/``click``/``type`` commands at all, and this
    Wayland session discards XTest, so neither could reach the screen.
    Synthetic input now goes through ``Atspi.generate_keyboard_event`` /
    ``generate_mouse_event``; under KWin that path reaches the focused surface
    (and Plasma shortcuts) the way real hardware input does.

Known limit (NOT fixed here)
----------------------------
On a Wayland session where the compositor does not act on AT-SPI synthetic
input, **key presses cannot be delivered** by any unprivileged path this
client has: XTest is a no-op under native Wayland, kdotool has no input
commands, and KWin 6.8.2 does not run scripting.  ``ydotool`` (AUR,
``/dev/uinput``, ``input`` group) or the XDG Remote Desktop portal are the
supported fixes; both need a decision by the machine's owner.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from . import env as env_mod
from . import keys as keys_mod
from .errors import BackendUnavailableError, KdeUiaError, NoDisplayError, NotFoundError, UsageError

_INSTALLED = False

#: Modifier names accepted in key combinations (case-insensitive).
_MODIFIER_NAMES = frozenset({
    "ctrl", "control", "shift", "alt", "altgr", "meta", "super", "win", "cmd", "hyper",
})


# --------------------------------------------------------------------------
# 1. diagnose(): raw Atspi.Accessible has get_child_count(), not child_count()
# --------------------------------------------------------------------------
def _patch_diagnose() -> None:
    from . import ops

    def diagnose(session: Any, args: dict[str, Any]) -> dict[str, Any]:
        """``ops.diagnose`` with the atspi check reading PyGObject's spelling."""
        checks: list[dict[str, Any]] = []

        def check(name: str, fn: Any) -> None:
            try:
                status, detail = fn()
                checks.append({"check": name, "status": status, "detail": detail})
            except KdeUiaError as exc:
                checks.append({"check": name, "status": "fail", "detail": exc.message,
                               "code": exc.code, "hint": exc.hint})
            except Exception as exc:  # noqa: BLE001 - diagnosis must not crash
                checks.append({"check": name, "status": "fail", "detail": f"{type(exc).__name__}: {exc}"})

        def display() -> tuple[str, str]:
            if not env_mod.has_gui_context():
                raise NoDisplayError("neither DISPLAY nor WAYLAND_DISPLAY is set", hint="See the plugin runtime notes.")
            env = env_mod.detect_environment(probe_atspi=False)
            return "ok", f"{env.desktop} / {env.session_type} / display={env.display or env.wayland_display}"

        def atspi() -> tuple[str, str]:
            desktop = session.conn.dispatch()
            count = 0
            if desktop is not None:
                fn_child = getattr(desktop, "get_child_count", None) or getattr(desktop, "child_count", None)
                if callable(fn_child):
                    try:
                        count = int(fn_child() or 0)
                    except Exception:
                        count = 0
            return "ok", f"atspi initialised; {count} registered applications"

        def windows() -> tuple[str, str]:
            found = session.tree.windows()
            return "ok", f"{len(found)} accessible windows"

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

    ops.diagnose = diagnose
    # The CLI dispatches through the OPS table, which bound the original
    # function at import time, so register the replacement there too.
    if "doctor" in getattr(ops, "OPS", {}):
        ops.OPS["doctor"] = diagnose


# --------------------------------------------------------------------------
# 2. AtspiElement.state_set(): PyGObject exposes ``.states``
# --------------------------------------------------------------------------
def _patch_states() -> None:
    from . import element

    def state_set(self: Any) -> Any | None:
        for attribute in ("states", "get_state_set"):
            value = getattr(self.acc, attribute, None)
            if value is None:
                continue
            return value() if callable(value) else value
        return None

    def _atspi_enum(conn: Any, family: str, member: str) -> Any:
        """``STATE_SHOWING`` -> ``StateType.SHOWING`` (PyGObject drops the prefix)."""
        gi = getattr(conn, "atspi", conn)
        holder = getattr(getattr(gi, "Atspi", gi), family)
        for candidate in (member, member.removeprefix("STATE_"), member.removeprefix("COORD_"),
                          member.split("_", 1)[-1]):
            value = getattr(holder, candidate, None)
            if value is not None:
                return value
        raise AttributeError(f"{family} has no member {member}")

    element.AtspiElement.state_set = state_set
    element._atspi_enum = _atspi_enum
    # ``_state_type``/``_coord_type`` look the module global up at call time.
    element._state_type = lambda conn, bit: _atspi_enum(conn, "StateType", bit)
    element._coord_type = lambda conn, coord: _atspi_enum(conn, "CoordType", coord.upper())


# --------------------------------------------------------------------------
# 3. Window backend: kdotool (KWin scripting is unusable in this KWin build)
#
# In KWin 6.8.2 here, ``Scripting.loadScript`` returns an id and
# ``isScriptLoaded`` answers true, but no ``/Scripting/Script<N>`` runnable
# object answers and no script ever executes, and ``/KWin`` exports no
# ``org.kde.KConfig``.  kdotool talks to KWin's own D-Bus API instead: it lists
# every window (Wayland clients included), with titles and geometry, and can
# activate, minimize, close and resize them.
# --------------------------------------------------------------------------
class KdotoolBackend:
    """Window management through ``kdotool`` (Plasma 6, Wayland or X11)."""

    def __init__(self) -> None:
        self.exe = shutil.which("kdotool")
        if self.exe is None:
            raise BackendUnavailableError(
                "kdotool is not on PATH", hint="Arch: yay -S kdotool (AUR) | other: pipx install kdotool",
            )

    # ------------------------------------------------------------- helpers
    def _run(self, args: list[str], *, timeout: float = 8.0) -> tuple[int, str, str]:
        try:
            proc = subprocess.run([self.exe, *args], capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise KdeUiaError(f"kdotool {args[0]} did not answer within {timeout:g}s", code="TIMEOUT") from None
        return proc.returncode, proc.stdout or "", proc.stderr or ""

    @staticmethod
    def _uuid(text: str) -> str:
        match = re.search(r"\{[0-9a-fA-F-]{36}\}", text)
        return match.group(0) if match else text.strip()

    def _ids(self) -> list[str]:
        code, out, _ = self._run(["search", "--name", "."])
        if code != 0:
            return []
        return [line.strip() for line in out.splitlines() if line.strip()]

    def _one(self, window: str) -> dict[str, Any]:
        window = self._uuid(window)
        code, out, err = self._run(["getwindowname", window])
        caption = out.strip() if code == 0 else ""
        if code != 0 and err.strip():
            raise NotFoundError(f"no window with id {window!r}", hint="Run `kde-uia windows`.")
        _, geo, _ = self._run(["getwindowgeometry", window])
        frame = {"x": 0, "y": 0, "width": 0, "height": 0}
        for key, pattern in (
            ("x", r"Position:\s*(-?\d+)"), ("y", r"Position:\s*-?\d+,(-?\d+)"),
            ("width", r"Geometry:\s*(\d+)"), ("height", r"Geometry:\s*\d+x(\d+)"),
        ):
            match = re.search(pattern, geo)
            if match:
                frame[key] = int(match.group(1))
        _, cls, _ = self._run(["getwindowclassname", window])
        _, pid, _ = self._run(["getwindowpid", window])
        _, active_id, _ = self._run(["getactivewindow"])
        app = cls.strip()
        return {
            "id": window,
            "caption": caption,
            "resourceClass": app,
            "resourceName": app,
            "pid": int(pid.strip()) if pid.strip().isdigit() else 0,
            "layer": 0,
            "minimized": False,
            "active": self._uuid(active_id) == window,
            "frame": frame,
            "client": dict(frame),
            "desktop": -1,
            "onAllDesktops": False,
            "fullScreen": False,
            "output": "",
        }

    # ----------------------------------------------------------------- API
    def windows(self) -> list[dict[str, Any]]:
        found = []
        for window_id in self._ids():
            try:
                found.append(self._one(window_id))
            except KdeUiaError:
                continue
        return found

    def active(self) -> dict[str, Any] | None:
        code, out, _ = self._run(["getactivewindow"])
        if code != 0 or not out.strip():
            return None
        try:
            return self._one(out.strip())
        except KdeUiaError:
            return None

    def outputs(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            import gi

            gi.require_version("Gdk", "3.0")
            from gi.repository import Gdk

            display = Gdk.Display.get_default()
        except Exception:
            display = None
        if display is None:
            return out
        for index in range(display.get_n_monitors()):
            monitor = display.get_monitor(index)
            geometry = monitor.get_geometry()
            out.append({
                "name": f"monitor{index}",
                "x": geometry.x, "y": geometry.y, "width": geometry.width, "height": geometry.height,
                "scale": float(monitor.get_scale_factor() or 1),
            })
        return out

    def info(self, window_id: str) -> dict[str, Any]:
        return self._one(self._window_token(window_id))

    def _window_token(self, window_id: str) -> str:
        """A kdotool window argument: a uuid, or a title matched to one uuid."""
        text = str(window_id).strip()
        if re.fullmatch(r"\{[0-9a-fA-F-]{36}\}", text):
            return text
        for candidate in self._ids():
            if self._run(["getwindowname", candidate])[1].strip() == text:
                return candidate
        return text

    def act(self, op: str, window_id: str, params: list[Any] | None = None) -> Any:
        window = self._window_token(str(window_id))
        params = params or []
        command = {
            "activate": ["windowactivate", window],
            "focus": ["windowactivate", window],
            "minimize": ["windowminimize", window],
            "close": ["windowclose", window],
            "resize": ["windowsize", window, str(params[0]), str(params[1])] if len(params) >= 2 else None,
        }.get(op)
        if command is None:
            raise UsageError(
                f"unknown or unsupported window action {op!r}",
                hint="kdotool supports activate, focus, minimize, close and resize.",
            )
        code, _, err = self._run(command)
        if code != 0:
            raise KdeUiaError(f"kdotool {command[0]} failed: {err.strip()}", code="BACKEND_UNAVAILABLE")
        return self._one(window)

    def capture(self, window_id: str, path: Path) -> dict[str, Any]:
        from .screenshot import ScreenshotService

        result = ScreenshotService(timeout=30).capture(str(window_id), str(path))
        return result if result.get("path") else {"error": "save-failed", "path": str(path)}


def _patch_window_backend() -> None:
    from . import window_backends as wb

    wb.KdotoolBackend = KdotoolBackend

    original_select = wb.select_backend

    def select_backend(mode: str = "auto") -> Any:
        if mode not in ("auto", "kwin", "x11", "kdotool"):
            raise UsageError(f"unknown window backend {mode!r}", hint="auto | kwin | kdotool | x11")
        errors: list[str] = []
        if mode == "kwin":
            return original_select(mode)
        if mode in ("auto", "kdotool"):
            try:
                backend = KdotoolBackend()
                backend.windows()
                return backend
            except KdeUiaError as exc:
                errors.append(f"kdotool: {exc.message}")
        if mode in ("auto", "x11"):
            try:
                return wb.X11Backend()
            except KdeUiaError as exc:
                errors.append(f"x11: {exc.message}")
        raise BackendUnavailableError(
            "no window-management backend is available: " + "; ".join(errors),
            hint="Install kdotool (Arch: yay -S kdotool), or install wmctrl/xdotool for an X11 session.",
        )

    def backend_name(actor: Any) -> str:
        if isinstance(actor, KdotoolBackend):
            return "kdotool"
        return original_name(actor)

    original_name = wb.backend_name
    wb.select_backend = select_backend
    wb.backend_name = backend_name


# --------------------------------------------------------------------------
# 4. Values: Qt reports uninitialised doubles for elements without a Value
#
# ``get_current_value()`` answers a tiny denormal (6.9e-310) for every Qt
# widget, and the tree printed it as each element's value.  Only roles that
# carry a meaningful value are read, and implausible doubles are dropped.
# --------------------------------------------------------------------------
_VALUE_ROLES = frozenset({
    "slider", "spin button", "progress bar", "scroll bar", "level bar", "dial",
    "scroll pane", "scroll area", "page tab", "combo box", "color chooser", "rotation",
})


def _patch_values() -> None:
    from . import element

    original_current = element.ValueCapability.current

    def current(self: Any) -> float | None:
        accessor = getattr(self, "_a", None)
        role = ""
        try:
            role = str(accessor.get_role_name() or "")
        except Exception:
            role = ""
        if role and role not in _VALUE_ROLES:
            return None
        value = original_current(self)
        if value is None:
            return None
        # Denormals and absurd magnitudes are Qt reporting an unset double.
        if abs(value) < 1e-300 or abs(value) > 1e12:
            return 0.0 if value == 0 else None
        return value

    element.ValueCapability.current = current


# --------------------------------------------------------------------------
# 5. Scope resolution: a role/name/text condition describes the *elements*
#
# ``TreeSession.find_windows`` applies ``selector.role`` to the window frame,
# so ``find {"window": "Gwenview", "role": "push button"}`` never matched any
# window and every scoped search failed.  A scoped search now resolves its
# window without the element conditions.
# --------------------------------------------------------------------------
def _patch_find_roots() -> None:
    from . import tree

    def find_windows(self: Any, selector: Any, *, include_hidden: bool = False) -> list[Any]:
        candidates = self.windows(include_hidden=include_hidden)
        scoped = bool(selector.window is not None or selector.window_id or selector.app)
        out = []
        for info in candidates:
            if selector.app and info.app != selector.app:
                continue
            if selector.window_id and info.backend_id != selector.window_id and info.ref != selector.window_id:
                continue
            if selector.window is not None and not selector._match_value(info.title, selector.window):
                continue
            if not scoped:
                if selector.role and not tree.role_matches(info.role, selector.role):
                    continue
                if selector.name is not None and not selector.matches_name(info.title):
                    continue
            if not selector.matches_states(lambda state: state in info.states):
                continue
            out.append(info)
        return out

    tree.TreeSession.find_windows = find_windows


# --------------------------------------------------------------------------
# 6. Refs: disambiguate applications that register under one name
#
# ``_ref_path`` drops ``path[0]`` (the index of the application under the
# desktop), which is fine until one application registers twice: two Gwenview
# windows both produced ``uia:1:gwenview:0`` and every lookup was ambiguous.
# A reference now carries ``instance`` - AT-SPI's numeric application index when
# PyGObject exposes ``path_suffix()``, otherwise the desktop index - while the
# ``path`` keeps its documented shape (``0`` is the first window of an app).
# Resolving prefers the application at ``instance`` when it still has the same
# name and falls back to the first name match, so plain ``uia:1:app:0`` refs
# from 0.1.0 keep working.
# --------------------------------------------------------------------------
def _application_index(self: Any) -> int | None:
    """The application's child index under the AT-SPI desktop, if available."""
    path = self.path()
    return path[0] if path else None


def _ref_instance(self: Any) -> str | None:
    """``instance`` for a ref: AT-SPI's numeric path suffix, else ``None``."""
    own = self.instance()
    if own is not None:
        return own
    index = _application_index(self)
    return None if index is None else f"t{index}"


def _patch_refs() -> None:
    from . import element, refs, tree

    def _ref_path(path: list[int]) -> list[int]:
        """Same contract as the original: child indexes below the app root."""
        return path[1:] if len(path) >= 2 else []

    def _real_instance(self: Any) -> str | None:
        getter = getattr(self.acc, "path_suffix", None)
        own = getter() if callable(getter) else getter
        if own is None:
            return None
        resolved = getattr(own, "hex", own)
        if isinstance(resolved, str) and resolved:
            return resolved
        if isinstance(resolved, (list, tuple)) and resolved:
            return ":".join(str(part) for part in resolved)
        return None

    def _instances(self: Any) -> list[Any]:
        """How many AT-SPI applications are registered under this name.

        Walks the desktop through this element's own connection, so it works
        for elements built with or without a parent chain.
        """
        label = self.app_label()
        count = 0
        try:
            desktop = self.conn.dispatch()
        except Exception:
            return 0
        if desktop is None:
            return 0
        for index in range(int(getattr(desktop, "get_child_count", lambda: 0)())):
            child = desktop.get_child_at_index(index)
            if child is None:
                continue
            try:
                if child.get_role_name() == "application" and child.get_name() == label:
                    count += 1
            except Exception:
                continue
        return count

    def ref(self: Any) -> str:
        instance = None
        try:
            if self.app_root_element().role_name() == "application" and _instances(self) > 1:
                instance = _real_instance(self)
                if instance is None:
                    # No path suffix in this binding: fall back to the desktop
                    # index in the form the ref grammar accepts (digits/dots).
                    index = _application_index(self)
                    instance = None if index is None else str(index)
        except Exception:
            if os.environ.get("KDE_UIA_PATCH_DEBUG"):
                import traceback

                traceback.print_exc()
            instance = None
        return element.make_ref(self.app_label(), _ref_path(self.path()), instance)

    def resolve_ref(self: Any, ref: str, *, timeout: float = 10.0) -> Any:
        parsed = refs.parse_ref(ref)
        apps = [app for app in self.applications() if app.name() == parsed.app]
        if not apps:
            return original_resolve(self, ref, timeout=timeout)
        chosen = apps[0]
        instance = parsed.instance
        if instance is not None:
            for candidate in apps:
                if _real_instance(candidate) == instance:
                    chosen = candidate
                    break
            else:
                if instance.isdigit():
                    wanted = int(instance)
                    chosen = next(
                        (app for app in apps if _application_index(app) == wanted),
                        chosen,
                    )
        node = chosen
        for depth, index in enumerate(parsed.path):
            child = node.child_at(index)
            if child is None:
                return original_resolve(self, ref, timeout=timeout)
            node = child
        return node

    original_resolve = tree.TreeSession.resolve_ref
    element.AtspiElement.ref = ref
    # ``path()`` above resolves the module-level ``_ref_path`` at call time.
    element._ref_path = _ref_path
    tree.TreeSession.resolve_ref = resolve_ref


# --------------------------------------------------------------------------
# 7. Register as an AT-SPI client so synthetic input and deep trees work
# --------------------------------------------------------------------------
def _a11y_bus_address() -> str:
    address = os.environ.get("AT_SPI_BUS_ADDRESS")
    if address:
        return address
    try:
        out = subprocess.run(
            ["busctl", "--user", "get-property", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus", "Address"],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except OSError:
        return ""
    return out.stdout.strip().strip('"') if out.returncode == 0 else ""


def _patch_client_registration() -> None:
    from . import atspi_client

    original_open = atspi_client.AtspiConnection.open

    def open(self: Any) -> Any:
        result = original_open(self)
        module = self.atspi.Atspi
        try:
            # Emit and drop-input: libatspi drops the key/mouse events this
            # process synthesises (atspi_generate_*) unless it is a client.
            module.set_application_bus_address(_a11y_bus_address())
        except Exception:
            pass
        try:
            module.set_cache_level(2, 2)  # CacheLevel.ALL: preload every child
        except Exception:
            pass
        return result

    atspi_client.AtspiConnection.open = open




# --------------------------------------------------------------------------
# 8. Actions: PyGObject spells the count ``get_n_actions()`` and
#    ``do_action(index)`` takes an index, not a name
#
# With ``get_action_count()`` every element reported no actions, so semantic
# clicks were impossible and the tree never showed ``actions=...``.  Qt leaves
# the action name empty while still exposing one action per widget, so a single
# unnamed action is reported as ``click``.
# --------------------------------------------------------------------------
def _patch_actions() -> None:
    from . import element

    def names(self: Any) -> list[str]:
        accessor = self._a
        count = 0
        for attribute in ("get_n_actions", "get_action_count"):
            fn = getattr(accessor, attribute, None)
            if callable(fn):
                try:
                    count = int(fn() or 0)
                except Exception:
                    count = 0
                break
        out = []
        for index in range(count):
            name = None
            try:
                name = accessor.get_action_name(index)
            except Exception:
                name = None
            out.append(name or ("click" if count == 1 else f"action{index}"))
        return out

    def do(self: Any, name: str) -> bool:
        accessor = self._a
        wanted = name.strip().lower()
        for index, candidate in enumerate(names(self)):
            if candidate.lower() != wanted:
                continue
            for call in (
                lambda: accessor.do_action(index),
                lambda: accessor.do_action(0, candidate),
            ):
                try:
                    _ = call()
                    return True
                except Exception:
                    continue
        return False

    element.ActionCapability.names = names
    element.ActionCapability.do = do


# --------------------------------------------------------------------------
# 9. Screenshots: spectacle's checker takes one argument, and `import` needs
#    -silent (otherwise ImageMagick waits for a filename on stdin)
# --------------------------------------------------------------------------
def _patch_screenshots() -> None:
    from . import screenshot as shot

    original = shot._require_png

    def require_png(path: Path, *rest: Any) -> None:
        return original(path)

    shot._require_png = require_png

    def import_(self: Any, out: Path) -> Any:
        shot._tool(["import", "-window", "root", "-silent", str(out)], "import", self.timeout)
        require_png(out, "import")
        return shot.Capture(out, "import", *shot.image_size(out))

    shot.ScreenshotService._import = import_


#: X keysym name -> Linux input-event key code (linux/input-event-codes.h),
#: used by the ``ydotool`` backend, which speaks raw key codes.
X11_TO_KEYCODE: dict[str, int] = {
    "0": 11,
    "1": 2,
    "2": 3,
    "3": 4,
    "4": 5,
    "5": 6,
    "6": 7,
    "7": 8,
    "8": 9,
    "9": 10,
    "Alt_L": 56,
    "Alt_R": 100,
    "BackSpace": 14,
    "Caps_Lock": 58,
    "Control_L": 29,
    "Control_R": 97,
    "Delete": 111,
    "Down": 108,
    "End": 107,
    "Escape": 1,
    "F1": 59,
    "F10": 68,
    "F11": 87,
    "F12": 88,
    "F2": 60,
    "F3": 61,
    "F4": 62,
    "F5": 63,
    "F6": 64,
    "F7": 65,
    "F8": 66,
    "F9": 67,
    "Home": 102,
    "Insert": 110,
    "KP_0": 82,
    "KP_1": 79,
    "KP_2": 80,
    "KP_3": 81,
    "KP_4": 75,
    "KP_5": 76,
    "KP_6": 77,
    "KP_7": 71,
    "KP_8": 72,
    "KP_9": 73,
    "KP_Add": 78,
    "KP_Decimal": 83,
    "KP_Divide": 98,
    "KP_Enter": 96,
    "KP_Multiply": 55,
    "KP_Subtract": 74,
    "Left": 105,
    "Menu": 139,
    "Next": 109,
    "Num_Lock": 69,
    "Prior": 104,
    "Return": 28,
    "Right": 106,
    "Scroll_Lock": 70,
    "Shift_L": 42,
    "Shift_R": 54,
    "Super_L": 125,
    "Super_R": 126,
    "Tab": 15,
    "Up": 103,
    "XF86Copy": 136,
    "XF86Cut": 135,
    "XF86Paste": 137,
    "XF86Search": 225,
    "a": 30,
    "ampersand": 8,
    "apostrophe": 40,
    "asciicircum": 7,
    "asciitilde": 41,
    "asterisk": 9,
    "at": 3,
    "b": 48,
    "backslash": 43,
    "bar": 43,
    "braceleft": 26,
    "braceright": 27,
    "bracketleft": 26,
    "bracketright": 27,
    "c": 46,
    "colon": 39,
    "comma": 51,
    "d": 32,
    "dollar": 5,
    "e": 18,
    "equal": 13,
    "exclam": 2,
    "f": 33,
    "g": 34,
    "grave": 41,
    "greater": 52,
    "h": 35,
    "i": 23,
    "j": 36,
    "k": 37,
    "l": 38,
    "less": 51,
    "m": 50,
    "minus": 12,
    "n": 49,
    "numbersign": 4,
    "o": 24,
    "p": 25,
    "parenleft": 10,
    "parenright": 11,
    "percent": 6,
    "period": 52,
    "plus": 13,
    "q": 16,
    "question": 53,
    "quotedbl": 40,
    "r": 19,
    "s": 31,
    "semicolon": 39,
    "slash": 53,
    "space": 57,
    "t": 20,
    "u": 22,
    "underscore": 12,
    "v": 47,
    "w": 17,
    "x": 45,
    "y": 21,
    "z": 44,
}

#: Modifier keysym -> its key code (left-hand variant).
MODIFIER_KEYCODES: dict[str, int] = {
    "CTRL": 29,
    "SHIFT": 42,
    "ALT": 56,
    "SUPER": 125,
    "HYPER": 125,
}


def keycode_for(keysym: str) -> int | None:
    """Key code for an X keysym name; ``None`` when this table does not know it."""
    direct = X11_TO_KEYCODE.get(keysym)
    if direct is not None:
        return direct
    if len(keysym) == 1:
        lowered = keysym.lower()
        if lowered.isascii() and lowered.isalpha():
            return X11_TO_KEYCODE.get(lowered)
        if keysym.isdigit():
            return X11_TO_KEYCODE.get(keysym)
    return None


def ydotool_sequence(combo: str) -> list[str]:
    """``CTRL+Shift+t`` -> ``["29:1", "42:1", "20:1", "20:0", "42:0", "29:0"]``.

    Raises :class:`UsageError` when a key has no key code, so the caller can
    fall through to another backend instead of sending a wrong event.
    """
    modifiers, key = keys_mod.parse_combo(combo)
    codes: list[int] = []
    for modifier in modifiers:
        code = MODIFIER_KEYCODES.get(modifier)
        if code is None:
            raise UsageError(f"{modifier} has no ydotool key code")
        codes.append(code)
    final = keycode_for(key)
    if final is None:
        raise UsageError(f"key {key!r} has no ydotool key code")
    events = [f"{code}:1" for code in codes] + [f"{final}:1", f"{final}:0"]
    events += [f"{code}:0" for code in reversed(codes)]
    return events


# --------------------------------------------------------------------------
# 11. Text: PyGObject exposes the Text interface as ``Atspi.Text``
#
# ``TextCapability`` called ``self._a.get_text(start, end)``; in PyGObject the
# accessor's ``get_text()`` takes no arguments and returns the accessible
# again, while the real reader is ``Atspi.Text.get_text(accessible, start,
# end)``.  Every read therefore came back empty — including a terminal's
# contents, which is how output can be verified without a screenshot.
# --------------------------------------------------------------------------
def _patch_text() -> None:
    from . import element

    def _getter(accessor: Any, name: str) -> Any:
        """The Text-interface callable for ``name`` (accessor method or namespace)."""
        from .atspi_client import Atspi

        module = Atspi.get().Atspi
        holder = getattr(module, "Text", None)
        if holder is not None:
            fn = getattr(holder, name, None)
            if callable(fn):
                return lambda *args: fn(accessor, *args)
        fn = getattr(accessor, name, None)
        return fn if callable(fn) else None

    def character_count(self: Any) -> int:
        fn = _getter(self._a, "get_character_count")
        if fn is None:
            return 0
        try:
            return int(fn() or 0)
        except Exception:
            return 0

    def text(self: Any, start: int = 0, end: int = -1) -> str:
        count = character_count(self)
        if end is None or end < 0 or end > count:
            end = count
        fn = _getter(self._a, "get_text")
        if fn is None:
            return ""
        try:
            value = fn(start, end)
        except Exception:
            return ""
        text = value if isinstance(value, str) else ""
        if text:
            return text
        # Konsole serves an empty slice for large ranges; walk backwards from
        # the end in smaller chunks until some text comes back.
        tail_start = max(start, end - 4000)
        while tail_start >= start:
            try:
                chunk = fn(tail_start, end)
            except Exception:
                return ""
            if isinstance(chunk, str) and chunk:
                return chunk
            tail_start -= 4000
        return ""

    element.TextCapability.character_count = character_count
    element.TextCapability.text = text


# --------------------------------------------------------------------------
# 12. tree/find/info: expose each node's accessible text
#
# A web page served by Firefox keeps its content in ``section`` nodes whose
# text lives behind the Text interface; ``tree`` printed only role and name,
# so the page body looked empty even though 88 text nodes were readable.  A
# tree rendered with ``include_text`` now appends every node's text, which is
# what makes "read the window" possible without a screenshot.
# --------------------------------------------------------------------------
def _patch_tree_text() -> None:
    from . import ops as ops_mod
    from . import tree as tree_mod

    original_line = tree_mod._line

    def _line(node: Any, depth: int, options: Any) -> str:
        line = original_line(node, depth, options)
        if not getattr(options, "include_text", False):
            return line
        try:
            text = node.text().strip()
        except Exception:
            text = ""
        if not text or text == node.name():
            return line
        # Collapse newlines so one element stays on one line.
        text = " / ".join(part.strip() for part in text.splitlines() if part.strip())
        if not text:
            return line
        if len(text) > 240:
            text = text[:239] + "…"
        return f"{line}  text={text!r}"

    tree_mod._line = _line

    # ops.tree() builds TreeRenderOptions itself; reproduce it with include_text.
    def ops_tree(session: Any, args: dict[str, Any]) -> dict[str, Any]:
        from .selector import Selector

        selector = Selector.from_dict(args.get("selector"))
        if args.get("window"):
            selector = Selector.from_dict({**selector.to_dict(), "window": args["window"]})
        if args.get("app"):
            selector = Selector.from_dict({**selector.to_dict(), "app": args["app"]})
        if args.get("ref"):
            root = session.tree.resolve_ref(str(args["ref"]))
            window = ops_mod._window_of(session, root)
        else:
            info = session.tree.resolve_window(selector)
            root = info.element
            window = info.to_dict()
        options = tree_mod.TreeRenderOptions(
            max_depth=ops_mod._as_int(args.get("depth", 4), "depth"),
            max_nodes=ops_mod._as_int(args.get("max_nodes", args.get("maxNodes", 200)), "max_nodes"),
            include_extents=bool(args.get("include_extents")),
            include_refs=not bool(args.get("no_refs")),
            include_text=bool(args.get("include_text") or args.get("includeText")),
        )
        rendered = tree_mod.render_tree(session.tree, root, options)
        return {"window": window, "text": rendered.text, "nodes": rendered.nodes,
                "truncated": rendered.truncated, "rootRef": root.ref(),
                "hint": "Re-run with depth>=6 or a ref to see deeper subtrees." if rendered.truncated else None}

    ops_mod.tree = ops_tree

    # Reading every node's text is what makes a page readable without a
    # screenshot; expose it as its own op because a tree of a web document
    # hides its content behind lazily-built children.
    def tree_text(session: Any, args: dict[str, Any]) -> dict[str, Any]:
        if args.get("ref"):
            root = session.tree.resolve_ref(str(args["ref"]))
        elif args.get("selector") or args.get("window") or args.get("app"):
            from .selector import Selector

            selector = Selector.from_dict(args.get("selector"))
            for key in ("window", "app"):
                if args.get(key):
                    selector = Selector.from_dict({**selector.to_dict(), key: args[key]})
            root = session.tree.resolve_window(selector).element
        else:
            from .errors import UsageError

            raise UsageError("tree-text needs a window, a selector or a ref")
        limit = ops_mod._as_int(args.get("max_chars", 20000), "max_chars")
        depth_limit = ops_mod._as_int(args.get("depth", 16), "depth")
        pieces: list[str] = []
        seen: set[str] = set()
        visited = 0

        def walk(element: Any, depth: int) -> None:
            nonlocal visited
            if depth > depth_limit or sum(len(p) for p in pieces) >= limit:
                return
            visited += 1
            text = ""
            try:
                text = element.text()
            except Exception:
                text = ""
            if not text:
                try:
                    text = element.text_or_value()
                except Exception:
                    text = ""
            for line in str(text).splitlines():
                line = line.strip()
                if line and set(line) - {"\ufffc"} and line not in seen:
                    seen.add(line)
                    pieces.append(line)
                    break
            for child in element.children():
                walk(child, depth + 1)

        walk(root, 0)
        out: list[str] = []
        total = 0
        for piece in pieces:
            if total + len(piece) > limit:
                out.append("… (truncated)")
                break
            out.append(piece)
            total += len(piece) + 1
        return {"text": "\n".join(out), "lines": len(out), "nodes": visited, "truncated": total >= limit}

    ops_mod.tree_text = tree_text
    if hasattr(ops_mod, "OPS"):
        ops_mod.OPS["tree-text"] = tree_text

    from . import ops as ops_mod

    original_options = tree_mod.TreeRenderOptions
    if not getattr(original_options, "_has_text", False):
        original_init = original_options.__init__

        def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
            self.include_text = bool(kwargs.pop("include_text", False))
            original_init(self, *args, **kwargs)

        original_options.__init__ = __init__
        original_options._has_text = True


# --------------------------------------------------------------------------
# 10. Synthetic input: Atspi.generate_keyboard_event / generate_mouse_event
#
# ``InputService`` only ever tried xdotool (XTest) and kdotool (0.3.0 has no
# input commands), so keys and pointer clicks always failed on this Wayland
# session.  libatspi's generators are delivered by the compositor as real
# input: under KWin they drive the focused surface, Plasma shortcuts included.
# --------------------------------------------------------------------------
def _handle_of(element: Any) -> Any | None:
    """The AT-SPI proxy behind an ``AtspiElement`` (None for anything else)."""
    handle = getattr(element, "acc", None)
    return handle if handle is not None and hasattr(handle, "do_action") else None


def _patch_input() -> None:
    from . import input as inp

    # Idempotent across double installation; mark only once every patch lands.
    if getattr(inp, "_patched_input", False):
        return

    def Atspi_module() -> Any:
        from .atspi_client import Atspi

        return Atspi.get().Atspi

    def pause(seconds: float = 0.03) -> None:
        time.sleep(seconds)

    def _key_notation(combo: str) -> list[tuple[str, str]]:
        """``ctrl+shift+T`` -> [(ctrl, "hold"), (shift, "hold"), (T, "tap")].

        A token is a modifier when it is one of the usual names *and* more
        tokens follow; a lone ``ctrl`` is a tap of that key.
        """
        parts = [part for part in re.split(r"[+\-]", str(combo)) if part]
        if not parts:
            raise inp.InputError(f"empty key combination {combo!r}")
        return [
            (part, "hold" if index < len(parts) - 1 and part.lower() in _MODIFIER_NAMES else "tap")
            for index, part in enumerate(parts)
        ]

    def atspi_key(combo: str, repeat: int) -> None:
        module = Atspi_module()
        notation = _key_notation(combo)
        types = module.KeySynthType
        # X11 keysyms are case-sensitive; a shifted lower-case letter only
        # types if upper-cased, so normalize it before the event.
        for _ in range(max(1, repeat)):
            held = False
            for token, role in notation:
                if role == "hold":
                    module.generate_keyboard_event(0, token, types.LOCKMODIFIERS)
                    held = True
                elif held:
                    module.generate_keyboard_event(0, token, types.PRESSRELEASE)
                    module.generate_keyboard_event(0, "", types.UNLOCKMODIFIERS)
                    held = False
                else:
                    module.generate_keyboard_event(0, token, types.PRESSRELEASE)
                pause(0.04)
            if held:
                module.generate_keyboard_event(0, "", types.UNLOCKMODIFIERS)

    def atspi_type(text: str, interval_ms: int = 0) -> None:
        module = Atspi_module()
        for char in text:
            module.generate_keyboard_event(0, char, module.KeySynthType.STRING)
            if interval_ms:
                time.sleep(interval_ms / 1000)
        pause(0.05)

    def atspi_click(x: int, y: int, button: str, clicks: int) -> None:
        module = Atspi_module()
        # The event name is libatspi's syntax: b1p/b1r press/release, b2*=middle,
        # b3*=right; a single call delivering press then release.
        number = {"left": 1, "middle": 2, "right": 3}.get(button, 1)
        for _ in range(max(1, clicks)):
            module.generate_mouse_event(x, y, f"b{number}p")
            pause(0.03)
            module.generate_mouse_event(x, y, f"b{number}r")
            pause(0.05)

    def atspi_scroll(x: int, y: int, direction: str, amount: int) -> None:
        module = Atspi_module()
        wheel = {"up": 4, "down": 5, "left": 6, "right": 7}[direction]
        for _ in range(max(1, amount)):
            module.generate_mouse_event(x, y, f"b{wheel}p")
            module.generate_mouse_event(x, y, f"b{wheel}r")
            pause()

    def ydotool_socket() -> str:
        """The ydotoold socket, or '' when no daemon is reachable."""
        configured = os.environ.get("YDOTOOL_SOCKET")
        if configured:
            return configured
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
        candidate = os.path.join(runtime_dir, ".ydotool_socket")
        return candidate if os.path.exists(candidate) else ""

    def ydotool_available() -> bool:
        return shutil.which("ydotool") is not None and bool(ydotool_socket())

    def ydotool_key(combo: str, repeat: int) -> None:
        """Press a combination through ydotoold (kernel-level input injection)."""
        socket_path = ydotool_socket()
        if not socket_path:
            raise inp.BackendUnavailableError(
                "no ydotoold socket", hint="Start it: ydotoold --socket-path=$XDG_RUNTIME_DIR/.ydotool_socket"
            )
        sequence = ydotool_sequence(combo)
        for _ in range(max(1, repeat)):
            proc = inp._run([shutil.which("ydotool"), "key", *sequence], timeout=10)
            if proc.returncode != 0:
                raise inp.InputError(f"ydotool key failed: {(proc.stderr or proc.stdout).strip()}")

    def ydotool_type(text: str, interval_ms: int) -> None:
        """Type text through ydotoold (layout-aware, unlike synthetic keysyms)."""
        socket_path = ydotool_socket()
        if not socket_path:
            raise inp.BackendUnavailableError("no ydotoold socket")
        # -d: delay between keys; -H: how long each key is held. Fast defaults
        # drop characters when the focused client is busy, so keep both wider.
        proc = inp._run(
            [shutil.which("ydotool"), "type", "-d", str(max(interval_ms, 40)), "-H", "40", "--", text],
            timeout=max(30.0, len(text) / 10),
        )
        if proc.returncode != 0:
            raise inp.InputError(f"ydotool type failed: {(proc.stderr or proc.stdout).strip()}")

    def ydotool_click(x: int, y: int, button: str, clicks: int) -> None:
        tool = shutil.which("ydotool")
        inp._run([tool, "mousemove", "--absolute", "-x", str(x), "-y", str(y)], timeout=5)
        code = {"left": 0xC0, "right": 0xC1, "middle": 0xC2}.get(button, 0xC0)
        for _ in range(max(1, clicks)):
            proc = inp._run([tool, "click", f"{code & 0xFF:02x}"], timeout=5)
            if proc.returncode != 0:
                raise inp.InputError(f"ydotool click failed: {(proc.stderr or proc.stdout).strip()}")

    original_key_order = inp.InputService._key_order

    # 1. Keys: ydotool (kernel input, always delivered) first when its daemon
    #    runs, then AT-SPI, then xdotool / kdotool.  Environments without
    #    ydotoold keep the previous order unchanged.
    def key_order(self: Any) -> list[str]:
        if self.strategy != "auto":
            return [self.strategy]
        order = [name for name in original_key_order(self) if name not in ("atspi", "ydotool")]
        preferred = ["ydotool"] if ydotool_available() else []
        return [*preferred, "atspi", *order]

    # 2. Keys dispatch through the same order.
    def press(self: Any, combo: str, *, repeat: int = 1) -> Any:
        if repeat < 1:
            raise inp.UsageError("repeat must be >= 1")
        if not str(combo).strip():
            raise inp.UsageError("press needs a key combination")
        if self.dry_run:
            return inp.InputResult("dry-run", "key", {"combo": combo, "repeat": repeat})
        errors: list[str] = []
        for backend in key_order(self):
            try:
                if backend == "ydotool":
                    ydotool_key(combo, repeat)
                elif backend == "atspi":
                    atspi_key(combo, repeat)
                elif backend == "xdotool":
                    inp._xdotool_key(combo, repeat)
                elif backend == "kdotool":
                    inp._kdotool_key(combo, repeat)
                else:
                    continue
                return inp.InputResult(backend, "key", {"combo": combo, "repeat": repeat})
            except KdeUiaError as exc:
                errors.append(f"{backend}: {exc.message}")
        raise inp.InputError(
            "no key backend could press the combination: " + "; ".join(errors),
            hint="Keys use names like Return, ctrl+l, ALT+F4. AT-SPI synthetic input needs "
                 "at-spi2-core and a compositor that accepts it.",
        )

    original_pointer_order = inp.InputService._pointer_order

    def pointer_order(self: Any) -> list[str]:
        if self.strategy != "auto":
            return [self.strategy]
        order = [name for name in original_pointer_order(self) if name != "ydotool"]
        return (["ydotool"] if ydotool_available() else []) + order

    # 3. Pointer clicks: the element's own action first, then synthetic
    #    pointer events at its centre, then the tool fallbacks.
    def click(self: Any, x: int, y: int, *, button: str = "left", clicks: int = 1, element: Any = None) -> Any:
        if self.dry_run:
            return inp.InputResult("dry-run", "click", {"x": x, "y": y, "button": button, "clicks": clicks})
        errors: list[str] = []
        handle = _handle_of(element)
        if handle is not None and inp._atspi_click(element):
            return inp.InputResult("atspi-action", "click", {"x": x, "y": y, "button": button, "clicks": clicks})
        try:
            atspi_click(x, y, button, clicks)
            return inp.InputResult("atspi", "click", {"x": x, "y": y, "button": button, "clicks": clicks})
        except KdeUiaError as exc:
            errors.append(f"atspi: {exc.message}")
        for backend, function in (("ydotool", ydotool_click), ("xdotool", inp._xdotool_click),
                                  ("kdotool", inp._kdotool_click)):
            if backend == "ydotool" and not ydotool_available():
                continue
            try:
                function(x, y, button, clicks)
                return inp.InputResult(backend, "click", {"x": x, "y": y, "button": button, "clicks": clicks})
            except KdeUiaError as exc:
                errors.append(f"{backend}: {exc.message}")
        raise inp.InputError("no pointer backend could click: " + "; ".join(errors))

    # 4. Typing: an editable element first (AT-SPI text insertion), then
    #    synthetic key events at the focus, then the tool fallbacks.
    def type_text(self: Any, text: str, *, element: Any = None, submit: bool = False, interval_ms: int = 0) -> Any:
        if not isinstance(text, str) or text == "":
            raise inp.UsageError("type needs non-empty text")
        if self.dry_run:
            return inp.InputResult("dry-run", "type", {"text": inp._preview(text), "submit": submit})
        errors: list[str] = []
        if element is not None and inp._atspi_insert_text(element, text):
            if submit:
                press(self, "Return")
            return inp.InputResult("atspi", "type", {"text": inp._preview(text)})
        if ydotool_available():
            try:
                ydotool_type(text, interval_ms)
                if submit:
                    press(self, "Return")
                return inp.InputResult("ydotool", "type", {"text": inp._preview(text)})
            except KdeUiaError as exc:
                errors.append(f"ydotool: {exc.message}")
        try:
            atspi_type(text, interval_ms)
            if submit:
                press(self, "Return")
            return inp.InputResult("atspi-keys", "type", {"text": inp._preview(text)})
        except KdeUiaError as exc:
            errors.append(f"atspi-keys: {exc.message}")
        for backend, function in (("xdotool", inp._xdotool_type), ("kdotool", inp._kdotool_type)):
            try:
                function(text, interval_ms)
                if submit:
                    press(self, "Return")
                return inp.InputResult(backend, "type", {"text": inp._preview(text)})
            except KdeUiaError as exc:
                errors.append(f"{backend}: {exc.message}")
        raise inp.InputError("no text backend could type: " + "; ".join(errors))

    inp.InputService._key_order = key_order
    inp.InputService._pointer_order = pointer_order
    inp.InputService.press = press
    inp.InputService.click = click
    inp.InputService.type_text = type_text
    inp._patched_input = True


def install_patches() -> None:
    """Apply every patch once per process.  Never raises."""
    global _INSTALLED
    if _INSTALLED or os.environ.get("KDE_UIA_NO_PATCHES"):
        return
    _INSTALLED = True
    for patch in (_patch_diagnose, _patch_states, _patch_window_backend, _patch_find_roots, _patch_values,
                  _patch_actions, _patch_screenshots, _patch_refs, _patch_client_registration, _patch_input, _patch_text, _patch_tree_text):
        try:
            patch()
        except Exception:  # noqa: BLE001 - a patch must never break the client
            if os.environ.get("KDE_UIA_PATCH_DEBUG"):
                import traceback

                traceback.print_exc()
