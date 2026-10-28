/**
 * Runtime resolution: how this DSH host reaches the Linux desktop.
 *
 * Three environments, two transports:
 *
 * | config.runtime | Windows host            | Linux host              |
 * |----------------|-------------------------|-------------------------|
 * | `wsl`          | `wsl.exe` -> distro     | treated as `local`      |
 * | `ssh`          | OpenSSH `ssh.exe`       | local `ssh`             |
 * | `local`        | rejected (no Linux)     | `python3 -m kde_uia`    |
 * | `auto`         | WSL if present, else SSH| local                   |
 *
 * Every call runs the bundled Python client's JSON protocol
 * (`python3 -m kde_uia ops <name> --args-file <uri> --result <uri>`), which
 * writes exactly one `{"ok": true|false, …}` document. The plugin never sends
 * a shell *string*: it builds an argv, quotes every element for the receiving
 * shell, and runs it through DSH's bash tool (`bash -lc '<argv>'`), i.e. the
 * same fixed wrapper DSH itself uses. Arguments travel as base64, so no
 * quoting mistake can change their meaning.
 *
 * Discovery sends no user data anywhere: each candidate is probed once with
 * `python -m kde_uia ops env` (an offline environment report) and remembered.
 * @module dsh-plugin-kde-uia/runtime
 */

import { existsSync, readFileSync } from 'node:fs'
import { join, resolve, win32 } from 'node:path'

/** Code of a transport failure (process output was not the client's JSON). */
export const TRANSPORT_INCOMPLETE = 'TRANSPORT_INCOMPLETE'

/**
 * @typedef {object} RuntimeConfig
 * @property {string} runtime - auto | wsl | ssh | local
 * @property {string} wslDistribution - WSL distro; empty = default
 * @property {string} sshHost - SSH destination (`user@host`)
 * @property {string} sshIdentity - optional private key (Windows path is converted)
 * @property {string[]} sshOptions - extra `-o` options passed verbatim
 * @property {string} remotePath - optional explicit client root inside Linux
 * @property {string} remotePython - interpreter name inside Linux
 * @property {string} wslCommand - explicit wsl.exe path
 * @property {number} timeoutMs - per-call budget
 * @property {boolean} doctorOnLoad
 */

/**
 * @typedef {object} Target
 * @property {string} kind - wsl | ssh | local
 * @property {string} label
 * @property {number} timeoutMs
 * @property {(args: string[], opts: { signal?: AbortSignal, timeoutMs?: number }) => Promise<{ text: string }>} run
 */

/**
 * A command runner over DSH's shell seam, with a child_process fallback for
 * tests and non-DSH hosts.
 * @param {{ shell?: any, shellEnv?: any, cwd?: string }} deps
 * @returns {(argv: string[], opts: { signal?: AbortSignal, timeoutMs?: number }) => Promise<{ text: string }>}
 */
export function createProcessRunner(deps) {
  return async (argv, opts = {}) => {
    if (typeof deps.shell === 'function') {
      let env
      try {
        if (deps.shellEnv && typeof deps.shellEnv.collect === 'function') env = deps.shellEnv.collect()
      } catch {
        env = undefined
      }
      const request = {
        argv,
        timeoutMs: opts.timeoutMs,
        ...(deps.cwd ? { workdir: deps.cwd } : {}),
        ...(opts.signal ? { signal: opts.signal } : {}),
        ...(env ? { env } : {})
      }
      const handle = await deps.shell(request)
      const result = await handle.result()
      if (result.aborted) throw abortError()
      return { text: `${result.stdout?.text ?? ''}${result.stderr?.text ?? ''}` }
    }
    const { execFile } = await import('node:child_process')
    const text = await new Promise((resolvePromise, reject) => {
      execFile(argv[0], argv.slice(1), {
        timeout: opts.timeoutMs,
        signal: opts.signal,
        windowsHide: true,
        maxBuffer: 64 * 1024 * 1024
      }, (error, stdout, stderr) => {
        if (error && (error.name === 'AbortError' || error.code === 'ABORT_ERR')) {
          reject(abortError(error.message))
          return
        }
        resolvePromise(`${stdout ?? ''}${stderr ?? ''}`)
      })
    })
    return { text }
  }
}

