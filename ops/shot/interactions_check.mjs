// 互动 P1 + 「新开一个对话」核验（2026-09-19，用户要求：主 agent 要接入互动；对话要能新开）。
//
// 断言（对着**真后端**跑，127.0.0.1:5178 + :8000）：
//   A) 说「帮我回复一下：<贴进来的评论>」→ 真起草一句，且草稿**只落盘**：
//      var/interactions/drafts.jsonl 必须多一行、那一行的 commentText 就是贴进去的那段、sent=false
//      —— 这是「起草 ≠ 发送」在磁盘上的证据（不是靠界面文案自证）；
//   B) 「新开一个对话」：先有确认框，确认后问答被清掉（起草那条消息消失），页面不报错；
//   C) 说「看看评论」→ 主 agent 真去读一遍（只读）：读到的条数或读不到的原因都要说出来；
//      读完之后**没有**任何「回复/发送」按钮，也不会有卡片一直挂在「正在照做…」；
//   D) 控制台 0 错误。
//
// 顺序有意为之：把**最慢**的那步（读一遍平台会真开一次浏览器，几十秒到几分钟，见
// docs/xhs-account-safety.md）放在最后，读慢了也不会挡住前面几条断言。
//
// 用法：node ops/shot/interactions_check.mjs   （截图落在 docs/evidence/）

import { chromium } from 'playwright'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

function findShell() {
  const base = process.env.HOME + '/.cache/ms-playwright'
  for (const d of existsSync(base) ? readdirSync(base) : []) {
    const p = base + '/' + d + '/chrome-headless-shell-linux64/chrome-headless-shell'
    if (d.startsWith('chromium_headless_shell') && existsSync(p)) return p
  }
}

const WS = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const BASE = process.env.PAPERCAST_WEB ?? 'http://127.0.0.1:5178/'
const DRAFTS = WS + '/var/interactions/drafts.jsonl'

const draftRows = () => {
  try {
    return readFileSync(DRAFTS, 'utf8').split('\n').filter((l) => l.trim())
  } catch {
    return []
  }
}

