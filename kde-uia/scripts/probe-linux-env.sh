#!/usr/bin/env bash
# Environment probe for kde-uia development (run inside WSL/Linux).
echo "== identity =="
id
echo "== sudo =="
if sudo -n true 2>/dev/null; then echo "sudo-nopasswd=yes"; else echo "sudo-nopasswd=no"; fi
echo "== python =="
python3 --version
python3 - <<'PY'
try:
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi
    print("pyatspi/Atspi GI: ok", Atspi)
except Exception as exc:  # noqa: BLE001
    print("pyatspi/Atspi GI: missing ->", type(exc).__name__, exc)
for extra in ("pyscreenshot", "PIL", "dbus"):
    try:
        __import__(extra)
        print(f"optional {extra}: ok")
    except Exception:  # noqa: BLE001
        print(f"optional {extra}: missing")
PY
echo "== typelibs =="
ls /usr/lib/x86_64-linux-gnu/girepository-1.0/ 2>/dev/null | grep -i -E 'atspi|gtk|glib' || true
echo "== apt candidates =="
apt-cache policy python3-pyatspi libatspi2.0-0 gir1.2-atspi-2.0 at-spi2-core 2>/dev/null | grep -E '^[a-z]|Candidate' || true
echo "== display =="
echo "DISPLAY=${DISPLAY:-} WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-} XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-}"
ls -la /tmp/.X11-unix 2>/dev/null || echo "no X11 socket"
echo "== tools =="
for t in xdotool wmctrl xprop kdotool qdbus6 qdbus dbus-send gdbus import xwd grim spectacle scrot; do
  command -v "$t" >/dev/null 2>&1 && echo "have $t"
done
