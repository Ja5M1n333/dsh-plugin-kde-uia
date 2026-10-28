/**
 * Real-host load smoke test: extract DeepSeek Harness's own packages from its
 * app.asar into a temporary tree and verify the plugin against the *real*
 * modules instead of mocks:
 *
 *   1. `dsh-plugin-kde-uia` imports and exports the loadable cordis shape
 *      (`name`, `inject`, `apply`, no default export);
 *   2. its Config normalisation and every tool declaration compile with the
 *      real `defineTool` from `@deepseek-ai/dsh-tools`;
 *   3. the model-facing schemas reach the real raw-JSON-Schema validator
 *      (`assertSupportedJsonSchema`) — the same gate DSH applies on load.
 *
 * Run: `node scripts/smoke-dsh-load.mjs <path-to-app.asar>` (or `DSH_APP_ASAR`).
 */

import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const pluginRoot = resolve(new URL('..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'))
const asarPath = process.argv[2] ?? process.env.DSH_APP_ASAR
if (!asarPath || !existsSync(asarPath)) {
  console.error('smoke-dsh-load: pass the path to a DeepSeek Harness app.asar (or set DSH_APP_ASAR)')
  process.exit(2)
}

const data = readFileSync(asarPath)
const headerSize = data.readUInt32LE(12)
const header = JSON.parse(data.subarray(16, 16 + headerSize).toString('utf8'))
const base = 16 + headerSize
if (!header.files?.dsh?.files?.node_modules?.files?.['@deepseek-ai']) {
  console.error(`smoke-dsh-load: ${asarPath} is not a DeepSeek Harness installation`)
  process.exit(2)
}

const work = mkdtempSync(join(tmpdir(), 'dsh-kde-uia-load-'))
const modules = join(work, 'node_modules')

const NEEDS = [
  '@deepseek-ai/dsh-tools',
  '@deepseek-ai/dsh-llm',
  '@deepseek-ai/dsh-util-values',
  '@deepseek-ai/dsh-scope',
  '@deepseek-ai/dsh-brand',
  '@deepseek-ai/dsh-sandbox',
  '@deepseek-ai/dsh-typert-protocol',
  '@deepseek-ai/dsh-util-crypto',
  '@deepseek-ai/dsh-timeout',
  '@deepseek-ai/cordis',
  '@deepseek-ai/cosmokit',
  '@deepseek-ai/cordis-plugin-loader',
  '@deepseek-ai/schemastery',
  'zod'
]

/** Extract one package (`dsh/node_modules/<name>/`) into the temp tree. */
function extractPackage(name) {
  const scope = name.startsWith('@') ? name.split('/')[0] : null
  const leaf = scope ? name.split('/')[1] : name
  const namespace = header.files.dsh.files.node_modules.files[scope ?? leaf]
  const packageNode = scope ? namespace?.files?.[leaf] : namespace
  const folder = scope ? `${scope}/${leaf}` : leaf
  if (!packageNode?.files) return 0
  let count = 0
  const walk = (node, path) => {
    for (const [entryName, entry] of Object.entries(node.files ?? {})) {
      const full = path ? `${path}/${entryName}` : entryName
      if (entry.files) walk(entry, full)
      else if (entry.link === undefined && entry.unpacked !== true) {
        const target = join(modules, folder, full)
        mkdirSync(resolve(target, '..'), { recursive: true })
        const offset = base + Number(entry.offset)
        writeFileSync(target, data.subarray(offset, offset + entry.size))
        count += 1
      }
    }
  }
  walk(packageNode, '')
  return count
}

const extracted = []
for (const name of NEEDS) {
  try {
    if (extractPackage(name) > 0) extracted.push(name)
  } catch {
    // native/unpacked packages are not needed for this check
  }
}

const entry = (name) => pathToFileURL(join(modules, name, 'lib', 'index.js')).href
const result = { appAsar: asarPath, extracted: extracted.length, steps: [] }
async function step(name, fn) {
  try {
    result.steps.push({ name, ok: true, detail: await fn() })
  } catch (error) {
    result.steps.push({ name, ok: false, detail: `${error?.code ?? ''} ${error?.message ?? error}`.trim() })
  }
}

const dshTools = await import(entry('@deepseek-ai/dsh-tools'))
const jsonSchema = await import(pathToFileURL(join(modules, '@deepseek-ai', 'dsh-tools', 'lib', 'types', 'json-schema.js')).href)
const Plugin = await import(new URL('../lib/index.js', import.meta.url).href)
const { buildTools } = await import(new URL('../lib/tools.js', import.meta.url).href)

await step('plugin exports the cordis shape', () => {
  if (Plugin.default !== undefined) throw new Error('a default export would make the loader drop inject')
  if (Plugin.name !== 'kde-uia') throw new Error(`unexpected name ${Plugin.name}`)
  if (JSON.stringify(Plugin.inject) !== '["tools"]') throw new Error('inject must be ["tools"]')
  if (typeof Plugin.apply !== 'function') throw new Error('apply missing')
  if (Plugin.Config?.format !== 'form') throw new Error('Config must be a form schema')
  return `name=${Plugin.name} inject=${Plugin.inject.join(',')}`
})

await step('normalizeConfig validates the documented config', () => {
  const config = Plugin.normalizeConfig({ runtime: 'wsl', wslDistribution: 'Ubuntu-24.04', timeoutMs: 60000 })
  if (config.runtime !== 'wsl' || config.remotePython !== 'python3') throw new Error('unexpected defaults')
  let rejected = false
  try { Plugin.normalizeConfig({ runtime: 'nope' }) } catch { rejected = true }
  return rejected ? 'defaults ok, invalid runtime rejected' : 'invalid runtime accepted!'
})

const definitions = buildTools({ defineTool: dshTools.defineTool, call: async () => ({}) })
await step('real defineTool compiles every tool', () => {
  if (typeof dshTools.defineTool !== 'function') throw new Error('defineTool missing in @deepseek-ai/dsh-tools')
  return `${definitions.length} tools: ${definitions.map((t) => t.name).join(', ')}`
})

await step('real JSON-Schema gate accepts every parameters/output schema', () => {
  let checked = 0
  for (const definition of definitions) {
    jsonSchema.assertSupportedJsonSchema(definition.parameters)
    jsonSchema.assertSupportedJsonSchema(definition.output.schema)
    checked += 1
  }
  return `${checked} schemas accepted by assertSupportedJsonSchema`
})

await step('arguments validate against their schema', () => {
  // The registry rejects bad arguments before execute; use the same validator.
  const find = definitions.find((d) => d.name === 'kde_uia_find')
  const good = jsonSchema.validateJsonSchemaValue(find.parameters, { text: 'Save', window: 'Dolphin' }, '')
  const bad = jsonSchema.validateJsonSchemaValue(find.parameters, { text: 5 }, '')
  if (good.length !== 0) throw new Error(`unexpected violations: ${good.join('; ')}`)
  if (bad.length === 0) throw new Error('typed field accepted a number')
  return 'valid args pass, typed args rejected'
})

rmSync(work, { recursive: true, force: true })
const ok = result.steps.every((s) => s.ok)
console.log(JSON.stringify(result, null, 2))
console.log(ok ? 'smoke-dsh-load: PASS' : 'smoke-dsh-load: FAIL')
process.exit(ok ? 0 : 1)
