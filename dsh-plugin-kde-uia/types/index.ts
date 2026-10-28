/**
 * ⚠️ 这是**模板**文件，不是可加载的插件入口。
 *
 * - 真正的入口是 `lib/index.js`（对照着看）。
 * - 本文件由 `npm run check:ts`（tsc）类型检查，保证模板与真实实现不会「名义上一致、实际对不上」。
 * - 想把它变成真入口：把内容搬到 `lib/index.ts`，删掉 `lib/index.js`，改 package.json 的
 *   `main` 为 `lib/index.ts`（DSH 的 Node 24 可直接执行带类型的 .ts）。
 *
 * 为什么要这份文件：DSH 的核心包都用 TypeScript 编写。把类型写清楚，能让未来接手的人
 * （包括未来的 AI）不必靠猜——「这里到底期望一个什么形状的插件」。项目被学生维护，
 * 接手的人很可能不熟悉 AT-SPI / Cordis，类型就是最好的说明书。
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
  parseDocument,
} from './runtime.js'

// ---------------------------------------------------------------------------
// 运行时配置与目标：与 lib/runtime.js 的 JSDoc 形状一一对应
// ---------------------------------------------------------------------------

/** 与 lib/index.js `normalizeConfig()` 的输出一致。 */
export interface RuntimeConfig {
  runtime: 'auto' | 'wsl' | 'ssh' | 'local'
  wslDistribution: string
  remotePath: string
  remotePython: string
  wslCommand: string
  sshHost: string
  sshIdentity: string
  sshOptions: string[]
  timeoutMs: number
  readOnly: boolean
  doctorOnLoad: boolean
  executable: string
}

/** lib/runtime.js `buildTarget()` 的返回值：一种传输方式。 */
export interface Target {
  readonly kind: 'wsl' | 'ssh' | 'local'
  readonly label: string
  readonly timeoutMs: number
  run(args: string[], options: { signal?: AbortSignal; timeoutMs?: number }): Promise<{ text: string }>
}

/** lib/tools.js `buildTools()` 的参数。 */
export interface BuildToolsOptions {
  defineTool: (definition: ToolDefinition) => ToolDefinition
  call: (op: string, args: any, exec?: ToolExecution) => Promise<unknown>
  readOnly?: boolean
}

// ---------------------------------------------------------------------------
// DSH 的扩展点（只声明本插件用到的部分；签名与 @deepseek-ai/dsh-tools 的公开类型一致）
// ---------------------------------------------------------------------------

/** 工具定义：与 dsh-tools 的 ToolDefinition 对齐（只列本插件用到的字段）。 */
export interface ToolDefinition {
  readonly name: string
  readonly description: string
  readonly parameters: unknown
  readonly output: { readonly schema: unknown; render: (args: any, value: any) => any }
  execute(args: any, exec: ToolExecution): Promise<unknown> | unknown
}

/** 一次调用的执行上下文：本插件只用 `signal` 做取消。 */
export interface ToolExecution {
  readonly signal?: AbortSignal
}

/** 工具注册表服务（`ctx.tools`）。register 返回反注册函数。 */
export interface ToolRegistry {
  register(tool: ToolDefinition): () => void
}

export interface Logger {
  info(message: string): void
  warn(message: string): void
  error(message: string): void
}

/** 本插件用到的 Cordis 上下文子集。 */
export interface PluginContext {
  readonly logger?: Logger
  get(name: 'tools'): ToolRegistry | undefined
  get(name: 'shell'): ((spec: ShellSpec) => Promise<ShellHandle>) | undefined
  get(name: string): unknown
  inject?(deps: string[], callback: (ctx: PluginContext) => void): void
}

export interface ShellSpec {
  readonly argv: readonly string[]
  readonly timeoutMs?: number
  readonly signal?: AbortSignal
  readonly env?: Record<string, string>
  readonly workdir?: string
}

export interface ShellHandle {
  result(): Promise<ShellResult>
}

export interface ShellResult {
  readonly stdout?: { text: string }
  readonly stderr?: { text: string }
  readonly aborted?: boolean
}