function abortError(message) {
  return codedError(message || 'command was aborted', 'ABORTED')
}

/**
 * Resolve the configured runtime into a target.
 * @param {RuntimeConfig} config
 * @param {(argv: string[], opts: object) => Promise<{ text: string }>} processRun
 * @param {object} [host] - injectable host facts for tests
 */
export function buildTarget(config, processRun, host = {}) {
  const platform = host.platform ?? process.platform
  const isWsl = host.isWsl ?? Boolean((host.env ?? process.env).WSL_DISTRO_NAME)
  const env = host.env ?? process.env
  const pathExists = host.pathExists ?? ((candidate) => { try { return existsSync(candidate) } catch { return false } })
  const kind = resolveKind(config.runtime, platform, isWsl)
  const timeoutMs = Number.isFinite(config.timeoutMs) && config.timeoutMs > 0 ? config.timeoutMs : 120_000

  if (kind === 'local') {
    return {
      kind,
      label: 'local Linux session',
      timeoutMs,
      run: (args, opts) => processRun(['bash', '-lc', quoteArgv(args)], opts)
    }
  }

  if (kind === 'wsl') {
    const wsl = resolveWslExecutable(config.wslCommand, pathExists, env)
    const distro = String(config.wslDistribution || '')
    return {
      kind,
      label: distro ? `WSL distro ${distro}` : 'WSL default distribution',
      timeoutMs,
      run: (args, opts) => {
        const argv = [wsl]
        if (distro) argv.push('-d', distro)
        argv.push('--exec', 'bash', '-lc', quoteArgv(args))
        return processRun(argv, opts)
      }
    }
  }

  // SSH. On Windows the wrapper must be PowerShell: a PowerShell-quoted script
  // would be read by bash as a relative path, and bash-quoted text would be
  // re-parsed by PowerShell. Windows therefore gets `pwsh … ssh … 'bash -lc …'`
  // while the inner command stays POSIX-quoted for the remote bash.
  const remote = String(config.sshHost || '')
  if (!remote) throw configError('config.runtime is "ssh" but config.sshHost is empty', 'Set sshHost to `user@host`, or use runtime "wsl"/"auto".')
  const shell = platform === 'win32' ? 'pwsh' : 'bash'
  const sshExe = platform === 'win32' ? resolveWindowsSshPath(pathExists, env) : 'ssh'
  const sshCommand = (bashCommand) => {
    const parts = [shell === 'pwsh' ? quotePwsh(sshExe) : '"' + sshExe + '"']
    if (config.sshIdentity) parts.push('-i', shell === 'pwsh' ? quotePwsh(config.sshIdentity) : quotePosix(config.sshIdentity))
    for (const option of config.sshOptions ?? []) parts.push('-o', shell === 'pwsh' ? quotePwsh(option) : quotePosix(option))
    parts.push('-o', 'BatchMode=yes')
    parts.push(shell === 'pwsh' ? quotePwsh(remote) : quotePosix(remote))
    parts.push('bash', '-lc', shell === 'pwsh' ? quotePwsh(bashCommand) : quotePosix(bashCommand))
    return parts.join(' ')
  }
  return {
    kind,
    label: `SSH host ${remote}`,
    timeoutMs,
    run: (args, opts) => {
      const command = sshCommand(quoteArgv(args))
      const argv = shell === 'pwsh'
        ? ['pwsh', '-NoProfile', '-NonInteractive', '-Command', command]
        : ['bash', '-lc', command]
      return processRun(argv, opts)
    }
  }
}

function resolveKind(runtime, platform, isWsl) {
  const value = String(runtime || 'auto')
  if (value === 'wsl' || value === 'ssh' || value === 'local') {
    if (value === 'wsl' && platform !== 'win32') return isWsl ? 'local' : 'local'
    return value
  }
  if (value !== 'auto') throw configError(`config.runtime must be auto|wsl|ssh|local, got ${JSON.stringify(value)}`)
  if (platform !== 'win32') return 'local'
  return 'wsl'
}

