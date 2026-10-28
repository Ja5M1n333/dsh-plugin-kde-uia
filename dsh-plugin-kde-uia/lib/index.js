/**
 * dsh-plugin-kde-uia — Windows-UI-Automation-style control of a Linux KDE
 * Plasma desktop for DeepSeek Harness agents.
 *
 * The plugin only contributes tools; all desktop work happens in the bundled
 * `kde_uia` Python client, which DSH reaches through its own shell seam in
 * the Linux environment (WSL distro, SSH host, or the local session). That
 * keeps the plugin host-agnostic: a Windows DSH can drive a WSL/Linux KDE
 * desktop without any Windows-side GUI libraries.
 *
 * Exports the function/namespace plugin shape DSH loaders expect: `name`,
 * `inject`, optional `Config`, and `apply`. Never add a default export — it
 * makes loaders unwrap the module and drop `inject`.
 * @module dsh-plugin-kde-uia
 */

import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { buildTools, MUTATING_TOOLS, TOOL_PREFIX } from './tools.js'
import {
  buildTarget,
  clientPathFor,
  configError,
  createProcessRunner,
  describeError,
  discoverClient,
  opsCall,
  parseDocument
} from './runtime.js'

/** Plugin name shown in loader diagnostics. */
export const name = 'kde-uia'

/** Tools are registered through the tool registry owned by `@deepseek-ai/dsh-tools`. */
export const inject = ['tools']

/**
 * Configuration schema. `format: 'form'` is an annotation the settings UI
 * understands; DSH itself does not validate these fields, so `apply()`
 * normalises them (see {@link normalizeConfig}).
 */
export const Config = {
  type: 'object',
  format: 'form',
  properties: {
    runtime: {
      type: 'string',
      enum: ['auto', 'wsl', 'ssh', 'local'],
      default: 'auto',
      description: 'Where the Linux desktop lives: auto (WSL on Windows, local on Linux), wsl, ssh, or local.'
    },
    wslDistribution: { type: 'string', default: '', description: 'WSL distribution (empty = the default one).' },
    remotePath: { type: 'string', default: '', description: 'Directory containing the kde_uia package inside Linux (default: auto-discovered).' },
    remotePython: { type: 'string', default: 'python3', description: 'Python interpreter inside Linux (must have PyGObject).' },
    wslCommand: { type: 'string', default: '', description: 'wsl.exe path (empty = System32/default).' },
    sshHost: { type: 'string', default: '', description: 'SSH destination user@host when runtime is ssh.' },
    sshIdentity: { type: 'string', default: '', description: 'SSH private key path (optional).' },
    sshOptions: { type: 'array', items: { type: 'string' }, default: [], description: 'Extra ssh -o options (advanced).' },
    timeoutMs: { type: 'number', default: 120000, minimum: 1000, description: 'Per-call timeout budget.' },
    readOnly: { type: 'boolean', default: false, description: 'Register only the read-only tools (no click/type/keys).' },
    doctorOnLoad: { type: 'boolean', default: true, description: 'Run the offline capability probe once when the plugin mounts.' },
    executable: { type: 'string', default: '', description: 'Command launching the kde_uia client (empty = bundled Python via DSH shell).' }
  }
}

let cachedDefineTool

/**
 * Test seam: install a `defineTool` implementation directly. Production code
 * never calls this; the plugin resolves `@deepseek-ai/dsh-tools` by itself.
 * @param {Function|null} defineTool
 */
export function setDefineToolForTests(defineTool) {
  cachedDefineTool = defineTool ?? undefined
}

/**
 * Load `defineTool` from the host's tool registry.
 * `@deepseek-ai/dsh-tools` is a DSH peer dependency resolved by the loader
 * (DSH's profile runtime resolution makes it importable from plugin code).
 */
async function resolveDefineTool(config, logger) {
  if (cachedDefineTool) return cachedDefineTool
  try {
    const tools = await import('@deepseek-ai/dsh-tools')
    if (typeof tools.defineTool !== 'function') throw new Error('@deepseek-ai/dsh-tools has no defineTool export')
    cachedDefineTool = tools.defineTool
    return cachedDefineTool
  } catch (cause) {
    const message = 'dsh-plugin-kde-uia could not load @deepseek-ai/dsh-tools to build tool definitions'
    const hint = 'The tool registry service (`ctx.tools`) must be mounted: keep the `tools` row of @deepseek-ai/dsh-base enabled.'
    const error = new Error(`${message}: ${describeError(cause)}\nHint: ${hint}`)
    error.cause = cause
    logger?.warn?.(`kde-uia: ${message}`)
    throw error
  }
}

