// 投递面板：点下去到底在等什么、界面有没有卡死、60 秒内重开会不会又重探一遍。
//
// 为什么要量这个（2026-09-19 用户问「点发布为什么这么卡」）：界面不卡（主线程没有长任务），
// 卡的是两段等待 —— ① 面板出现 → 「确认发布」可点（要真去问一次渠道状态）；
// ② 点「确认发布」→ 真发完（渠道那边开浏览器、填稿、传图、点发布、回来核验，几十秒）。
// 这个脚本只量 ① 与界面本身，**绝不点确认发布**（不可逆动作不进自动化检查）。
//
// 判定（任何一条不过就 exit 1）：
//   · 面板出现 ≤ 1s；面板出现 → 「确认发布」可点 ≤ 3s（超了说明探测又变慢/又串行排队了）
//   · 主线程长任务 = 0（有长任务说明是**界面**卡，不是等服务器）
//   · 60 秒内关掉再打开：不重新拉 drafts（应仍是 1 次），且 ≤ 300ms
//   · 控制台 0 错误
import { chromium } from 'playwright'
import { existsSync, readdirSync } from 'node:fs'

const ORIGIN = process.env.PC_BASE || 'http://127.0.0.1:5178'
const EVID = 'docs/evidence/publish-waiting.png'

function findShell() {
  const base = process.env.HOME + '/.cache/ms-playwright'
  for (const d of existsSync(base) ? readdirSync(base) : []) {
    const p = base + '/' + d + '/chrome-headless-shell-linux64/chrome-headless-shell'
    if (d.startsWith('chromium_headless_shell') && existsSync(p)) return p
  }
}
// 环境变量里的代理会让本机地址 502；必须在启动前加进 NO_PROXY（--no-proxy-server 挡不住它）
process.env.NO_PROXY = '127.0.0.1,localhost'
process.env.no_proxy = process.env.NO_PROXY

const browser = await chromium.launch({
  executablePath: findShell(),
  args: ['--no-sandbox', '--disable-gpu', '--no-proxy-server'],
})
const page = await browser.newPage({ viewport: { width: 1400, height: 1050 } })
await page.addInitScript(() => {
  window.__lt = []
  new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__lt.push(Math.round(e.duration)) })
    .observe({ entryTypes: ['longtask'] })
})

const slow = []
const errors = []
let drafts = 0
page.on('request', (r) => {
  r.__t = Date.now()
  if (/\/drafts/.test(r.url())) drafts++
})
page.on('requestfinished', (r) => {
  const ms = Date.now() - (r.__t || Date.now())
  if (ms > 1000) slow.push(ms + 'ms ' + r.method() + ' ' + r.url().slice(-46))
})
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message.slice(0, 120)))

