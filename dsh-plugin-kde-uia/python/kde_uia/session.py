"""Process-wide session object used by the CLI and the library API.

:class:`DesktopSession` wires the AT-SPI tree, the window backend and the
input/screenshot services together for one command.  Long-lived callers keep
one around; CLI invocations construct one, run a single operation and close
it.  Everything is lazy: importing and constructing a session never touches
the accessibility bus or the compositor.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from . import env as env_mod


@dataclass
class Options:
    """Per-invocation options shared by CLI and library callers."""

    window_backend: str = "auto"      # auto | kwin | x11 | atspi
    input_strategy: str = "auto"      # auto | atspi | xdotool | kdotool | dbus | dry-run
    screenshot_strategy: str = "auto"
    allow_xdotool_on_wayland: bool = False
    atspi_timeout: float = 10.0
    wait_timeout: float = 10.0
    poll_interval: float = 0.25
    dry_run: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Options":
        data = data or {}
        return cls(
            window_backend=str(data.get("window_backend", data.get("windowBackend", "auto"))),
            input_strategy=str(data.get("input_strategy", data.get("inputStrategy", "auto"))),
            screenshot_strategy=str(data.get("screenshot_strategy", data.get("screenshotStrategy", "auto"))),
            allow_xdotool_on_wayland=bool(data.get("allow_xdotool_on_wayland", data.get("allowXdotoolOnWayland", False))),
            atspi_timeout=float(data.get("atspi_timeout", data.get("atspiTimeout", 10.0))),
            wait_timeout=float(data.get("wait_timeout", data.get("waitTimeout", 10.0))),
            poll_interval=float(data.get("poll_interval", data.get("pollInterval", 0.25))),
            dry_run=bool(data.get("dry_run", data.get("dryRun", False))),
        )


class DesktopSession:
    def __init__(self, options: Options | None = None, *, environment: env_mod.Environment | None = None) -> None:
        self.options = options or Options()
        self.environment = environment or env_mod.detect_environment()
        self._conn: Any = None
        self._tree: Any = None
        self._wm_backend: Any = None

    # ------------------------------------------------------------ AT-SPI
    @property
    def conn(self) -> Any:
        if self._conn is None:
            from .atspi_client import AtspiConnection

            self._conn = AtspiConnection(timeout=self.options.atspi_timeout).open()
        return self._conn

    @property
    def tree(self) -> Any:
        from .tree import TreeSession

        if self._tree is None:
            env_mod.require_display_context()
            from .atspi_client import check_a11y_enabled

            check_a11y_enabled(self.conn)
            self._tree = TreeSession(self.conn)
        return self._tree

    # ------------------------------------------------------ windows/input
    def window_backend(self) -> Any:
        """KWin or X11 backend, or ``None`` when only AT-SPI is available."""
        if self._wm_backend is None:
            from .window_backends import select_backend

            if self.options.window_backend == "atspi":
                return None
            self._wm_backend = select_backend(self.options.window_backend)
        return self._wm_backend

    def input(self) -> Any:
        from .input import InputService

        return InputService(
            strategy="dry-run" if self.options.dry_run else self.options.input_strategy,
            dry_run=self.options.dry_run,
            allow_xdotool_on_wayland=self.options.allow_xdotool_on_wayland,
        )

    def screenshots(self) -> Any:
        from .screenshot import ScreenshotService

        return ScreenshotService(strategy=self.options.screenshot_strategy)

    # ----------------------------------------------------------- helpers
    def screen_map(self) -> Any:
        from .screens import map_from_outputs, map_single

        backend = None
        try:
            backend = self.window_backend()
        except Exception:
            backend = None
        if backend is not None and hasattr(backend, "outputs"):
            try:
                return map_from_outputs(backend.outputs())
            except Exception:
                pass
        width, height = _x11_screen_size()
        return map_single(width, height)

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._tree = None

    def __enter__(self) -> "DesktopSession":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _x11_screen_size() -> tuple[int, int]:
    import subprocess

    display = os.environ.get("DISPLAY")
    if not display:
        return (0, 0)
    try:
        proc = subprocess.run(["xdpyinfo"], capture_output=True, text=True, timeout=4, check=False)
    except OSError:
        return (0, 0)
    for line in proc.stdout.splitlines():
        if "dimensions:" in line:
            token = line.split("dimensions:")[1].strip().split()[0]
            if "x" in token:
                w, _, h = token.partition("x")
                if w.isdigit() and h.isdigit():
                    return (int(w), int(h))
    return (0, 0)
