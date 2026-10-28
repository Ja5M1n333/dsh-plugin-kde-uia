"""The AT-SPI2 client core.

libatspi runs its own GLib main loop on a private thread (``atspi.init()``)
and marshals every call through it.  Two consequences shape this module:

1. A registry of every :class:`AtspiElement` exposed to Python must exist so
   the C thread's references stay alive and ``__g_object_unref__`` callbacks
   can find (or drop) the wrapper.
2. AT-SPI calls can block indefinitely when an application is wedged.  Every
   call made through :class:`AtspiConnection` therefore runs on a helper
   thread with a timeout, and :class:`BusyError` guards re-entrancy (the
   event loop can be in the middle of another blocking call).
"""

from __future__ import annotations

import concurrent.futures
import os
import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from .errors import AT_SPI_HINT, AtspiUnavailableError, BackendUnavailableError, KdeUiaError

AT_SPI_IMPORT_HINT = (
    "kde-uia needs PyGObject and the libatspi typelib. On Arch Linux (the primary target): "
    "`sudo pacman -S python-gobject at-spi2-core` — at-spi2-core ships /usr/lib/girepository-1.0/Atspi-2.0.typelib. "
    "On Debian/Ubuntu/KDE neon: `sudo apt install python3-gi gir1.2-atspi-2.0 at-spi2-core`; "
    "on Fedora: `sudo dnf install python3-gobject at-spi2-core`."
)

#: Distribution package that provides each helper the client may look for.
#: Arch is listed first everywhere: it is the primary, tested target.
#: Package names were checked against the Arch package database / AUR RPC
#: (see tests/test_pure.py::DistroHintTests, which pins the important ones).
PACKAGE_HINTS: dict[str, str] = {
    "python3": "Arch: python | Debian: python3 | Fedora: python3",
    "xdotool": "Arch: xdotool | Debian: xdotool | Fedora: xdotool",
    "kdotool": "Arch: AUR only — yay -S kdotool (or kdotool-bin) | Fedora: kdotool | else: cargo install kdotool",
    "wmctrl": "Arch: wmctrl | Debian: wmctrl | Fedora: wmctrl",
    "spectacle": "Arch: spectacle | Debian: spectacle | Fedora: spectacle",
    "grim": "Arch: grim | Debian: grim | Fedora: grim",
    "imagemagick": "Arch: imagemagick | Debian: imagemagick | Fedora: ImageMagick",
    "qdbus6": "Arch: qt6-tools | Debian: qdbus-qt6 | Fedora: qt6-qttools",
    "kwriteconfig6": "Arch: kconfig | Debian: kconfig-cli | Fedora: kf6-kconfig",
    "kreadconfig6": "Arch: kconfig | Debian: kconfig-cli | Fedora: kf6-kconfig",
    "busctl": "Arch: systemd | Debian: systemd | Fedora: systemd",
    "gdbus": "Arch: glib2 | Debian: libglib2.0-bin | Fedora: glib2",
}


def package_hint(name: str) -> str:
    """Where to install a helper tool, per distribution (Arch first)."""
    return PACKAGE_HINTS.get(name, f"Arch: {name} | Debian: {name} | Fedora: {name}")


def import_atspi() -> tuple[Any, Any]:
    """Import ``gi.repository.Atspi`` and ``GObject``; raise a coded error otherwise."""
    try:
        import gi  # noqa: F401
    except Exception as exc:  # pragma: no cover - depends on host
        raise AtspiUnavailableError(
            f"PyGObject (python3-gi) is not importable: {exc}",
            hint=AT_SPI_IMPORT_HINT,
            details={"requirement": "gi"},
        ) from exc
    try:
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi, GObject
    except Exception as exc:  # pragma: no cover - depends on host
        raise AtspiUnavailableError(
            f"libatspi GI typelib is not available: {exc}",
            hint=AT_SPI_IMPORT_HINT,
            details={"requirement": "gir1.2-atspi-2.0"},
        ) from exc
    return Atspi, GObject


