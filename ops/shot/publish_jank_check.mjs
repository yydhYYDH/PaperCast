// 量「点发布」这条路上的两段等待：① 面板出现→「确认发布」可点 ② 关掉再打开是否还要重等（不真发布）
import { chromium } from 'playwright'
import { existsSync, readdirSync } from 'node:fs'
function findShell() {
  const base = process.env.HOME + '/.cache/ms-playwright'
  for (const d of existsSync(base) ? readdirSync(base) : []) {
    const p = base + '/' + d + '/chrome-headless-shell-linux64/chrome-headless-shell'
    if (d.startsWith('chromium_headless_shell') && existsSync(p)) return p
  }
}
process.env.NO_PROXY = '127.0.0.1,localhost'; process.env.no_proxy = process.env.NO_PROXY
const browser = await chromium.launch({ executablePath: findShell(), args: ['--no-sandbox','--disable-gpu','--no-proxy-server'] })
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } })
let drafts = 0, probes = 0, envs = 0, dur = []
page.on('request', (r) => { r.__t = Date.now(); if (/\/drafts/.test(r.url())) drafts++; if (/\/platforms/.test(r.url())) probes++; if (/\/env/.test(r.url())) envs++ })
page.on('requestfinished', (r) => { if (/drafts|platforms|env/.test(r.url())) dur.push(Math.round(Date.now() - (r.__t || Date.now())) + 'ms ' + r.url().slice(-34)) })
const step = (m) => console.log(m)
await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.rail .item', { timeout: 25000 })
await page.waitForTimeout(1500)
await page.locator('.rail .item[title="作品库"]').click()
await page.waitForSelector('.work', { timeout: 25000 })
await page.waitForTimeout(2000)
await page.locator('.work', { hasText: 'DeepRare' }).first().click()
await page.waitForTimeout(1200)
const a0 = await page.evaluate(() => performance.now())
await page.locator('.btn', { hasText: /发布这一件|再发一次/ }).first().click()
await page.waitForFunction(() => !!document.querySelector('.pub'), null, { timeout: 20000 })
const a1 = await page.evaluate(() => performance.now())
await page.waitForSelector('.gate .btn.primary', { timeout: 60000 })
const a2 = await page.evaluate(() => performance.now())
step('① 点「发布这一件」→ 面板出现: ' + Math.round(a1 - a0) + 'ms')
step('   面板出现 → 「确认发布」真的能点: ' + Math.round(a2 - a1) + 'ms  ← 这一段原来是「点了没反应」的窗口')
await page.locator('.pub .close, .pub button', { hasText: /关闭/ }).first().click().catch(() => {})
await page.waitForTimeout(800)
const b0 = await page.evaluate(() => performance.now())
const reopened = await page.locator('.btn', { hasText: /发布这一件|再发一次/ }).first().click().then(() => true).catch(() => false)
if (reopened) {
  await page.waitForSelector('.gate .btn.primary', { timeout: 60000 })
  const b1 = await page.evaluate(() => performance.now())
  step('② 关掉再打开 → 「确认发布」可点: ' + Math.round(b1 - b0) + 'ms  ← 60 秒内复用上次结果，不再探一次')
}
step('③ 请求数：drafts ' + drafts + ' 次、platforms ' + probes + ' 次、env ' + envs + ' 次')
step('   慢请求: ' + (dur.length ? dur.join(' | ') : '无'))
await browser.close()