function resolveWslExecutable(configured, pathExists, env) {
  if (configured) {
    if (!pathExists(configured)) throw configError(`wsl.exe not found at ${configured}`, 'Fix config.wslCommand or clear it to use the system default.')
    return configured
  }
  const systemRoot = env.SystemRoot || env.windir || 'C:\\Windows'
  const candidates = [join(systemRoot, 'System32', 'wsl.exe'), join(systemRoot, 'Sysnative', 'wsl.exe'), 'wsl.exe']
  for (const candidate of candidates) if (candidate === 'wsl.exe' || pathExists(candidate)) return candidate
  return 'wsl.exe'
}

function resolveWindowsSshPath(pathExists, env) {
  const systemRoot = env.SystemRoot || env.windir || 'C:\\Windows'
  const candidates = [
    join(systemRoot, 'System32', 'OpenSSH', 'ssh.exe'),
    join(env.ProgramFiles || 'C:\\Program Files', 'OpenSSH', 'ssh.exe'),
    'ssh.exe'
  ]
  for (const candidate of candidates) if (candidate === 'ssh.exe' || pathExists(candidate)) return candidate
  return 'ssh.exe'
}

/** Join already-quoted argv elements with single spaces. */
export function quoteArgv(args) {
  return args.map((arg) => quotePosix(String(arg))).join(' ')
}

