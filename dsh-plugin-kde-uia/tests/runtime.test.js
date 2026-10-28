/**
 * Runtime tests: quoting, path mapping, transports, discovery and the JSON
 * protocol. No network, no WSL and no desktop: the runner captures the argv
 * the plugin would submit.
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  buildTarget,
  clientCandidates,
  clientPathFor,
  createProcessRunner,
  discoverClient,
  opsCall,
  parseDocument,
  quoteArgv,
  quotePosix,
  quotePwsh,
  toRemotePath,
  windowsPathToWsl
} from '../lib/runtime.js'

/** Collect argv without spawning anything. */
function recordingRunner(replies = []) {
  const calls = []
  const queue = [...replies]
  const run = async (argv, opts = {}) => {
    calls.push({ argv, opts })
    const reply = queue.length ? queue.shift() : '{"ok":true,"result":{}}'
    if (reply instanceof Error) throw reply
    return { text: typeof reply === 'function' ? reply(argv) : reply }
  }
  return { run, calls }
}

const winHost = { platform: 'win32', env: { SystemRoot: 'C:\\Windows' }, pathExists: () => true }

test('POSIX quoting protects every shell metacharacter', () => {
  assert.equal(quotePosix('plain'), 'plain')
  assert.equal(quotePosix('a b'), "'a b'")
  assert.equal(quotePosix("it's"), "'it'\\''s'")
  assert.equal(quotePosix('$(id)'), "'$(id)'")
  assert.equal(quotePosix('`id`'), "'`id`'")
  assert.equal(quotePosix('a\nb'), "'a\nb'")
  assert.equal(quotePosix(''), "''")
  assert.equal(quotePwsh("C:\\it's\\x"), "'C:\\it''s\\x'")
  assert.equal(quoteArgv(['bash', '-lc', 'echo "$HOME"']), "bash -lc 'echo \"$HOME\"'")
})

test('Windows paths map into WSL paths', () => {
  assert.equal(windowsPathToWsl('C:\\Users\\me\\app'), '/mnt/c/Users/me/app')
  assert.equal(windowsPathToWsl('D:/data'), '/mnt/d/data')
})

test('toRemotePath maps a checkout into /opt when configured', () => {
  const mapping = { winRoot: 'C:\\src', linuxRoot: '/opt/dsh/kde-uia' }
  assert.equal(toRemotePath('C:\\src\\python\\kde_uia', 'wsl', mapping), '/opt/dsh/kde-uia/python/kde_uia')
  assert.equal(toRemotePath('C:\\elsewhere\\x', 'wsl', mapping), '/mnt/c/elsewhere/x')
  // Non-Windows hosts get identity mapping (paths are host-dependent: this suite runs on Windows too).
  const local = toRemotePath('/opt/dsh/kde-uia/python', 'local', mapping)
  assert.ok(local.endsWith('python'), local)
})

test('WSL transport uses wsl.exe --exec bash -lc with one quoted argv', () => {
  const { run, calls } = recordingRunner()
  const target = buildTarget({ runtime: 'wsl', wslDistribution: 'Ubuntu-24.04', timeoutMs: 1000 }, run, winHost)
  assert.equal(target.kind, 'wsl')
  void target.run(['bash', '-lc', "echo 'hi there'"], { timeoutMs: 10 })
  const argv = calls[0].argv
  assert.equal(argv[0], 'C:\\Windows\\System32\\wsl.exe')
  assert.deepEqual(argv.slice(1, 3), ['-d', 'Ubuntu-24.04'])
  assert.deepEqual(argv.slice(3, 5), ['--exec', 'bash'])
  assert.equal(argv[5], '-lc')
  assert.equal(argv[6], "bash -lc 'echo '\\''hi there'\\'''")
})

test('auto picks WSL on Windows and local on Linux', () => {
  const collect = (config, host) => buildTarget(config, async () => ({ text: '' }), host).kind
  assert.equal(collect({ runtime: 'auto' }, winHost), 'wsl')
  assert.equal(collect({ runtime: 'auto' }, { platform: 'linux' }), 'local')
  assert.equal(collect({ runtime: 'local' }, { platform: 'linux' }), 'local')
  assert.equal(collect({ runtime: 'wsl' }, { platform: 'linux' }), 'local')
})

test('ssh without a host is a config error', () => {
  assert.throws(() => buildTarget({ runtime: 'ssh' }, async () => ({ text: '' }), winHost), /sshHost/)
})

test('ssh on Windows wraps ssh.exe in PowerShell and keeps the inner command POSIX', () => {
  const { run, calls } = recordingRunner()
  const target = buildTarget({ runtime: 'ssh', sshHost: 'me@kdebox', sshIdentity: 'C:\\keys\\id_ed25519', sshOptions: ['StrictHostKeyChecking=yes'], timeoutMs: 1000 }, run, winHost)
  void target.run(['bash', '-lc', "env | grep HOME"], {})
  const argv = calls[0].argv
  assert.deepEqual(argv.slice(0, 5), ['pwsh', '-NoProfile', '-NonInteractive', '-Command', argv[4]])
  const command = argv[4]
  assert.match(command, /'C:\\Windows\\System32\\OpenSSH\\ssh.exe'/)
  assert.match(command, /-i 'C:\\keys\\id_ed25519'/)
  assert.match(command, /-o 'StrictHostKeyChecking=yes'/)
  assert.match(command, /'me@kdebox'/)
  // The inner bash command is PowerShell-quoted once; `''` is the PowerShell
  // escape, and the remote bash only ever sees the plain command text.
  assert.match(command, /bash -lc 'bash -lc ''env \| grep HOME'''/)
})

