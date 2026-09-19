// 工作台「用对话发任务」核验（2026-09-19，用户要求：主 agent 要能用对话派活，不只是问答）。
//
// 断言四件事（对着**真后端**跑，127.0.0.1:5178 + :8000）：
//   1) 只读动作（看数据）自动执行：先说一句「我去各平台取一遍…」，随后补一条**一句话结论**；
//   2) 有副作用的动作（重跑一遍）只出卡片、不动手：卡片有确认按钮 + 「先不做」，点了「先不做」就收起来；
//   3) 普通的提问不产生任何卡片（不许硬塞动作）；
//   4) 控制台 0 错误。
//
// 注意：**这个脚本不会点任何会真发出去的动作**（发布/投递/起停服务都不碰）。
// 运营数据先由调用方预热一次缓存（后端 60s 缓存），避免脚本自己去撞小红书的浏览器预算。
//
// 用法：node ops/shot/chat_action_check.mjs   （截图落在 docs/evidence/）

import { chromium } from 'playwright'
import { existsSync, readdirSync } from 'node:fs'
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

// 先预热后端 60s 缓存：这一条脚本要断言「取数据」，而每次未命中都要**真开一次浏览器**
// （小红书那条尤其敏感，见 docs/xhs-account-safety.md）。预热一次，界面上的那次就命中缓存。
try {
  const t0 = Date.now()
  await fetch('http://127.0.0.1:8000/api/ops/metrics')
  console.error(`[warm] 运营数据缓存已预热 ${Date.now() - t0}ms`)
} catch (e) {
  console.error('[warm] 后端不可达，跳过预热：' + e.message)
}

const browser = await chromium.launch({ executablePath: findShell(), args: ['--no-sandbox', '--disable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } })
const errors = []
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 160)) })
page.on('pageerror', (e) => errors.push('pageerror ' + e.message.slice(0, 160)))

await page.goto(BASE, { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.composer textarea', { timeout: 20000 })
await page.waitForTimeout(2000)

/** 像用户那样说一句话（点「开始」而不是回车，和真人一致） */
async function say(text) {
  await page.fill('.composer textarea', text)
  await page.click('.composer .btn.primary')
}

/** 等最后一条助手消息里出现某个片段 */
async function waitForText(fragment, timeout = 30000) {
  await page.waitForFunction(
    (f) => Array.from(document.querySelectorAll('.msg-agent .text')).some((el) => el.innerText.includes(f)),
    fragment,
    { timeout },
  )
}

const result = {}

// ---- 1) 只读动作：自动执行 + 一句话结论 ----
async function dump(tag) {
  result[tag] = await page.evaluate(() => ({
    texts: Array.from(document.querySelectorAll('.msg-agent .text')).map((e) => e.innerText.trim().slice(0, 110)),
    toasts: Array.from(document.querySelectorAll('.toast')).map((e) => e.innerText.trim().slice(0, 140)),
  }))
}

await say('看下现在的数据')
await waitForText('我去各平台取一遍', 45000)
result.readonly_card = await page.locator('.act').count() // 只读动作不摆卡片
// 结论只有两种合法形态：① 真读到数字（…条内容）；② 如实说读不到。等不到就把现场打出来。
try {
  await page.waitForFunction(
    () => {
      const els = Array.from(document.querySelectorAll('.msg-agent .text'))
      const last = els[els.length - 1]?.innerText ?? ''
      return last.includes('条内容') || last.includes('读不到任何数字') || last.includes('没做成')
    },
    null,
    { timeout: 180000 },
  )
} catch {
  await dump('readonly_timeout')
}
result.readonly_conclusion = await page.evaluate(() => {
  const els = Array.from(document.querySelectorAll('.msg-agent .text'))
  return els[els.length - 1]?.innerText.trim().slice(0, 120) ?? ''
})
await page.screenshot({ path: WS + '/docs/evidence/chat-action-metrics.png' })

// ---- 2) 有副作用的动作：只出卡片，点了「先不做」就收起 ----
await say('重新跑一遍')
await page.waitForSelector('.act', { timeout: 30000 })
result.rerun = await page.evaluate(() => {
  const act = document.querySelector('.act')
  return {
    title: act.querySelector('.act-t')?.innerText.trim() ?? '',
    buttons: Array.from(act.querySelectorAll('button')).map((b) => b.innerText.trim()),
  }
})
await page.screenshot({ path: WS + '/docs/evidence/chat-action-card.png' })
// 点「先不做」：卡片必须收起来，且**不能**开新的一遍（页面上不该出现新的运行）
const runsBefore = await page.evaluate(() => document.querySelectorAll('.rail-side .item').length)
await page.locator('.act button', { hasText: '先不做' }).first().click()
await page.waitForTimeout(1200)
result.dismissed = await page.evaluate(() => {
  const act = document.querySelector('.act')
  return {
    buttonsLeft: act.querySelectorAll('button').length,
    note: act.querySelector('.act-note')?.innerText.trim() ?? '',
  }
})
const runsAfter = await page.evaluate(() => document.querySelectorAll('.rail-side .item').length)
result.no_side_effect = runsBefore === runsAfter
await page.screenshot({ path: WS + '/docs/evidence/chat-action-dismissed.png' })

// ---- 3) 普通提问不产生卡片 ----
// 注意：收起来的旧卡片仍留在对话里（那是历史记录），所以这里数的是**还带按钮的**卡片
const armedBefore = await page.locator('.act button').count()
await say('这篇论文的局限是什么')
await page.waitForTimeout(9000)
result.plain_question_new_cards = (await page.locator('.act button').count()) - armedBefore
result.plain_question_last = await page.evaluate(() => {
  const els = Array.from(document.querySelectorAll('.msg-agent .text'))
  return els[els.length - 1]?.innerText.trim().slice(0, 100) ?? ''
})

result.console_errors = errors
console.log(JSON.stringify(result, null, 1))
await browser.close()
