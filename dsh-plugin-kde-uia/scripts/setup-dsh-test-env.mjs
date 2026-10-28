/**
 * Resolve the published packages the plugin's tests need (`@deepseek-ai/dsh-tools`,
 * `@deepseek-ai/schemastery`, `@deepseek-ai/cordis`) from the running DeepSeek
 * Harness installation, without touching the installation.
 *
 * It reads `resources/app.asar` directly (a small header parser, no dependency),
 * extracts the packages plus their transitive bare imports into `.cache/asar/`,
 * links them into `node_modules/`, and then the tests `import '@deepseek-ai/dsh-tools'`
 * exactly as they would on a machine where the plugin was installed beside DSH.
 *
 * Usage: `node scripts/setup-dsh-test-env.mjs`  (or `DSH_APP_ASAR=<path> node …`)
 * Safe to re-run; it rebuilds `.cache/asar`.
 */

import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

const here = resolve(new URL('..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'))
const cacheRoot = join(here, '.cache', 'asar')
const SEEDS = ['@deepseek-ai/dsh-tools', '@deepseek-ai/schemastery', '@deepseek-ai/cordis']

function safeReaddir(dir) {
  try {
    return readdirSync(dir)
  } catch {
    return []
  }
}

function readHeader(asarPath) {
  const data = readFileSync(asarPath)
  const headerSize = data.readUInt32LE(12)
  return { data, base: 16 + headerSize, header: JSON.parse(data.subarray(16, 16 + headerSize).toString('utf8')) }
}

/** True when the archive carries DSH's package tree (`dsh/node_modules/@deepseek-ai`). */
export function isHarnessAsar(asarPath) {
  try {
    return Boolean(readHeader(asarPath).header.files?.dsh?.files?.node_modules?.files?.['@deepseek-ai'])
  } catch {
    return false
  }
}

/** Locate the DSH installation's app.asar. */
export function locateAsar() {
  if (process.env.DSH_APP_ASAR) return process.env.DSH_APP_ASAR
  const roots = []
  if (process.env.LOCALAPPDATA) roots.push(join(process.env.LOCALAPPDATA, 'Programs'))
  if (process.env.ProgramFiles) roots.push(process.env.ProgramFiles)
  for (const root of roots) {
    for (const entry of safeReaddir(root)) {
      const candidate = join(root, entry, 'resources', 'app.asar')
      if (existsSync(candidate) && isHarnessAsar(candidate)) return candidate
    }
  }
  return null
}

/** Extract every packed file under `prefix` into `outDir`; returns the file count. */
function extractPrefix(archive, prefix, outDir) {
  let count = 0
  const walk = (node, path) => {
    for (const [name, entry] of Object.entries(node.files ?? {})) {
      const full = path ? `${path}/${name}` : name
      if (entry.files) walk(entry, full)
      else if (full.startsWith(prefix) && entry.link === undefined && entry.unpacked !== true) {
        const target = join(outDir, full.slice(prefix.length))
        mkdirSync(resolve(target, '..'), { recursive: true })
        const offset = archive.base + Number(entry.offset)
        writeFileSync(target, archive.data.subarray(offset, offset + entry.size))
        count += 1
      }
    }
  }
  walk(archive.header, '')
  return count
}

/** Bare package names a directory tree imports. */
function bareImports(dir) {
  const found = new Set()
  const visit = (current) => {
    let entries
    try {
      entries = readdirSync(current, { withFileTypes: true })
    } catch {
      return
    }
    for (const entry of entries) {
      const full = join(current, entry.name)
      if (entry.isDirectory()) {
        if (entry.name !== 'node_modules') visit(full)
        continue
      }
      if (!/\.(?:js|mjs|cjs)$/.test(entry.name)) continue
      const text = readFileSync(full, 'utf8')
      for (const match of text.matchAll(/(?:from|import|require)\s*\(?\s*['"]([^'"]+)['"]/g)) {
        const spec = match[1]
        if (spec.startsWith('.') || spec.startsWith('node:') || spec.startsWith('/') || spec.startsWith('#')) continue
        // Local identifiers and whitespace-separated specifiers are not package names.
        if (!/^(?:@[a-z0-9._~-]+\/)?[a-z0-9._~-]+(?:\/[a-z0-9._~-]+)*$/i.test(spec)) continue
        const parts = spec.split('/')
        found.add(spec.startsWith('@') ? `${parts[0]}/${parts[1]}` : parts[0])
      }
    }
  }
  visit(dir)
  return [...found]
}

function linkInto(target, source) {
  rmSync(target, { recursive: true, force: true })
  try {
    execFileSync('cmd', ['/c', 'mklink', '/J', target, source], { stdio: 'ignore' })
  } catch {
    mkdirSync(target, { recursive: true })
    execFileSync('robocopy', [source, target, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NC', '/NS'], { stdio: 'ignore' })
  }
}

const asar = locateAsar()
if (!asar) {
  console.error('setup: no DeepSeek Harness app.asar found.')
  console.error('       Set DSH_APP_ASAR to its path (…\\resources\\app.asar), e.g. C:\\HARNESS\\resources\\app.asar.')
  console.error('       Without it, the Node tests use the strict schema mock and still pass.')
  process.exit(0)
}
console.log(`setup: using ${asar}`)
const archive = readHeader(asar)
rmSync(cacheRoot, { recursive: true, force: true })
const extracted = new Map()
const queue = [...SEEDS]
const missing = []
while (queue.length) {
  const name = queue.shift()
  if (extracted.has(name) || missing.includes(name)) continue
  const out = join(cacheRoot, name)
  const count = extractPrefix(archive, `dsh/node_modules/${name}/`, out)
  if (!count) {
    missing.push(name)
    console.log(`setup: ${name} not present in this installation (skipped)`)
    continue
  }
  extracted.set(name, out)
  console.log(`setup: ${name} (${count} files)`)
  for (const dependency of bareImports(out)) queue.push(dependency)
}
for (const [name, source] of extracted) {
  const target = join(here, 'node_modules', name)
  mkdirSync(resolve(target, '..'), { recursive: true })
  linkInto(target, source)
}
if (missing.length) console.log(`setup: unresolved dependencies: ${missing.join(', ')} (Node builtins are expected here)`)
console.log('setup: done')
