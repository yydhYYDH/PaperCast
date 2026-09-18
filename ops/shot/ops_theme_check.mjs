// 核验「明亮 SaaS 卡片风 + 运营维护页」：换肤是否生效、运营页是否真的拿到后端数字、有没有控制台错误。
// 用法：node ops/shot/ops_theme_check.mjs
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

const WS = new URL('../../', import.meta.url).pathname.replace(/\/$/, '')
const browser = await chromium.launch({
  executablePath: findShell(),
  args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
})
const page = await browser.newPage({ viewport: { width: 1720, height: 1040 } })
const errors = []
const api = []
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message))
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 200)) })
page.on('response', (res) => {
  const u = res.url()
  if (u.includes(':8000')) api.push(res.status() + ' ' + u.replace('http://127.0.0.1:8000', ''))
})

await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded', timeout: 20000 })
await page.waitForSelector('.rail .item', { timeout: 15000 })
await page.waitForTimeout(2500)

// 换肤是否生效：读计算样式，而不是靠肉眼看截图
const theme = await page.evaluate(() => {
  const cs = getComputedStyle(document.documentElement)
  const panel = document.querySelector('.panel')
  return {
    bg: cs.getPropertyValue('--bg').trim(),
    accent: cs.getPropertyValue('--accent').trim(),
    bodyBg: getComputedStyle(document.body).backgroundColor,
    bodyColor: getComputedStyle(document.body).color,
    panelBg: panel ? getComputedStyle(panel).backgroundColor : null,
    panelShadow: panel ? getComputedStyle(panel).boxShadow.slice(0, 40) : null,
    colorScheme: cs.getPropertyValue('color-scheme').trim(),
  }
})
await page.screenshot({ path: WS + '/docs/evidence/theme-light-workbench.png' })

// 平台账号页（换肤后的卡片）
await page.locator('.rail .item[title="平台账号"]').click()
await page.waitForTimeout(1200)
await page.screenshot({ path: WS + '/docs/evidence/theme-light-platforms.png' })

// 运营维护页
await page.locator('.rail .item[title="运营维护"]').click()
await page.waitForSelector('.stat-grid, .empty', { timeout: 20000 })
await page.waitForTimeout(4500)
const dashboard = {
  navActive: await page.locator('.rail .item.on .txt').first().textContent().catch(() => null),
  title: await page.locator('.panel-title').first().textContent().catch(() => null),
  statCards: await page.locator('.stat-card').count(),
  summaryText: await page.locator('.stat-grid').first().innerText().catch(() => ''),
  channelPanels: await page.locator('.panel-title').allInnerTexts().catch(() => []),
  tables: await page.locator('table.tbl tbody tr').count(),
  warnLines: await page.locator('.warn-line').allInnerTexts().catch(() => []),
  bodyHasView: await page.locator('text=播放').count(),
}
await page.screenshot({ path: WS + '/docs/evidence/ops-dashboard.png' })

// 服务与日志标签页
await page.locator('.seg button', { hasText: '服务与日志' }).click()
await page.waitForSelector('.svc-grid .svc', { timeout: 15000 })
await page.waitForTimeout(2500)
const services = {
  cards: await page.locator('.svc').count(),
  text: await page.locator('.svc-grid').innerText().catch(() => ''),
  logLines: await page.locator('.logbox').count(),
  logPreview: (await page.locator('.logbox').first().innerText().catch(() => '')).slice(0, 260),
  pills: await page.locator('.pill').count(),
}
await page.screenshot({ path: WS + '/docs/evidence/ops-services.png' })

console.log(JSON.stringify({ theme, dashboard, services, api: [...new Set(api)].slice(0, 14), errors }, null, 1))
await browser.close()
