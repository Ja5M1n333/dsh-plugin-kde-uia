#!/usr/bin/env bash
# Install dsh-plugin-kde-uia into the DSH Desktop profile (no restart).
#
# The Desktop manages its own profile ("desktop" is reserved by the app), so
# this script does only the two things the app cannot do for it:
#
#   1. the Python client.  The plugin resolves `<package>/python` and
#      `/opt/dsh/kde-uia`; the package only carries a copy created by
#      `scripts/sync-python.sh`, so the client from the repository's `kde-uia/`
#      directory is mirrored there, with the local Plasma 6 fix module.
#   2. the package.  pnpm's tarball import mangles a `lib/` directory and a
#      `file:` link leaves the profile without a `lib/` either, so the package
#      is copied it into the profile's node_modules as a plain directory.
#
# Afterwards select it once in DSH: Plugins -> dsh-plugin-kde-uia, then the
# agent gains the kde_uia_* tools on the next composition.
set -u

APP="/opt/DeepSeek Harness"
RT="$APP/resources/runtime/primary-runtime/dependencies"
NODE="$RT/node/bin/node"
PROFILE="${DSH_HOME:-$HOME/.dsh}/profiles/desktop"
REPO="${1:-$(cd "$(dirname "$0")" && pwd)}"
PKG="$REPO/dsh-plugin-kde-uia"
CLIENT="$REPO/kde-uia/src"

echo "== dsh-plugin-kde-uia install =="
echo "repository: $REPO"
echo "package:    $PKG"
echo "profile:    $PROFILE"

[[ -f "$PKG/lib/index.js" ]] || { echo "not a plugin package: $PKG" >&2; exit 1; }

# ---- 1. Python client ------------------------------------------------------
mkdir -p /opt/dsh
if [[ -d /opt/dsh/kde-uia && ! -w /opt/dsh/kde-uia ]]; then
  sudo -n chown -R "$(id -u):$(id -g)" /opt/dsh/kde-uia 2>/dev/null || true
fi
rm -rf /opt/dsh/kde-uia/kde_uia /opt/dsh/kde-uia/__pycache__ 2>/dev/null
if [[ -f "$CLIENT/kde_uia/ops.py" ]]; then
  mkdir -p /opt/dsh/kde-uia
  cp -r "$CLIENT/kde_uia" /opt/dsh/kde-uia/
  echo "client: $CLIENT/kde_uia -> /opt/dsh/kde-uia"
else
  echo "WARNING: $CLIENT/kde_uia not found; /opt/dsh/kde-uia left as it was" >&2
fi
if [[ -f "$REPO/kde_uia_patches.py" && -d /opt/dsh/kde-uia/kde_uia ]]; then
  cp "$REPO/kde_uia_patches.py" /opt/dsh/kde-uia/kde_uia/patches.py
  if ! grep -q install_patches /opt/dsh/kde-uia/kde_uia/__init__.py; then
    "$NODE" -e '
      const fs = require("fs")
      const file = "/opt/dsh/kde-uia/kde_uia/__init__.py"
      const src = fs.readFileSync(file, "utf8")
      const anchor = src.indexOf("__all__ = [")
      if (anchor < 0) throw new Error("cannot find __all__ in " + file)
      const hook = "# Local Plasma 6 compatibility fixes (see patches.py).\ntry:\n    from .patches import install_patches as _install_patches\nexcept Exception:\n    _install_patches = None\nif _install_patches is not None:\n    _install_patches()\n\n"
      fs.writeFileSync(file, src.slice(0, anchor) + hook + src.slice(anchor))
    '
    echo "patches: hooked into the client's __init__.py"
  fi
fi

# ---- 2. Package into the profile -------------------------------------------
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$PROFILE/node_modules"
[[ -f "$PROFILE/package.json" ]] && cp "$PROFILE/package.json" "$PROFILE/package.json.bak-$STAMP"
rm -rf "$PROFILE/node_modules/dsh-plugin-kde-uia"
cp -r "$PKG" "$PROFILE/node_modules/dsh-plugin-kde-uia"
rm -rf "$PROFILE/node_modules/dsh-plugin-kde-uia/tests" "$PROFILE/node_modules/dsh-plugin-kde-uia/docs" \
       "$PROFILE/node_modules/dsh-plugin-kde-uia/.github" "$PROFILE/node_modules/dsh-plugin-kde-uia/scripts"
echo "package:    copied into $PROFILE/node_modules/dsh-plugin-kde-uia"

# The manifest needs the dependency recorded for pnpm; if pnpm removes the
# plain copy on its next run, re-run this script.
"$NODE" -e '
  const fs = require("fs")
  const file = process.argv[1]
  const manifest = JSON.parse(fs.readFileSync(file, "utf8"))
  manifest.dependencies ??= {}
  manifest.dependencies["dsh-plugin-kde-uia"] = "file:./node_modules/dsh-plugin-kde-uia"
  fs.writeFileSync(file, JSON.stringify(manifest, null, 2) + "\n")
' "$PROFILE/package.json"

# ---- 3. Verify -------------------------------------------------------------
cd "$PROFILE"
"$NODE" --input-type=module -e '
  const m = await import("dsh-plugin-kde-uia")
  console.log("import ok:", m.name, "| apply:", typeof m.apply, "| inject:", m.inject)
' 2>&1 || echo "WARNING: plugin import check failed" >&2
PYTHONPATH=/opt/dsh/kde-uia timeout 120 python3 -m kde_uia doctor 2>&1 | head -8

cat <<'EOF'
== done ==
Next: in DSH, open 插件 (Plugins) and switch dsh-plugin-kde-uia on.
The kde_uia_* tools then appear for the agent; kde_uia_doctor reports what works.
EOF
