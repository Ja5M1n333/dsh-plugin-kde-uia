#!/usr/bin/env bash
# Regenerate the vendored Python client inside the DSH plugin from the
# authoritative library source (kde-uia/src/kde_uia).
#
# The plugin ships `python/kde_uia/` so one `cp -r` installs it into the Linux
# environment; this script, `npm run vendor` and the CI check keep that copy in
# sync with the library. layout:
#   kde-uia/src/kde_uia/**.py     -> dsh-plugin-kde-uia/python/kde_uia/**.py
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/kde-uia/src/kde_uia"
DEST="$ROOT/dsh-plugin-kde-uia/python/kde_uia"

if [ "${1:-}" = "--check" ]; then
  if diff -r --exclude=__pycache__ "$SRC" "$DEST" >/dev/null 2>&1; then
    echo "vendor: in sync with kde-uia/src/kde_uia"
    exit 0
  fi
  echo "vendor: OUT OF SYNC with kde-uia/src/kde_uia (run scripts/sync-python.sh)"
  diff -r --exclude=__pycache__ "$SRC" "$DEST" | head -40 || true
  exit 1
fi

rm -rf "$DEST"
mkdir -p "$DEST"
cp -r "$SRC/." "$DEST/"
find "$DEST" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
echo "vendor: copied $(find "$DEST" -name '*.py' | wc -l) modules to dsh-plugin-kde-uia/python/kde_uia"
echo "        (versions: library $(grep -m1 '__version__' "$SRC/__init__.py") )"
