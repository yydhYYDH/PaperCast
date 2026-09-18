import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const EXE = '/home/yydh/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell'
const OUT = '/home/yydh/hack/apps/papercast/screenshots'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'] })

// ---- 1. 用真实浏览器渲染 poster.html → poster.png（补上流水线里「待渲染」的那一格）----
const poster = await browser.newPage({ viewport: { width: 1080, height: 1440 } })
await poster.goto('file:///home/yydh/hack/apps/papercast/public/samples/poster/poster.html', { waitUntil: 'load' })
await poster.waitForTimeout(400)
await poster.screenshot({ path: '/home/yydh/hack/apps/papercast/public/samples/poster/poster.png' })
console.log('poster.png rendered')
await poster.close()

// ---- 2. 打开 dashboard，收集控制台错误 ----
const page = await browser.newPage({ viewport: { width: 1720, height: 1040 }, deviceScaleFactor: 1 })
const errors = []
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()) })
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message))

await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.timeline .card', { timeout: 15000 })
await page.waitForTimeout(1600)
await page.screenshot({ path: OUT + '/01-workbench-digest.png' })
console.log('shot: workbench / digest')

const tabs = [['文章', '02-article'], ['Poster', '03-poster'], ['视频', '04-video'], ['发布', '05-publish']]
for (const [label, file] of tabs) {
  await page.locator('.tabs-head .tabbar button', { hasText: label }).first().click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: OUT + '/' + file + '.png' })
  console.log('shot: ' + label)
}

// ---- 3. 起一条新运行，验证流水线动起来 ----
await page.locator('.tabs-head .tabbar button', { hasText: '论文理解层' }).first().click()
await page.getByRole('checkbox').first().check().catch(() => {})
await page.getByRole('button', { name: /开始生成/ }).click()
await page.waitForTimeout(6000)
await page.screenshot({ path: OUT + '/06-running.png' })
console.log('shot: running')
await page.waitForTimeout(9000)
await page.screenshot({ path: OUT + '/07-running-later.png' })
const stageStates = await page.$$eval('.timeline .card', (nodes) =>
  nodes.map((n) => (n.className.match(/card (\w+)/)?.[1] ?? '?') + ':' + (n.querySelector('.c-title')?.textContent ?? '').trim()),
)
console.log('stages:', JSON.stringify(stageStates))

// ---- 4. 其它视图 ----
for (const [label, file] of [['运行历史', '08-runs'], ['产物库', '09-library'], ['引擎与环境', '10-settings']]) {
  await page.locator('.rail .item', { hasText: label }).first().click()
  await page.waitForTimeout(1000)
  await page.screenshot({ path: OUT + '/' + file + '.png' })
  console.log('shot: ' + label)
}

console.log('ERRORS(' + errors.length + '):')
for (const e of errors.slice(0, 20)) console.log('  ' + e)
await browser.close()
