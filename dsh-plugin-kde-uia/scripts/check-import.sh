#!/usr/bin/env bash
# Import sanity check for the vendored python client.
set -u
PLUGIN="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PLUGIN" || exit 1
PYTHONPATH="$PLUGIN/python" python3 -c 'import kde_uia; print("vendored import ok", kde_uia.__version__, kde_uia.__file__)'
PYTHONPATH="$PLUGIN/python" python3 -m kde_uia ops env --result /tmp/kde-uia-vendor-env.json >/dev/null
echo "ops env exit=$?"
