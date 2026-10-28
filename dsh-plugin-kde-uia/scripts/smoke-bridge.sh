#!/usr/bin/env bash
# End-to-end smoke test of the DSH plugin <-> Python client bridge, run inside
# WSL/Linux (the Windows-side Node host calls this through wsl.exe exactly like
# the plugin does).
set -u
PLUGIN="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PLUGIN" || exit 1
export PYTHONPATH="$PLUGIN/python"

echo "== vendored client import =="
python3 -c 'import kde_uia; print("import ok", kde_uia.__version__)'

echo "== ops protocol (same command shape the plugin builds) =="
python3 -m kde_uia ops env --result /tmp/kde-uia-smoke-env.json >/dev/null
echo "ops env exit=$?"
python3 -m kde_uia ops windows --args '{}' --result /tmp/kde-uia-smoke-windows.json | tail -c 400
echo
echo "ops windows exit=$?"

echo "== node available? =="
if command -v node >/dev/null 2>&1; then
  echo "node: $(node --version)"
  node scripts/smoke-bridge.mjs
  echo "bridge smoke exit=$?"
else
  echo "node: not installed in this WSL distro."
  echo "The Node side is covered by: cd dsh-plugin-kde-uia && node --test tests/   (Windows or any Node >= 20)"
fi