// ---------------------------------------------------------------------------
// 插件表面：loader 读取 name / inject / Config / apply
// ---------------------------------------------------------------------------

export const name = 'kde-uia'
export const inject = ['tools'] as const

export const Config = {
  type: 'object',
  format: 'form',
  properties: {
    runtime: { type: 'string', enum: ['auto', 'wsl', 'ssh', 'local'], default: 'auto' },
    wslDistribution: { type: 'string', default: '' },
    remotePath: { type: 'string', default: '' },
    remotePython: { type: 'string', default: 'python3' },
    wslCommand: { type: 'string', default: '' },
    sshHost: { type: 'string', default: '' },
    sshIdentity: { type: 'string', default: '' },
    sshOptions: { type: 'array', items: { type: 'string' }, default: [] },
    timeoutMs: { type: 'number', default: 120_000, minimum: 1000 },
    readOnly: { type: 'boolean', default: false },
    doctorOnLoad: { type: 'boolean', default: true },
    executable: { type: 'string', default: '' },
  },
} as const

/** 插件挂载后可用的句柄：loader 卸载时调用 dispose。 */
export interface KdeUiaPluginHandle {
  dispose(): void
}

export function apply(ctx: PluginContext, rawConfig?: Partial<RuntimeConfig>): KdeUiaPluginHandle {
  const config = normalizeConfig(rawConfig)
  const logger = ctx.logger
  const shell = ctx.get('shell')
  const processRun = createProcessRunner({ shell, shellEnv: ctx.get('shellEnv') as never })
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')

  let target: Target | null = null
  let runtimeError: Error | null = null
  try {
    target = buildTarget(config, processRun)
  } catch (error) {
    runtimeError = error as Error
    logger?.warn?.(`kde-uia: runtime is misconfigured: ${describeError(error)}`)
  }

  const disposers: Array<() => void> = []
  let disposed = false

  const register = async (toolCtx: PluginContext): Promise<void> => {
    const { defineTool } = await import('@deepseek-ai/dsh-tools')
    if (disposed) return
    const tools = buildTools({
      defineTool,
      call: async (op: string, args: never, exec?: ToolExecution) => {
        if (!target) throw configError('kde-uia runtime is misconfigured', 'Fix the plugin configuration.')
        const found = await discoverClient(target, { config, packageRoot: root, signal: exec?.signal })
        const document = await opsCall(target, found.python, found.root, op, args, { signal: exec?.signal })
        if (!document.ok) throw new Error(document.error?.message ?? 'operation failed')
        return document.result
      },
    } as BuildToolsOptions)
    for (const tool of tools) {
      const dispose = toolCtx.get('tools')?.register(tool)
      if (dispose) disposers.push(dispose)
    }
    logger?.info?.(`kde-uia: registered ${disposers.length} tools (${TOOL_PREFIX}*) via ${target?.label ?? 'an invalid runtime'}`)
    if (runtimeError) logger?.warn?.(`kde-uia: ${MUTATING_TOOLS.size} mutating tools are present; fix the runtime before use`)
  }

  if (ctx.inject && !ctx.get('tools')) ctx.inject(['tools'], (toolCtx) => void register(toolCtx))
  else void register(ctx)

  return {
    dispose() {
      disposed = true
      for (const dispose of disposers.splice(0)) dispose()
    },
  }
}

/** 配置归一化：未知键忽略，类型错误抛 CONFIG。与 lib/index.js 的行为一致。 */
export function normalizeConfig(raw?: Partial<RuntimeConfig>): RuntimeConfig {
  const config: RuntimeConfig = {
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
    executable: '',
    ...(raw ?? {}),
  }
  if (!['auto', 'wsl', 'ssh', 'local'].includes(config.runtime)) {
    throw configError(`config.runtime must be one of auto, wsl, ssh, local (got ${JSON.stringify(config.runtime)})`)
  }
  if (!Number.isFinite(config.timeoutMs) || config.timeoutMs < 1000) {
    throw configError('config.timeoutMs must be a number >= 1000')
  }
  return config as RuntimeConfig
}

export { clientPathFor, parseDocument }
