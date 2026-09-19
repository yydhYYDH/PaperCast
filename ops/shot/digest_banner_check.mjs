// 论文理解抬头：必须是暖白底（曾经是深蓝黑）
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
await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.thread', { timeout: 15000 })
await page.waitForTimeout(2600)
await page.locator('.toggle').first().click()
await page.waitForSelector('.banner', { timeout: 20000 })
await page.waitForTimeout(1200)
const banner = await page.evaluate(() => {
  const el = document.querySelector('.banner')
  const cs = getComputedStyle(el)
  const t = document.querySelector('.d-title')
  const lum = (c) => {
    const [r, g, b] = c.match(/\d+/g).map(Number)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
  }
  return {
    background: cs.backgroundColor,
    backgroundImage: cs.backgroundImage,
    luminance: +lum(cs.backgroundColor).toFixed(3),
    title: t?.textContent?.trim().slice(0, 46),
    titleColor: getComputedStyle(t).color,
    borderColor: cs.borderTopColor,
  }
})
await page.locator('.banner').screenshot({ path: '/home/yydh/hack/docs/evidence/digest-banner.png' })
console.log(JSON.stringify({ banner, errors }, null, 1))
await browser.close()
