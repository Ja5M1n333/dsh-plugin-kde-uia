"""Element references: the UIA ``RuntimeId`` analogue.

A Windows UIA element is addressed by a *runtime id* that is only valid inside
the process that obtained it.  kde-uia does the same with an opaque string:

    uia:1:<app-name>:<path>[:<instance>]

* ``app-name``  - the AT-SPI application name (e.g. ``dolphin``, ``kwrite``).
* ``path``      - ``/``-separated child indexes from the application root to
                  the element, e.g. ``1/0/3``.
* ``instance``  - D-Bus instance suffix (``:1.42`` -> ``1.42``) when the
                  application has more than one registered root.

The reference is deliberately *stateless*: resolving it opens the application
root fresh and walks the path, so it survives between CLI invocations and
across DSH tool calls.  It is not a hash - it is a path, which means it is as
fresh as the tree it was taken from.  When the application changed in
between, resolution fails with ``INVALID_REF`` or silently resolves to a
different element; callers that need stability should match by role/name
instead (``kde-uia find``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import InvalidRefError

REF_PREFIX = "uia:1:"
_REF_RE = re.compile(r"^uia:1:(?P<app>[^:/][^:]*):(?P<path>(?:/|\d+(?:/\d+)*))(?::(?P<inst>[\d.]+))?$")


@dataclass(frozen=True)
class ElementRef:
    app: str
    path: tuple[int, ...]
    instance: str | None = None

    def __str__(self) -> str:
        body = self.app + ":" + self._path_text()
        if self.instance:
            body += ":" + self.instance
        return REF_PREFIX + body

    def _path_text(self) -> str:
        return "/".join(str(i) for i in self.path) if self.path else "/"

    def to_dict(self) -> dict[str, object]:
        return {"ref": str(self), "app": self.app, "path": list(self.path), "instance": self.instance}


def make_ref(app: str, path: list[int] | tuple[int, ...], instance: str | None = None) -> str:
    """Build the canonical string form of a reference."""
    app = app.strip()
    if not app or ":" in app:
        raise InvalidRefError(f"cannot build a reference for application name {app!r}", hint="Application names must be non-empty and contain no ':'.")
    return str(ElementRef(app=app, path=tuple(int(i) for i in path), instance=instance))


def parse_ref(ref: str) -> ElementRef:
    """Parse ``uia:1:...`` and raise :class:`InvalidRefError` for anything else."""
    match = _REF_RE.match(ref.strip()) if isinstance(ref, str) else None
    if match is None:
        raise InvalidRefError(
            f"not a kde-uia element reference: {ref!r}",
            hint="Take refs verbatim from `kde-uia tree`, `find`, `focused` or `windows` (they look like uia:1:kwrite:1/2/0).",
        )
    raw_path = match.group("path")
    path = () if raw_path.strip("/") == "" else tuple(int(part) for part in raw_path.strip("/").split("/"))
    return ElementRef(app=match.group("app"), path=path, instance=match.group("inst") or None)
