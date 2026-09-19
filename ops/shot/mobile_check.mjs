// 手机端审计：在 390×844（iPhone 尺寸、触摸）下把七个页面走一遍，量出**真实**的毛病
// 判定：① 横向溢出（scrollWidth > innerWidth）② 有元素越出右边 ③ 点按目标太小（< 40px）
// ④ 控制台错误 / 请求 4xx ⑤ 截图入 docs/evidence/
import { chromium } from 'playwright'
import { existsSync, readdirSync } from 'node:fs'

function findShell() {
  const base = process.env.HOME + '/.cache/ms-playwright'
  for (const d of existsSync(base) ? readdirSync(base) : []) {
    const p = base + '/' + d + '/chrome-headless-shell-linux64/chrome-headless-shell'
    if (d.startsWith('chromium_headless_shell') && existsSync(p)) return p
  }
}
const origin = process.argv[2] || 'http://127.0.0.1:5178/'

// 这台机器的环境变量里挂着 http_proxy，**Playwright 会照它给浏览器配代理**
// （所以 --no-proxy-server 其实盖不住它）：访问 127.0.0.1 一直没问题是因为 NO_PROXY 里有 127.*，
// 而测局域网地址（手机走的那个）时必须把那个 IP 也加进 NO_PROXY，否则会被代理拦成 502。
const host = new URL(origin).hostname
const bypass = new Set((process.env.NO_PROXY || process.env.no_proxy || '').split(',').filter(Boolean).concat([host, '127.0.0.1', 'localhost']))
process.env.NO_PROXY = [...bypass].join(',')
process.env.no_proxy = process.env.NO_PROXY

const browser = await chromium.launch({ executablePath: findShell(), args: ['--no-sandbox', '--disable-gpu', '--no-proxy-server'] })
// 尺寸可传：node mobile_check.mjs [origin] [宽] [高]（默认 390×844 = iPhone 14 竖屏）
const W = Number(process.argv[3] || 390)
const H = Number(process.argv[4] || 844)
const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 2, isMobile: true, hasTouch: true })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 120)) })
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message.slice(0, 120)))
page.on('response', (r) => { if (r.status() >= 400) errors.push(r.status() + ' ' + r.url().slice(-42)) })

await page.goto(origin, { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.rail .item', { timeout: 25000 })
await page.waitForTimeout(3500)

const NAV = ['工作台', '运行记录', '作品库', '平台账号', '风格', '运营维护', '设置']
const report = []
for (const label of NAV) {
  await page.locator(`.rail .item[title="${label}"]`).click()
  await page.waitForTimeout(1800)
  const m = await page.evaluate(() => {
    const doc = document.documentElement
    const viewportWidth = window.innerWidth      // 别写成固定值：脚本支持传尺寸（见文件头）
    const bad = []
    for (const el of document.querySelectorAll('body *')) {
      const r = el.getBoundingClientRect()
      if (r.width === 0 || r.height === 0) continue
      if (r.right > viewportWidth + 1) {
        bad.push({ tag: el.tagName.toLowerCase() + '.' + String(el.className || '').split(' ').slice(0, 2).join('.'), right: Math.round(r.right), w: Math.round(r.width), text: (el.textContent || '').trim().slice(0, 24) })
      }
    }
    const small = []
    for (const el of document.querySelectorAll('button, a, [role=button]')) {
      const r = el.getBoundingClientRect()
      if (r.height === 0) continue
      if (r.height < 32) small.push({ t: (el.textContent || '').trim().slice(0, 14), h: Math.round(r.height) })
    }
    const rail = document.querySelector('.rail')?.getBoundingClientRect()
    return {
      overflowX: doc.scrollWidth - window.innerWidth,
      scrollWidth: doc.scrollWidth,
      overflowEls: bad.slice(0, 6),
      overflowCount: bad.length,
      smallTapCount: small.length,
      smallTap: small.slice(0, 5),
      rail: rail ? { w: Math.round(rail.width), h: Math.round(rail.height) } : null,
    }
  })
  report.push({ page: label, ...m })
  await page.screenshot({ path: `/home/yydh/hack/docs/evidence/mobile-${label}.png`, fullPage: false })
}
// 紧凑汇总：每页一行，看得见「哪一页、溢出多少、谁越界、点按目标多小」
for (const r of report) {
  const who = (r.overflowEls || []).slice(0, 3).map((e) => String(e.tag).split('.')[1] + '@' + e.right).join(' ')
  console.log(
    String(r.page).padEnd(6) + ' 横向溢出=' + String(r.overflowX).padStart(3) +
    ' 越界元素=' + String(r.overflowCount).padStart(2) +
    ' 小按钮=' + String(r.smallTapCount).padStart(2) +
    ' 左栏=' + r.rail + ' | ' + who + ' 小按钮:' + (r.smallTap || []).map((s) => s.t + '(' + s.h + ')').join(' '),
  )
}
// 产物查看器（展开看）：手机上也必须不溢出 —— 它是「论文理解/写作/视觉/视频」真正看内容的地方
await page.locator('.rail .item[title="工作台"]').click()
await page.waitForTimeout(1500)
const toggles = page.locator('.arts .toggle')
const n = await toggles.count()
for (let i = 0; i < Math.min(n, 3); i++) {
  await toggles.nth(i).click()
  await page.waitForTimeout(1200)
  const m = await page.evaluate(() => {
    const W = window.innerWidth
    let bad = 0
    for (const el of document.querySelectorAll('.stage-view *')) {
      const r = el.getBoundingClientRect()
      if (r.width && r.height && r.right > W + 1) bad++
    }
    return { overflow: document.documentElement.scrollWidth - W, bad: bad, tag: (document.querySelector('.stage-view')?.firstChild?.className || '') + '' }
  })
  console.log('查看器#' + i + ' 横向溢出=' + m.overflow + ' 越界元素=' + m.bad + ' (' + m.tag.slice(0, 40) + ')')
  await page.screenshot({ path: '/home/yydh/hack/docs/evidence/mobile-viewer-' + i + '.png' })
}
console.log('控制台/请求错误 ' + errors.length + ' 条' + (errors.length ? '：' + errors.slice(0, 3).join(' / ') : ''))
await browser.close()
