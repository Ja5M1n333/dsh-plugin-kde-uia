/**
 * Bridge smoke test against a LIVE transport (WSL or SSH) from the host that
 * runs DSH. It exercises the production path end to end:
 *   wsl.exe --exec bash -lc … → python3 -m kde_uia ops … → JSON document.
 *
 * Usage (from Windows with WSL, client installed in the distro):
 *   node scripts/smoke-bridge.mjs
 *   KDE_UIA_CLIENT=/opt/dsh/kde-uia node scripts/smoke-bridge.mjs
 *
 * It also proves the base64 argument transport survives quotes, newlines,
 * Unicode and shell metacharacters by round-tripping through a real call whose
 * error details echo the arguments back.
 */

import { fileURLToPath } from 'node:url'

import { buildTarget, createProcessRunner, opsCall } from '../lib/runtime.js'

const clientRoot = process.env.KDE_UIA_CLIENT ?? '/opt/dsh/kde-uia'
const processRun = createProcessRunner({})
const target = buildTarget({ runtime: 'wsl', timeoutMs: 60_000 }, processRun, { platform: 'win32' })
console.log(`transport: ${target.label} -> client ${clientRoot}`)

async function call(op, args) {
  try {
    return await opsCall(target, 'python3', clientRoot, op, args)
  } catch (error) {
    if (error.code !== 'TRANSPORT_INCOMPLETE') throw error
    console.log('client not installed at', clientRoot)
    console.log(error.hint)
    process.exit(2)
  }
}

const env = await call('env', {})
console.log('env:', env.ok ? `${env.result.platform}/${env.result.sessionType} (gui=${env.result.guiContext})` : env.error)

const doctor = await call('doctor', {})
if (doctor.ok) {
  for (const check of doctor.result.checks) console.log(` ${check.status === 'ok' ? '[+]' : check.status === 'skip' ? '[-]' : '[x]'} ${check.check}: ${check.detail}`)
} else {
  console.log('doctor:', doctor.error?.code, doctor.error?.message)
}

const windows = await call('windows', {})
console.log('windows:', windows.ok ? `${windows.result.count} window(s)` : `${windows.error.code}: ${windows.error.message}`)

// Argument transport: a key combination that cannot exist echoes back in the
// transport error, so the whole argv round-trip is observable without a desktop.
const tricky = "it's \"quoted\"\nline2 — 中文 '\\' $HOME `id` ; $(whoami) ; rm -rf /"
const press = await call('press', { key: tricky })
const echoed = press.ok ? JSON.stringify(press.result) : `${press.error?.message ?? ''} ${press.error?.hint ?? ''}`
// The hint quotes the received value with Python repr escapes, so compare the
// fragments that prove the round trip: Unicode, quote, dollar/backtick payload.
const survived = ['中文', '$(whoami)', '`id`', '\\\'', '"quoted"'].every((fragment) => echoed.includes(fragment))
console.log('argument transport survived shell quoting:', survived ? 'yes' : `NO — got: ${echoed.slice(0, 300)}`)

function describe(value) {
  return JSON.stringify(value)
}