test('opsCall base64-encodes arguments so no quoting can change them', async () => {
  let captured
  const run = async (argv, opts = {}) => {
    // The last element is the whole `bash -lc <steps>` command line; find the
    // base64 payload after `-d >` regardless of how the quote characters print.
    const script = argv[argv.length - 1]
    const match = /([A-Za-z0-9+/]{8,}={0,2})\s*\| base64 -d/.exec(script)
    assert.ok(match, `script must pipe a base64 payload: ${script}`)
    captured = JSON.parse(Buffer.from(match[1], 'base64').toString('utf8'))
    return { text: JSON.stringify({ ok: true, result: { echoed: captured } }) }
  }
  const target = buildTarget({ runtime: 'local', timeoutMs: 1000 }, run, { platform: 'linux' })
  const tricky = { key: "it's \"quoted\"\nline2 — 中文 '\\' $HOME `id`" }
  const document = await opsCall(target, 'python3', '/opt/kde-uia', 'press', tricky)
  assert.deepEqual(captured, tricky)
  assert.deepEqual(document.result.echoed, tricky)
})

test('parseDocument finds the JSON answer in noisy transport output', () => {
  assert.deepEqual(parseDocument('{"ok":true,"result":{"a":1}}'), { ok: true, result: { a: 1 } })
  assert.deepEqual(parseDocument('noise\nmore noise\n{"ok":false,"error":{"code":"X"}}\n') , { ok: false, error: { code: 'X' } })
  assert.deepEqual(parseDocument('stderr: warning\n{\n "ok": true,\n "result": 2\n}\n'), { ok: true, result: 2 })
  assert.throws(() => parseDocument(''), /no output/)
  assert.throws(() => parseDocument('python3: command not found'), /no JSON answer/)
})

test('discovery tries candidates in order and reports every failure', async () => {
  const { run, calls } = recordingRunner(['{"ok":false,"error":{"code":"ATSPI_UNAVAILABLE","message":"no gi"}}', '{"ok":true,"result":{"platform":"linux"}}'])
  const target = buildTarget({ runtime: 'wsl', timeoutMs: 1000 }, run, winHost)
  const found = await discoverClient(target, { config: { runtime: 'wsl', remotePython: 'python3', timeoutMs: 1000 }, packageRoot: 'C:\\plugins\\dsh-plugin-kde-uia', mapping: { winRoot: 'C:\\plugins\\dsh-plugin-kde-uia' } })
  assert.equal(found.root, '/mnt/c/plugins/dsh-plugin-kde-uia/python')
  assert.equal(calls.length, 2)

  const failing = recordingRunner(['{"ok":false,"error":{"code":"ATSPI_UNAVAILABLE","message":"no gi"}}', '{"ok":false,"error":{"code":"ATSPI_UNAVAILABLE","message":"no gi"}}'])
  const target2 = buildTarget({ runtime: 'wsl', timeoutMs: 1000 }, failing.run, winHost)
  await assert.rejects(
    discoverClient(target2, { config: { runtime: 'wsl', timeoutMs: 1000 }, packageRoot: 'C:\\p', mapping: { winRoot: 'C:\\p' } }),
    (error) => /not reachable/.test(error.message) && /ATSPI_UNAVAILABLE/.test(error.hint) && /apt install python3-gi/.test(error.hint)
  )
})

test('explicit remotePath skips discovery candidates', async () => {
  const { run, calls } = recordingRunner(['{"ok":true,"result":{}}'])
  const target = buildTarget({ runtime: 'wsl', timeoutMs: 1000 }, run, winHost)
  const found = await discoverClient(target, { config: { runtime: 'wsl', remotePath: '/srv/kde-uia', timeoutMs: 1000 }, packageRoot: 'C:\\p' })
  assert.equal(found.root, '/srv/kde-uia')
  assert.equal(calls.length, 1)
  assert.equal(clientPathFor('C:\\p', 'wsl', { remotePath: 'D:\\tools\\kde-uia' }), '/mnt/d/tools/kde-uia')
})

test('clientCandidates: portable first, checkout last', () => {
  assert.deepEqual(clientCandidates('wsl', {}, 'C:\\p', { winRoot: 'C:\\p' }), ['/opt/dsh/kde-uia', '/mnt/c/p/python'])
  assert.deepEqual(clientCandidates('ssh', { remotePath: '/opt/x' }, 'C:\\p'), ['/opt/x'])
})

test('aborted runs surface as ABORTED, not transport failures', async () => {
  const controller = new AbortController()
  const run = createProcessRunner({ shell: undefined })
  const pending = run(['bash', '-lc', 'sleep 5'], { signal: controller.signal, timeoutMs: 10_000 })
  controller.abort()
  await assert.rejects(pending, (error) => error.code === 'ABORTED')
})