class _ElementRegistry:
    """Live AT-SPI element wrappers, keyed by wrapper id."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_ref: dict[int, Any] = {}

    def register(self, wrapper: Any) -> None:
        with self._lock:
            self._by_ref[id(wrapper)] = wrapper

    def lookup(self, key: int) -> Any | None:
        with self._lock:
            return self._by_ref.get(key)

    def forget(self, wrapper: Any) -> None:
        with self._lock:
            self._by_ref.pop(id(wrapper), None)


REGISTRY = _ElementRegistry()


class Atspi:  # noqa: N801 - mirrors the GI namespace
    """Thin process-wide handle on the ``Atspi`` GI namespace."""

    _instance: "Atspi | None" = None

    def __init__(self) -> None:
        self.Atspi, self.GObject = import_atspi()

    @classmethod
    def get(cls) -> "Atspi":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


def safe_call(fn: Callable[..., Any], /, *args: Any, default: Any = None) -> Any:
    """Call a libatspi method, swallowing GLib errors into ``default``."""
    try:
        return fn(*args)
    except Exception:  # GLib.Error / RuntimeError from a dying app
        return default


class AtspiConnection:
    """Initialised AT-SPI client with timed, serialised calls.

    ``open()`` is idempotent per process.  Calls are serialised: libatspi's
    event loop services one blocking call at a time and a second concurrent
    call can deadlock, so overlapping calls get :class:`BusyError` instead.
    """

    def __init__(self, *, timeout: float = 10.0) -> None:
        self.timeout = timeout
        self.atspi = Atspi.get()
        self._busy = threading.Lock()
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="kde-uia-atspi")
        self._initialised = False

    # ------------------------------------------------------------ lifecycle
    def open(self) -> "AtspiConnection":
        if self._initialised:
            return self
        try:
            self.atspi.Atspi.init()
        except Exception as exc:
            raise AtspiUnavailableError(
                f"atspi.init() failed: {exc}",
                hint=AT_SPI_HINT,
            ) from exc
        self._initialised = True
        return self

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def __enter__(self) -> "AtspiConnection":
        return self.open()

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ----------------------------------------------------------------- calls
    def call(self, fn: Callable[..., Any], *args: Any, default: Any = None, label: str = "AT-SPI call") -> Any:
        """Run ``fn(*args)`` on the helper thread, bounded by ``self.timeout``."""
        if not self._busy.acquire(blocking=False):
            raise KdeUiaError(
                "the AT-SPI event loop is busy with another call; retry when it finishes",
                code="BUSY",
                hint="AT-SPI calls are serialised per process; a wedged application is usually the cause.",
            )
        try:
            future = self._pool.submit(safe_call, fn, *args, default=default)
            try:
                return future.result(timeout=self.timeout)
            except concurrent.futures.TimeoutError:
                raise KdeUiaError(
                    f"{label} did not answer within {self.timeout:g}s",
                    code="ATSPI_TIMEOUT",
                    hint="The application is not responding to accessibility queries. It may be hung, "
                    "still starting, or running without accessibility enabled.",
                ) from None
        finally:
            self._busy.release()

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Hold the call lock across a group of calls (also used between threads)."""
        if not self._busy.acquire(timeout=max(self.timeout, 1.0)):
            raise KdeUiaError("the AT-SPI event loop stayed busy", code="BUSY")
        try:
            yield
        finally:
            self._busy.release()

    def dispatch(self) -> Any:
        """Return the desktop (root) accessor."""
        return self.call(self.atspi.Atspi.get_desktop, 0, default=None, label="Atspi.get_desktop(0)")

    # ---------------------------------------------------------------- state
    def registry_lookup(self, key: int) -> Any | None:
        return REGISTRY.lookup(key)


def require(condition: Any, message: str, *, code: str = "INTERNAL", hint: str = "") -> None:
    if not condition:
        raise KdeUiaError(message, code=code, hint=hint)


def check_a11y_enabled(conn: "AtspiConnection") -> None:
    """Warn (or fail) when the desktop reports accessibility as disabled.

    ``org.a11y.Status.IsEnabled`` is ``false`` on many distro images; every
    toolkit then stops exposing widgets and the tree looks empty.  This is
    checked once per session so agents do not mistake it for "no windows".
    """
    import shutil
    import subprocess

    if os.environ.get("KDE_UIA_SKIP_A11Y_CHECK"):
        return
    for argv in (
        ["busctl", "--user", "get-property", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status", "IsEnabled"],
        ["gdbus", "call", "--session", "--dest", "org.a11y.Bus", "--object-path", "/org/a11y/bus",
         "--method", "org.freedesktop.DBus.Properties.Get", "org.a11y.Status", "IsEnabled"],
    ):
        if shutil.which(argv[0]) is None:
            continue
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=3, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return
        if proc.returncode != 0:
            return
        if "false" in proc.stdout.lower():
            raise KdeUiaError(
                "accessibility is disabled on this desktop (org.a11y.Status.IsEnabled = false), so toolkits "
                "do not expose their widgets",
                code="ACCESSIBILITY_DISABLED",
                hint="Enable it: `gsettings set org.gnome.desktop.interface toolkit-accessibility true` "
                     "(or GNOME Settings > Accessibility), or in KDE System Settings > Accessibility. "
                     "Restart the target applications afterwards. Set KDE_UIA_SKIP_A11Y_CHECK=1 to skip this check.",
            )
        return


def which_or_raise(name: str, purpose: str) -> str:
    """Resolve a helper executable or raise BACKEND_UNAVAILABLE."""
    import shutil

    path = shutil.which(name)
    if path is None:
        raise BackendUnavailableError(
            f"{name!r} is required for {purpose} but is not on PATH",
            hint=f"Install it ({package_hint(name)}) or use another --strategy.",
            details={"tool": name, "purpose": purpose},
        )
    return path
