"""AT-SPI tree operations: applications, windows, traversal, find, focus, refs.

The desktop tree is::

    desktop
     └── application (root, one per a11y-enabled process)
          ├── frame        <- a top-level window (optionally with a titlebar child)
          │    └── ...     <- panels, toolbars, views, ...
          ├── dialog
          ├── popup menu
          └── ...

``windows`` enumerates frames/dialogs across applications; ``tree`` renders a
window (or an element) as an indented, agent-readable list; ``find`` walks the
same trees applying a :class:`~kde_uia.selector.Selector`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from .atspi_client import AtspiConnection
from .element import AtspiElement, _rect_dict
from .errors import AmbiguousError, AtspiUnavailableError, InvalidRefError, NotFoundError, UsageError
from .refs import ElementRef, parse_ref
from .selector import Selector, role_matches

WINDOW_ROLES = ("frame", "dialog", "alert", "window", "file chooser", "document frame", "menu")
#: Roles only reported by some toolkits for popups; never treated as windows.
_NON_WINDOW_ROLES = ("popup menu", "tool tip", "notification")
#: A frame whose only child is a titlebar-like widget is reported by KWin's own
#: accessibility bridge; prefer the accessible toplevel inside it.
_TITLEBAR_ROLES = ("titlebar", "title bar")

ACTION_ALIASES = {
    "click": "click",
    "press": "click",
    "activate": "click",
    "toggle": "click",
    "check": "click",
    "default": "default",
    "focus": "focus",
    "expand": "expand",
    "collapse": "collapse",
    "showmenu": "show menu",
    "show menu": "show menu",
    "menu": "show menu",
}


@dataclass
class WindowInfo:
    element: AtspiElement
    app: str
    title: str
    role: str
    ref: str
    extents: dict[str, int] | None
    states: list[str]
    backend_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "app": self.app,
            "role": self.role,
            "ref": self.ref,
            "backendId": self.backend_id,
            "extents": self.extents,
            "states": self.states,
        }


class TreeSession:
    """One connection's worth of tree queries."""

    def __init__(self, conn: AtspiConnection) -> None:
        self.conn = conn

    # ----------------------------------------------------------- desktop
    def desktop(self) -> AtspiElement:
        root = self.conn.dispatch()
        if root is None:
            raise AtspiUnavailableError(
                "AT-SPI desktop could not be reached",
                hint="Is the a11y bus running (at-spi2-core active) and this process in the session's user bus?",
            )
        return AtspiElement(self.conn, root)

    def applications(self) -> Iterator[AtspiElement]:
        desktop = self.desktop()
        for index in range(desktop.child_count()):
            app = desktop.child_at(index)
            if app is None:
                continue
            yield app

    def application(self, name: str) -> AtspiElement:
        matches = [app for app in self.applications() if app.name() == name]
        if not matches:
            known = sorted({app.name() for app in self.applications()})
            raise NotFoundError(
                f"no accessibility application named {name!r}",
                hint=f"Registered application names: {', '.join(known) or '(none)'}.",
            )
        return matches[0]

    # ----------------------------------------------------------- windows
    def windows(self, *, include_hidden: bool = False) -> list[WindowInfo]:
        found: list[WindowInfo] = []
        for app in self.applications():
            for child in app.children():
                if not self._is_window(child, include_hidden=include_hidden):
                    continue
                found.append(self._window_info(child, app, include_hidden=include_hidden))
        return found

    def _is_window(self, child: AtspiElement, *, include_hidden: bool) -> bool:
        role = child.role_name()
        if role in _NON_WINDOW_ROLES:
            return False
        if role not in WINDOW_ROLES:
            # Some toolkits only expose tooltips/notifications with odd roles.
            return False
        if not include_hidden and not child.state("showing"):
            return False
        return True

    def _window_info(self, element: AtspiElement, app: AtspiElement, *, include_hidden: bool = False) -> WindowInfo:
        # Windows are one level under the application, except for decorated KWin
        # frames whose only child is the real toplevel widget.
        if element.role_name() == "frame":
            kids = list(element.children())
            if len(kids) == 1 and kids[0].role_name() in _TITLEBAR_ROLES:
                inner = [k for k in kids[0].children() if self._is_window(k, include_hidden=include_hidden)]
                if inner:
                    element = inner[0]
            else:
                inner = [k for k in kids if self._is_window(k, include_hidden=include_hidden)]
                if inner and not element.name():
                    element = inner[0]
        return WindowInfo(
            element=element,
            app=element.app_label(),
            title=element.name(),
            role=element.role_name(),
            ref=element.ref(),
            extents=_rect_dict(element.extents()),
            states=element.states(),
            backend_id=element.backend_id(),
        )

    def find_windows(
        self,
        selector: Selector,
        *,
        include_hidden: bool = False,
    ) -> list[WindowInfo]:
        candidates = self.windows(include_hidden=include_hidden)
        out: list[WindowInfo] = []
        for info in candidates:
            if selector.app and info.app != selector.app:
                continue
            if selector.window_id and info.backend_id != selector.window_id and info.ref != selector.window_id:
                continue
            if selector.window is not None and not selector._match_value(info.title, selector.window):
                continue
            if selector.role and not role_matches(info.role, selector.role):
                continue
            # When the selector scopes to one window, the title and name conditions
            # describe the window; the element condition is applied inside it.
            scoped = bool(selector.window is not None or selector.window_id)
            if not scoped and selector.name is not None and not selector.matches_name(info.title):
                continue
            if not selector.matches_states(lambda s: s in info.states):
                continue
            out.append(info)
        return out

    def resolve_window(self, selector: Selector) -> WindowInfo:
        """Resolve exactly one window, failing loudly on 0 or >1 matches."""
        matches = self.find_windows(selector, include_hidden=False)
        if not matches:
            visible = self.find_windows(Selector(limit=10**6))
            listing = ", ".join(f"{m.title!r} [{m.app}]" for m in visible[:12]) or "(none)"
            raise NotFoundError(
                f"no window matched {selector.describe()} (scope: {selector.scope_text()})",
                hint=f"Visible windows: {listing}. Try `kde-uia windows`.",
            )
        if len(matches) > 1:
            listing = ", ".join(f"{m.title!r} [{m.app}] {m.ref}" for m in matches[:12])
            raise AmbiguousError(
                f"{len(matches)} windows matched {selector.describe()}: {listing}",
                hint="Narrow the selector (add `app`, `window` or `window_id`) or pass ref explicitly.",
            )
        return matches[0]

    # ---------------------------------------------------------------- refs
    def resolve_ref(self, ref: str, *, timeout: float = 10.0) -> AtspiElement:
        parsed = parse_ref(ref)
        apps = [app for app in self.applications() if app.name() == parsed.app]
        if not apps:
            raise InvalidRefError(
                f"reference {ref} names application {parsed.app!r}, which is not registered",
                hint="Refresh refs with `kde-uia windows` / `kde-uia find`; the application may have closed.",
            )
        app = apps[0]
        if parsed.instance is not None:
            for candidate in apps:
                if candidate.instance() == parsed.instance:
                    app = candidate
                    break
        node = app
        for depth, index in enumerate(parsed.path):
            child = node.child_at(index)
            if child is None:
                raise InvalidRefError(
                    f"reference {ref} is stale: no child {index} at depth {depth} under {node.role_name()!r}",
                    hint="Widgets were added/removed since the ref was taken. Re-run `tree`/`find` and use the fresh ref.",
                )
            node = child
        return node
    def resolve_element(
        self,
        *,
        ref: str | None = None,
        selector: Selector | None = None,
        require_unique: bool = True,
    ) -> AtspiElement:
        """Resolve an action target by explicit ref, else by selector."""
        if ref:
            return self.resolve_ref(ref)
        selector = selector or Selector()
        if selector.is_empty:
            raise UsageError(
                "an action needs a target: pass `ref` or a selector (role/name/text/states)",
                hint='Example: --text "Save" --role push-button, or --ref uia:1:kwrite:1/0/2.',
            )
        matches = self.find(selector)
        if not matches:
            raise NotFoundError(
                f"no element matched {selector.describe()} (scope: {selector.scope_text()})",
                hint="Run `kde-uia tree --window <title>` to inspect the window's elements.",
            )
        if require_unique and len(matches) > 1:
            listing = ", ".join(f"{m.role_name()}:{m.name()!r} {m.ref()}" for m in matches[:10])
            raise AmbiguousError(
                f"{len(matches)} elements matched {selector.describe()}: {listing}",
                hint="Add a condition, narrow the scope, or pass `ref` for an exact target.",
            )
        return matches[0]

    # ------------------------------------------------------------ walking
    def walk(
        self,
        root: AtspiElement,
        *,
        max_depth: int,
        predicate: Callable[[AtspiElement], bool] | None = None,
        visible_only: bool = True,
    ) -> Iterator[AtspiElement]:
        """Depth-first pre-order traversal, bounded by ``max_depth``."""
        stack: list[tuple[AtspiElement, int]] = [(root, 0)]
        while stack:
            node, depth = stack.pop()
            if predicate is not None and predicate(node):
                yield node
            if depth >= max_depth:
                continue
            children = []
            for child in node.children():
                if visible_only and not child.state("showing"):
                    continue
                children.append((child, depth + 1))
            stack.extend(reversed(children))

    def find(self, selector: Selector) -> list[AtspiElement]:
        roots = self._find_roots(selector)
        max_depth = selector.depth if selector.depth is not None else 40

        def matches(element: AtspiElement) -> bool:
            if not element.matches_role(selector.role):
                return False
            if selector.name is not None and not selector.matches_name(element.name()):
                return False
            if selector.description is not None and not selector.matches_description(element.description()):
                return False
            if selector.text is not None:
                name = element.name()
                value_text = element.text_or_value()
                if not (selector.matches_text(value_text) or selector.matches_text(name)):
                    return False
            if selector.states and not selector.matches_states(element.state):
                return False
            for attribute, expected in selector.attributes.items():
                if element.attributes().get(attribute, element.attributes().get(attribute.replace("_", "-"), "")) != str(expected):
                    return False
            return True

        out: list[AtspiElement] = []
        for root, include_root in roots:
            if include_root and matches(root):
                out.append(root)
            for element in self.walk(root, max_depth=max_depth, predicate=matches, visible_only=selector.visible_only):
                if element is root:
                    continue
                out.append(element)
                if len(out) >= selector.limit:
                    return out
        return out

    def _find_roots(self, selector: Selector) -> list[tuple[AtspiElement, bool]]:
        if selector.window or selector.app or selector.window_id:
            matches = self.find_windows(selector, include_hidden=False)
            if not matches:
                raise NotFoundError(
                    f"no window matched scope ({selector.scope_text()})",
                    hint="Run `kde-uia windows` to list window titles and apps.",
                )
            return [(info.element, True) for info in matches]
        return [(info.element, True) for info in self.windows()]

    # ------------------------------------------------------------- focus
    def focused(self) -> AtspiElement | None:
        for app in self.applications():
            for element in self.walk(app, max_depth=48, predicate=lambda e: bool(e.state("focused"))):
                return element
        return None

    def active_window(self) -> WindowInfo:
        element = self.focused()
        if element is not None:
            for ancestor in [element, *element.ancestors()]:
                if ancestor.role_name() in WINDOW_ROLES:
                    app = ancestor.app_root()
                    return self._window_info(ancestor, app)
        raise NotFoundError("no window has keyboard focus", hint="Click into the target window first, or activate it by title.")


