// 作品库验收：结构 + 可量指标（对比度/间距/行宽/溢出/折叠），眼睛看不到图时这些就是证据
import { chromium } from 'playwright'
import { existsSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const EVID = fileURLToPath(new URL('../../docs/evidence/', import.meta.url))

function findShell() {
  const base = process.env.HOME + '/.cache/ms-playwright'
  for (const d of readdirSync(base)) {
    if (!d.startsWith('chromium_headless_shell')) continue
    const p = base + '/' + d + '/chrome-headless-shell-linux64/chrome-headless-shell'
    if (existsSync(p)) return p
  }
  return undefined
}

const out = { errors: [] }
const browser = await chromium.launch({ executablePath: findShell(), args: ['--no-sandbox', '--disable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1720, height: 1180 } })
page.on('pageerror', (e) => out.errors.push('pageerror: ' + e.message))
page.on('console', (m) => { if (m.type() === 'error') out.errors.push('console: ' + m.text().slice(0, 200)) })

await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded', timeout: 20000 })
await page.waitForTimeout(1800)

try {
  await page.getByText('作品库', { exact: true }).first().click({ timeout: 6000 })
} catch (e) {
  out.enterFailed = String(e).slice(0, 120)
}
await page.waitForTimeout(1200)

out.mounted = (await page.locator('.card').count()) > 0
if (!out.mounted) { console.log(JSON.stringify(out, null, 1)); await browser.close(); process.exit(0) }

out.lead = await page.locator('.page-lead').first().innerText()
out.sections = await page.$$eval('section.sec', (els) => els.map((e) => ({
  id: e.id,
  title: (e.querySelector('.panel-title') || {}).textContent,
  count: (e.querySelector('.count') || {}).textContent,
  rendered: e.querySelectorAll('.card').length,
  hasExpand: !!Array.from(e.querySelectorAll('.more .mini')).length,
})))
out.cardFrom = await page.$$eval('.card .card-from', (els) => els.slice(0, 3).map((e) => e.textContent.trim().slice(0, 28)))

// ---- 可量指标：对比度 / 间距 / 行宽 / 溢出 ----
out.metrics = await page.evaluate(() => {
  function parse(c) {
    const m = String(c).match(/rgba?\(([^)]+)\)/)
    if (!m) return null
    const p = m[1].split(',').map((v) => parseFloat(v))
    return [p[0], p[1], p[2]]
  }
  function lum(rgb) {
    const s = rgb.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) })
    return 0.2126 * s[0] + 0.7152 * s[1] + 0.0722 * s[2]
  }
  function ratio(fg, bg) {
    const a = lum(fg), b = lum(bg)
    const hi = Math.max(a, b), lo = Math.min(a, b)
    return Math.round(((hi + 0.05) / (lo + 0.05)) * 100) / 100
  }
  const pick = (sel) => document.querySelector(sel)
  const contrastOf = (sel, bgSel) => {
    const el = pick(sel); const bg = bgSel ? pick(bgSel) : pick('.card')
    if (!el || !bg) return null
    const fg = parse(getComputedStyle(el).color)
    const b = parse(getComputedStyle(bg).backgroundColor)
    return fg && b ? ratio(fg, b) : null
  }
  const gapOf = (sel) => {
    const el = pick(sel)
    return el ? getComputedStyle(el).rowGap + ' / ' + getComputedStyle(el).columnGap : null
  }
  const title = pick('.card-title')
  const foot = pick('.card-foot')
  return {
    contrast: {
      title: contrastOf('.card-title'),
      when: contrastOf('.card .when'),
      from: contrastOf('.card-from'),
      vol: contrastOf('.card-foot .vol'),
      lead: contrastOf('.page-lead', '.page'),
      panelSub: contrastOf('.panel-sub', '.sec'),
    },
    gaps: { cards: gapOf('.cards'), cardInner: gapOf('.card'), foot: gapOf('.card-foot') },
    cardWidth: title ? Math.round(title.getBoundingClientRect().width) : null,
    overflowX: document.documentElement.scrollWidth > window.innerWidth + 2,
    pageHeight: document.documentElement.scrollHeight,
    focusable: pick('.card-title') ? getComputedStyle(pick('.card-title')).outlineStyle : null,
  }
})

// 键盘焦点：连按几次 Tab，看落点有没有可见轮廓（craft floor 明确要求）
await page.keyboard.press('Tab')
await page.keyboard.press('Tab')
await page.keyboard.press('Tab')
out.focus = await page.evaluate(() => {
  const el = document.activeElement
  if (!el) return null
  const s = getComputedStyle(el)
  return { tag: el.tagName, cls: String(el.className).slice(0, 40), outline: s.outlineWidth + ' ' + s.outlineStyle + ' ' + s.outlineColor }
})

await page.screenshot({ path: EVID + 'library-top.png' })

// 折叠 → 展开
const before = await page.$$eval('section.sec', (els) => els[els.length - 1].querySelectorAll('.card').length)
const moreBtn = page.locator('.more .mini').first()
if (await moreBtn.count()) {
  out.expandLabel = await moreBtn.innerText()
  await moreBtn.click()
  await page.waitForTimeout(500)
}
out.materialCards = { before: before, after: await page.$$eval('section.sec', (els) => els[els.length - 1].querySelectorAll('.card').length) }

// 详情
await page.locator('.card .card-title').first().click()
await page.waitForTimeout(1200)
out.modal = await page.evaluate(() => {
  const box = document.querySelector('.dlg-box')
  if (!box) return null
  const body = box.querySelector('.dlg-body')
  return {
    title: (box.querySelector('.dlg-title') || {}).textContent,
    sub: (box.querySelector('.dlg-sub') || {}).textContent,
    bodyH: body ? Math.round(body.getBoundingClientRect().height) : 0,
    media: body ? { img: body.querySelectorAll('img').length, iframe: body.querySelectorAll('iframe').length, video: body.querySelectorAll('video').length } : null,
    buttons: Array.from(box.querySelectorAll('.dlg-foot .btn')).map((b) => b.textContent.trim()),
  }
})
await page.screenshot({ path: EVID + 'library-detail.png' })
await page.keyboard.press('Escape')
await page.waitForTimeout(400)
out.escCloses = (await page.locator('.dlg-box').count()) === 0

await page.setViewportSize({ width: 430, height: 900 })
await page.waitForTimeout(600)
out.narrow = await page.evaluate(() => ({
  overflowX: document.documentElement.scrollWidth > window.innerWidth + 2,
  cardsPerRow: document.querySelectorAll('.cards').length ? getComputedStyle(document.querySelector('.cards')).gridTemplateColumns.split(' ').length : 0,
}))
await page.screenshot({ path: EVID + 'library-narrow.png' })

console.log(JSON.stringify(out, null, 1))
await browser.close()
