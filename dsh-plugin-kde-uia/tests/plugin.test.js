/**
 * Plugin-level tests: the exported cordis shape, configuration validation,
 * tool registration through a fake `ctx.tools`, readOnly mode, the
 * doctor-on-load probe, and dispose. The Python client is simulated by a
 * fake runner so these run on any host.
 */

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'

import * as plugin from '../lib/index.js'
import * as toolsModule from '../lib/tools.js'
import { loadDefineTool } from './helpers/dsh-tools.js'

const PLUGIN_ROOT = new URL('..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')

/** A ctx fake whose tool registry records definitions and unregistrations. */
function fakeContext({ shell } = {}) {
  const registered = new Map()
  const disposed = []
  const logs = { info: [], warn: [], error: [] }
  const effects = []
  const ctx = {
    // Like cordis: apply() registers teardown through the plugin context.
    effect: (factory) => {
      effects.push(factory)
      return () => {}
    },
    logger: {
      info: (m) => logs.info.push(String(m)),
      warn: (m) => logs.warn.push(String(m)),
      error: (m) => logs.error.push(String(m))
    },
    get: (name) => (name === 'tools' ? ctx.tools : name === 'shell' ? shell : name === 'shellEnv' ? undefined : undefined),
    tools: {
      register(tool) {
        if (registered.has(tool.name)) throw new Error(`duplicate tool ${tool.name}`)
        registered.set(tool.name, tool)
        return () => {
          registered.delete(tool.name)
          disposed.push(tool.name)
        }
      }
    }
  }
  return { ctx, registered, disposed, logs, effects }
}

/** Run the effect disposers a cordis fiber would call on unload. */
function disposeEffects(effects) {
  for (const factory of effects.splice(0)) {
    const disposer = factory()
    if (typeof disposer === 'function') disposer()
  }
}

const envDocument = JSON.stringify({ ok: true, result: { platform: 'linux', sessionType: 'wayland' } })
const doctorDocument = JSON.stringify({ ok: true, result: { ok: true, checks: [{ check: 'display', status: 'ok', detail: 'kde' }] } })

/** Shell fake answering the discovery env call and doctor. */
function fakeShell(calls = []) {
  return async (request) => {
    calls.push(request)
    const command = request.argv.join(' ')
    const text = command.includes('ops doctor') ? doctorDocument : envDocument
    return { result: async () => ({ stdout: { text }, stderr: { text: '' }, aborted: false }) }
  }
}

/**
 * The plugin only imports `@deepseek-ai/dsh-tools`; for tests we pre-install a
 * module resolver hook is overkill, so inject via the documented stub: the
 * tests call apply() with the real defineTool provided through a module-level
 * cache in index.js (see resolveDefineTool). If the package is unavailable the
 * registration test is skipped rather than silently passing.
 */
const loader = await loadDefineTool()

test('exports the cordis function-plugin shape (no default export)', async () => {
  assert.equal(plugin.name, 'kde-uia')
  assert.deepEqual(plugin.inject, ['tools'])
  assert.equal(typeof plugin.apply, 'function')
  assert.equal(plugin.default, undefined, 'a default export makes loaders drop inject')
  // The loader validates through cordis' Standard Schema bridge; a plain
  // JSON-Schema object (what 0.1.0 shipped) makes it throw
  // `Cannot read properties of undefined (reading 'validate')` and the entry
  // never activates.
  assert.equal(typeof plugin.Config['~standard']?.validate, 'function')
  const resolved = plugin.Config['~standard'].validate({ runtime: 'local' })
  assert.equal(resolved.issues, undefined)
  assert.equal(resolved.value.runtime, 'local')
})

test('apply() returns nothing and registers teardown through ctx.effect', () => {
  // Cordis reads apply()'s return value as a setup promise; the 0.1.0 handle
  // object broke activation, so apply() must stay void and hand cleanup to the
  // lifecycle hook instead.
  const { ctx, effects } = fakeContext({})
  const returned = plugin.apply(ctx, { runtime: 'wsl', doctorOnLoad: false })
  assert.equal(returned, undefined)
  assert.equal(effects.length, 1, 'apply must register exactly one effect')
  let disposed = false
  const disposer = effects[0]()
  if (typeof disposer === 'function') {
    disposer()
    disposed = true
  }
  assert.equal(disposed, true, 'the effect must return a disposer')
})

