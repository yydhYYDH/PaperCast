// 前端「真的能用吗」核验：不只看 HTTP 200，而是看页面是否渲染、是否真的在调真后端、有无控制台错误。
// 用法：node ops/shot/live_check.mjs [--shot <输出png>]
import { chromium } from 'playwright'
import { existsSync, readdirSync } from 'node:fs'

function findShell() {
  const base = process.env.HOME + '/.cache/ms-playwright'
  if (!existsSync(base)) return undefined
  for (const d of readdirSync(base)) {
    if (!d.startsWith('chromium_headless_shell')) continue
    const p = base + '/' + d + '/chrome-headless-shell-linux64/chrome-headless-shell'
    if (existsSync(p)) return p
  }
  return undefined
}

const shotIdx = process.argv.indexOf('--shot')
const shot = shotIdx > -1 ? process.argv[shotIdx + 1] : undefined
const browser = await chromium.launch({
  executablePath: findShell(),
  args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
})
const page = await browser.newPage({ viewport: { width: 1720, height: 1040 } })
const errors = []
const api = []
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message))
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 160)) })
page.on('response', (res) => {
  const u = res.url()
  if (u.includes(':8000')) api.push(res.status() + ' ' + u.replace('http://127.0.0.1:8000', ''))
  if (u.includes(':5178') && res.status() >= 400) errors.push('asset ' + res.status() + ' ' + u)
})

// 不能用 networkidle：Vite dev server 的 HMR 长连接会让它永远等不到空闲。
await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded', timeout: 15000 })
  .catch((e) => errors.push('goto: ' + e.message))
await page.waitForSelector('.rail .item, .timeline .card, .stage-card', { timeout: 10000 })
  .catch(() => errors.push('页面骨架未出现（选择器超时）'))
await page.waitForTimeout(2000)

const txt = (sel) => page.locator(sel).first().textContent().catch(() => null)
const out = {
  title: await page.title(),
  railItems: await page.locator('.rail .item').count(),
  timelineCards: await page.locator('.timeline .card, .stages .card, .stage-card').count(),
  historyRows: await page.locator('table tbody tr').count(),
  visibleRunTitle: (await txt('.run-header, .runhead, header h2'))?.trim().slice(0, 80) ?? null,
  bodyHasMinerU: await page.locator('text=MinerU').count(),
  bodyChars: (await txt('body'))?.length ?? 0,
  apiCalls: api.length,
  apiStatuses: [...new Set(api)].slice(0, 12),
  errors,
}
if (shot) await page.screenshot({ path: shot, fullPage: false })
console.log(JSON.stringify(out, null, 1))
await browser.close()
