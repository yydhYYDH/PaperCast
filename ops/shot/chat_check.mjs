import { chromium } from 'playwright'
import { existsSync, readdirSync } from 'node:fs'
function findShell() {
  const base = process.env.HOME + '/.cache/ms-playwright'
  for (const d of existsSync(base) ? readdirSync(base) : []) {
    const p = base + '/' + d + '/chrome-headless-shell-linux64/chrome-headless-shell'
    if (d.startsWith('chromium_headless_shell') && existsSync(p)) return p
  }
}
const WS = '/home/yydh/hack'
const browser = await chromium.launch({ executablePath: findShell(), args: ['--no-sandbox', '--disable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
const errors = []
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 140)) })
page.on('pageerror', (e) => errors.push('pageerror ' + e.message.slice(0, 140)))
await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.thread', { timeout: 15000 })
await page.waitForTimeout(2600)
await page.screenshot({ path: WS + '/docs/evidence/chat-workbench.png' })

// 展开一个产物（看查看器能不能在对话里渲染）
const before = await page.locator('.stage-view').count()
await page.locator('.toggle').first().click().catch(() => {})
await page.waitForTimeout(2500)
const expanded = await page.evaluate(() => ({
  stageViews: document.querySelectorAll('.stage-view').length,
  inside: document.querySelector('.stage-view')?.innerText?.trim().slice(0, 80) ?? '',
}))
await page.screenshot({ path: WS + '/docs/evidence/chat-artifact.png' })

// 窄屏
await page.setViewportSize({ width: 1120, height: 860 })
await page.waitForTimeout(900)
await page.screenshot({ path: WS + '/docs/evidence/chat-narrow.png' })
const narrow = await page.evaluate(() => ({
  rail: getComputedStyle(document.querySelector('.rail-side')).display,
  cols: getComputedStyle(document.querySelector('.chat-page')).gridTemplateColumns,
}))
console.log(JSON.stringify({ before, expanded, narrow, errors }, null, 1))
await browser.close()