test('package.json declares a valid dsh bundle and DSH peer versions', async () => {
  const manifest = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'))
  assert.equal(manifest.name, 'dsh-plugin-kde-uia')
  assert.equal(manifest.type, 'module')
  assert.equal(manifest.main, 'lib/index.js')
  assert.deepEqual(manifest.dsh.bundle, { patch: './cordis.patch.yml' })
  assert.equal(manifest.peerDependencies['@deepseek-ai/dsh'], '0.2.0-rc.2')
  assert.ok(manifest.files.includes('python/**/*.py'), 'the python client must ship')
  assert.ok(manifest.files.includes('cordis.patch.yml'))
})

test('cordis.patch.yml is a loadable insert list with one row', async () => {
  const yaml = await readFile(new URL('../cordis.patch.yml', import.meta.url), 'utf8')
  assert.match(yaml, /^- insert:\n/m)
  assert.match(yaml, /id: tool-kde-uia/)
  assert.match(yaml, /name: dsh-plugin-kde-uia/)
  assert.match(yaml, /runtime: auto/)
  assert.match(yaml, /remotePython: 'python3'/)
  // no YAML tabs
  assert.ok(!yaml.includes('\t'))
})

test('normalizeConfig rejects bad values and fills defaults', () => {
  const config = plugin.normalizeConfig({ runtime: 'wsl', timeoutMs: 5000 })
  assert.equal(config.runtime, 'wsl')
  assert.equal(config.remotePython, 'python3')
  assert.equal(config.readOnly, false)
  assert.throws(() => plugin.normalizeConfig({ runtime: 'docker' }), /must be one of/)
  assert.throws(() => plugin.normalizeConfig({ timeoutMs: 10 }), />= 1000/)
  assert.throws(() => plugin.normalizeConfig({ sshOptions: 'x' }), /array/)
})

test('opFor maps every tool to its client op', () => {
  assert.equal(plugin.opFor('kde_uia_keys'), 'press')
  assert.equal(plugin.opFor('kde_uia_set_value'), 'set')
  assert.equal(plugin.opFor('kde_uia_wait_for'), 'wait')
  assert.equal(plugin.opFor('kde_uia_activate'), 'window-op')
  assert.throws(() => plugin.opFor('kde_uia_nope'), /unknown/)
  assert.deepEqual(plugin.planOperation('kde_uia_activate', { action: 'close', window: 'x' }), { op: 'window', args: { op: 'close', window: 'x', app: undefined, id: undefined, x: undefined, y: undefined, width: undefined, height: undefined } })
})

test('apply() registers the tools with the fake registry', async (t) => {
  if (loader.kind !== 'real') {
    t.skip('requires the harness dsh-tools package to validate defineTool (set DSH_TOOLS_SCHEMA)')
    return
  }
  const realDefineTool = loader.defineTool
  // The plugin resolves dsh-tools through a dynamic import; provide it here.
  const { setDefineToolForTests } = plugin
  setDefineToolForTests(realDefineTool)
  const shell = fakeShell()
  const { ctx, registered, logs, effects } = fakeContext({ shell })
  plugin.apply(ctx, { runtime: 'wsl', doctorOnLoad: false })
  await waitFor(() => registered.size > 0)
  assert.equal(registered.size, 13)
  assert.ok(registered.has('kde_uia_doctor'))
  assert.ok(registered.has('kde_uia_click'))
  assert.match(logs.info.join('\n'), /registered 13 tools/)
  disposeEffects(effects)
  assert.equal(registered.size, 0)
})

test('apply() in readOnly mode registers only read tools', async (t) => {
  if (loader.kind !== 'real') {
    t.skip('needs the harness schema compiler')
    return
  }
  plugin.setDefineToolForTests(loader.defineTool)
  const { ctx, registered } = fakeContext({ shell: fakeShell() })
  plugin.apply(ctx, { runtime: 'wsl', readOnly: true, doctorOnLoad: false })
  await waitFor(() => registered.size > 0)
  assert.equal(registered.size, 13 - toolsModule.MUTATING_TOOLS.size)
  for (const name of toolsModule.MUTATING_TOOLS) assert.ok(!registered.has(name), name)
  disposeEffects(effects)
})

test('doctor runs once on load and warnings are logged', async (t) => {
  if (loader.kind !== 'real') {
    t.skip('needs the harness schema compiler')
    return
  }
  plugin.setDefineToolForTests(loader.defineTool)
  const calls = []
  const failingDoctor = async (request) => {
    calls.push(request)
    const command = request.argv.join(' ')
    const text = command.includes('ops doctor')
      ? JSON.stringify({ ok: true, result: { ok: false, checks: [{ check: 'atspi', status: 'fail', detail: 'no typelib', hint: 'apt install' }] } })
      : envDocument
    return { result: async () => ({ stdout: { text }, stderr: { text: '' }, aborted: false }) }
  }
  const { ctx, logs } = fakeContext({ shell: failingDoctor })
  plugin.apply(ctx, { runtime: 'wsl' })
  await waitFor(() => calls.some((c) => c.argv.join(' ').includes('ops doctor')))
  await waitFor(() => logs.warn.some((line) => /atspi: no typelib/.test(line)))
  disposeEffects(effects)
})

