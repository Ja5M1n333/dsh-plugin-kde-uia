/**
 * Load the *real* `defineTool` from an installed DeepSeek Harness, so this
 * plugin's tool declarations are validated by the same schema compiler the
 * host runs — not only by a hand-written mock.
 *
 * `@deepseek-ai/dsh-tools/lib/types/schema.js` (the schema DSL and
 * `defineTool`) only needs `HarnessError` from `@deepseek-ai/dsh-llm`, which
 * itself pulls the whole harness dependency graph. Instead of installing that,
 * a ~6 line shim directory provides `@deepseek-ai/dsh-llm` (with a compatible
 * `HarnessError`) and `@deepseek-ai/dsh-util-values`, and the two real modules
 * are re-linked there. Everything that validates schemas is genuine harness
 * code; only the error base class is shimmed.
 *
 * Resolution order for the real modules:
 *   1. `DSH_TOOLS_SCHEMA` — path to `…/dsh-tools/lib/types/schema.js`.
 *   2. `DSH_HOME`-independent probe copy used by this repository
 *      (`<repo>/_probe/asar/dsh/node_modules/@deepseek-ai/dsh-tools/…`).
 *   3. `./_probe/asar/...` relative to the current directory.
 *
 * When none is present, `createCoreMockDefineTool()` is used: it enforces the
 * documented DSL rules (allowed keys, `required: true`, explicit
 * `additionalProperties`, enum shapes), which is what the plugin can get wrong.
 */

import { copyFile, mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { createCoreMockDefineTool } from './dsh-tools-mock.js'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

/** `…/node_modules/@deepseek-ai/dsh-tools/lib/types/schema.js` next to this test. */
const INSTALLED_SCHEMA = join(dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')), '..', '..', 'node_modules', '@deepseek-ai', 'dsh-tools', 'lib', 'types', 'schema.js')

/** @returns {Promise<{ defineTool: Function, source: string }|null>} */
export async function loadRealDefineTool() {
  for (const schemaPath of candidateSchemaPaths()) {
    try {
      const dir = await prepareShim(schemaPath)
      const module = await import(pathToFileURL(join(dir, 'schema.js')).href)
      if (module && typeof module.defineTool === 'function') return { defineTool: module.defineTool, source: schemaPath }
    } catch {
      // fall through to the next candidate / the mock
    }
  }
  return null
}

function candidateSchemaPaths() {
  const relative = 'node_modules/@deepseek-ai/dsh-tools/lib/types/schema.js'
  const paths = []
  if (process.env.DSH_TOOLS_SCHEMA) paths.push(process.env.DSH_TOOLS_SCHEMA)
  // The package installed beside the tests (`npm run setup:test`).
  paths.push(INSTALLED_SCHEMA)
  // The development probe copy extracted from a Harness app.asar.
  paths.push(resolve(process.cwd(), '_probe/asar/dsh', relative))
  paths.push(resolve(process.cwd(), relative))
  return [...new Set(paths)]
}

async function prepareShim(schemaPath) {
  const typesDir = dirname(schemaPath)
  const dir = await mkdtemp(join(tmpdir(), 'dsh-kde-uia-schema-'))
  const scope = join(dir, 'node_modules', '@deepseek-ai')
  await mkdir(join(scope, 'dsh-llm'), { recursive: true })
  await mkdir(join(scope, 'dsh-util-values'), { recursive: true })
  await writeFile(join(scope, 'dsh-llm', 'index.js'), ['export class HarnessError extends Error {', '  constructor(message, code) {', '    super(message)', '    this.code = code', '  }', '}', ''].join('\n'))
  await writeFile(join(scope, 'dsh-llm', 'package.json'), JSON.stringify({ name: '@deepseek-ai/dsh-llm', type: 'module', main: 'index.js' }))
  await writeFile(join(scope, 'dsh-util-values', 'index.js'), 'export const assertNever = (value) => { throw new Error(String(value)) }\nexport const isJsonValue = () => true\n')
  await writeFile(join(scope, 'dsh-util-values', 'package.json'), JSON.stringify({ name: '@deepseek-ai/dsh-util-values', type: 'module', main: 'index.js' }))
  for (const name of ['schema.js', 'json-schema.js']) {
    const text = await readFile(join(typesDir, name), 'utf8')
    await writeFile(join(dir, name), text)
  }
  return dir
}

export { createCoreMockDefineTool }

/** Load the real compiler when present, else the mock. */
export async function loadDefineTool() {
  const real = await loadRealDefineTool()
  if (real) return { defineTool: real.defineTool, kind: 'real', source: real.source }
  return { defineTool: createCoreMockDefineTool(), kind: 'mock', source: 'tests/helpers/dsh-tools.js' }
}

export { copyFile }
