/**
 * Documentation contract tests: the README must keep answering the questions a
 * cautious installer asks first (scope, install, DSH compatibility, security),
 * and the shipped python client must stay in sync with the library source.
 */

import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'
import { test } from 'node:test'

const root = new URL('..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')
const repoRoot = join(root, '..')

async function read(name) {
  return readFile(join(root, name), 'utf8')
}

test('README (en) documents scope, install, compatibility, security and limits', async () => {
  const text = await read('README.md')
  for (const heading of ['## What it does', '## Requirements', '## Install', '## DSH compatibility', '## Security', '## Known limitations', '## Troubleshooting']) {
    assert.ok(text.includes(heading), `README.md is missing "${heading}"`)
  }
  assert.match(text, /0\.2\.0-rc\.2/, 'README must state the tested DSH version')
  assert.match(text, /python3-gi gir1\.2-atspi-2\.0 at-spi2-core/, 'README must name the AT-SPI packages')
})

test('README.zh mirrors the same contract in Chinese', async () => {
  const text = await read('README.zh.md')
  for (const heading of ['## 功能边界', '## 环境要求', '## 安装', '## DSH 版本兼容性', '## 安全声明', '## 已知限制', '## 故障排查']) {
    assert.ok(text.includes(heading), `README.zh.md is missing "${heading}"`)
  }
  assert.match(text, /0\.2\.0-rc\.2/)
})

test('SECURITY documents the trust boundary, permissions and data handling', async () => {
  const text = await read('SECURITY.md')
  for (const phrase of ['threat model', 'Permissions', 'Data handling', 'Reporting a vulnerability', 'No network']) {
    assert.match(text, new RegExp(phrase, 'i'), `SECURITY.md must cover ${phrase}`)
  }
})

test('CHANGELOG has an entry for the current version', async () => {
  const manifest = JSON.parse(await read('package.json'))
  const changelog = await read('CHANGELOG.md')
  assert.ok(changelog.includes(`## [${manifest.version}]`), `CHANGELOG.md has no ${manifest.version} entry`)
  assert.match(changelog, /Compatibility/, 'CHANGELOG must track compatibility changes')
})

test('cordis.patch.yml documents every config key it uses', async () => {
  const patch = await read('cordis.patch.yml')
  const manifest = await read('lib/index.js')
  for (const key of ['runtime', 'wslDistribution', 'sshHost', 'remotePath', 'remotePython', 'timeoutMs', 'doctorOnLoad']) {
    assert.match(patch, new RegExp(`${key}:`), `patch is missing ${key}`)
    assert.match(manifest, new RegExp(`${key}:`), `Config is missing ${key}`)
  }
})

test('the vendored python client matches kde-uia/src/kde_uia', async () => {
  // Pure file comparison, so it runs on every host.
  const source = join(repoRoot, 'kde-uia', 'src', 'kde_uia')
  const vendored = join(root, 'python', 'kde_uia')
  const files = (await readdir(source)).filter((name) => name.endsWith('.py') || name === 'py.typed')
  assert.ok(files.length >= 18, `expected the full client, found ${files.length} files`)
  for (const name of files) {
    const a = createHash('sha256').update(await readFile(join(source, name))).digest('hex')
    const b = createHash('sha256').update(await readFile(join(vendored, name))).digest('hex')
    assert.equal(a, b, `python/kde_uia/${name} is out of date (run scripts/sync-python.sh)`)
  }
})

test('LICENSE is present and MIT', async () => {
  const text = await read('LICENSE')
  assert.match(text, /MIT License/)
  assert.match(text, /Permission is hereby granted, free of charge/)
})

test('docs/ lists every tool with its effect', async () => {
  const text = await read('docs/tools.md')
  for (const tool of ['kde_uia_doctor', 'kde_uia_windows', 'kde_uia_tree', 'kde_uia_find', 'kde_uia_info', 'kde_uia_click', 'kde_uia_keys', 'kde_uia_type', 'kde_uia_set_value', 'kde_uia_scroll', 'kde_uia_wait_for', 'kde_uia_screenshot', 'kde_uia_activate']) {
    assert.ok(text.includes(tool), `docs/tools.md is missing ${tool}`)
  }
})

export { execFileSync }