/** Normalise and validate the user configuration. */
export function normalizeConfig(raw) {
  const config = { ...defaults(), ...(raw ?? {}) }
  if (!['auto', 'wsl', 'ssh', 'local'].includes(config.runtime)) {
    throw configError(`config.runtime must be one of auto, wsl, ssh, local (got ${JSON.stringify(config.runtime)})`)
  }
  if (!Number.isFinite(config.timeoutMs) || config.timeoutMs < 1000) {
    throw configError('config.timeoutMs must be a number >= 1000')
  }
  if (!Array.isArray(config.sshOptions)) throw configError('config.sshOptions must be an array of strings')
  config.readOnly = config.readOnly === true
  config.doctorOnLoad = config.doctorOnLoad !== false
  return config
}

function defaults() {
  return {
    runtime: 'auto',
    wslDistribution: '',
    remotePath: '',
    remotePython: 'python3',
    wslCommand: '',
    sshHost: '',
    sshIdentity: '',
    sshOptions: [],
    timeoutMs: 120_000,
    readOnly: false,
    doctorOnLoad: true,
    executable: ''
  }
}

/** The directory of this package (`…/dsh-plugin-kde-uia`). */
export function packageRoot() {
  // `fileURLToPath` turns `file:///C:/x` into `C:\x`; `URL.pathname` would
  // hand Windows callers a `/C:/x` pathname instead.
  return resolve(dirname(fileURLToPath(import.meta.url)), '..')
}

/**
 * Map one tool call onto a client operation. Most tools use the client's own
 * op names; `window-op` splits into `activate` / `window close|minimize|…`.
 */
export function planOperation(toolName, args) {
  const op = opFor(toolName)
  if (op === 'window-op') {
    const action = args?.action ?? 'activate'
    if (action === 'activate') return { op: 'activate', args: { window: args?.window, app: args?.app, id: args?.id } }
    return { op: 'window', args: { op: action, window: args?.window, app: args?.app, id: args?.id, x: args?.x, y: args?.y, width: args?.width, height: args?.height } }
  }
  return { op, args: args ?? {} }
}

/** Client operation for a `kde_uia_*` tool name. */
export function opFor(toolName) {
  const suffix = String(toolName).startsWith(TOOL_PREFIX) ? String(toolName).slice(TOOL_PREFIX.length) : null
  const map = {
    doctor: 'doctor',
    windows: 'windows',
    tree: 'tree',
    find: 'find',
    info: 'info',
    click: 'click',
    keys: 'press',
    type: 'type',
    set_value: 'set',
    scroll: 'scroll',
    wait_for: 'wait',
    screenshot: 'screenshot',
    activate: 'window-op'
  }
  const op = suffix ? map[suffix] : undefined
  if (!op) throw configError(`unknown kde-uia tool ${JSON.stringify(toolName)}`)
  return op
}

/**
 * Client for one resolved runtime: discovers the Python client lazily, runs
 * operations with abort propagation, and caches nothing about results.
 * @param {{ config: object, target: object, packageRoot: string, mapping?: object, logger?: any }} options
 */
export function createClient({ config, target, packageRoot: root, mapping = {}, logger }) {
  let discovered
  const mappingFor = {
    winRoot: mapping.winRoot ?? root,
    linuxRoot: mapping.linuxRoot ?? (process.platform === 'win32' && target.kind === 'ssh' ? config.remotePath : undefined)
  }
  const discover = (signal) => {
    if (!discovered) {
      discovered = discoverClient(target, { config, packageRoot: root, mapping: mappingFor, signal })
      discovered.catch(() => { discovered = undefined })
    }
    return discovered
  }
  return {
    target,
    async run(op, args, exec) {
      const signal = exec?.signal
      const { root: clientRoot, python } = await discover(signal)
      const document = await opsCall(target, python, clientRoot, op, args, { signal })
      if (document.ok) return document.result
      const error = new Error(document.error?.message ?? 'kde-uia operation failed')
      error.code = document.error?.code ?? 'ERROR'
      if (document.error?.hint) error.hint = document.error.hint
      if (document.error?.details) error.details = document.error.details
      throw error
    },
    /** Synchronous location of the bundled client (for diagnostics). */
    clientPath() {
      return clientPathFor(root, target.kind, config, mappingFor)
    }
  }
}

/**
 * Plugin entry. Cordis calls `apply(ctx, config)`; returning a disposable
 * object with `dispose()` lets the loader release the tool registrations on
 * reload without relying on a global effect service.
 * @param {object} ctx - the plugin context (owns `tools`)
 * @param {object} rawConfig - user configuration
 */
