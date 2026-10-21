// 个性化风格层 核验 +「Agent 审核已下线」回归
//
// 断言的是「计算出来的东西」，不是「某人说改过了」：
//   1. **Agent 审核那一步确实没了**（2026-09-23 用户要求）：右侧名单不再有「审核」行、
//      对话里不再有 #m-review、闸门上方不再有 .gate-review 那句汇总；
//   2. 风格页列出的是后端从本机只读目录里读到的技能，展开能看到 SKILL.md 原文，
//      换风格会落 localStorage 并在输入框那一行显示出来；
//   3. 控制台 0 错误。
import { chromium } from 'playwright'
import { existsSync, readdirSync } from 'node:fs'
function findShell() {
  const base = process.env.HOME + '/.cache/ms-playwright'
  for (const d of existsSync(base) ? readdirSync(base) : []) {
    const p = base + '/' + d + '/chrome-headless-shell-linux64/chrome-headless-shell'
    if (d.startsWith('chromium_headless_shell') && existsSync(p)) return p
  }
}
const browser = await chromium.launch({ executablePath: findShell(), args: ['--no-sandbox', '--disable-gpu', '--no-proxy-server'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 1050 } })
const errors = []
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 140)) })
page.on('pageerror', (e) => errors.push('pageerror ' + e.message.slice(0, 140)))
page.on('response', (r) => { if (r.status() >= 400) errors.push(r.status() + ' ' + r.url().slice(-44)) })
await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.thread', { timeout: 20000 })
await page.waitForTimeout(3000)

const review = await page.evaluate(() => {
  const rows = [...document.querySelectorAll('.roster li')].map((li) => li.innerText.replace(/\s+/g, ' ').trim())
  return {
    rosterRows: rows,
    // 这几项都应为 false：审核那一步已经下线
    hasReviewRow: rows.some((r) => r.startsWith('审核')),
    hasReviewMessage: !!document.querySelector('#m-review'),
    hasReviewChips: !!document.querySelector('.checks .chk'),
    hasGateReviewLine: !!document.querySelector('.gate-review'),
    gatePresent: !!document.querySelector('.gate'),
  }
})
await page.screenshot({ path: '/home/yydh/hack/docs/evidence/review-flow.png' })

await page.locator('.rail .item[title="风格"]').click()
await page.waitForSelector('.lead-line', { timeout: 20000 })
await page.waitForTimeout(2000)
const stylePage = await page.evaluate(() => ({
  title: document.querySelector('.page-title')?.textContent?.trim(),
  lead: document.querySelector('.lead-line')?.textContent?.replace(/\s+/g, ' ').trim().slice(0, 80),
  src: document.querySelector('.src')?.textContent?.replace(/\s+/g, ' ').trim().slice(0, 60),
  rows: [...document.querySelectorAll('.lines li')].map((li) => li.innerText.replace(/\s+/g, ' ').trim().slice(0, 48)),
  inUse: [...document.querySelectorAll('.lines li')].filter((li) => li.innerText.includes('在用')).length,
}))
await page.locator('.lines li .btn.ghost', { hasText: '看它的规矩' }).first().click()
await page.waitForSelector('.skill-body', { timeout: 20000 })
await page.waitForTimeout(500)
const skillBody = await page.evaluate(() => {
  const t = document.querySelector('.skill-body')?.innerText ?? ''
  return { path: document.querySelector('.src-line')?.innerText.trim(), hasFrontmatter: t.includes('name:'), chars: t.length }
})
await page.screenshot({ path: '/home/yydh/hack/docs/evidence/style-layer.png' })

await page.locator('.lines li .btn', { hasText: '用这个' }).first().click()
await page.waitForSelector('.toast', { timeout: 8000 }).catch(() => {})
const toast = await page.locator('.toast').first().innerText().catch(() => null)
const stored = await page.evaluate(() => localStorage.getItem('papercast.style'))
await page.locator('.rail .item[title="工作台"]').click()
await page.waitForTimeout(1500)
const composerLine = await page.evaluate(
  () => [...document.querySelectorAll('.hint')].map((p) => p.innerText.replace(/\s+/g, ' ').trim()).find((t) => t.startsWith('风格')) ?? null,
)
console.log(JSON.stringify({ review, stylePage, skillBody, toast, stored, composerLine, errors }, null, 1))
const reviewGone = !review.hasReviewRow && !review.hasReviewMessage && !review.hasReviewChips && !review.hasGateReviewLine
console.log(reviewGone ? '[审核下线] 通过：名单无「审核」行、无 #m-review、无检查项、闸门上方无汇总句。' : '[审核下线] 失败：仍能看到审核那一步的痕迹。')
await browser.close()