test('tool calls go through the transport and return the client value', async (t) => {
  if (loader.kind !== 'real') {
    t.skip('needs the harness schema compiler')
    return
  }
  plugin.setDefineToolForTests(loader.defineTool)
  const requests = []
  const shell = async (request) => {
    requests.push(request)
    const command = request.argv.join(' ')
    let text = envDocument
    if (command.includes('ops windows')) text = JSON.stringify({ ok: true, result: { windows: [{ title: 'Dolphin' }], count: 1 } })
    else if (command.includes('ops click')) text = JSON.stringify({ ok: true, result: { x: 10, y: 20, backend: 'xdotool' } })
    else if (command.includes('ops doctor')) text = doctorDocument
    return { result: async () => ({ stdout: { text }, stderr: { text: '' }, aborted: false }) }
  }
  const { ctx, registered, effects } = fakeContext({ shell })
  plugin.apply(ctx, { runtime: 'wsl', doctorOnLoad: false })
  await waitFor(() => registered.size > 0)
  const windows = await registered.get('kde_uia_windows').execute({}, {})
  assert.equal(windows.windows[0].title, 'Dolphin')
  const rendered = registered.get('kde_uia_windows').output.render({}, windows)
  assert.match(rendered[0].text, /Dolphin/)
  const click = await registered.get('kde_uia_click').execute({ ref: 'uia:1:dolphin:0/0/0' }, {})
  assert.equal(click.backend, 'xdotool')
  // Every command goes through wsl.exe with the fixed bash wrapper.
  const wslCalls = requests.filter((request) => request.argv[0].toLowerCase().includes('wsl'))
  assert.ok(wslCalls.length >= 2, 'calls must be routed through wsl.exe')
  for (const request of wslCalls) {
    // wsl.exe [--exec] bash -lc '<argv>': the plugin submits the fixed wrapper,
    // never a caller-built shell string.
    const bash = request.argv.indexOf('bash')
    assert.ok(bash > 0, `wsl argv: ${request.argv.join(' ')}`)
    assert.equal(request.argv[bash + 1], '-lc')
    assert.match(request.argv[bash + 2], /^bash -lc /)
  }
  disposeEffects(effects)
})

test('a failing client document becomes a tool Error with its hint', async (t) => {
  if (loader.kind !== 'real') {
    t.skip('needs the harness schema compiler')
    return
  }
  plugin.setDefineToolForTests(loader.defineTool)
  const shell = async (request) => {
    const command = request.argv.join(' ')
    const text = command.includes('ops find')
      ? JSON.stringify({ ok: false, error: { code: 'NOT_FOUND', message: 'no element matched', hint: 'run kde_uia_tree' } })
      : envDocument
    return { result: async () => ({ stdout: { text }, stderr: { text: '' }, aborted: false }) }
  }
  const { ctx, registered, effects } = fakeContext({ shell })
  plugin.apply(ctx, { runtime: 'wsl', doctorOnLoad: false })
  await waitFor(() => registered.size > 0)
  await assert.rejects(registered.get('kde_uia_find').execute({ text: 'Save' }, {}), /no element matched\nHint: run kde_uia_tree/)
  disposeEffects(effects)
})

test('a misconfigured runtime still registers tools that report CONFIG', async (t) => {
  if (loader.kind !== 'real') {
    t.skip('needs the harness schema compiler')
    return
  }
  plugin.setDefineToolForTests(loader.defineTool)
  const { ctx, registered, logs } = fakeContext({})
  plugin.apply(ctx, { runtime: 'ssh', doctorOnLoad: false })
  await waitFor(() => registered.size > 0)
  assert.match(logs.warn.join('\n'), /misconfigured/)
  await assert.rejects(registered.get('kde_uia_windows').execute({}, {}), /misconfigured/)
  disposeEffects(effects)
})

async function waitFor(predicate, timeoutMs = 3000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (predicate()) return
    await new Promise((resolve) => setTimeout(resolve, 10))
  }
  throw new Error('condition not reached in time')
}

export { PLUGIN_ROOT }
