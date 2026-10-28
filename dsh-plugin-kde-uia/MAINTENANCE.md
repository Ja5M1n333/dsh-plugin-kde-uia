# Maintenance & continuity

This plugin is maintained **voluntarily by a student**, in the gaps between classes. That shapes
what you can expect, and this page says so plainly so nobody is surprised later.

## Who maintains it

- **Author:** a student (GitHub handle added at release time in `package.json` / the repository).
- **Code authors:** the code in this repository was written with a **DeepSeek Harness (DSH)
  agent**; the human maintainer directs, reviews by behaviour (does it work, does it fail safely)
  and does **not** claim deep expertise in AT-SPI, KWin scripting or DSH internals.
- **Time budget:** irregular. Expect gaps of weeks around exam periods.

## What you can expect

| Topic | Commitment |
|---|---|
| Reading issues | **Yes.** All issues are read, including ones that stay unanswered. |
| Reply speed | **No promise.** When free time exists, not within a fixed SLA. |
| Bug fixes | **Best effort, not promised.** Crash/security/data-loss bugs are prioritised. |
| Feature requests | Welcome; many will stay open for a long time. |
| Compatibility with new DSH releases | Tracked in the CHANGELOG when the maintainer gets to it. |
| Pull requests | Very welcome — that is the fastest path for a fix you need now. |

If your problem is **urgent or data-endangering**, do not wait for a reply: disable the plugin
(`disabled: true` on the `tool-kde-uia` row, or `readOnly: true`) and open an issue with the
`kde_uia_doctor` output.

## How the project stays alive anyway

Because the maintainer may disappear for a while, the project is built so that others can take
over without asking:

- **Tests run without the maintainer.** `node --test "tests/**/*.test.js"` (Node side) and
  `python3 -m unittest discover -s tests` (client) need no DSH install and no desktop. CI
  (`.github/workflows/test.yml`) runs both on every push and pull request.
- **No hidden state.** The plugin is three small Node modules with zero dependencies; the client
  is one Python package with zero pip dependencies. `docs/architecture.md` and
  `docs/protocol.md` describe every moving part, and `docs/protocol.md` lets anyone replay or
  replace the client with a script.
- **Fail loud, fail closed.** Missing backends, a stale element reference or a disabled
  accessibility bus become coded errors with a hint instead of silent wrong actions.
- **Boring, invertible changes.** Every working state is a commit; nothing special is needed to
  roll back. The release checklist below keeps that true.

## Successors: how to take over

1. Ask the maintainer to add you to the repository (or fork it; MIT licence allows that).
2. Read `docs/architecture.md` (call path), then `docs/tools.md` (surface).
3. Run the tests. If they pass in your environment, you can change code with confidence.
4. Follow the release checklist below.

## How to publish the repository (for the maintainer)

The repository root is the folder containing `kde-uia/`, `dsh-plugin-kde-uia/` and
`scripts/`. Two small scripts do the boring part without touching anything else:

```bash
# 1) create a repository from tracked files only (never drags in __pycache__)
scripts/publish/git-init.sh

# 2) create the GitHub repository once (web UI or `gh repo create`), then:
scripts/publish/git-push.sh https://github.com/<you>/<repo>.git
```

`git-init.sh` writes `.gitattributes` (LF endings, so Windows does not flip them) and a
`.gitignore`, then makes the first commit. It refuses to run if a `.git` directory already
exists. Nothing is deleted or moved; the folder simply becomes a git work tree.

If you prefer the web UI: GitHub → New repository (public, no README) → **Add file → Upload
files** → drag the *contents* of this folder → Commit. The command-line route is more reliable
for ~80 files.

## Release checklist (for every version)

1. `node scripts/sync-python.sh` — refresh the vendored client (see `dsh-plugin-kde-uia/python/`).
2. `node --test "tests/**/*.test.js"` — Node suite, all green.
3. `cd kde-uia && PYTHONPATH=src python3 -m unittest discover -s tests` — client suite, all green.
4. Optionally, on a machine with DSH: `node scripts/smoke-dsh-load.mjs <…>/resources/app.asar`.
5. Bump `version` in **both** `kde-uia/pyproject.toml` and `dsh-plugin-kde-uia/package.json`
   (they must match; `tests/packaging.test.js` enforces it).
6. Add a CHANGELOG entry; put anything compatibility-relevant under **Compatibility**.
7. `git tag vX.Y.Z && git push --tags`; attach a zip of the plugin folder to the GitHub release.

## Safety is part of maintenance

The project's first rule is **a good product does not hurt people**:

- the plugin cannot elevate privileges, cannot run an arbitrary shell command supplied by the
  model, and does not call the network;
- `readOnly: true` removes every state-changing tool;
- `dry_run` resolves a click without performing it;
- errors are explicit and named, never a silent wrong click.

Changes that weaken any of the points above are treated as security issues, not features. See
[SECURITY.md](SECURITY.md).
