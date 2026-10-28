"""The ``AutomationElement`` analogue: a wrapper around one :class:`Atspi.Accessible`.

Every property is read through :class:`AtspiConnection` so a wedged
application degrades into a coded ``ATSPI_TIMEOUT`` instead of hanging the
caller.  The wrapper computes - at first use - the facts needed to build a
stable, stateless :class:`~kde_uia.refs.ElementRef`: the application name and
the child-index path from the application root.
"""

from __future__ import annotations

from typing import Any, Iterator

from .refs import make_ref
from .selector import dedupe, normalize_role, role_matches

#: AT-SPI ``STATE_*`` bits with their agent-facing names.
STATES = {
    "active": "STATE_ACTIVE",
    "armed": "STATE_ARMED",
    "busy": "STATE_BUSY",
    "checked": "STATE_CHECKED",
    "collapsed": "STATE_COLLAPSED",
    "defunct": "STATE_DEFUNCT",
    "editable": "STATE_EDITABLE",
    "enabled": "STATE_ENABLED",
    "expandable": "STATE_EXPANDABLE",
    "expanded": "STATE_EXPANDED",
    "focusable": "STATE_FOCUSABLE",
    "focused": "STATE_FOCUSED",
    "has_tooltip": "STATE_HAS_TOOLTIP",
    "horizontal": "STATE_HORIZONTAL",
    "iconified": "STATE_ICONIFIED",
    "indeterminate": "STATE_INDETERMINATE",
    "invalid_entry": "STATE_INVALID_ENTRY",
    "is_default": "STATE_IS_DEFAULT",
    "modal": "STATE_MODAL",
    "multi_line": "STATE_MULTI_LINE",
    "opaque": "STATE_OPAQUE",
    "pressed": "STATE_PRESSED",
    "read_only": "STATE_READ_ONLY",
    "required": "STATE_REQUIRED",
    "resizable": "STATE_RESIZABLE",
    "selectable": "STATE_SELECTABLE",
    "selected": "STATE_SELECTED",
    "sensitive": "STATE_SENSITIVE",
    "showing": "STATE_SHOWING",
    "single_line": "STATE_SINGLE_LINE",
    "stale": "STATE_STALE",
    "supports_autocompletion": "STATE_SUPPORTS_AUTOCOMPLETION",
    "transient": "STATE_TRANSIENT",
    "vertical": "STATE_VERTICAL",
    "visible": "STATE_VISIBLE",
    "visited": "STATE_VISITED",
}

_STATE_ALIASES = {"focus": "focused", "check": "checked"}


def _state_alias(name: str) -> str:
    return _STATE_ALIASES.get(name, name)


class Navigator:
    def __init__(self, query: Any) -> None:
        self._q = query

    def child_count(self) -> int:
        value = self._q.get_child_count()
        return int(value) if value and value > 0 else 0

    def child_at(self, index: int) -> Any:
        return self._q.get_child_at_index(index)


class Component:
    def __init__(self, acc: Any) -> None:
        self._a = acc

    def extents(self, coord: int) -> tuple[int, int, int, int] | None:
        try:
            rect = self._a.get_extents(coord)
        except Exception:
            return None
        if rect is None or rect.width <= 0 or rect.height <= 0:
            return None
        return (int(rect.x), int(rect.y), int(rect.width), int(rect.height))

    def contains(self, x: int, y: int, coord: int) -> bool:
        try:
            return bool(self._a.contains(x, y, coord))
        except Exception:
            return False

    def grab_focus(self) -> bool:
        try:
            return bool(self._a.grab_focus())
        except Exception:
            return False


class ActionCapability:
    def __init__(self, acc: Any) -> None:
        self._a = acc

    def names(self) -> list[str]:
        try:
            count = int(self._a.get_action_count() or 0)
        except Exception:
            return []
        out = []
        for index in range(count):
            try:
                name = self._a.get_action_name(index)
            except Exception:
                name = None
            out.append(name or f"action{index}")
        return out

    def do(self, name: str) -> bool:
        try:
            return bool(self._a.do_action(0, name))
        except Exception:
            return False


