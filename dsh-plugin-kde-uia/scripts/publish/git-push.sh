#!/usr/bin/env bash
# Push this repository to GitHub.
#
#   bash scripts/publish/git-push.sh [repo-root] [remote-url]
#
#   repo-root   defaults to the current directory
#   remote-url  defaults to https://github.com/Ja5M1n333/dsh-plugin-kde-uia.git
#               (an SSH URL such as git@github.com:Ja5M1n333/… also works)
#
# Safe to re-run: it corrects a wrong `origin` and retries the push.
set -eu

ROOT="${1:-$(pwd)}"
URL="${2:-https://github.com/Ja5M1n333/dsh-plugin-kde-uia.git}"
ROOT="$(cd "$ROOT" && pwd)"
cd "$ROOT"

if [ ! -d .git ]; then
  echo "git-push: no git repository in $ROOT" >&2
  echo "           Run this from the repository root, e.g. after git-init:" >&2
  echo "             bash dsh-plugin-kde-uia/scripts/publish/git-push.sh \"\$(pwd)\"" >&2
  exit 1
fi

CURRENT="$(git remote get-url origin 2>/dev/null || true)"
if [ -z "$CURRENT" ]; then
  git remote add origin "$URL"
  echo "git-push: added origin -> $URL"
elif [ "$CURRENT" != "$URL" ]; then
  git remote set-url origin "$URL"
  echo "git-push: origin was $CURRENT, now $URL"
else
  echo "git-push: origin already $URL"
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" != "main" ]; then
  echo "git-push: warning — current branch is $BRANCH; GitHub's default is main" >&2
fi

echo "git-push: pushing $BRANCH from $ROOT"
echo "git-push: (the first push asks you to sign in to GitHub through the browser)"
git push -u origin "$BRANCH"
echo "git-push: done -> https://github.com/Ja5M1n333/dsh-plugin-kde-uia"
echo "git-push: optional release: git tag v0.1.0 && git push --tags"
