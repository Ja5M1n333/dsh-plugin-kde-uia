"""Error taxonomy for kde-uia.

Every failure raised by the library is a :class:`KdeUiaError` carrying a stable,
machine-readable ``code`` (mirrored in :data:`ERROR_CODES`) plus a
``hint`` that tells an agent or a human what to do next.  The CLI maps codes
to process exit statuses (see ``kde_uia.cli``); the DSH plugin forwards both
the code and the hint verbatim.
"""

from __future__ import annotations

from typing import Any

#: Every stable error code this package can emit.  Tool authors may switch on
#: these; adding a code is a backward-compatible change, removing one is not.
ERROR_CODES: tuple[str, ...] = (
    "USAGE",               # caller supplied invalid arguments
    "NO_DISPLAY",          # no graphical session reachable from this process
    "NO_GUI_CONTEXT",      # stdin/stdout are ttys but no DISPLAY/WAYLAND_DISPLAY
    "UNSUPPORTED_PLATFORM",  # not Linux
    "ATSPI_UNAVAILABLE",   # AT-SPI bus / GI bindings unreachable
    "ATSPI_TIMEOUT",       # an AT-SPI call did not answer in time
    "ATSPI_ERROR",         # libatspi reported a failure
    "ACCESSIBILITY_DISABLED",  # org.a11y.Status.IsEnabled == false
    "BUSY",                # the AT-SPI event loop is busy with another call
    "NOT_FOUND",           # no window/element matched
    "AMBIGUOUS",           # more than one candidate and ambiguity is an error
    "INVALID_REF",         # an element ref/path did not resolve
    "NOT_ACTIONABLE",      # the resolved element exposes no such action
    "NO_WINDOW",           # no window is focused / active
    "BACKEND_UNAVAILABLE", # a capability backend (screenshot, kwin, xdotool) is missing
    "DRM_DENIED",          # reading DRM node for screenshots was denied
    "SCREENSHOT_FAILED",   # every screenshot backend failed
    "INPUT_FAILED",        # synthetic input failed on every backend
    "INPUT_DENIED",        # input was refused by policy (e.g. not allowed in this mode)
    "TIMEOUT",             # a wait exceeded its timeout
    "INTERNAL",            # unexpected library/third-party failure
)


class KdeUiaError(Exception):
    """Base class of every kde-uia failure.

    Attributes:
        code: one of :data:`ERROR_CODES`.
        hint: actionable next step for a human or an agent.
        details: structured, JSON-serialisable extra facts.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "INTERNAL",
        hint: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.hint:
            payload["hint"] = self.hint
        if self.details:
            payload["details"] = self.details
        return payload

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class UsageError(KdeUiaError):
    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message, code="USAGE", hint=hint)


class NotFoundError(KdeUiaError):
    def __init__(self, message: str, *, hint: str = "", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="NOT_FOUND", hint=hint, details=details)


class AmbiguousError(KdeUiaError):
    def __init__(self, message: str, *, hint: str = "", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="AMBIGUOUS", hint=hint, details=details)


class InvalidRefError(KdeUiaError):
    def __init__(self, message: str, *, hint: str = "", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="INVALID_REF", hint=hint, details=details)


class NotActionableError(KdeUiaError):
    def __init__(self, message: str, *, hint: str = "", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="NOT_ACTIONABLE", hint=hint, details=details)


class BackendUnavailableError(KdeUiaError):
    def __init__(self, message: str, *, hint: str = "", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="BACKEND_UNAVAILABLE", hint=hint, details=details)


class AtspiUnavailableError(KdeUiaError):
    def __init__(self, message: str, *, hint: str = "", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="ATSPI_UNAVAILABLE", hint=hint, details=details)


class NoDisplayError(KdeUiaError):
    def __init__(self, message: str, *, hint: str = "", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="NO_DISPLAY", hint=hint, details=details)


class InputError(KdeUiaError):
    def __init__(self, message: str, *, hint: str = "", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="INPUT_FAILED", hint=hint, details=details)


class WaitTimeoutError(KdeUiaError):
    def __init__(self, message: str, *, hint: str = "", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="TIMEOUT", hint=hint, details=details)


AT_SPI_HINT = (
    "AT-SPI2 must be reachable. Install the runtime: "
    "Arch: `sudo pacman -S python-gobject at-spi2-core` (at-spi2-core ships Atspi-2.0.typelib); "
    "Debian/Ubuntu: `sudo apt install python3-gi gir1.2-atspi-2.0 at-spi2-core`; "
    "Fedora: `sudo dnf install python3-gobject at-spi2-core`. "
    "Run inside the desktop session's user (not as root), and make sure accessibility "
    "is not disabled (gsettings set org.gnome.desktop.interface toolkit-accessibility true, "
    "or enable it in KDE System Settings > Accessibility)."
)