const browser = await chromium.launch({ executablePath: findShell(), args: ['--no-sandbox', '--disable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } })
/**
 * 控制台错误分两堆：
 * - errors：**我们的代码**真报错，必须为 0；
 * - hmrErrors：带 ?t=<时间戳> 的模块 URL —— 那是 Vite 热更新把模块换掉了。本仓库常有别的会话在同时改
 *   前端（poster / 作品库 / …），它们一保存就会让**正在跑的这一页**换模块，偶尔冒出
 *   「_ctx.xxx is not a function」这类刷新瞬间的报错，与本次核验无关（2026-09-19 实测踩到）。
 *   所以单独记下来、不算失败，但也不藏起来。
 */
const errors = []
const hmrErrors = []
const isHmr = (t) => /\?t=\d+/.test(t)
page.on('console', (m) => {
  if (m.type() !== 'error') return
  const t = m.text().slice(0, 200)
  ;(isHmr(t) ? hmrErrors : errors).push(t)
})
page.on('pageerror', (e) => {
  const t = 'pageerror ' + e.message.slice(0, 200)
  ;(isHmr(t) ? hmrErrors : errors).push(t)
})

await page.goto(BASE, { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.composer textarea', { timeout: 20000 })
await page.waitForTimeout(2000)

async function say(text) {
  // 等输入框可用：上一句若是长动作，按钮会显示「开始中…」（只读动作已经不再冻住整轮，见 stores/chat.ts）
  await page
    .waitForFunction(() => {
      const b = document.querySelector('.composer .btn.primary')
      return !!b && !b.disabled
    }, null, { timeout: 240000 })
    .catch(() => {})
  await page.fill('.composer textarea', text)
  await page.click('.composer .btn.primary')
}

const agentTexts = () =>
  page.evaluate(() => Array.from(document.querySelectorAll('.msg-agent .text')).map((e) => e.innerText.trim()))

const result = {}
async function dump(tag) {
  result[tag] = await page.evaluate(() => ({
    texts: Array.from(document.querySelectorAll('.msg-agent .text')).map((e) => e.innerText.trim().slice(0, 140)),
    toasts: Array.from(document.querySelectorAll('.toast')).map((e) => e.innerText.trim().slice(0, 140)),
  }))
}

// ---- A) 起草：只落盘 ----
const COMMENT = '图表里的那个对比实验，样本量是不是有点小？'
const before = draftRows().length
await say('帮我回复一下：' + COMMENT)
try {
  await page.waitForFunction(
    () => Array.from(document.querySelectorAll('.msg-agent .text')).some((e) => e.innerText.includes('起草好了')),
    null,
    { timeout: 120000 },
  )
} catch {
  await dump('draft_timeout')
}
result.draft = await page.evaluate(() => {
  const el = Array.from(document.querySelectorAll('.msg-agent .text')).filter((e) => e.innerText.includes('起草好了')).pop()
  return {
    text: el?.innerText.trim().slice(0, 240) ?? '',
    bullets: Array.from(el?.parentElement?.querySelectorAll('.bullets li') ?? []).map((e) => e.innerText.trim().slice(0, 200)),
  }
})
const rows = draftRows()
result.draft_lines = { before, after: rows.length }
result.draft_disk = rows.length
  ? (() => {
      const d = JSON.parse(rows[rows.length - 1])
      return { id: d.id, sent: d.sent, stage: d.stage, commentText: d.commentText, reply: (d.reply ?? '').slice(0, 120), model: d.model }
    })()
  : null
await page.screenshot({ path: WS + '/docs/evidence/interactions-draft.png' })

// ---- B) 新开一个对话 ----
result.thread_before = await page.evaluate(() => ({
  user: document.querySelectorAll('.msg-user').length,
  hasDraftMsg: Array.from(document.querySelectorAll('.msg-agent .text')).some((e) => e.innerText.includes('起草好了')),
}))
await page.locator('.composer button', { hasText: '新开一个对话' }).first().click()
await page.waitForSelector('.sheet-title', { timeout: 10000 }).catch(() => {})
result.new_thread_dialog = await page.evaluate(() => {
  const t = document.querySelector('.sheet-title')
  const btns = Array.from(document.querySelectorAll('.sheet button')).map((b) => b.innerText.trim())
  return { title: t?.innerText.trim() ?? '', buttons: btns }
})
await page.locator('.sheet button', { hasText: '新开' }).first().click()
await page.waitForTimeout(1200)
result.thread_after = await page.evaluate(() => ({
  user: document.querySelectorAll('.msg-user').length,
  hasDraftMsg: Array.from(document.querySelectorAll('.msg-agent .text')).some((e) => e.innerText.includes('起草好了')),
  // 注意：主按钮在输入框为空时本来就禁用，所以这里看的是「能不能接着说话」= 没卡在忙
  canSpeak: !document.querySelector('.composer .box')?.classList.contains('busy'),
}))
await page.screenshot({ path: WS + '/docs/evidence/chat-new-thread.png' })

// ---- C) 读一遍评论：只读（最慢的一步放最后） ----
const armedBeforeRead = await page.locator('.act button').count()
await say('看看评论')
await page.waitForTimeout(1200)
result.reading_state = await page.evaluate(() => {
  const el = document.querySelector('.act-wait')
  return el ? el.innerText.trim() : null
})
try {
  await page.waitForFunction(
    () => {
      // 只认**结果那条**：开场白里也有「读不到我会直接说……」这几个字，用 includes 会提前命中（踩过）
      return Array.from(document.querySelectorAll('.msg-agent .text')).some((el) => /^(读到 |这次没读到评论|没做成)/.test(el.innerText.trim()))
    },
    null,
    { timeout: 300000 },
  )
} catch {
  await dump('read_timeout')
}
result.read = await page.evaluate(() => {
  const el = Array.from(document.querySelectorAll('.msg-agent .text')).filter((e) => /^(读到 |这次没读到评论|没做成)/.test(e.innerText.trim())).pop()
  return {
    text: el?.innerText.trim().slice(0, 240) ?? '',
    bullets: Array.from(el?.parentElement?.querySelectorAll('.bullets li') ?? []).map((e) => e.innerText.trim().slice(0, 120)),
  }
})
result.wait_line_cleared = (await page.locator('.act-wait').count()) === 0
result.send_buttons = await page.evaluate(() =>
  Array.from(document.querySelectorAll('button')).map((b) => b.innerText.trim()).filter((t) => /^(回复|发送|发布|回他|回一下)$/.test(t)),
)
result.read_new_armed_cards = (await page.locator('.act button').count()) - armedBeforeRead
await page.screenshot({ path: WS + '/docs/evidence/interactions-read.png' })

result.console_errors = errors
result.console_errors_hmr = hmrErrors
console.log(JSON.stringify(result, null, 1))
await browser.close()

const fail = []
if (!result.draft.text) fail.push('没等到起草结果')
if (result.draft_lines.after !== result.draft_lines.before + 1) fail.push('草稿没有落盘：' + JSON.stringify(result.draft_lines))
if (result.draft_disk?.sent !== false) fail.push('草稿的 sent 不是 false')
if (result.draft_disk && !String(result.draft_disk.commentText).includes('样本量')) fail.push('落盘那条草稿的评论原文对不上')
if (!result.new_thread_dialog.title.includes('新开一个对话')) fail.push('「新开一个对话」没有确认框：' + JSON.stringify(result.new_thread_dialog))
if (result.thread_after.hasDraftMsg) fail.push('新开之后问答没清干净（起草那条还挂着）')
if (result.thread_after.user >= result.thread_before.user && result.thread_before.user > 0) fail.push('新开之后你说过的话没清掉')
if (!result.read.text) fail.push('没等到读评论的结果')
if (result.send_buttons.length) fail.push('冒出了发送类按钮：' + result.send_buttons.join('/'))
if (result.read_new_armed_cards > 0) fail.push('只读动作摆了 ' + result.read_new_armed_cards + ' 张待点卡片')
if (!result.wait_line_cleared) fail.push('读完了「正在照做…」还赖着不走')
if (errors.length) fail.push('控制台有 ' + errors.length + ' 条错误')
if (fail.length) {
  console.error('\n[interactions_check] 失败：\n- ' + fail.join('\n- '))
  process.exit(1)
}
console.error('\n[interactions_check] 通过：起草只落盘（sent=false）+ 新开对话清干净 + 只读读一遍 + 无发送按钮 + 控制台 0 错误')
