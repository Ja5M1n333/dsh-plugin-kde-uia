"""kde-uia: a Windows-UIA-style desktop automation client for Linux, KDE Plasma first.

The public surface is intentionally small and JSON-shaped, mirroring the
Windows UI Automation concepts agents know:

======================================  ====================================
Windows UI Automation                     kde-uia
======================================  ====================================
``AutomationElement.RootElement``         :class:`DesktopSession` + ``windows``
``TreeWalker``                            :func:`walk` / ``tree``
``AutomationElement.FindFirst/All``       :class:`Selector` + ``find``
``RuntimeId``                             :class:`~kde_uia.refs.ElementRef`
``InvokePattern`` / ``TogglePattern``     ``click`` / ``toggle``
``ValuePattern``                          ``set`` / ``info``
``TextPattern`` / ``SelectionPattern``    ``info``, ``focused``
``WindowPattern``                         ``activate`` / ``window`` ops
``Keyboard``/``Mouse``                    ``press`` / ``type`` / ``click`` / ``scroll``
``Screenshot`` (Win32 capture APIs)       ``screenshot``
======================================  ====================================

Example::

    from kde_uia import Client, Selector

    with Client() as ui:
        window = ui.window(window="Dolphin")
        button = ui.find_first(Selector(role="push-button", name="Places"), window=window.title)
        ui.click(button)
        ui.press("ctrl+l")
        ui.type("trash:///")
        ui.press("Return")
"""

from __future__ import annotations

from typing import Any

from .element import AtspiElement
from .env import detect_environment
from .errors import ERROR_CODES, KdeUiaError
from .refs import ElementRef, make_ref, parse_ref
from .selector import Selector
from .session import DesktopSession, Options

__version__ = "0.1.0"

__all__ = [
    "Client",
    "Selector",
    "ElementRef",
    "make_ref",
    "parse_ref",
    "KdeUiaError",
    "ERROR_CODES",
    "detect_environment",
    "__version__",
]


class Client:
    """High-level facade used by library callers and tests."""

    def __init__(self, options: Options | None = None, **keyword: Any) -> None:
        if keyword:
            data = {k.replace("-", "_"): v for k, v in keyword.items()}
            options = Options.from_dict({**data, **(options.__dict__ if options else {})})
        self.session = DesktopSession(options)

    # ---------------------------------------------------------- lifecycle
    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self.session.close()

    # ------------------------------------------------------------ queries
    def windows(self, *, include_hidden: bool = False) -> list[dict[str, Any]]:
        from .ops import list_windows

        return list_windows(self.session, {"include_hidden": include_hidden})["windows"]

    def window(self, **selector: Any) -> Any:
        """Return the single matching AT-SPI window element; raises when not unique."""
        chosen = Selector.from_dict(selector)
        return self.session.tree.resolve_window(chosen).element

    def find(self, selector: Selector, *, limit: int = 50) -> list[AtspiElement]:
        if limit and limit < selector.limit:
            selector.limit = limit
        return self.session.tree.find(selector)

    def find_first(self, selector: Selector) -> AtspiElement | None:
        found = self.find(selector, limit=1)
        return found[0] if found else None

    def element(self, ref: str) -> AtspiElement:
        return self.session.tree.resolve_ref(ref)

    def focused(self) -> AtspiElement | None:
        return self.session.tree.focused()

    def tree(self, **selector: Any) -> str:
        from .ops import tree

        return tree(self.session, {"selector": selector})["text"]

    # ----------------------------------------------------------- actions
    def activate(self, **window: Any) -> dict[str, Any]:
        from .ops import activate_window

        return activate_window(self.session, window)

    def click(self, target: AtspiElement | str, *, strategy: str = "auto") -> dict[str, Any]:
        from .ops import click

        ref = target if isinstance(target, str) else target.ref()
        return click(self.session, {"ref": ref, "strategy": strategy})

    def press(self, combo: str, *, repeat: int = 1) -> dict[str, Any]:
        from .ops import press_key

        return press_key(self.session, {"key": combo, "repeat": repeat})

    def type(self, text: str, *, target: AtspiElement | str | None = None, submit: bool = False) -> dict[str, Any]:
        from .ops import type_text

        args: dict[str, Any] = {"text": text, "submit": submit}
        if target is not None:
            args["ref"] = target if isinstance(target, str) else target.ref()
        return type_text(self.session, args)

    def set_value(self, target: AtspiElement | str, value: Any) -> dict[str, Any]:
        from .ops import set_value

        ref = target if isinstance(target, str) else target.ref()
        return set_value(self.session, {"ref": ref, "value": value})

    def screenshot(self, output: str | None = None, **options: Any) -> dict[str, Any]:
        from .ops import screenshot

        return screenshot(self.session, {"output": output, **options})
