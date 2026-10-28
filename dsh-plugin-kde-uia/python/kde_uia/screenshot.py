"""Screenshot capture backends and backend selection.

Strategies (try each in order with ``auto``):

``kwin``       KWin shadow buffer through the kde-uia KWin script.  Fast
               (<200 ms), needs no external tools, works under Wayland, but
               requires the compositor to keep a shadow buffer (most Plasma
               setups) and Plasma 6 for portal-free window crops.
``spectacle``  ``spectacle --background --fullscreen --output <png>`` (KDE).
               The most faithful "what the user sees" on Plasma Wayland.
``grim``       ``grim -g "x,y wxh"`` for Wayland compositors implementing
               ``zwlr_screencopy`` (KWin supports it).
``import``     ImageMagick ``import -window root`` on X11.
``xwd``        ``xwd -root`` + ImageMagick ``convert``/Pillow decode on X11.
``portal``     XDG Desktop Portal ``org.freedesktop.portal.Screenshot``; the
               desktop shows its own one-time permission prompt.
``drm``        Read the framebuffer node (``--drm-node /dev/fb0``); needs read
               permission, which is an explicit operator decision.

All outputs are PNG.  ``drm`` is never tried by ``auto``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import BackendUnavailableError, KdeUiaError
from .screens import ScreenMap

STRATEGIES = ("kwin", "spectacle", "grim", "import", "xwd", "portal", "drm")
_AUTO_ORDER = ("kwin", "spectacle", "grim", "import", "xwd")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@dataclass
class Capture:
    path: Path
    strategy: str
    width: int
    height: int
    scale: float = 1.0
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "path": str(self.path),
            "strategy": self.strategy,
            "width": self.width,
            "height": self.height,
            "scale": self.scale,
        }
        if self.details:
            out.update(self.details)
        return out


class ScreenshotService:
    def __init__(self, *, strategy: str = "auto", timeout: float = 25.0) -> None:
        if strategy not in ("auto", *STRATEGIES):
            raise KdeUiaError(f"unknown screenshot strategy {strategy!r}", code="USAGE",
                              hint=f"auto | {' | '.join(STRATEGIES)}")
        self.strategy = strategy
        self.timeout = timeout

    def available(self) -> dict[str, bool]:
        wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        x11 = bool(os.environ.get("DISPLAY"))
        return {
            "spectacle": shutil.which("spectacle") is not None,
            "grim": shutil.which("grim") is not None and wayland,
            "import": shutil.which("import") is not None and x11,
            "xwd": shutil.which("xwd") is not None and (x11 or bool(os.environ.get("DISPLAY"))),
            "portal": _portal_tool() is not None,
            "kwin": _kwin_reachable(),
            "drm": Path("/dev/fb0").exists(),
        }

    def capture_screen(self, out: Path, *, layout: ScreenMap | None = None) -> Capture:
        order = [self.strategy] if self.strategy != "auto" else list(_AUTO_ORDER)
        errors: list[str] = []
        for name in order:
            try:
                if name == "kwin":
                    return self._kwin(await_kwin_shadow=True)
                if name == "spectacle":
                    cap = self._spectacle(out)
                elif name == "grim":
                    cap = self._grim(out, None)
                elif name == "import":
                    cap = self._import(out)
                elif name == "xwd":
                    cap = self._xwd(out)
                elif name == "portal":
                    cap = self._portal(out)
                elif name == "drm":
                    cap = self._drm(out)
                else:  # pragma: no cover - guarded above
                    continue
                return cap
            except KdeUiaError as exc:
                errors.append(f"{name}: {exc.message}")
            except Exception as exc:  # a broken helper must not end the attempt list
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
        raise KdeUiaError(
            "every screenshot strategy failed: " + "; ".join(errors),
            code="SCREENSHOT_FAILED",
            hint=SCREENSHOT_HINT,
        )

    def capture_window(self, out: Path, *, window: dict[str, Any], layout: ScreenMap | None = None,
                       full_screen: Capture | None = None) -> Capture:
        """Capture one window: KWin direct crop, spectacle, or crop of a full capture."""
        errors: list[str] = []
        if self.strategy in ("auto", "kwin"):
            try:
                return self._kwin_window(out, window)
            except KdeUiaError as exc:
                errors.append(f"kwin: {exc.message}")
        frame = window.get("frame") or {}
        if self.strategy in ("auto", "spectacle") and shutil.which("spectacle"):
            try:
                return self._spectacle_window(out, window)
            except KdeUiaError as exc:
                errors.append(f"spectacle: {exc.message}")
        if self.strategy == "grim" or (self.strategy == "auto" and shutil.which("grim")):
            try:
                geometry = f"{int(frame.get('x', 0))},{int(frame.get('y', 0))} {int(frame.get('width', 0))}x{int(frame.get('height', 0))}"
                return self._grim(out, geometry, frame=frame)
            except KdeUiaError as exc:
                errors.append(f"grim: {exc.message}")
        try:
            base = full_screen or self.capture_screen(out.with_name(out.stem + "-screen.png"), layout=layout)
            return crop_capture(base, out, frame, layout=layout)
        except KdeUiaError as exc:
            errors.append(f"crop: {exc.message}")
        raise KdeUiaError("window capture failed: " + "; ".join(errors), code="SCREENSHOT_FAILED", hint=SCREENSHOT_HINT)

    # -------------------------------------------------------------- kwin
    def _kwin(self, *, await_kwin_shadow: bool = False) -> Capture:
        from .window_backends import KwinBackend

        backend = KwinBackend()
        active = backend.active()
        if not active:
            raise KdeUiaError("no active window to crop the screen around", code="NO_WINDOW")
        tmp = Path(tempfile.mkdtemp(prefix="kde-uia-shot-")) / "window.png"
        info = backend.capture(str(active["id"]), tmp)
        if not tmp.is_file():
            raise KdeUiaError("the KWin script reported success but no file appeared", code="SCREENSHOT_FAILED")
        return Capture(tmp, "kwin", *image_size(tmp), details={"source": "kwin-shadow-buffer", **info})

    def _kwin_window(self, out: Path, window: dict[str, Any]) -> Capture:
        from .window_backends import KwinBackend

        backend = KwinBackend()
        window_id = str(window.get("id"))
        try:
            info = backend.capture(window_id, out)
        except KdeUiaError as exc:
            if "no-shadow-buffer" in exc.message:
                # Plasma 6: bring the window forward so the compositor keeps a buffer for it.
                backend.command("activate", window_id)
                time.sleep(0.6)
                info = backend.capture(window_id, out)
            else:
                raise
        width, height = image_size(out)
        scale = float(info.get("scale", 1.0) or 1.0) if isinstance(info, dict) else 1.0
        return Capture(out, "kwin", width, height, scale=scale, details=info if isinstance(info, dict) else {})

    # ---------------------------------------------------------- spectacle
    def _spectacle(self, out: Path) -> Capture:
        args = ["spectacle", "--background", "--nonotify", "--fullscreen", "--output", str(out)]
        _tool(args, "spectacle", self.timeout)
        _require_png(out, "spectacle")
        return Capture(out, "spectacle", *image_size(out))

    def _spectacle_window(self, out: Path, window: dict[str, Any]) -> Capture:
        # --activewindow captures the currently active window; --current is the active one too.
        from .window_backends import KwinBackend

        try:
            KwinBackend().command("activate", str(window.get("id")))
        except KdeUiaError:
            pass
        args = ["spectacle", "--background", "--nonotify", "--activewindow", "--output", str(out)]
        _tool(args, "spectacle", self.timeout)
        _require_png(out, "spectacle")
        return Capture(out, "spectacle", *image_size(out), details={"windowId": window.get("id")})

    # --------------------------------------------------------------- grim
    def _grim(self, out: Path, geometry: str | None, *, frame: dict[str, Any] | None = None) -> Capture:
        args = ["grim", *(["-g", geometry] if geometry else []), str(out)]
        _tool(args, "grim", self.timeout)
        _require_png(out, "grim")
        return Capture(out, "grim", *image_size(out), details={"geometry": geometry} if geometry else {})

    # ------------------------------------------------------------- import
    def _import(self, out: Path) -> Capture:
        _tool(["import", "-window", "root", str(out)], "import", self.timeout)
        _require_png(out, "import")
        return Capture(out, "import", *image_size(out))

    # ---------------------------------------------------------------- xwd
    def _xwd(self, out: Path) -> Capture:
        xwd = shutil.which("xwd")
        if xwd is None:
            raise BackendUnavailableError("xwd is not installed (x11-apps)")
        raw = out.with_suffix(".xwd")
        proc = _tool([xwd, "-root", "-silent", "-out", str(raw)], "xwd", self.timeout)
        del proc
        convert = shutil.which("convert") or shutil.which("magick")
        if convert is None:
            raise BackendUnavailableError(
                "xwd output needs ImageMagick (convert) to become PNG",
                hint="Arch: sudo pacman -S imagemagick | Debian: sudo apt install imagemagick | Fedora: sudo dnf install ImageMagick; or use --strategy grim/spectacle/kwin.",
            )
        argv = [convert, str(raw), str(out)] if convert.endswith("convert") else [convert, str(raw), str(out)]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=self.timeout, check=False)
        if proc.returncode != 0 or not out.is_file():
            raise KdeUiaError(f"ImageMagick could not convert xwd: {proc.stderr.strip()}", code="SCREENSHOT_FAILED")
        raw.unlink(missing_ok=True)
        return Capture(out, "xwd", *image_size(out))

    # -------------------------------------------------------------- portal
    def _portal(self, out: Path) -> Capture:
        tool = _portal_tool()
        if tool is None:
            raise BackendUnavailableError("no D-Bus tool for the Screenshot portal (gdbus/busctl/dbus-send)")
        # The portal always captures the whole desktop and shows its own prompt once.
        target = out.with_name(out.stem + "-portal.png")
        if tool.endswith("gdbus"):
            argv = [tool, "call", "--session", "--dest", "org.freedesktop.portal.Desktop",
                    "--object-path", "/org/freedesktop/portal/desktop",
                    "--method", "org.freedesktop.portal.Screenshot.Screenshot",
                    "", "{}"]
        elif tool.endswith("busctl"):
            argv = [tool, "--user", "--timeout=120", "call", "org.freedesktop.portal.Desktop",
                    "/org/freedesktop/portal/desktop", "org.freedesktop.portal.Screenshot", "Screenshot", "sa{sv}", "", "0"]
        else:
            argv = [tool, "--session", "--print-reply", "--dest=org.freedesktop.portal.Desktop",
                    "/org/freedesktop/portal/desktop", "org.freedesktop.portal.Screenshot", "Screenshot",
                    "string:", "dict:string:variant:"]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=max(self.timeout, 120), check=False)
        if proc.returncode != 0:
            raise KdeUiaError(f"Screenshot portal failed: {proc.stderr.strip()}", code="SCREENSHOT_FAILED",
                              hint="The portal may be disabled or the prompt was declined.")
        match = _find_uri(proc.stdout)
        if match is None:
            raise KdeUiaError(
                "the Screenshot portal answered asynchronously (Request object); accepting the desktop "
                "prompt is required and no synchronous result came back",
                code="SCREENSHOT_FAILED",
                hint="Accept the portal prompt, or use --strategy spectacle/grim/kwin which do not prompt.",
            )
        source = Path(match)
        if not source.is_file():
            raise KdeUiaError(f"portal returned a missing file: {source}", code="SCREENSHOT_FAILED")
        shutil.move(str(source), target)
        return Capture(target, "portal", *image_size(target))

    # ---------------------------------------------------------------- drm
    def _drm(self, out: Path) -> Capture:
        node = Path(os.environ.get("KDE_UIA_DRM_NODE", "/dev/fb0"))
        if not node.exists():
            raise BackendUnavailableError(f"{node} does not exist", hint="Pass --drm-node or use another strategy.")
        try:
            data = node.read_bytes()
        except PermissionError:
            raise KdeUiaError(
                f"permission denied reading {node}",
                code="DRM_DENIED",
                hint="Reading the framebuffer is an explicit permission decision: add your user to the "
                     "'video' group (log out and back in) or run under a udev rule. Prefer --strategy grims/spectacle.",
            ) from None
        # /dev/fb0 is a raw framebuffer, not a PNG; converting is out of scope.
        del data
        raise BackendUnavailableError(
            f"{node} is a raw framebuffer without metadata; use ImageMagick on an X11 copy instead",
            hint="Use --strategy import/xwd (X11) or grim/spectacle (Wayland).",
        )


def _kwin_reachable() -> bool:
    try:
        from .window_backends import DbusCli

        DbusCli()
        return shutil.which("kwin_wayland") is not None or shutil.which("qdbus6") is not None
    except KdeUiaError:
        return False


def _portal_tool() -> str | None:
    for name in ("gdbus", "busctl", "dbus-send"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _find_uri(text: str) -> str | None:
    marker = "file://"
    index = text.find(marker)
    if index < 0:
        return None
    end = index
    while end < len(text) and text[end] not in "\"'),\n":
        end += 1
    return text[index + len(marker): end].replace("%20", " ")


def _tool(argv: list[str], name: str, timeout: float) -> subprocess.CompletedProcess[str]:
    exe = shutil.which(argv[0])
    if exe is None:
        raise BackendUnavailableError(f"{name} is not installed")
    try:
        proc = subprocess.run([exe, *argv[1:]], capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise KdeUiaError(f"{name} did not finish within {timeout:g}s (a permission prompt may be waiting)",
                          code="SCREENSHOT_FAILED", hint="Accept the prompt, then retry.") from None
    if proc.returncode != 0:
        raise KdeUiaError(f"{name} failed: {(proc.stderr or proc.stdout).strip() or proc.returncode}",
                          code="SCREENSHOT_FAILED")
    return proc


def _require_png(path: Path) -> None:
    if not path.is_file():
        raise KdeUiaError(f"no screenshot file was written to {path}", code="SCREENSHOT_FAILED")
    with path.open("rb") as handle:
        if handle.read(8) != PNG_MAGIC:
            raise KdeUiaError(f"{path} is not a PNG", code="SCREENSHOT_FAILED")


def image_size(path: Path) -> tuple[int, int]:
    """Read PNG dimensions without Pillow (IHDR is at a fixed offset)."""
    try:
        with path.open("rb") as handle:
            head = handle.read(24)
    except OSError:
        return (0, 0)
    if len(head) < 24 or head[:8] != PNG_MAGIC:
        return (0, 0)
    return (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big"))


def crop_capture(base: Capture, out: Path, frame: dict[str, Any], *, layout: ScreenMap | None = None) -> Capture:
    """Crop ``frame`` (logical) out of a full-desktop capture."""
    scale = base.scale or 1.0
    if layout is not None and layout.logical_extent()["width"] > 0:
        from .screens import infer_scale

        scale = infer_scale((base.width, base.height), layout) or scale
    x = int(round(int(frame.get("x", 0)) * scale))
    y = int(round(int(frame.get("y", 0)) * scale))
    w = max(1, int(round(int(frame.get("width", 1)) * scale)))
    h = max(1, int(round(int(frame.get("height", 1)) * scale)))
    try:
        from PIL import Image  # type: ignore
    except Exception:
        Image = None  # type: ignore
    if Image is not None:
        with Image.open(base.path) as image:
            image.crop((x, y, x + w, y + h)).save(out, "PNG")
    else:
        convert = shutil.which("convert") or shutil.which("magick")
        if convert is None:
            raise BackendUnavailableError(
                "cropping a full-screen capture needs Pillow or ImageMagick",
                hint="pip install pillow, or Arch: sudo pacman -S imagemagick | Debian: sudo apt install imagemagick; or use --strategy kwin.",
            )
        proc = subprocess.run([convert, str(base.path), "-crop", f"{w}x{h}+{x}+{y}", "+repage", str(out)],
                              capture_output=True, text=True, timeout=30, check=False)
        if proc.returncode != 0:
            raise KdeUiaError(f"crop failed: {proc.stderr.strip()}", code="SCREENSHOT_FAILED")
    _require_png(out)
    return Capture(out, base.strategy + "+crop", *image_size(out), scale=scale,
                   details={"crop": {"x": x, "y": y, "width": w, "height": h}, "from": str(base.path)})


SCREENSHOT_HINT = (
    "No screenshot backend worked. On Plasma Wayland install spectacle; on other Wayland "
    "compositors install grim. On X11 install imagemagick (import). The XDG portal backend asks "
    "the desktop for one-time permission. Selecting a capture backend never needs root; reading "
    "the framebuffer directly (DRM) is never attempted automatically."
)
