"""Declarative matching: the ``AutomationElementCondition`` analogue.

A :class:`Selector` is a small, serialisable condition tree.  Every field is
optional; when several are present they are ANDed.  Text comparisons support
three modes, which keep the rules explicit instead of relying on "smart"
defaults:

``exact``    case-sensitive equality
``contains`` case-insensitive substring (the agent-useful default)
``regex``    :mod:`re.search` with ``re.IGNORECASE`` unless ``case_sensitive``
             (``case`` alias) is set

The same selector language narrows the search *scope*: pass ``window``,
``app`` or ``window_id`` to search inside one window only, otherwise all
on-screen application windows are searched.

Selectors serialise to JSON, so an agent can store a locator in a skill or a
test and replay it later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .errors import UsageError

MATCH_MODES = ("exact", "contains", "regex")
DEFAULT_MATCH_MODE = "contains"


@dataclass
class Selector:
    """A condition tree over element properties and the search scope."""

    # --- element conditions (ANDed) ---
    role: str | None = None
    name: str | None = None
    description: str | None = None
    text: str | None = None  # shorthand: value OR name
    match: str = DEFAULT_MATCH_MODE
    case: bool = False
    states: dict[str, bool] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    # --- scope conditions ---
    window: str | None = None
    app: str | None = None
    window_id: str | None = None
    # --- traversal options ---
    depth: int | None = None
    limit: int = 200
    visible_only: bool = True

    def __post_init__(self) -> None:
        if self.match not in MATCH_MODES:
            raise UsageError(f"match must be one of {', '.join(MATCH_MODES)}, got {self.match!r}")
        if self.limit <= 0:
            raise UsageError("limit must be positive")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Selector":
        """Build a selector from JSON-ish data, rejecting unknown keys."""
        if not data:
            return cls()
        if not isinstance(data, dict):
            raise UsageError("a selector must be a JSON object")
        allowed = {
            "role", "name", "description", "text", "match", "case", "case_sensitive",
            "states", "attributes", "window", "app", "window_id", "windowId",
            "depth", "limit", "visible_only", "visibleOnly",
        }
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise UsageError(f"unknown selector keys: {', '.join(unknown)}", hint=f"Allowed keys: {', '.join(sorted(allowed))}.")
        states = data.get("states") or {}
        if not isinstance(states, dict):
            raise UsageError("selector.states must be an object of {state: boolean}")
        attributes = data.get("attributes") or {}
        if not isinstance(attributes, dict):
            raise UsageError("selector.attributes must be an object of {attribute: string}")
        depth = data.get("depth")
        if depth is not None and (not isinstance(depth, int) or depth < 0):
            raise UsageError("selector.depth must be a non-negative integer")
        limit = data.get("limit", 200)
        if not isinstance(limit, int):
            raise UsageError("selector.limit must be an integer")
        text = data.get("text")
        name = data.get("name")
        if text is not None and name is not None:
            raise UsageError("use either `text` or `name`, not both (text matches name OR value)")
        return cls(
            role=data.get("role"),
            name=name,
            description=data.get("description"),
            text=text,
            match=data.get("match", DEFAULT_MATCH_MODE),
            case=bool(data.get("case", data.get("case_sensitive", False))),
            states={str(k): bool(v) for k, v in states.items()},
            attributes={str(k): v for k, v in attributes.items()},
            window=data.get("window"),
            app=data.get("app"),
            window_id=data.get("windowId", data.get("window_id")),
            depth=depth,
            limit=limit,
            visible_only=bool(data.get("visibleOnly", data.get("visible_only", True))),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"match": self.match}
        for key in ("role", "name", "description", "text", "window", "app", "window_id"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        if self.case:
            out["case"] = True
        if self.states:
            out["states"] = dict(self.states)
        if self.attributes:
            out["attributes"] = dict(self.attributes)
        if self.depth is not None:
            out["depth"] = self.depth
        if self.limit != 200:
            out["limit"] = self.limit
        if not self.visible_only:
            out["visible_only"] = False
        return out

    # ------------------------------------------------------------------ text
    def matches_text(self, candidate: str | None) -> bool:
        if self.text is None:
            return True
        return self._match_value(candidate or "", self.text)

    def matches_name(self, candidate: str | None) -> bool:
        if self.name is None:
            return True
        return self._match_value(candidate or "", self.name)

    def matches_description(self, candidate: str | None) -> bool:
        if self.description is None:
            return True
        return self._match_value(candidate or "", self.description)

    def _match_value(self, candidate: str, pattern: str) -> bool:
        if self.match == "exact":
            return candidate == pattern if self.case else candidate.casefold() == pattern.casefold()
        if self.match == "contains":
            return pattern in candidate if self.case else pattern.casefold() in candidate.casefold()
        flags = 0 if self.case else re.IGNORECASE
        try:
            return re.search(pattern, candidate, flags) is not None
        except re.error as exc:
            raise UsageError(f"invalid regex {pattern!r}: {exc}") from exc

    # --------------------------------------------------------------- states
    def matches_states(self, state_lookup) -> bool:
        """``state_lookup(state_name_or_list) -> bool`` is supplied by the backend."""
        return all(bool(state_lookup(state)) is expected for state, expected in self.states.items())

    @property
    def is_empty(self) -> bool:
        """True when this selector only carries traversal/scope options."""
        return not (
            self.role
            or self.name is not None
            or self.description is not None
            or self.text is not None
            or self.states
            or self.attributes
        )

    def describe(self) -> str:
        """Human-readable form used in error messages and trees."""
        if self.is_empty:
            return "*"
        parts: list[str] = []
        if self.role:
            parts.append(f"role={self.role}")
        if self.name is not None:
            parts.append(f"name{_op(self.match)}={self.name!r}")
        if self.text is not None:
            parts.append(f"text{_op(self.match)}={self.text!r}")
        if self.description is not None:
            parts.append(f"description{_op(self.match)}={self.description!r}")
        for state, expected in self.states.items():
            parts.append(state if expected else f"not {state}")
        for attribute, expected in self.attributes.items():
            parts.append(f"{attribute}={expected!r}")
        return " and ".join(parts)

    def scope_text(self) -> str:
        bits = []
        if self.app:
            bits.append(f"app={self.app}")
        if self.window:
            bits.append(f"window{_op(self.match)}={self.window!r}")
        if self.window_id:
            bits.append(f"window-id={self.window_id!r}")
        return ", ".join(bits) or "all application windows"


def _op(mode: str) -> str:
    return "=" if mode == "exact" else "~" if mode == "contains" else "~=/"


def normalize_role(role: str | None) -> str | None:
    """Accept both AT-SPI spellings: ``push button`` / ``PUSH_BUTTON`` / ``push-button``."""
    if not role:
        return None
    text = role.strip()
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)  # CamelCase -> spaced
    text = text.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def role_matches(actual: str | None, wanted: str | None) -> bool:
    if not wanted or wanted == "*":
        return True
    return normalize_role(actual) == normalize_role(wanted)


def dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
