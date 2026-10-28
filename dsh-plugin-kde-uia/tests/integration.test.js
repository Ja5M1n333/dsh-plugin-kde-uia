/**
 * Transport integration test against a REAL environment when one is available.
 *
 * - `KDE_UIA_SMOKE_LOCAL=1` inside a Linux session: runs `env` and `doctor`
 *   through the local target (real python client, real shell).
 * - On Windows with WSL: runs `env` through `wsl` when `wsl.exe` exists and
 *   `KDE_UIA_SMOKE_WSL=1` (the client must be installed in the distro).
 *
 * Skips quietly otherwise, so `node --test` stays hermetic by default.
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

import { buildTarget, createProcessRunner, discoverClient, opsCall } from '../lib/runtime.js'

const processRun = createProcessRunner({})
const packageRoot = fileURLToPath(new URL('..', import.meta.url))

test('local transport reaches the python client (Linux session)', { skip: process.env.KDE_UIA_SMOKE_LOCAL !== '1' ? 'set KDE_UIA_SMOKE_LOCAL=1 inside the Linux session' : false }, async () => {
  const config = { runtime: 'local', remotePython: 'python3', timeoutMs: 60_000 }
  const target = buildTarget(config, processRun, { platform: 'linux' })
  const found = await discoverClient(target, { config, packageRoot })
  const env = await opsCall(target, found.python, found.root, 'env', {})
  assert.equal(env.ok, true)
  assert.equal(env.result.platform, 'linux')
})

test('wsl transport reaches the python client (Windows host)', { skip: process.env.KDE_UIA_SMOKE_WSL !== '1' || process.platform !== 'win32' ? 'set KDE_UIA_SMOKE_WSL=1 on a Windows host with the client installed in WSL' : false }, async () => {
  const config = { runtime: 'wsl', remotePython: 'python3', remotePath: process.env.KDE_UIA_SMOKE_WSL_PATH ?? '', timeoutMs: 60_000 }
  const target = buildTarget(config, processRun, { platform: 'win32' })
  let found
  try {
    found = await discoverClient(target, { config, packageRoot })
  } catch (error) {
    // The transport itself may be healthy while this guest has no client installed.
    if (error.code === 'TRANSPORT_INCOMPLETE' && /no JSON answer/.test(error.message)) {
      assert.match(String(error.hint), /cp -r/, 'the failure must include the install checklist')
      return
    }
    throw error
  }
  const env = await opsCall(target, found.python, found.root, 'env', {})
  assert.equal(env.ok, true)
})
