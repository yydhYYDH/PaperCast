// 平台账号页核验：渠道是否来自真后端、二维码是否真能出来。
// 只对小红书点开登录弹层取二维码（无副作用：显示二维码≠登录）；
// 知乎是「唤起桌面窗口」形态，只读状态，不点开，避免弹出桌面窗口。
import { chromium } from 'playwright'
import { existsSync, readdirSync } from 'node:fs'

function findShell() {
  const base = process.env.HOME + '/.cache/ms-playwright'
  for (const d of readdirSync(base)) {
    if (!d.startsWith('chromium_headless_shell')) continue
    const p = base + '/' + d + '/chrome-headless-shell-linux64/chrome-headless-shell'
    if (existsSync(p)) return p
  }
  return undefined
}

const browser = await chromium.launch({ executablePath: findShell(), args: ['--no-sandbox', '--disable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1720, height: 1040 } })
const out = { channels: [], errors: [] }
page.on('pageerror', (e) => out.errors.push('pageerror: ' + e.message))
page.on('console', (m) => { if (m.type() === 'error') out.errors.push('console: ' + m.text().slice(0, 140)) })
page.on('response', async (res) => {
  if (res.url().endsWith('/api/platforms') || /\/api\/platforms\/[a-z]+\/login\/qrcode/.test(res.url())) {
    try { out.channels.push({ url: res.url().replace('http://127.0.0.1:8000', ''), status: res.status(), body: await res.json() }) } catch {}
  }
})

await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded', timeout: 15000 })
await page.waitForTimeout(1500)

// 进「平台账号」页
const nav = page.locator('.rail .item', { hasText: '平台' }).first()
if (await nav.count()) await nav.click().catch(() => out.errors.push('点不开平台导航'))
else out.errors.push('导航里没有「平台」入口')
await page.waitForTimeout(4000)

out.panelTitle = (await page.locator('.panel-title').first().textContent().catch(() => null))?.trim()
out.chip = (await page.locator('.chip').first().textContent().catch(() => null))?.trim()
const rows = page.locator('.panel-body .row, .panel-body tr, .channels .channel, .ch-item')
out.rowCount = await rows.count()
out.rowTexts = (await rows.allTextContents().catch(() => [])).slice(0, 6).map((t) => t.replace(/\s+/g, ' ').trim().slice(0, 90))

await page.screenshot({ path: 'var/scratch/platforms-view.png', fullPage: false })

// 小红书：打开登录弹层，验证二维码真的渲染
const xhsBtn = page.locator('button', { hasText: /登录/ }).first()
out.loginButtonText = (await xhsBtn.textContent().catch(() => null))?.trim() ?? null
if (await xhsBtn.count()) {
  await xhsBtn.click().catch(() => out.errors.push('登录按钮点不动'))
  await page.waitForTimeout(6000)
  const img = page.locator('img.qr').first()
  out.qrRendered = await img.count() > 0
  out.qrSrcPrefix = (await img.getAttribute('src').catch(() => null))?.slice(0, 60) ?? null
  out.qrNaturalWidth = await img.evaluate((el) => el.naturalWidth).catch(() => null)
  out.dialogText = (await page.locator('.dialog, .modal, .login-dialog').first().textContent().catch(() => null))?.replace(/\s+/g, ' ').trim().slice(0, 200) ?? null
  await page.screenshot({ path: 'var/scratch/platforms-login-xhs.png', fullPage: false })
}
console.log(JSON.stringify(out, null, 1))
await browser.close()