@dataclass
class TreeRenderOptions:
    max_depth: int = 4
    max_nodes: int = 200
    include_refs: bool = True
    include_extents: bool = False


@dataclass
class TreeRenderResult:
    text: str
    nodes: int
    truncated: bool = False


def render_tree(session: TreeSession, root: AtspiElement, options: TreeRenderOptions) -> TreeRenderResult:
    """Render an element subtree as indented text with refs."""
    lines: list[str] = []
    count = 0
    truncated = False

    def visit(node: AtspiElement, depth: int) -> None:
        nonlocal count, truncated
        if count >= options.max_nodes:
            truncated = True
            return
        count += 1
        lines.append(_line(node, depth, options))
        if depth >= options.max_depth:
            children_left = node.child_count()
            if children_left:
                lines.append("  " * (depth + 1) + f"… ({children_left} children, max-depth reached)")
                truncated = True
            return
        for child in node.children():
            if not child.state("showing"):
                continue
            visit(child, depth + 1)

    visit(root, 0)
    if truncated:
        lines.append(f"… output truncated at {options.max_nodes} nodes / depth {options.max_depth}")
    return TreeRenderResult(text="\n".join(lines), nodes=count, truncated=truncated)


def _line(node: AtspiElement, depth: int, options: TreeRenderOptions) -> str:
    indent = "  " * depth
    parts = [f"{indent}{node.role_name()} {node.name()!r}".rstrip()]
    details: list[str] = []
    try:
        value = node.text_or_value()
        if value and value != node.name():
            details.append(f"value={_short(value)}")
    except Exception:
        pass
    actions = []
    try:
        actions = [a for a in node.actions() if a not in ("show menu",)]
    except Exception:
        actions = []
    if actions:
        details.append("actions=" + ",".join(actions[:5]))
    try:
        states = node.states()
    except Exception:
        states = []
    interesting = [s for s in ("checked", "selected", "focused", "pressed", "expanded", "busy", "sensitive") if s in states]
    if "sensitive" in interesting and True:
        interesting.remove("sensitive")
    if interesting:
        details.append("[" + " ".join(interesting) + "]")
    if options.include_extents:
        rect = node.extents()
        if rect is not None:
            details.append(f"@ {rect[0]},{rect[1]} {rect[2]}x{rect[3]}")
    if options.include_refs:
        details.append(node.ref())
    if details:
        parts.append("  " + "  ".join(details))
    return "".join(parts)


def _short(text: str, limit: int = 40) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