export function apply(ctx, rawConfig) {
  const config = normalizeConfig(rawConfig)
  const logger = ctx.logger
  const processRun = createProcessRunner({ shell: ctx.get('shell'), shellEnv: ctx.get('shellEnv') })
  let target = null
  let client = null
  let runtimeError = null
  try {
    target = buildTarget(config, processRun)
    client = createClient({ config, target, packageRoot: packageRoot(), logger })
  } catch (error) {
    runtimeError = error
    logger?.warn?.(`kde-uia: runtime is misconfigured; tools will report CONFIG: ${describeError(error)}`)
  }

  const registered = []
  let disposing = false

  const call = async (op, args, exec) => {
    if (config.executable) return runExecutable(config, op, args, exec, processRun)
    if (!client) {
      throw configError(
        `kde-uia runtime is misconfigured: ${describeError(runtimeError)}`,
        'Fix the plugin configuration (runtime/wslDistribution/sshHost), then run kde_uia_doctor.'
      )
    }
    return client.run(op, args, exec)
  }

  const register = async (toolCtx) => {
    const defineTool = await resolveDefineTool(config, logger)
    if (disposing) return
    const tools = buildTools({ defineTool, call, readOnly: config.readOnly })
    for (const tool of tools) {
      try {
        const dispose = toolCtx.tools.register(tool)
        if (typeof dispose === 'function') registered.push(dispose)
      } catch (error) {
        logger?.warn?.(`kde-uia: could not register ${tool.name}: ${describeError(error)}`)
      }
    }
    logger?.info?.(
      `kde-uia: registered ${registered.length} tools via ${target ? target.label : 'an invalid runtime'} ` +
      `(${config.readOnly ? 'read-only' : 'interactive'}): ${tools.map((t) => t.name).join(', ')}`
    )
    if (config.doctorOnLoad) void probe()
  }

  const probe = async () => {
    if (!client) return
    try {
      const health = await client.run('doctor', {}, {})
      const failing = (health?.checks ?? []).filter((check) => check.status === 'fail')
      if (failing.length) {
        logger?.warn?.(`kde-uia: capability problems: ${failing.map((c) => `${c.check}: ${c.detail}`).join('; ')}. Run kde_uia_doctor for hints.`)
      } else {
        logger?.info?.(`kde-uia: desktop automation ready (${target.label}): ${(health?.checks ?? []).map((c) => c.check).join(', ')}`)
      }
    } catch (error) {
      logger?.warn?.(
        `kde-uia: the Python client is not reachable in ${target?.label ?? 'the runtime'}: ${describeError(error)}. ` +
        'Run kde_uia_doctor for the install checklist; the tools stay registered.'
      )
    }
  }

  // Tolerate both wiring orders: registry already present, or appearing later.
  if (typeof ctx.inject === 'function' && !ctx.get?.('tools')) {
    ctx.inject(['tools'], (toolCtx) => {
      void register(toolCtx).catch((error) => logger?.error?.(`kde-uia: tool registration failed: ${describeError(error)}`))
    })
  } else if (ctx.get?.('tools')) {
    void register(ctx).catch((error) => logger?.error?.(`kde-uia: tool registration failed: ${describeError(error)}`))
  } else {
    logger?.warn?.('kde-uia: no tool registry (ctx.tools); mount @deepseek-ai/dsh-tools.')
  }

  return {
    /** Dispose the tool registrations (the loader calls this on reload). */
    dispose() {
      disposing = true
      for (const dispose of registered.splice(0)) {
        try {
          dispose()
        } catch {
          // the registry may already be gone
        }
      }
    },
    /** Introspection for tests and settings UIs. */
    info: {
      config,
      runtime: target?.kind ?? null,
      clientPath: client?.clientPath() ?? null,
      mutatingTools: [...MUTATING_TOOLS]
    }
  }
}

async function runExecutable(config, op, args, exec, processRun) {
  const argv = [...config.executable.split(' ').filter(Boolean), 'ops', op, '--args', JSON.stringify(args ?? {})]
  const { text } = await processRun(argv, { signal: exec?.signal, timeoutMs: config.timeoutMs })
  const document = parseDocument(text)
  if (document.ok) return document.result
  const error = new Error(document.error?.message ?? 'kde-uia executable failed')
  error.code = document.error?.code ?? 'ERROR'
  if (document.error?.hint) error.hint = document.error.hint
  throw error
}
