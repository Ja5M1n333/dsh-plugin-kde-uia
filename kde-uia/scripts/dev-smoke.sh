#!/usr/bin/env bash
# Smoke-test the kde-uia Python package without a desktop (run inside WSL/Linux).
# Usage: scripts/dev-smoke.sh [--with-deps]
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE" || exit 1

if [ "${1:-}" = "--with-deps" ]; then
  echo "== installing AT-SPI runtime + PyGObject (apt) =="
  sudo -n apt-get install -y -q python3-gi gir1.2-atspi-2.0 at-spi2-core >/dev/null 2>&1 \
    && echo "deps: ok" || echo "deps: NOT installed (no passwordless sudo or no candidate)"
fi

export PYTHONPATH="$HERE/src"
echo "== import =="
python3 - <<'PY'
import kde_uia
from kde_uia import cli, ops, ops_cli, tree, input, screenshot, screens, window_backends, wait  # noqa: F401
print("import ok", kde_uia.__version__)
PY
status=$?
echo "== doctor (expected to report failures without a desktop) =="
python3 -m kde_uia doctor
echo "doctor exit=$?"
echo "== ops protocol =="
python3 -m kde_uia ops env --result /tmp/kde-uia-env.json >/dev/null
echo "ops env exit=$? result=$(test -f /tmp/kde-uia-env.json && echo written)"
python3 -m kde_uia ops windows --args '{}'
echo "ops windows exit=$?"
echo "== unit tests =="
python3 -m unittest discover -s tests -q
echo "unittest exit=$?"
exit "$status"