/** POSIX shell quoting for one word (safe words stay bare). */
export function quotePosix(value) {
  const text = String(value)
  if (text === '') return "''"
  if (/^[A-Za-z0-9_@%+=:,./-]+$/.test(text)) return text
  return "'" + text.replace(/'/g, "'\\''") + "'"
}

/** PowerShell single-quoted string. */
export function quotePwsh(value) {
  return "'" + String(value).replace(/'/g, "''") + "'"
}

/** `C:\a b` -> `/mnt/c/a b`. */
export function windowsPathToWsl(path) {
  let text = String(path)
  // Accept URL pathnames too (`/C:/x/…` or `/C:\x\…`), which is what
  // `new URL(...).pathname` yields on Windows.
  if (/^\/[A-Za-z]:[\\/]/.test(text)) text = text.slice(1)
  const absolute = /^[A-Za-z]:[\\/]/.test(text) || process.platform === 'win32' ? win32.resolve(text) : resolve(text)
  const match = /^([A-Za-z]):[\\/](.*)$/.exec(absolute)
  if (!match) return absolute.split('\\').join('/')
  return `/mnt/${match[1].toLowerCase()}/${match[2].split('\\').join('/')}`
}

/**
 * Map a host path into the receiving file system.
 *
 * The host may not be the platform this Node process runs on (a Windows DSH
 * host drives a WSL guest, and tests simulate hosts), so drive-letter paths
 * are always recognised, never `path.win32`-oriented `process.platform`.
 * @param {string} path - path in this process
 * @param {string} kind - wsl | ssh | local
 * @param {{ winRoot?: string, linuxRoot?: string }} mapping
 */
export function toRemotePath(path, kind, mapping = {}) {
  let original = String(path)
  if (/^\/[A-Za-z]:[\\/]/.test(original)) original = original.slice(1)
  const winPath = /^([A-Za-z]:[\\/]|[A-Za-z]:$)/.test(original) || (process.platform === 'win32' && !original.startsWith('/'))
  const absolute = winPath ? win32.resolve(original) : original
  if (kind === 'wsl') {
    if (winPath) {
      const winRoot = mapping.winRoot ? win32.resolve(String(mapping.winRoot)) : null
      if (winRoot && mapping.linuxRoot) {
        const rel = win32.relative(winRoot, absolute)
        if (rel !== '' && !rel.startsWith('..') && !/^[A-Za-z]:/.test(rel)) {
          return `${mapping.linuxRoot.replace(/\/$/, '')}/${rel.split('\\').join('/')}`
        }
      }
      return windowsPathToWsl(absolute)
    }
    return absolute
  }
  if (kind === 'ssh') {
    if (!winPath) return absolute
    const winRoot = mapping.winRoot ? win32.resolve(String(mapping.winRoot)) : null
    if (!mapping.linuxRoot) {
      throw configError(
        'the plugin is installed on Windows but the SSH target needs the client path',
        'Set config.remotePath to the directory holding the `kde_uia` package on the SSH host (e.g. /opt/dsh/kde-uia).'
      )
    }
    if (!winRoot) return mapping.linuxRoot
    const rel = win32.relative(winRoot, absolute)
    if (rel.startsWith('..') || /^[A-Za-z]:/.test(rel)) throw configError(`cannot map ${absolute} onto the SSH host`, 'Set config.remotePath explicitly.')
    return `${mapping.linuxRoot.replace(/\/$/, '')}/${rel.split('\\').join('/')}`
  }
  return absolute
}

function isAbsoluteOutside(rel) {
  return /^[A-Za-z]:/.test(rel) || rel.startsWith('\\') || rel.startsWith('/')
}

/** Where the bundled client (`<package>/python`) lives on the receiving side. */
export function clientPathFor(packageRoot, kind, config, mapping = {}) {
  const explicit = String(config.remotePath || '').trim()
  if (explicit) {
    if (explicit.startsWith('/') && !/^\/mnt\/[a-z]\//i.test(explicit)) return explicit
    return kind === 'local' ? explicit : windowsPathToWsl(explicit)
  }
  if (kind === 'ssh' && mapping.linuxRoot) return mapping.linuxRoot
  return toRemotePath(join(packageRoot, 'python'), kind, mapping)
}

/**
 * Candidate client roots for discovery, best first.
 * @param {string} kind
 * @param {RuntimeConfig} config
 * @param {string} packageRoot
 * @param {object} mapping
 */
export function clientCandidates(kind, config, packageRoot, mapping = {}) {
  const explicit = String(config.remotePath || '').trim()
  if (explicit) {
    if (kind === 'local') return [explicit]
    return [explicit.startsWith('/') && !/^\/mnt\/[a-z]\//i.test(explicit) ? explicit : windowsPathToWsl(explicit)]
  }
  if (kind === 'wsl') {
    return ['/opt/dsh/kde-uia', toRemotePath(join(packageRoot, 'python'), 'wsl', mapping)]
  }
  if (kind === 'ssh') return [toRemotePath(join(packageRoot, 'python'), 'ssh', mapping)]
  return [join(packageRoot, 'python'), '/opt/dsh/kde-uia']
}

/**
 * Probe candidates and return the first that answers.
 * @param {Target} target
 * @param {{ config: RuntimeConfig, packageRoot: string, mapping?: object, signal?: AbortSignal }} options
 */
export async function discoverClient(target, options) {
  const python = String(options.config.remotePython || 'python3')
  const candidates = [...new Set(clientCandidates(target.kind, options.config, options.packageRoot, options.mapping ?? {}))]
  const failures = []
  for (const root of candidates) {
    try {
      const document = await opsCall(target, python, root, 'env', {}, { signal: options.signal, timeoutMs: Math.min(target.timeoutMs, 60_000) })
      if (document.ok) return { root, env: document.result ?? {}, python }
      failures.push(`${root}: ${document.error?.code ?? 'ERROR'} ${document.error?.message ?? ''}`.trim())
    } catch (error) {
      failures.push(`${root}: ${describeError(error)}`)
    }
  }
  throw transportError(
    `the kde-uia python client is not reachable in ${target.label}`,
    [
      'Install it inside the Linux environment:',
      '  sudo mkdir -p /opt/dsh && sudo cp -r <plugin>/python /opt/dsh/kde-uia',
      '  Debian/Ubuntu: sudo apt install python3-gi gir1.2-atspi-2.0 at-spi2-core',
      'Check with: wsl -e bash -lc \'PYTHONPATH=/opt/dsh/kde-uia python3 -m kde_uia doctor\'',
      failures.length ? `Probed: ${failures.join(' | ')}` : ''
    ].join('\n')
  )
}

/**
 * Run one client operation and parse its JSON document.
 * @param {Target} target
 * @param {string} python
 * @param {string} root
 * @param {string} op
 * @param {object} args
 * @param {{ signal?: AbortSignal, timeoutMs?: number }} [options]
 */
export async function opsCall(target, python, root, op, args, options = {}) {
  const base = `${root.replace(/\/$/, '')}/.runtime`
  // Plain paths: the shell writes/removes files, and the client resolves the
  // paths itself (a Windows `file://` prefix is not a path bash can create).
  const argsUri = `${base}/args.json`
  const resultUri = `${base}/result.json`
  const payload = Buffer.from(JSON.stringify(args ?? {}), 'utf8').toString('base64')
  const q = quotePosix
  const steps = [
    `mkdir -p ${q(base)}`,
    `printf '%s' ${q(payload)} | base64 -d > ${q(argsUri)}`,
    `PYTHONPATH=${q(root)} ${q(python)} -m kde_uia ops ${q(op)} --args-file ${q(argsUri)} --result ${q(resultUri)}`,
    `cat ${q(resultUri)} 2>/dev/null; :`,
    `rm -f ${q(argsUri)} ${q(resultUri)}`
  ].join('; ')
  const timeoutMs = options.timeoutMs ?? target.timeoutMs
  const { text } = await target.run(['bash', '-lc', steps], { signal: options.signal, timeoutMs })
  return parseDocument(text)
}

/** Extract the last JSON document from mixed output. */
export function parseDocument(text) {
  const trimmed = String(text ?? '').trim()
  if (!trimmed) throw transportError('the kde-uia client returned no output', 'Check that python3 and the client are installed (see runtime notes).')
  // The answer is one top-level JSON object, but transport noise can precede
  // *and* follow it (WSL prints PATH warnings on stderr, merged after stdout).
  // Scan balanced `{ … }` objects and keep the last one that parses as an
  // ok/error document.
  const attempts = [trimmed]
  const starts = []
  for (let index = 0; index < trimmed.length; index += 1) if (trimmed[index] === '{') starts.push(index)
  for (const start of starts.reverse()) {
    const end = balancedObjectEnd(trimmed, start)
    if (end > start) attempts.push(trimmed.slice(start, end + 1))
  }
  const first = trimmed.indexOf('{')
  if (first > 0) attempts.push(trimmed.slice(first))
  let parsed
  for (const candidate of attempts) {
    try {
      const document = JSON.parse(candidate)
      if (document && typeof document === 'object' && ('ok' in document || 'error' in document)) parsed = document
    } catch {
      // try the next candidate
    }
  }
  if (parsed) return parsed
  throw transportError('the kde-uia client produced no JSON answer', `Transport output (tail): ${trimmed.slice(-1200)}`)
}

/** Index of the `}` closing the object opened at `start`, honouring strings. */
function balancedObjectEnd(text, start) {
  let depth = 0
  let inString = false
  for (let index = start; index < text.length; index += 1) {
    const char = text[index]
    if (inString) {
      if (char === '\\') index += 1
      else if (char === '"') inString = false
      continue
    }
    if (char === '"') inString = true
    else if (char === '{') depth += 1
    else if (char === '}') {
      depth -= 1
      if (depth === 0) return index
    }
  }
  return -1
}

export function configError(message, hint) {
  return codedError(message, 'CONFIG', hint)
}

export function transportError(message, hint) {
  return codedError(message, TRANSPORT_INCOMPLETE, hint)
}

function codedError(message, code, hint) {
  const error = new Error(message)
  error.code = code
  if (hint) error.hint = hint
  return error
}

export function describeError(error) {
  if (error === undefined || error === null) return 'unknown error'
  const message = typeof error === 'object' && typeof error.message === 'string' && error.message ? error.message : String(error)
  const code = typeof error === 'object' && error.code ? ` [${error.code}]` : ''
  return `${message}${code}`
}

export { readFileSync }
