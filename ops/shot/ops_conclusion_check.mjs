// 全站「去仪表盘化」核验 + 运营页只留结论
// 1) 每个页面都不该再出现统计卡/服务卡片墙；2) 运营页默认只有结论，服务与日志要手动展开；3) 控制台 0 错误。
import { chromium } from 'playwright'
import { existsSync, readdirSync } from 'node:fs'
function findShell() {
  const base = process.env.HOME + '/.cache/ms-playwright'
  for (const d of existsSync(base) ? readdirSync(base) : []) {
    const p = base + '/' + d + '/chrome-headless-shell-linux64/chrome-headless-shell'
    if (d.startsWith('chromium_headless_shell') && existsSync(p)) return p
  }
}
const browser = await chromium.launch({ executablePath: findShell(), args: ['--no-sandbox', '--disable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
const errors = []
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 140)) })
page.on('pageerror', (e) => errors.push('pageerror ' + e.message.slice(0, 140)))

const PAGES = ['工作台', '运行记录', '作品库', '平台账号', '运营维护', '设置']
await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.rail .item', { timeout: 15000 })

const scan = []
for (const label of PAGES) {
  await page.locator(`.rail .item[title="${label}"]`).click()
  await page.waitForTimeout(1400)
  scan.push(await page.evaluate((label) => ({
    page: label,
    dashboardBits: document.querySelectorAll('.stat-card, .stat-grid, .svc-grid, .svc').length,
    h1: document.querySelector('.page-title')?.textContent?.trim() ?? '(无页头)',
  }), label))
}

// 运营页细查
await page.locator('.rail .item[title="运营维护"]').click()
await page.waitForSelector('.lead-line', { timeout: 20000 })
await page.waitForTimeout(1800)
const ops = await page.evaluate(() => {
  const svcPanel = [...document.querySelectorAll('.panel')].find((p) => p.querySelector('.fold'))
  return {
    lead: document.querySelector('.lead-line')?.textContent?.trim() ?? null,
    keys: [...document.querySelectorAll('.key')].map((k) => k.innerText.replace(/\n/g, ' ')),
    platformLines: [...document.querySelectorAll('.lines li')].map((li) => li.innerText.replace(/\n/g, ' ').slice(0, 46)),
    fold: document.querySelector('.fold')?.innerText.replace(/\n/g, ' ').trim() ?? null,
    servicesHiddenByDefault: svcPanel ? getComputedStyle(svcPanel.querySelector('.panel-body')).display : null,
    tablesVisible: [...document.querySelectorAll('.tbl')].filter((t) => getComputedStyle(t.parentElement).display !== 'none').length,
    src: document.querySelector('.src')?.textContent?.trim() ?? null,
    runLine: document.querySelector('.lead-line.small')?.textContent?.trim() ?? null,
  }
})
await page.screenshot({ path: '/home/yydh/hack/docs/evidence/ops-conclusion.png' })

await page.locator('.fold').click()
await page.waitForTimeout(500)
await page.locator('.btn.ghost', { hasText: '看日志' }).last().click()
await page.waitForTimeout(1600)
ops.afterExpand = await page.evaluate(() => ({
  rows: document.querySelectorAll('.lines li').length,
  logLines: document.querySelectorAll('.logbox span').length,
  logVisible: !!document.querySelector('.logbox'),
}))
await page.screenshot({ path: '/home/yydh/hack/docs/evidence/ops-conclusion-expanded.png' })
console.log(JSON.stringify({ scan, ops, errors }, null, 1))
await browser.close()
