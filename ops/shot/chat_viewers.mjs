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
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
const bad = []
const errors = []
page.on('response', (r) => { if (r.status() >= 400) bad.push(r.status() + ' ' + r.url().slice(-70)) })
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 120)) })
page.on('pageerror', (e) => errors.push('pageerror ' + e.message.slice(0, 120)))
await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.thread', { timeout: 15000 })
await page.waitForTimeout(2500)

const out = {}
// 逐个展开：论文理解 / 文章 / 海报 / 视频（对话里直接渲染查看器）
const toggles = await page.locator('.toggle').count()
out.toggles = toggles
for (let i = 0; i < toggles; i++) {
  await page.locator('.toggle').nth(i).click()
  await page.waitForTimeout(1800)
}
out.expanded = await page.evaluate(() =>
  [...document.querySelectorAll('.stage-view')].map((v) => v.innerText.replace(/\s+/g, ' ').trim().slice(0, 70)),
)
out.videoSrc = await page.evaluate(() => [...document.querySelectorAll('video')].map((v) => v.getAttribute('src')))
out.imgSrcs = await page.evaluate(() => [...document.querySelectorAll('.stage-view img')].map((i) => i.getAttribute('src')?.slice(-46)).slice(0, 4))
await page.screenshot({ path: '/home/yydh/hack/docs/evidence/chat-artifact.png', fullPage: false })
console.log(JSON.stringify({ out, bad, errors }, null, 1))
await browser.close()