class TextCapability:
    def __init__(self, acc: Any) -> None:
        self._a = acc

    def character_count(self) -> int:
        try:
            return int(self._a.get_character_count() or 0)
        except Exception:
            return 0

    def text(self, start: int = 0, end: int = -1) -> str:
        try:
            return self._a.get_text(start, end) or ""
        except Exception:
            return ""

    def set_caret_offset(self, offset: int) -> bool:
        try:
            return bool(self._a.set_caret_offset(offset, True))
        except Exception:
            return False


class ValueCapability:
    def __init__(self, acc: Any) -> None:
        self._a = acc

    def current(self) -> float | None:
        try:
            value = self._a.get_current_value()
        except Exception:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _bounds(self, getter: str) -> float | None:
        try:
            return float(getattr(self._a, getter)())
        except Exception:
            return None

    def minimum(self) -> float | None:
        return self._bounds("get_minimum_value")

    def maximum(self) -> float | None:
        return self._bounds("get_maximum_value")

    def set_current(self, value: float) -> bool:
        try:
            return bool(self._a.set_current_value(value, True))
        except Exception:
            return False


class EditableTextCapability:
    def __init__(self, acc: Any) -> None:
        self._a = acc

    def text(self) -> str:
        try:
            return self._a.get_text() or ""
        except Exception:
            return ""

    def insert(self, offset: int, text: str) -> bool:
        try:
            return bool(self._a.insert_text(offset, text, len(text), True))
        except Exception:
            return False

    def replace(self, start: int, end: int, text: str) -> bool:
        try:
            if not self._a.delete_text(start, end, True):
                return False
        except Exception:
            return False
        if not text:
            return True
        try:
            return bool(self._a.insert_text(start, text, len(text), True))
        except Exception:
            return False

    def copy_text(self, start: int, end: int) -> bool:
        try:
            return bool(self._a.copy_text(start, end))
        except Exception:
            return False

    def cut_text(self, start: int, end: int) -> bool:
        try:
            return bool(self._a.cut_text(start, end))
        except Exception:
            return False

    def paste_text(self, start: int) -> bool:
        try:
            return bool(self._a.paste_text(start))
        except Exception:
            return False


