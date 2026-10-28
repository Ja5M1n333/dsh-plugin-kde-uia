/**
 * `kde-uia-dsh` — the plugin's own CLI for operators, without an agent.
 *
 * It uses the same runtime code as the tools, so a command here behaves exactly
 * like the corresponding tool call (same transport, same quoting, same JSON
 * document). Useful for checking a deployment from the host that runs DSH:
 *
 *   npm link            # or: node lib/cli.js …
 *   kde-uia-dsh doctor
 *   kde-uia-dsh call windows --json '{}'
 *   kde-uia-dsh call tree --json '{"window":"Dolphin","depth":5}'
 *   kde-uia-dsh call click --json '{"ref":"uia:1:dolphin:0/1/0"}' --read-only
 *
 * Flags: --runtime auto|wsl|ssh|local, --wsl <distro>, --ssh <user@host>,
 *        --remote-path <dir>, --timeout <ms>, --read-only (= mutating calls refused).
 */

import { buildTarget, createProcessRunner, describeError, discoverClient, opsCall } from './runtime.js'
import { buildTools, MUTATING_TOOLS, TOOL_PREFIX } from './tools.js'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function usage() {
  process.stdout.write(
    'usage: kde-uia-dsh <doctor|tools|windows|tree|call> [options]\n\n' +
    '  doctor                     capability report through the configured transport\n' +
    '  tools                      list the tool names and which ones mutate the desktop\n' +
    "  windows                    list desktop windows\n" +
    "  tree --window <title> [--depth N]   print one window's element tree\n" +
    '  call <tool> --json <args>  run one tool (e.g. call kde_uia_find --json \'{"text":"Save"}\')\n\n' +
    'options: --runtime auto|wsl|ssh|local  --wsl <distro>  --ssh <user@host>\n' +
    '         --remote-path <dir>  --timeout <ms>  --read-only  --json\n'
  )
}

function parse(argv) {
  const options = { readsOnly: false, json: false }
  const rest = []
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg === '--runtime') options.runtime = argv[++index]
    else if (arg === '--wsl') options.wslDistribution = argv[++index]
    else if (arg === '--ssh') options.sshHost = argv[++index]
    else if (arg === '--remote-path') options.remotePath = argv[++index]
    else if (arg === '--timeout') options.timeoutMs = Number(argv[++index])
    else if (arg === '--read-only') options.readsOnly = true
    else if (arg === '--json') options.json = true
    else rest.push(arg)
  }
  return { options, rest }
}

async function main() {
  const { options, rest } = parse(process.argv.slice(2))
  const command = rest[0]
  if (!command || command === '-h' || command === '--help') {
    usage()
    return 0
  }
  const config = {
    runtime: options.runtime ?? 'auto',
    wslDistribution: options.wslDistribution ?? '',
    sshHost: options.sshHost ?? '',
    remotePath: options.remotePath ?? '',
    remotePython: 'python3',
    sshOptions: [],
    timeoutMs: options.timeoutMs ?? 120_000,
    readOnly: false,
    doctorOnLoad: false
  }
  const target = buildTarget(config, createProcessRunner({}))
  const invoke = async (op, args) => {
    const found = await discoverClient(target, { config, packageRoot: root })
    const document = await opsCall(target, found.python, found.root, op, args)
    if (!document.ok) throw Object.assign(new Error(document.error?.message ?? 'operation failed'), document.error ?? {})
    return document.result
  }

  if (command === 'tools') {
    // The declarations need defineTool; for a listing a pass-through is enough.
    const tools = buildTools({ defineTool: (definition) => definition, call: async () => ({}) })
    for (const tool of tools) {
      process.stdout.write(`${tool.name.padEnd(28)} ${MUTATING_TOOLS.has(tool.name) ? 'mutates' : 'reads  '} ${tool.description.split('.')[0]}\n`)
    }
    return 0
  }
  if (command === 'doctor') {
    const health = await invoke('doctor', {})
    if (options.json) {
      process.stdout.write(`${JSON.stringify(health, null, 2)}\n`)
    } else {
      for (const check of health?.checks ?? []) {
        process.stdout.write(`${check.status === 'ok' ? '[+]' : check.status === 'skip' ? '[-]' : '[x]'} ${check.check}: ${check.detail}\n`)
        if (check.hint) process.stdout.write(`    hint: ${check.hint}\n`)
      }
    }
    return health?.ok ? 0 : 1
  }
  if (command === 'windows') {
    const result = await invoke('windows', {})
    if (options.json) {
      process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
      return 0
    }
    const rows = result?.windows ?? []
    for (const row of rows) {
      const frame = row.frame ?? row.extents ?? {}
      const geometry = frame.width ? `${frame.width}x${frame.height}+${frame.x}+${frame.y}` : '?'
      process.stdout.write(`${row.active ? '*' : ' '} ${String(row.id ?? row.ref ?? '').padEnd(12)} ${geometry.padEnd(16)} ${String(row.app ?? '').padEnd(16)} ${row.title ?? ''}\n`)
    }
    if (!rows.length) process.stdout.write('(no windows; run doctor)\n')
    return rows.length ? 0 : 1
  }
  if (command === 'tree') {
    const windowIndex = rest.indexOf('--window')
    const depthIndex = rest.indexOf('--depth')
    const result = await invoke('tree', {
      ...(windowIndex >= 0 ? { window: rest[windowIndex + 1] } : {}),
      depth: depthIndex >= 0 ? Number(rest[depthIndex + 1]) : 4
    })
    process.stdout.write(`${result?.text ?? ''}\n`)
    return result?.text ? 0 : 1
  }
  if (command === 'call') {
    const toolName = rest[1]
    const jsonIndex = rest.indexOf('--json')
    let args = {}
    if (rest[2] && rest[2] !== '--json') args = JSON.parse(rest[2])
    else if (jsonIndex >= 0) args = JSON.parse(rest[jsonIndex + 1] ?? '{}')
    if (!toolName?.startsWith(TOOL_PREFIX)) throw new Error(`call needs a ${TOOL_PREFIX}* tool name`)
    const suffix = toolName.slice(TOOL_PREFIX.length)
    if (options.readsOnly && MUTATING_TOOLS.has(toolName)) throw new Error(`${toolName} is a mutating tool (--read-only)`)
    let op = suffix === 'keys' ? 'press' : suffix === 'set_value' ? 'set' : suffix === 'wait_for' ? 'wait' : suffix
    if (op === 'activate') {
      const action = args.action ?? 'activate'
      const value = action === 'activate' ? await invoke('activate', { window: args.window, app: args.app, id: args.id })
        : await invoke('window', { op: action, window: args.window, app: args.app, id: args.id, x: args.x, y: args.y, width: args.width, height: args.height })
      process.stdout.write(`${JSON.stringify(value, null, 2)}\n`)
      return 0
    }
    const value = await invoke(op, args)
    process.stdout.write(`${JSON.stringify(value, null, 2)}\n`)
    return 0
  }
  usage()
  return 2
}

try {
  process.exitCode = await main()
} catch (error) {
  process.stderr.write(`kde-uia-dsh: ${describeError(error)}\n`)
  if (error?.hint) process.stderr.write(`hint: ${error.hint}\n`)
  process.exitCode = 1
}