await page.goto(ORIGIN + '/', { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.rail .item', { timeout: 25000 })
await page.waitForTimeout(1500)
await page.locator('.rail .item[title="作品库"]').click()
await page.waitForSelector('.work', { timeout: 25000 })
await page.waitForTimeout(2000)
await page.locator('.work').first().click()
await page.waitForTimeout(1200)

await page.evaluate(() => { window.__lt.length = 0 })
// 作品库详情有时要等一下才渲染出动作区；等不到就重开一次详情，别把「没点上」报成慢。
// 注意：这一段的耗时**包含 Playwright 等元素可点/可稳定点击的时间**，机器忙时会多几秒，
// 所以它只做参考值（>3s 才报），真正的硬指标是下面的「面板→确认发布可点」。
const openBtn = page.locator('.btn', { hasText: /发布这一件|再发一次/ }).first()
await openBtn.waitFor({ timeout: 15000 }).catch(() => {})
let retried = false
let t0 = await page.evaluate(() => performance.now())
await openBtn.click()
try {
  await page.waitForFunction(() => !!document.querySelector('.pub'), null, { timeout: 20000 })
} catch {
  retried = true
  await page.locator('.rail .item[title="作品库"]').click()
  await page.waitForSelector('.work', { timeout: 25000 })
  await page.waitForTimeout(1200)
  await page.locator('.work').first().click()
  await page.waitForTimeout(1200)
  await page.evaluate(() => { window.__lt.length = 0 })
  t0 = await page.evaluate(() => performance.now())
  await openBtn.click()
  await page.waitForFunction(() => !!document.querySelector('.pub'), null, { timeout: 20000 })
}
const t1 = await page.evaluate(() => performance.now())
await page.waitForSelector('.gate .btn.primary', { timeout: 60000 })
const t2 = await page.evaluate(() => performance.now())
const openMs = Math.round(t1 - t0)
const gateMs = Math.round(t2 - t1)

// 60 秒内重开：应当复用上次结果，不再重新拉 drafts
const reuseMs = await page.evaluate(async () => {
  const pinia = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia
  const s = pinia._s.get('publish')
  const a = performance.now()
  await s.openFor(s.runId, s.runTitle, s.channelId)
  return Math.round(performance.now() - a)
})
const draftsAfterReopen = drafts
// 「重新检查」必须真的重探（否则这个复用就是拿旧数据骗人）
const forceMs = await page.evaluate(async () => {
  const pinia = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia
  const s = pinia._s.get('publish')
  const a = performance.now()
  await s.load(true)
  return Math.round(performance.now() - a)
})

// 把「正在投递」的样子摆出来截一张（只改 store 状态，不调 deliver()）
await page.evaluate(() => {
  const pinia = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia
  const s = pinia._s.get('publish')
  s.busy = 'publish'
  s.elapsed = 62
})
await page.waitForTimeout(600)
const waitText = await page.locator('.waiting').innerText().catch(() => '')
await page.evaluate(() => { const el = document.querySelector('.waiting'); if (el) el.scrollIntoView({ block: 'center' }) })
await page.waitForTimeout(300)
await page.screenshot({ path: EVID })
const lt = await page.evaluate(() => window.__lt)
await browser.close()

console.log('点「发布这一件」→ 面板出现: ' + openMs + 'ms' + (retried ? '（第一次没点上，重开了一次详情）' : ''))
console.log('面板出现 → 「确认发布」可点: ' + gateMs + 'ms')
console.log('60 秒内重开面板: ' + reuseMs + 'ms（drafts 请求 ' + draftsAfterReopen + ' 次，应仍是 1）')
console.log('「重新检查」强制重探: ' + forceMs + 'ms（drafts 请求 ' + drafts + ' 次，应为 2）')
console.log('主线程长任务(>50ms): ' + lt.length + ' 个（最长 ' + (lt.length ? Math.max(...lt) : 0) + 'ms）')
console.log('慢请求(>1s): ' + (slow.length ? slow.join(' | ') : '无'))
console.log('等待块: ' + (waitText ? waitText.replace(/\s+/g, ' ').slice(0, 150) : '(没渲染出来)'))
console.log('截图: ' + EVID)

const bad = []
if (openMs > 3000) bad.push('面板出现用了 ' + openMs + 'ms（>3s，含等元素可点的时间）')
if (gateMs > 3000) bad.push('面板到「确认发布」可点用了 ' + gateMs + 'ms（>3s：探测又慢了）')
if (reuseMs > 300) bad.push('60 秒内重开用了 ' + reuseMs + 'ms（>300ms：没复用）')
if (draftsAfterReopen !== 1) bad.push('60 秒内重开又拉了 drafts（' + draftsAfterReopen + ' 次）')
if (drafts !== 2) bad.push('「重新检查」没有真的重探（drafts ' + drafts + ' 次，应为 2）')
if (lt.length) bad.push('主线程有 ' + lt.length + ' 个长任务（界面真卡了）')
if (!waitText) bad.push('投递等待块没渲染')
if (errors.length) bad.push('控制台错误 ' + errors.length + ' 个')
console.log(bad.length ? '✗ ' + bad.join('；') : '✓ 投递面板等待与反馈都正常')
process.exitCode = bad.length ? 1 : 0
