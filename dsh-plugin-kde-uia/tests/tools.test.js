/**
 * Tool declaration tests. Every tool is compiled by the **real** harness
 * `defineTool` when the probe copy is available (see tests/helpers/dsh-tools.js),
 * so a schema the host would reject fails here.
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'

import { buildTools, MUTATING_TOOLS, TOOL_PREFIX, windowOp } from '../lib/tools.js'
import { loadDefineTool } from './helpers/dsh-tools.js'

const { defineTool, kind } = await loadDefineTool()

const tools = buildTools({ defineTool, call: async () => ({}) })
const byName = Object.fromEntries(tools.map((tool) => [tool.name, tool]))

test(`tool declarations compile (defineTool source: ${kind})`, () => {
  assert.ok(tools.length >= 12, `expected at least 12 tools, got ${tools.length}`)
  for (const tool of tools) {
    assert.match(tool.name, /^kde_uia_[a-z_]+$/)
    assert.ok(tool.description.length > 40, `${tool.name} needs a real description`)
    assert.equal(tool.parameters.type, 'object')
    // The author-only `json` node compiles to an annotation-only (empty) schema;
    // it must never accidentally become a string/object/array schema.
    assert.deepEqual(tool.output.schema, {}, `${tool.name} output must be the annotation-only json schema`)
    assert.equal(typeof tool.execute, 'function')
    assert.equal(typeof tool.output.render, 'function')
  }
})

test('every tool uses the kde_uia_ prefix exactly once', () => {
  for (const tool of tools) assert.equal(tool.name.split(TOOL_PREFIX).length, 2, tool.name)
})

test('no tool declares an unknown author key', () => {
  // The real compiler already rejects these; this pins the common mistakes
  // (the DSL forbids raw JSON-Schema keywords like "format" or "pattern").
  const forbidden = ['format', 'pattern', 'minimum', 'maximum', 'oneOf', 'anyOf', 'allOf', '$ref']
  for (const tool of tools) {
    for (const [property, spec] of Object.entries(tool.parameters.properties ?? {})) {
      assert.ok(!forbidden.includes(property), `${tool.name}.${property} must not be a parameter`)
      for (const key of Object.keys(spec)) {
        assert.ok(!['format', 'pattern', 'minimum', 'maximum'].includes(key), `${tool.name}.${property} uses raw JSON-Schema keyword ${key}`)
      }
    }
  }
})

test('required parameters are declared with required: true', () => {
  // keys, type, set_value take required inputs; the registry enforces it.
  assert.deepEqual(byName.kde_uia_keys.parameters.required, ['key'])
  assert.deepEqual(byName.kde_uia_type.parameters.required, ['text'])
  assert.deepEqual(byName.kde_uia_set_value.parameters.required, ['value'])
  assert.equal(byName.kde_uia_windows.parameters.required, undefined)
})

test('schemas stay small: object params declare additionalProperties', () => {
  const selector = byName.kde_uia_find.parameters.properties.selector
  assert.equal(selector.type, 'object')
  assert.equal(selector.additionalProperties, false)
  // The DSL only accepts boolean `additionalProperties`, so maps are open objects.
  assert.equal(selector.properties.states.type, 'object')
  assert.equal(selector.properties.states.additionalProperties, true)
})

test('mutating tools are exactly the ones that change desktop state', () => {
  const flagged = tools.filter((tool) => MUTATING_TOOLS.has(tool.name)).map((tool) => tool.name).sort()
  assert.deepEqual(flagged, [
    'kde_uia_activate',
    'kde_uia_click',
    'kde_uia_keys',
    'kde_uia_scroll',
    'kde_uia_set_value',
    'kde_uia_type'
  ])
})

test('readOnly builds no mutating tools', () => {
  const readOnly = buildTools({ defineTool, call: async () => ({}), readOnly: true })
  assert.equal(readOnly.length, tools.length - MUTATING_TOOLS.size)
  for (const tool of readOnly) assert.ok(!MUTATING_TOOLS.has(tool.name))
})

test('each tool routes to its client op and maps arguments', async () => {
  const calls = []
  const record = buildTools({ defineTool, call: async (op, args) => { calls.push([op, args]); return {} } })
  const run = async (name, args) => {
    const tool = record.find((candidate) => candidate.name === name)
    await tool.execute(args, {})
  }
  await run('kde_uia_windows', { window: 'Dolphin' })
  await run('kde_uia_tree', { window: 'Dolphin', depth: 6 })
  await run('kde_uia_find', { text: 'Save', actionable: 'button', window: 'kwrite' })
  await run('kde_uia_click', { ref: 'uia:1:kwrite:1/0', dry_run: true })
  await run('kde_uia_keys', { key: 'ctrl+l' })
  await run('kde_uia_type', { text: 'hello', submit: true })
  await run('kde_uia_set_value', { ref: 'uia:1:kwrite:1/1', value: '42' })
  await run('kde_uia_scroll', { ref: 'uia:1:kwrite:2', direction: 'down', amount: 2 })
  await run('kde_uia_wait_for', { selector: { text: 'Ready' }, timeout_s: 3 })
  await run('kde_uia_screenshot', { window: 'Dolphin' })
  await run('kde_uia_activate', { window: 'Dolphin', action: 'activate' })
  await run('kde_uia_activate', { window: 'Dolphin', action: 'close' })
  const ops = calls.map(([op]) => op)
  assert.deepEqual(ops, ['windows', 'tree', 'find', 'click', 'press', 'type', 'set', 'scroll', 'wait', 'screenshot', 'activate', 'window'])
  assert.equal(calls[2][1].selector.role, 'push button')
  assert.equal(calls[1][1].depth, 6)
  assert.equal(calls[8][1].for, 'element')
  // `kde_uia_activate` reaches the client as `activate` or `window` with its
  // own `op`; the `window-op` sentinel must never travel to the client.
  assert.equal(calls[10][1].window, 'Dolphin')
  assert.equal(calls[10][1].id, undefined)
  assert.equal(calls[11][1].op, 'close')
  assert.equal(calls[11][1].window, 'Dolphin')
})

test('actionable kinds map to AT-SPI roles', async () => {
  let selector
  const record = buildTools({ defineTool, call: async (op, args) => { selector = args.selector } })
  for (const [kind, role] of [['button', 'push button'], ['link', 'link'], ['checkbox', 'check box'], ['radio', 'radio button'], ['textbox', 'entry'], ['menuitem', 'menu item'], ['tab', 'page tab']]) {
    selector = undefined
    await record.find((t) => t.name === 'kde_uia_find').execute({ text: 'x', actionable: kind }, {})
    assert.equal(selector.role, role, kind)
  }
})

test('tool errors surface as Error with the client hint', async () => {
  const failing = buildTools({ defineTool, call: async () => { const error = new Error('no window matched'); error.code = 'NOT_FOUND'; error.hint = 'run kde_uia_windows'; throw error } })
  await assert.rejects(failing[1].execute({}, {}), (error) => /no window matched/.test(error.message) && /Hint: run kde_uia_windows/.test(error.message))
})

test('presentCall names the operation for UIs', () => {
  const call = byName.kde_uia_click.presentCall({ ref: 'uia:1:a:1' })
  assert.equal(call.title, 'kde-uia click')
  assert.equal(call.kind, 'other')
  assert.equal(byName.kde_uia_doctor.presentCall({}).kind, 'search')
})

test('window-op resolves to a real client operation', () => {
  // 0.1.0 sent the sentinel verbatim: every kde_uia_activate call failed with
  // "unknown op 'window-op'".
  assert.deepEqual(windowOp('window-op', { action: 'activate', id: 'w' }), {
    op: 'activate',
    args: { window: undefined, app: undefined, id: 'w' }
  })
  assert.deepEqual(windowOp('window-op', { action: 'close', id: 'w' }).op, 'window')
  assert.equal(windowOp('window-op', { action: 'close', id: 'w' }).args.op, 'close')
  assert.deepEqual(windowOp('window-op', { action: 'resize', id: 'w', width: 800, height: 600 }).args, {
    window: undefined,
    app: undefined,
    id: 'w',
    op: 'resize',
    width: 800,
    height: 600
  })
  // Every other tool op is passed through untouched.
  assert.deepEqual(windowOp('tree', { ref: 'r' }), { op: 'tree', args: { ref: 'r' } })
})
