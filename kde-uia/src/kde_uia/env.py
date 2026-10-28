"""Environment discovery shared by every backend.

Reports what kind of graphical session the calling process can see, which
desktop it is, and which optional helper executables exist.  Nothing here
starts a backend or talks to the accessibility bus; :func:`introspect` adds
the probe results from the optional layers.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import AT_SPI_HINT, NoDisplayError

__version__ = "0.1.0"
SCHEMA_VERSION = 1

_HINT = (
    "Run kde-uia from inside a KDE Plasma desktop session as the logged-in user. "
    "If DSH itself cannot see the desktop, configure the DSH plugin's `runtime` row: "
    "`wsl` runs commands through wsl.exe into your KDE distro, `ssh` runs them on a remote "
    "host over an SSH control socket. DSH strips DISPLAY/WAYLAND_DISPLAY from GUI sessions, "
    "so a child process cannot see the desktop by default (DSH_NO_GUI_CONTEXT=1)."
)


def has_gui_context() -> bool:
    """Whether *this* process can plausibly reach a display.

    Returns ``True`` on non-Linux platforms (the check is Linux-specific) and
    whenever either display variable is set.
    """
    if sys.platform != "linux":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def require_display_context() -> None:
    """Raise :class:`NoDisplayError` when no display is reachable."""
    if sys.platform != "linux":
        raise NoDisplayError(
            f"kde-uia targets Linux desktops (KDE Plasma first); this process runs on {sys.platform!r}.",
            hint="Run it inside the Linux desktop session (WSL: use the plugin's runtime row).",
        )
    if has_gui_context():
        return
    code = "NO_GUI_CONTEXT" if _under_dsh_pty() else "NO_DISPLAY"
    from .errors import KdeUiaError

    raise KdeUiaError(
        "no graphical session is reachable: neither DISPLAY nor WAYLAND_DISPLAY is set.",
        code=code,
        hint=_HINT,
    )


def _under_dsh_pty() -> bool:
    """Best-effort: detect a pty launched by a DSH-like GUI host."""
    if not (os.isatty(0) or os.isatty(1)):
        return False
    env = os.environ
    return any(k.startswith("DSH_") for k in env) and env.get("DSH_NO_GUI_CONTEXT", "1") not in ("0", "false", "False")


def current_desktop() -> str:
    """Return a normalised desktop id: ``kde``, ``gnome``, ``other`` or ``unknown``."""
    marker = " ".join(
        filter(None, (os.environ.get("XDG_CURRENT_DESKTOP", ""), os.environ.get("DESKTOP_SESSION", "")))
    ).lower()
    if "kde" in marker or "plasma" in marker:
        return "kde"
    if "gnome" in marker:
        return "gnome"
    if marker.strip():
        return "other"
    return "unknown"


def session_type() -> str:
    """``wayland``, ``x11`` or ``unknown``."""
    explicit = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if explicit in ("wayland", "x11"):
        return explicit
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def _probe_atspi() -> dict[str, Any]:
    """Check for the libatspi GI binding and a reachable a11y bus without keeping them open."""
    result: dict[str, Any] = {"gi_bindings": False, "atspi_bus": False, "address": None}
    try:
        import gi  # noqa: F401  (presence is the fact that matters)

        result["gi_bindings"] = True
    except Exception:
        return result
    address = atspi_bus_address()
    if address:
        result["atspi_bus"] = True
        result["address"] = address
    return result


def atspi_bus_address() -> str | None:
    """Return the a11y bus address via ``org.a11y.Bus.GetAddress`` (or the inherited override)."""
    inherited = os.environ.get("AT_SPI_BUS_ADDRESS")
    if inherited:
        return inherited
    for argv in (
        ["busctl", "--user", "call", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus", "GetAddress"],
        ["gdbus", "call", "--session", "--dest", "org.a11y.Bus", "--object-path", "/org/a11y/bus", "--method", "org.a11y.Bus.GetAddress"],
        ["dbus-send", "--session", "--print-reply", "--dest=org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus.GetAddress"],
    ):
        if shutil.which(argv[0]) is None:
            continue
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=3, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        address = _extract_bus_address(proc.stdout or "")
        if address:
            return address
    return None


def _extract_bus_address(output: str) -> str | None:
    for line in output.splitlines():
        line = line.strip()
        # gdbus: ('unix:path=/run/user/1000/at-spi/bus_0',)
        if line.startswith("(") and "unix:" in line:
            start = line.find("unix:")
            end = line.find("'", start)
            return line[start : end if end != -1 else None].strip()
        # busctl: s "unix:path=/run/user/1000/at-spi/bus_0"
        if line.startswith("s ") and "unix:" in line:
            return line.split('"', 2)[1] if '"' in line else line[2:].strip()
        # dbus-send: string "unix:path=..."
        if line.startswith("string ") and "unix:" in line:
            return line.split('"', 2)[1] if '"' in line else line[len("string ") :].strip()
    return None


@dataclass
class Environment:
    """Snapshot of everything the backends need to know about the session."""

    platform: str
    under_wsl: bool
    desktop: str
    session_type: str
    display: str | None
    wayland_display: str | None
    xdg_runtime_dir: str | None
    atspi: dict[str, Any] = field(default_factory=dict)
    tools: dict[str, str | None] = field(default_factory=dict)
    input_backend: str | None = None
    screenshot_backends: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "kdeUiaVersion": __version__,
            "platform": self.platform,
            "underWsl": self.under_wsl,
            "desktop": self.desktop,
            "sessionType": self.session_type,
            "display": self.display,
            "waylandDisplay": self.wayland_display,
            "xdgRuntimeDir": self.xdg_runtime_dir,
            "hostname": socket.gethostname(),
            "atspi": dict(self.atspi),
            "tools": dict(self.tools),
            "inputBackend": self.input_backend,
            "screenshotBackends": list(self.screenshot_backends),
        }

    @property
    def hint_for_missing_atspi(self) -> str:
        return AT_SPI_HINT


TOOLS_OF_INTEREST = (
    "kdotool",
    "xdotool",
    "wmctrl",
    "xprop",
    "spectacle",
    "kwrite",
    "import",
    "xwd",
    "busctl",
    "gdbus",
    "qdbus6",
)


def _which(names: tuple[str, ...]) -> dict[str, str | None]:
    return {name: shutil.which(name) for name in names}


def detect_environment(*, probe_atspi: bool = True) -> Environment:
    """Collect the current session facts.  Never raises for a missing display."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    return Environment(
        platform=sys.platform,
        under_wsl=bool(os.environ.get("WSL_INTEROP") or os.environ.get("WSL_DISTRO_NAME")),
        desktop=current_desktop(),
        session_type=session_type(),
        display=os.environ.get("DISPLAY") or None,
        wayland_display=os.environ.get("WAYLAND_DISPLAY") or None,
        xdg_runtime_dir=runtime_dir if runtime_dir and Path(runtime_dir).is_dir() else None,
        atspi=_probe_atspi() if probe_atspi else {},
        tools=_which(TOOLS_OF_INTEREST),
    )
