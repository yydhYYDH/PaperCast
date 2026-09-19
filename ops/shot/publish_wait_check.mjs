// 发布面板核验：① 打开面板要多久 ② 「正在投递」那一块长什么样（**不会真的发布**）
import { chromium } from 'playwright'
import { existsSync, readdirSync } from 'node:fs'
function findShell() {
  const base = process.env.HOME + '/.cache/ms-playwright'
  for (const d of existsSync(base) ? readdirSync(base) : []) {
    const p = base + '/' + d + '/chrome-headless-shell-linux64/chrome-headless-shell'
    if (d.startsWith('chromium_headless_shell') && existsSync(p)) return p
  }
}
process.env.NO_PROXY = '127.0.0.1,localhost'
process.env.no_proxy = process.env.NO_PROXY
const browser = await chromium.launch({ executablePath: findShell(), args: ['--no-sandbox', '--disable-gpu', '--no-proxy-server'] })
const page = await browser.newPage({ viewport: { width: 1400, height: 1050 } })
const errors = []
const slow = []
page.on('request', (r) => { r.__t = Date.now() })
page.on('requestfinished', (r) => { const ms = Date.now() - (r.__t || Date.now()); if (ms > 1200) slow.push(ms + 'ms ' + r.method() + ' ' + r.url().slice(-52)) })
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message.slice(0, 120)))
await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.rail .item', { timeout: 25000 })
await page.waitForTimeout(1500)
await page.locator('.rail .item[title="作品库"]').click()
await page.waitForSelector('.work', { timeout: 25000 })
await page.waitForTimeout(2000)
const t1 = Date.now()
await page.locator('.work', { hasText: 'DeepRare' }).first().click()
await page.waitForTimeout(1200)
await page.locator('.btn', { hasText: /发布这一件|再发一次/ }).first().click()
await page.waitForSelector('.pub', { timeout: 30000 })
console.log('点「发布这一件」→ 面板出现: ' + (Date.now() - t1) + 'ms')
// 面板里选一个渠道，让「发布闸门」那一段真的渲染出来
const chan = page.locator('.pub button', { hasText: /小红书|知乎/ }).first()
if (await chan.count()) { await chan.click(); await page.waitForTimeout(500) }
const loadingText = await page.locator('.pub-note').first().innerText().catch(() => '')
console.log('面板加载中文案:', loadingText.replace(/\s+/g, ' ').slice(0, 150))
// 等渠道状态回来（最多 40 秒），再看闸门
await page.waitForTimeout(6000)
const gate = await page.locator('.gate').first().innerText().catch(() => '(还没有闸门)')
console.log('闸门:', gate.replace(/\s+/g, ' ').slice(0, 160))
// 手动摆出「正在投递」状态（不调 deliver()，绝不真发布）
await page.evaluate(() => {
  const pinia = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia
  const s = pinia._s.get('publish')
  s.busy = 'publish'; s.elapsed = 62
})
await page.waitForTimeout(700)
const waitText = await page.locator('.waiting').innerText().catch(() => '(没有 .waiting 块)')
console.log('等待块:', waitText.replace(/\s+/g, ' ').slice(0, 240))
await page.screenshot({ path: '/home/yydh/hack/docs/evidence/publish-waiting.png' })
console.log('慢请求(>1.2s):'); slow.slice(0, 6).forEach((s) => console.log('  ' + s))
console.log('错误:', errors.length)
await browser.close()
