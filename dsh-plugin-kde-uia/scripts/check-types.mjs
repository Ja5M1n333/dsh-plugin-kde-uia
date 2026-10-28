/**
 * `npm run check:ts` —— 用本机已有的 Node 检查类型模板，**不下载任何东西**。
 *
 * 1. 用 `node --check` 确认 `types/index.ts` 语法正确（Node 24 可直接解析 TS）；
 * 2. 真实导入 `lib/tools.js` / `lib/runtime.js`，逐个确认模板里 import 的名字确实存在；
 * 3. 确认模板里声明的类型（interface）都能在自己的文件里找到定义；
 * 4. 确认 package.json 的 `name` / `inject` / `Config` 与模板一致。
 *
 * 完整的 TypeScript 类型检查（会检查每个字段的类型）需要 `typescript`——
 * 那是可选的：`npm install --no-save typescript @types/node && npm run typecheck`。
 * 注意：不要在插件目录里直接 `npm install <包>`，npm 会顺着 `.cache/asar` 的链接
 * 把整个 DSH 依赖树装进来（曾因此下载 77 MB）；要用时先删掉 `.cache` 或在本目录外安装。
 */

import { spawnSync } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const failures = []
const ok = (message) => console.log(`  [OK]   ${message}`)
const bad = (message) => {
  failures.push(message)
  console.log(`  [FAIL] ${message}`)
}

const templatePath = join(root, 'types', 'index.ts')
const template = await readFile(templatePath, 'utf8')

// 1. 语法
const checked = spawnSync(process.execPath, ['--check', templatePath], { encoding: 'utf8' })
if (checked.status === 0) ok('types/index.ts 语法正确（node --check）')
else bad(`types/index.ts 语法错误：${checked.stderr.split('\n')[0]}`)

// 2. 导入的名字真的存在
const modules = { tools: await import('./../lib/tools.js'), runtime: await import('./../lib/runtime.js'), index: await import('./../lib/index.js') }
const importRe = /import\s+\{([^}]+)\}\s+from\s+'\.\.?\/(?:lib\/)?(tools|runtime|index)\.js'/g
for (const match of template.matchAll(importRe)) {
  const [, rawNames, moduleName] = match
  for (const raw of rawNames.split(',')) {
    const name = raw.replace(/^type\s+/, '').trim()
    if (!name) continue
    if (name in modules[moduleName]) ok(`lib/${moduleName}.js 导出了 ${name}`)
    else bad(`lib/${moduleName}.js 没有导出 ${name}（模板引用了不存在的名字）`)
  }
}

// 3. 模板用到的类型都在文件内定义（全局/内置类型除外）
const used = new Set()
for (const match of template.matchAll(/:\s*(?:Partial<)?([A-Z][A-Za-z]+)(?:>|\b)/g)) used.add(match[1])
// Types provided by the JS runtime / lib.dom / @types/node rather than by this file.
const GLOBAL_TYPES = new Set([
  'AbortSignal', 'Promise', 'Error', 'Record', 'Readonly', 'Array', 'Files', 'String', 'Number', 'Boolean', 'Map', 'Set'
])
for (const name of used) {
  if (GLOBAL_TYPES.has(name)) continue
  if (/^(?:Partial|Readonly|Array|Record|Promise)<$/.test(name)) continue
  if (new RegExp(`export (?:interface|type) ${name}\\b`).test(template)) ok(`类型 ${name} 已定义`)
  else bad(`类型 ${name} 被使用但没有定义`)
}

// 4. 模板与 lib/index.js 的表面一致
const indexModule = modules.index
const declaresName = new RegExp(`export const name = '${indexModule.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}'`).test(template)
declaresName ? ok(`name 与 lib/index.js 一致（${indexModule.name}）`) : bad('模板里的 name 与 lib/index.js 不一致')
const injectMatches = template.includes(`export const inject = [${indexModule.inject.map((d) => `'${d}'`).join(', ')}]`)
injectMatches ? ok(`inject 与 lib/index.js 一致（${indexModule.inject.join(', ')}）`) : bad('模板里的 inject 与 lib/index.js 不一致')
template.includes("format: 'form'") ? ok('Config 声明为 form 形式') : bad('Config 缺少 format: form')

// 5. 可选：真正的 tsc
const tsc = join(root, 'node_modules', 'typescript', 'bin', 'tsc')
try {
  await readFile(tsc)
  const full = spawnSync(process.execPath, [tsc, '--noEmit', '-p', 'tsconfig.types.json'], { cwd: root, encoding: 'utf8' })
  if (full.status === 0) ok('tsc 完整类型检查通过')
  else bad(`tsc 报告了类型错误：\n${full.stdout}`)
} catch {
  console.log('  [SKIP] 没装 typescript，跳过完整类型检查（这是可选的，见脚本头部说明）')
}

console.log(failures.length ? `\ncheck-types: ${failures.length} 个问题` : '\ncheck-types: 全部通过')
process.exit(failures.length ? 1 : 0)