class AtspiElement:
    """A read-mostly wrapper around one accessible object."""

    def __init__(
        self,
        conn: Any,
        acc: Any,
        *,
        parent: "AtspiElement | None" = None,
        index_in_parent: int | None = None,
        window: "AtspiElement | None" = None,
    ) -> None:
        self.conn = conn
        self.acc = acc
        self.parent = parent
        self.index_in_parent = index_in_parent
        self.window = window
        self._ref_cache: dict[str, Any] = {}

    # ------------------------------------------------------------ identity
    def __repr__(self) -> str:  # pragma: no cover - debug aid
        try:
            return f"<AtspiElement role={self.role_name()!r} name={self.name()!r}>"
        except Exception:
            return "<AtspiElement>"

    def app_root(self) -> "AtspiElement":
        node: AtspiElement = self
        seen = 0
        while seen < 512:
            candidate = getattr(node, "parent", None)
            if not isinstance(candidate, AtspiElement):
                break
            node = candidate
            seen += 1
        return node

    def _is_desktop(self) -> bool:
        """The AT-SPI root is the parentless object whose direct children are applications."""
        if self.parent is not None:
            return False
        first = self.child_at(0)
        if first is not None and first.role_name() == "application":
            return True
        return not self.name() and self.role_name() in ("desktop", "desktop frame", "root")

    def _resolved_app_name(self) -> str | None:
        """The AT-SPI application name (``acc.get_name()``), cached; ``None`` when empty."""
        if "resolved_name" not in self._ref_cache:
            try:
                name = self.acc.get_name()
            except Exception:
                name = None
            self._ref_cache["resolved_name"] = name or None
        return self._ref_cache["resolved_name"]

    def app_name(self) -> str:
        """Display name of the owning application (never ``None``)."""
        root = self.app_root()
        if root is not self:
            return root.app_name()
        name = self._resolved_app_name()
        if name is None:
            name = "application" if self.role_name() == "application" else "desktop"
        return name

    def app_root_element(self) -> "AtspiElement":
        """The nearest application root at or above this element."""
        node: AtspiElement = self
        seen = 0
        while seen < 512 and node.role_name() != "application":
            candidate = node.parent
            if not isinstance(candidate, AtspiElement):
                break
            node = candidate
            seen += 1
        return node

    def app_label(self) -> str:
        """The application a reference is namespaced by.

        References use the AT-SPI application root name (``dolphin``,
        ``konsole``); elements that are not under an application root fall
        back to the desktop label.
        """
        label_root = self.app_root_element()
        if label_root.role_name() != "application":
            return "desktop"
        return label_root._resolved_app_name() or "application"

    def instance(self) -> str | None:
        """AT-SPI's path suffix (``:1.42``) as ``1.42``; ``None`` when unavailable.

        PyGObject exposes ``path_suffix`` as a method returning an
        :class:`Atspi.AccessiblePath` whose ``hex`` list holds two hex strings.
        """
        try:
            suffix = self.acc.path_suffix()
        except Exception:
            return None
        resolved = getattr(suffix, "hex", suffix)
        if isinstance(resolved, str) and resolved:
            return resolved
        if isinstance(resolved, (list, tuple)) and resolved:
            return ":".join(str(part) for part in resolved)
        return None

    def path(self) -> list[int]:
        path: list[int] = []
        node = self
        while node.parent is not None:
            if node.index_in_parent is None:
                break
            path.append(node.index_in_parent)
            node = node.parent
        path.reverse()
        return path

    def ref(self) -> str:
        return make_ref(self.app_label(), _ref_path(self.path()), self.instance())

    def backend_id(self) -> str:
        """The raw AT-SPI D-Bus path (unique only while the app lives)."""
        try:
            path = self.acc.get_accessible_object_path()
        except Exception:
            path = None
        return path or ""

    # ---------------------------------------------------------- properties
    def role_name(self) -> str:
        if "role" not in self._ref_cache:
            try:
                self._ref_cache["role"] = normalize_role(self.acc.get_role_name()) or "unknown"
            except Exception:
                self._ref_cache["role"] = "unknown"
        return self._ref_cache["role"]

    def role(self) -> int | None:
        try:
            return int(self.acc.get_role())
        except Exception:
            return None

    def name(self) -> str:
        try:
            return self.acc.get_name() or ""
        except Exception:
            return ""

    def description(self) -> str:
        try:
            return self.acc.get_description() or ""
        except Exception:
            return ""

    def state_set(self) -> Any | None:
        try:
            return self.acc.get_state_set()
        except Exception:
            return None

    def state(self, name: str) -> bool | None:
        """Read one state by agent name (``showing``) or AT-SPI name (``STATE_SHOWING``)."""
        key = _state_alias(name.lower())
        bit = STATES.get(key)
        if bit is None:
            if name.upper() in STATES.values():
                bit = name.upper()
            else:
                return None
        states = self.state_set()
        if states is None:
            return False
        try:
            attr = _state_type(self.conn, bit)
            return bool(states.contains(attr))
        except Exception:
            return False

    def states(self, *, only_set: bool = True) -> list[str]:
        out = []
        for key, bit in STATES.items():
            value = self.state(key)
            if only_set and not value:
                continue
            out.append(key)
        return out

    def attributes(self) -> dict[str, str]:
        out: dict[str, str] = {}
        try:
            attrs = self.acc.get_attributes() or {}
        except Exception:
            return out
        try:
            items = attrs.items()
        except AttributeError:
            items = []
        for key, value in items:
            out[str(key)] = str(value)
        return out

    # ------------------------------------------------------------ children
    def child_count(self) -> int:
        try:
            count = self.acc.get_child_count()
        except Exception:
            return 0
        return int(count) if count and count > 0 else 0

    def child_at(self, index: int) -> "AtspiElement | None":
        try:
            child = self.acc.get_child_at_index(index)
        except Exception:
            return None
        if child is None:
            return None
        return AtspiElement(self.conn, child, parent=self, index_in_parent=index, window=self.window)

    def children(self) -> Iterator["AtspiElement"]:
        for index in range(self.child_count()):
            child = self.child_at(index)
            if child is not None:
                yield child

    def ancestors(self) -> Iterator["AtspiElement"]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    # ---------------------------------------------------------- capabilities
    def has_component(self) -> bool:
        return bool(self.state("showing")) or self.extents() is not None

    def extents(self, coord: str = "screen") -> tuple[int, int, int, int] | None:
        if coord not in ("screen", "window"):
            return None
        return Component(self.acc).extents(_coord_type(self.conn, coord))

    def actions(self) -> list[str]:
        return ActionCapability(self.acc).names()

    def do_action(self, name: str) -> bool:
        return ActionCapability(self.acc).do(name)

    def text(self) -> str:
        return TextCapability(self.acc).text()

    def value(self) -> float | None:
        return ValueCapability(self.acc).current()

    def editable_text(self) -> str:
        return EditableTextCapability(self.acc).text()

    def text_or_value(self) -> str:
        """The best-effort "what does this element show" string (UIA ValuePattern analogue)."""
        role = self.role_name()
        if role in ("text", "editbar", "entry"):
            text = self.text()
            if text:
                return text
        value = self.value()
        if value is not None and role in ("slider", "spin button", "progress bar", "scroll bar", "level bar"):
            return _fmt_number(value)
        text = self.text()
        if text:
            return text
        if value is not None:
            return _fmt_number(value)
        return ""

    def editable_text_value(self) -> str | None:
        try:
            value = self.acc.get_text()
        except Exception:
            return None
        return value if isinstance(value, str) else None

    # ------------------------------------------------------------ selectors
    def matches_role(self, wanted: str | None) -> bool:
        return role_matches(self.role_name(), wanted)

    def match_summary(self) -> dict[str, Any]:
        """Small JSON projection used in find results."""
        rect = self.extents()
        return {
            "ref": self.ref(),
            "role": self.role_name(),
            "name": self.name(),
            "app": self.app_name(),
            "window": (self.window.name() if self.window is not None else None),
            "extents": _rect_dict(rect),
            "actions": [a for a in self.actions() if a != "show menu"],
        }

    def role_supported_interfaces(self) -> list[str]:
        found: list[str] = []
        try:
            self.acc.get_action_count()
            found.append("action")
        except Exception:
            pass
        for method, iface in (
            ("get_character_count", "text"),
            ("get_text", "editable_text"),
            ("get_current_value", "value"),
            ("get_extents", "component"),
            ("get_child_count", "navigator"),
        ):
            try:
                getattr(self.acc, method)()
                found.append(iface)
            except Exception:
                continue
        return dedupe(found)


def _ref_path(path: list[int]) -> list[int]:
    """The child-index path of an element, counting from its application root.

    ``path`` lists child indexes from the AT-SPI desktop root down to the
    element, so ``path = [app, *below_app]`` and the reference keeps
    ``below_app`` (the application root itself has ``path == [app]``).
    """
    if len(path) >= 2:
        return path[1:]
    return []


def _fmt_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _atspi_enum(conn: Any, family: str, member: str) -> Any:
    """Accept both ``conn.atspi.Atspi.<family>`` and ``conn.atspi.<family>`` (test doubles)."""
    gi = getattr(conn, "atspi", conn)
    holder = getattr(getattr(gi, "Atspi", gi), family)
    return getattr(holder, member)


def _coord_type(conn: Any, coord: str) -> Any:
    return _atspi_enum(conn, "CoordType", coord.upper())


def _state_type(conn: Any, bit: str) -> Any:
    return _atspi_enum(conn, "StateType", bit)


def _rect_dict(rect: tuple[int, int, int, int] | None) -> dict[str, int] | None:
    if rect is None:
        return None
    x, y, w, h = rect
    return {"x": x, "y": y, "width": w, "height": h}
