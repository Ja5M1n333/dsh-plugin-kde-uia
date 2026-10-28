#!/usr/bin/env bash
# Verifies the concrete details kde-uia depends on (run inside the target Linux desktop).
# Write-only script: prints findings, changes nothing.
set +e
echo "### kde-uia contract probe ###"
echo "os: $(grep PRETTY_NAME /etc/os-release | cut -d= -f2-)"
echo "session: XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-} DESKTOP=${XDG_CURRENT_DESKTOP:-} KDE=${KDE_SESSION_VERSION:-}"
echo "display: DISPLAY=${DISPLAY:-} WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-}"

echo "--- python ---"
python3 --version
python3 - <<'PY'
import importlib
for extra in ("gi", "dbus", "dbus_next", "PIL"):
    try:
        importlib.import_module(extra)
        print(f"{extra}: ok")
    except Exception as exc:  # noqa: BLE001
        print(f"{extra}: missing ({type(exc).__name__})")
PY

echo "--- tools ---"
for t in kwin_wayland kwin_x11 kdotool xdotool wmctrl xprop spectacle kwrite import xwd gdbus busctl dbus-send qdbus6 qdbus; do
  command -v "$t" >/dev/null 2>&1 && echo "have $t"
done

echo "--- AT-SPI bus ---"
if command -v busctl >/dev/null 2>&1; then
  busctl --user call org.a11y.Bus /org/a11y/bus org.a11y.Bus GetAddress 2>&1 | head -2
elif command -v gdbus >/dev/null 2>&1; then
  gdbus call --session --dest org.a11y.Bus --object-path /org/a11y/bus --method org.a11y.Bus.GetAddress 2>&1 | head -2
fi

echo "--- kdotool search/getwindowgeometry sample ---"
if command -v kdotool >/dev/null 2>&1; then
  id=$(kdotool search --name . 2>/dev/null | head -1)
  echo "first window id: ${id:-none}"
  [ -n "${id:-}" ] && kdotool getwindowgeometry --shell "$id" 2>&1 | head -6
fi

echo "--- spectacle help (flags) ---"
if command -v spectacle >/dev/null 2>&1; then
  spectacle --help 2>&1 | grep -E '\-\-(background|fullscreen|current|activewindow|output|nonotify|outfile|region)' | head -12
fi

echo "### done ###"
