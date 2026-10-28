#!/usr/bin/env bash
# Create the initial git repository for this project.
#
# The repository root is the directory run from; it must contain kde-uia/,
# dsh-plugin-kde-uia/ and scripts/. Only those three paths are committed.
#
# That matters here: the working folder may also contain unrelated files from
# older projects, and a plain `git add -A` would sweep them into the first
# commit. An allow-list `.gitignore` (`/*` plus `!/project-dir`) makes every
# other top-level entry invisible to git.
#
# The script refuses to run when a repository already exists, and it never
# deletes, moves or rewrites anything outside `.git/` and the two ignore files.
set -eu

ROOT="${1:-$(pwd)}"
ROOT="$(cd "$ROOT" && pwd)"
cd "$ROOT"

if [ -d .git ]; then
  echo "git-init: a repository already exists in $ROOT" >&2
  echo "           To push it, use scripts/publish/git-push.sh <url>." >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git-init: git is not installed or not on PATH" >&2
  exit 1
fi

NAME="$(git config --global --get user.name || true)"
EMAIL="$(git config --global --get user.email || true)"
if [ -z "$NAME" ] || [ -z "$EMAIL" ]; then
  echo "git-init: set your identity first:" >&2
  echo "  git config --global user.name  \"your name\"" >&2
  echo "  git config --global user.email \"you@example.com\"" >&2
  exit 1
fi

for dir in kde-uia dsh-plugin-kde-uia scripts; do
  if [ ! -d "$ROOT/$dir" ]; then
    echo "git-init: expected $dir/ in $ROOT" >&2
    exit 1
  fi
done

# Line endings: keep LF in the repository so a Windows checkout does not flip every file.
cat > .gitattributes <<'EOF'
* text=auto eol=lf
*.png binary
*.ico binary
EOF

# Allow-list: only the project trees exist as far as git is concerned.
cat > .gitignore <<'EOF'
# This working folder also holds unrelated files (older projects, notes, downloads).
# Everything at the top level is ignored, then the project directories are re-included.
/*
!/scripts
!/kde-uia
!/dsh-plugin-kde-uia
!/.gitignore
!/.gitattributes

# Build artifacts, caches and local scratch data.
node_modules/
.cache/
*.tgz
package-lock.json
__pycache__/
*.pyc
*.pyo
.pytest_cache/
*.egg-info/
build/
dist/
.runtime/
kde-uia/.runtime/
*.png

# Editor / OS
.vscode/
.idea/
.DS_Store
Thumbs.db
EOF

git init -b main >/dev/null

# Stage exactly the project trees, whatever the ignore rules say elsewhere.
git add -A -- kde-uia dsh-plugin-kde-uia scripts .gitignore .gitattributes

if git diff --cached --quiet; then
  echo "git-init: nothing to commit — are the project folders empty?" >&2
  exit 1
fi

git commit -q -m "kde-uia 0.1.0: DSH plugin for Linux KDE desktop automation

Windows-UI-Automation-style tools (kde_uia_*) backed by an AT-SPI2 Python
client shipped inside the plugin, reached over WSL/SSH/local transports.

Not yet run against a live KDE session: see CHANGELOG, Verification status."

STRAY="$(git status --porcelain --untracked-files=normal | wc -l)"
echo "git-init: committed $(git rev-list --count HEAD) commit on branch main"
echo "git-init: tracked $(git ls-files | wc -l) files ($(du -sh .git 2>/dev/null | cut -f1) history)"
if [ "$STRAY" -gt 0 ] 2>/dev/null; then
  echo "git-init: warning — $STRAY path(s) are still untracked and NOT ignored:" >&2
  git status --porcelain --untracked-files=normal | head -10 >&2
fi
echo "git-init: next -> bash scripts/publish/git-push.sh https://github.com/<you>/<repo>.git"
