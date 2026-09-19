// 只验一件事：关掉面板再打开，还要不要重新探一次（60 秒复用）
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
let drafts = 0
page.on('request', (r) => { if (/\/drafts/.test(r.url())) drafts++ })
await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.rail .item', { timeout: 25000 })
await page.waitForTimeout(1500)
await page.locator('.rail .item[title="作品库"]').click()
await page.waitForSelector('.work', { timeout: 25000 })
await page.waitForTimeout(2000)
await page.locator('.work', { hasText: 'DeepRare' }).first().click()
await page.waitForTimeout(1200)
const a = await page.evaluate(() => performance.now())
await page.locator('.btn', { hasText: /发布这一件|再发一次/ }).first().click()
await page.waitForSelector('.gate .btn.primary', { timeout: 60000 })
const b = await page.evaluate(() => performance.now())
console.log('第一次：到「确认发布」可点 ' + Math.round(b - a) + 'ms，drafts 请求 ' + drafts + ' 次')
const closed = await page.locator('.pub button', { hasText: '关闭' }).first().click().then(() => 'ok').catch((e) => 'fail ' + String(e).slice(0, 60))
console.log('关闭面板: ' + closed)
await page.waitForTimeout(1000)
// 直接走 store 重开一次（等价于再点一次「发布这一件」）：看它还要不要重新探一遍
const second = await page.evaluate(async () => {
  const pinia = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia
  const s = pinia._s.get('publish')
  const t0 = performance.now()
  await s.openFor(s.runId, s.runTitle, 'xhs')
  return Math.round(performance.now() - t0)
})
console.log('第二次（60 秒内）重开面板用时：' + second + 'ms，drafts 请求共 ' + drafts + ' 次')
const forced = await page.evaluate(async () => {
  const pinia = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia
  const s = pinia._s.get('publish')
  const t0 = performance.now()
  await s.load(true)          // 「重新检查」= 强制重探
  return Math.round(performance.now() - t0)
})
console.log('点「重新检查」强制重探用时：' + forced + 'ms，drafts 请求共 ' + drafts + ' 次')
await page.screenshot({ path: '/home/yydh/hack/docs/evidence/publish-reopen.png' })
await browser.close()
