/**
 * 生成仓库里的 WORKFLOW.md —— 会话日志自动导出的开发记录。
 * 用法: node gen-workflow.mjs <events.jsonl> <output.md>
 */
import { readFileSync, writeFileSync } from 'node:fs'

const [src, out] = process.argv.slice(2)
const all = readFileSync(src, 'utf8')
  .split('\n')
  .filter(Boolean)
  .map((line) => JSON.parse(line))
  .sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0))

const textOf = (content) =>
  (content ?? [])
    .filter((p) => p.type === 'text' && p.text)
    .map((p) => p.text)
    .join('\n')
    .trim()

const toolNames = {}
const userTurns = []
let current = null
let toolTotal = 0

for (const e of all) {
  if (e.type === 'user/message' && e.data?.source?.kind === 'user') {
    const text = textOf(e.data.content)
    if (!text) continue
    current = { prompt: text, tools: [], time: e.time }
    userTurns.push(current)
    continue
  }
  if (e.type === 'tool/call' && current) {
    const name = e.data?.name ?? e.data?.toolName
    if (name) {
      toolTotal += 1
      toolNames[name] = (toolNames[name] ?? 0) + 1
      current.tools.push(name)
    }
  }
}

// 跳过系统注入的提醒等，只保留用户真正说的话
const turns = userTurns.filter((t) => t.prompt.length > 2)
const first = turns[0]?.time
const last = turns.at(-1)?.time
const days = first && last ? Math.max(1, Math.round((last - first) / 86400000)) : 0
const fmt = (ms) => (ms ? new Date(ms).toISOString().slice(0, 10) : '?')

const lines = []
lines.push('# 开发记录：这一版是怎么做出来的')
lines.push('')
lines.push('> 这份文件由 DeepSeek Harness 的会话日志**自动导出**（`scripts/publish/gen-workflow.mjs`），')
lines.push('> 记录的是插件最初一版从零到第一次推送的完整对话流水。它不是文档，而是一份"过程证据"：')
lines.push('> 可以看到需求是怎么一步步提出来、踩了哪些坑、又是怎么修的。')
lines.push('')
lines.push('## 概览')
lines.push('')
lines.push('| 项目 | 数值 |')
lines.push('|---|---|')
lines.push(`| 对话轮次 | ${turns.length} 轮 |`)
lines.push(`| 工具调用 | ${toolTotal} 次 |`)
lines.push(`| 时间跨度 | ${fmt(first)} → ${fmt(last)}（约 ${days} 天，中间有多次休息） |`)
lines.push(`| 用到的工具 | ${Object.entries(toolNames).sort((a, b) => b[1] - a[1]).map(([n, c]) => `\`${n}\`×${c}`).join('、')} |`)
lines.push('')
lines.push('## 对话轮次')
lines.push('')
lines.push('下面每一节对应作者提出的一个需求（或一次追问），括号里是这一轮里 AI 实际动用的工具。')
lines.push('')

turns.forEach((turn, i) => {
  const firstLine = turn.prompt.split('\n')[0].trim()
  const title = firstLine.length > 70 ? firstLine.slice(0, 70) + '…' : firstLine
  lines.push(`### ${i + 1}. ${title.replace(/^#+\s*/, '')}`)
  lines.push('')
  if (turn.tools.length) {
    const counts = {}
    for (const t of turn.tools) counts[t] = (counts[t] ?? 0) + 1
    const summary = Object.entries(counts).map(([n, c]) => `${n}×${c}`).join('、')
    lines.push(`<sub>工具：${summary}</sub>`)
    lines.push('')
  }
})

lines.push('---')
lines.push('')
lines.push('## 说明')
lines.push('')
lines.push('- 原始日志是 DSH 会话文件（zstd 压缩的 jsonl），这里只提取了"用户说了什么 + 每轮调用了哪些工具"。')
lines.push('- 工具调用的**具体参数和输出**没有导出：里面有大量文件内容、路径和命令，不适合公开发布。')
lines.push('- 想复现这个版本的仓库状态：`git log` 里第一个提交即可。')
lines.push('')

const md = lines.join('\n')
writeFileSync(out, md, 'utf8')
console.log(`已写出 ${out}：${turns.length} 轮，${toolTotal} 次工具调用，${md.length} 字符`)
