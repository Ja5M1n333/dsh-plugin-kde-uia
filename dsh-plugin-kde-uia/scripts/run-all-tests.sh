#!/usr/bin/env bash
# Run every test suite, then the real-DSH load smoke test when an installation
# is reachable.
#
#   bash scripts/run-all-tests.sh                 # inside WSL / Linux
#   DSH_APP_ASAR=C:\\HARNESS\\resources\\app.asar bash scripts/run-all-tests.sh   # from Windows
#
# Sections that cannot run in this environment are reported as skipped, and
# only real failures make the script exit non-zero.
set -u
PLUGIN="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE="$(dirname "$PLUGIN")"
cd "$PLUGIN" || exit 1
fail=0

echo "== 1. vendored python client in sync with kde-uia/src/kde_uia =="
if command -v diff >/dev/null 2>&1; then
  bash "$WORKSPACE/scripts/sync-python.sh" --check || fail=1
else
  echo "skipped: diff unavailable"
fi

echo "== 2. python library tests =="
if command -v python3 >/dev/null 2>&1; then
  ( cd "$WORKSPACE/kde-uia" && PYTHONPATH=src python3 -m unittest discover -s tests -q 2>&1 | tail -3 ) || fail=1
else
  echo "skipped: python3 unavailable"
fi

echo "== 3. node tests (tool declarations, runtime, plugin, docs) =="
if command -v node >/dev/null 2>&1; then
  node --test "tests/**/*.test.js" 2>&1 | grep -E '^ℹ (tests|pass|fail)' || fail=1
else
  echo "skipped: node unavailable"
fi

echo "== 4. real DSH load smoke =="
ASAR="${DSH_APP_ASAR:-}"
if [ -z "$ASAR" ] && [ -f /mnt/c/HARNESS/resources/app.asar ]; then ASAR=/mnt/c/HARNESS/resources/app.asar; fi
if [ -n "$ASAR" ] && [ -f "$ASAR" ] && command -v node >/dev/null 2>&1; then
  node scripts/smoke-dsh-load.mjs "$ASAR" | tail -2 || fail=1
else
  echo "skipped: set DSH_APP_ASAR to a DeepSeek Harness app.asar to run it"
fi

echo "== result: $([ "$fail" -eq 0 ] && echo PASS || echo FAIL) =="
exit "$fail"
