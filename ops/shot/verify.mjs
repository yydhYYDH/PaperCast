import { chromium } from 'playwright'
// 浏览器路径自己探测（与 live_check.mjs 同一套逻辑，不写死机器）
import { existsSync, readdirSync } from 'node:fs'
function findShell() {
  if (process.env.SHOT_CHROME) return process.env.SHOT_CHROME
  const base = (process.env.PLAYWRIGHT_BROWSERS_PATH || process.env.HOME + '/.cache/ms-playwright')
  if (!existsSync(base)) return undefined
  for (const d of readdirSync(base)) {
    if (!d.startsWith('chromium_headless_shell')) continue
    const p = base + '/' + d + '/chrome-headless-shell-linux64/chrome-headless-shell'
    if (existsSync(p)) return p
  }
  return undefined
}
const EXE = findShell()
const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'] })
const page = await browser.newPage({ viewport: { width: 1720, height: 1040 } })
const errors = []
page.on('pageerror', (e) => errors.push(e.message))
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.timeline .card')

const r = {}
r.cols = await page.$$eval('.workspace > .col', (ns) => ns.map((n) => Math.round(n.getBoundingClientRect().width)))
r.timelineCards = await page.locator('.timeline .card').count()
r.stepperNodes = await page.locator('.stepper .node').count()
r.bodyBg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor)
r.hOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
r.digest = {
  contribs: await page.locator('.contrib li').count(),
  figs: await page.locator('.fig').count(),
  resultRows: await page.locator('.tbl tbody tr').count(),
}
const tab = (t) => page.locator('.tabs-head .tabbar button', { hasText: t }).first().click()

await tab('文章')
await page.waitForTimeout(900)
r.article = {
  tabs: await page.locator('.toolbar .tabbar button').count(),
  h1: await page.locator('.reader h1').count(),
  h2: await page.locator('.reader h2').count(),
  tex: await page.locator('.reader .texblock, .reader .tex-inline').count(),
}
await page.locator('.toolbar .tabbar button', { hasText: '小红书 × 媒体' }).first().click()
await page.waitForTimeout(700)
r.xhsCards = await page.locator('.xcard').count()

await tab('Poster')
await page.waitForTimeout(1200)
const frame = page.frames().find((f) => f.url().includes('poster.html'))
r.poster = {
  iframe: page.frames().filter((f) => f.url().includes('poster.html')).length,
  innerCols: frame ? await frame.locator('.body > .col').count() : 0,
  innerCards: frame ? await frame.locator('.card').count() : 0,
  checks: await page.locator('.side .check').count(),
  pngBtnEnabled: await page.locator('.toolbar button', { hasText: '打开 PNG' }).isEnabled(),
}

await tab('视频')
await page.waitForTimeout(1500)
r.video = {
  el: await page.locator('video').count(),
  readyState: await page.evaluate(() => document.querySelector('video')?.readyState ?? -1),
  duration: await page.evaluate(() => Math.round(document.querySelector('video')?.duration ?? 0)),
  slides: await page.locator('.slide').count(),
}
await page.locator('.slide').nth(3).click()
await page.waitForTimeout(600)
r.videoSeeked = await page.evaluate(() => Math.round(document.querySelector('video')?.currentTime ?? 0))

await tab('发布')
await page.waitForTimeout(700)
r.publish = { channels: await page.locator('.ch').count(), gate: await page.locator('.gate-card').count() }

for (const [label, sel] of [['运行历史', '.tbl tbody tr'], ['产物库', '.card'], ['引擎与环境', '.tbl tbody tr']]) {
  await page.locator('.rail .item', { hasText: label }).first().click()
  await page.waitForTimeout(700)
  r[label] = await page.locator(sel).count()
}
r.errors = errors
console.log(JSON.stringify(r, null, 1))
await browser.close()
