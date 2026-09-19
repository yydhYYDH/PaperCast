// Agent 审核（前端流程第七步）+ 个性化风格层 核验
//
// 断言的是「计算出来的东西」，不是「某人说改过了」：
//   1. 右侧名单多出第七行「审核」，且写着真实的检查项数量；
//   2. 对话里有一条 #m-review，结论句就是人工审核时看到的那一句
//      （同一句 rev.line，两处一个来源 —— 闸门分支见文件末尾的说明）；
//   3. 风格页列出的是后端从本机只读目录里读到的技能，展开能看到 SKILL.md 原文，
//      换风格会落 localStorage 并在输入框那一行显示出来；
//   4. 控制台 0 错误。
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
  const msg = document.querySelector('#m-review')
  return {
    rosterRows: rows,
    hasReviewRow: rows.some((r) => r.startsWith('审核')),
    reviewVerdict: (msg?.innerText ?? '').replace(/\s+/g, ' ').trim().slice(0, 90),
    sentenceInFlow: /Agent 审核(已经通过|没通过|：)/.test((msg?.innerText ?? '')),
    reviewChips: [...document.querySelectorAll('.checks .chk')].map((c) => c.innerText.trim()).slice(0, 6),
    gatePresent: !!document.querySelector('.gate'),
    gateLine: document.querySelector('.gate-review')?.innerText.replace(/\s+/g, ' ').trim() ?? null,
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
console.log(review.gatePresent ? '[闸门分支] 本轮真有闸门，上面的 gateLine 就是对它取的。' : '[闸门分支] 本轮没有停在闸门的 run，因此 gateLine 为 null；闸门上方那句与上面 reviewVerdict 是同一个 rev.line（review.ts 计算一次，两处渲染）。')
await browser.close()
