"""Coordinate mapping between the three stacks that tell us about pixels.

* **AT-SPI / KWin** report geometry in *logical* compositor pixels
  (frameGeometry / clientGeometry), which is what input devices use.
* **Screenshots** produced by X11 tools (xwd, ImageMagick ``import``) or by
  KWin's shadow buffer are in *device* pixels, i.e. scaled by the output's
  ``devicePixelRatio`` (WSLg under Windows scaling is the common trap: the
  frame is 800x600 logical but the capture is 1200x900).
* **Pointer input** must receive logical coordinates.

A :class:`ScreenMap` carries that scale so ``element centre -> click`` and
``screenshot pixel -> screen point`` (and back) round-trip correctly.  Pure
arithmetic, no GUI dependency, fully unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

KNOWN_SCALES = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0)


@dataclass
class Screen:
    name: str
    x: int
    y: int
    width: int
    height: int
    scale: float = 1.0

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "x": self.x, "y": self.y, "width": self.width,
                "height": self.height, "scale": self.scale}


@dataclass
class ScreenMap:
    """Layout of the desktop in logical pixels plus the capture scale factor.

    The capture is the full desktop at ``scale`` times the logical size, with
    the same origin; a logical point ``(x, y)`` therefore lands on capture
    pixel ``(x * scale, y * scale)``.  Per-screen scales are preserved for
    mixed-DPI layouts: point mapping uses the screen that contains the point.
    """

    screens: list[Screen] = field(default_factory=list)
    scale: float = 1.0

    def screen_for(self, x: float, y: float) -> Screen | None:
        for screen in self.screens:
            if screen.contains(x, y):
                return screen
        return None

    def logical_extent(self) -> dict[str, int]:
        """Bounding box of all screens in logical coordinates."""
        if not self.screens:
            return {"x": 0, "y": 0, "width": 0, "height": 0}
        left = min(s.x for s in self.screens)
        top = min(s.y for s in self.screens)
        right = max(s.x + s.width for s in self.screens)
        bottom = max(s.y + s.height for s in self.screens)
        return {"x": left, "y": top, "width": right - left, "height": bottom - top}

    def logical_to_capture(self, x: float, y: float) -> tuple[int, int]:
        """Logical desktop point -> pixel in the full-desktop capture."""
        screen = self.screen_for(x, y)
        factor = screen.scale if screen is not None else self.scale
        return (int(round(x * factor)), int(round(y * factor)))

    def capture_to_logical(self, px: float, py: float) -> tuple[int, int]:
        """Pixel in the full-desktop capture -> logical desktop point."""
        factor = self.scale
        for screen in self.screens:
            if screen.contains(px / screen.scale, py / screen.scale):
                factor = screen.scale
                break
        return (int(round(px / factor)), int(round(py / factor)))

    def element_center(self, extents: dict[str, Any], *, region: str = "client") -> tuple[int, int]:
        """Centre of an element rectangle (logical) -> click point."""
        x = int(extents.get("x", 0))
        y = int(extents.get("y", 0))
        w = max(1, int(extents.get("width", 0)))
        h = max(1, int(extents.get("height", 0)))
        if region == "client":
            # Bias inside the element so titlebar/decoration touches do not steal the click.
            return (x + max(1, w // 2), y + max(1, h // 2))
        return (x + w // 2, y + h // 2)

    def within(self, x: float, y: float) -> bool:
        extent = self.logical_extent()
        if not self.screens:
            return True
        return extent["x"] <= x < extent["x"] + extent["width"] and extent["y"] <= y < extent["y"] + extent["height"]

    def to_dict(self) -> dict[str, Any]:
        return {"screens": [s.to_dict() for s in self.screens],
                "scale": self.scale,
                "extent": self.logical_extent()}


def map_from_outputs(outputs: list[dict[str, Any]]) -> ScreenMap:
    """Build from KWin ``outputs`` rows (logical geometry + devicePixelRatio)."""
    screens = []
    for out in outputs:
        try:
            screens.append(Screen(
                name=str(out.get("name", "")),
                x=int(out.get("x", 0)),
                y=int(out.get("y", 0)),
                width=max(1, int(out.get("width", 0))),
                height=max(1, int(out.get("height", 0))),
                scale=float(out.get("scale", 1.0)) or 1.0,
            ))
        except (TypeError, ValueError):
            continue
    scale = screens[0].scale if screens else 1.0
    return ScreenMap(screens=screens, scale=scale)


def map_single(width: int, height: int, scale: float = 1.0) -> ScreenMap:
    """Single screen of logical size ``width``x``height`` (X11 fallback)."""
    return ScreenMap(screens=[Screen(name="screen", x=0, y=0, width=width, height=height, scale=scale)], scale=scale)


def infer_scale(capture_size: tuple[int, int], layout: ScreenMap) -> float:
    """Infer the device-pixel scale from a capture size against the logical layout."""
    extent = layout.logical_extent()
    if extent["width"] <= 0 or capture_size[0] <= 0:
        return layout.scale
    ratio = capture_size[0] / extent["width"]
    for known in KNOWN_SCALES:
        if abs(ratio - known) < 0.02:
            return known
    return round(ratio, 2) if ratio > 0 else layout.scale
