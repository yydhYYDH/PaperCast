// 作品库验收：封面是不是真图、状态是不是真回执、点开是不是一篇文章/一条视频。
// 眼睛看不到图的时候，这些可量指标就是证据（naturalWidth / duration / 计算样式 / DOM 数量）。
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
// 媒体在关弹层时被浏览器主动 abort 是正常的（preload=metadata 的收尾），不算错
page.on('requestfailed', (r) => {
  const why = (r.failure() || {}).errorText || ''
  if (why.includes('ERR_ABORTED')) { out.aborted = (out.aborted || 0) + 1; return }
  out.errors.push('requestfailed(' + why + '): ' + r.url().slice(0, 80))
})

await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded', timeout: 20000 })
await page.waitForTimeout(1800)
await page.getByText('作品库', { exact: true }).first().click({ timeout: 8000 })
await page.waitForTimeout(2000)   // 等回执读完

// 封面是 loading=lazy 的：先滚一遍再量，否则量到的是还没解码的 0x0（那是脚本的错，不是页面的错）
await page.evaluate(async () => {
  const scroller = document.querySelector('.page')
  if (!scroller) return
  for (let y = 0; y < scroller.scrollHeight; y += 600) {
    scroller.scrollTop = y
    await new Promise((r) => setTimeout(r, 300))
  }
  scroller.scrollTop = 0
})
// 等到每张封面都解码完（lazy 图会晚一步），再去量尺寸，否则量到的是 0x0
await page.waitForFunction(
  () => Array.from(document.querySelectorAll('.work .shot img')).every((i) => i.complete),
  null, { timeout: 20000 },
).catch(() => { out.coversTimedOut = true })
await page.waitForTimeout(1000)

out.lead = await page.locator('.page-lead').first().innerText()
out.mounted = (await page.locator('.work').count()) > 0
if (!out.mounted) { console.log(JSON.stringify(out, null, 1)); await browser.close(); process.exit(0) }

// ---- 板块：平台 + 量词 + 一句结论 ----
out.sections = await page.$$eval('section.sec', (els) => els.map((e) => ({
  id: e.id,
  platform: (e.querySelector('.panel-title') || {}).textContent,
  unit: (e.querySelector('.sec-unit') || {}).textContent,
  note: (e.querySelector('.sec-note') || {}).textContent,
  works: e.querySelectorAll('.work').length,
  older: e.querySelectorAll('.older-list li').length,
  olderLabel: (e.querySelector('.older-t') || {}).textContent,
})))
out.featuredBounded = out.sections.every((s) => s.works <= 6)

// 展开更早的：行式列表要真的出来，且点得开
const more = page.locator('.older-t').first()
out.older = null
if (await more.count()) {
  await more.click()
  await page.waitForTimeout(400)
  out.older = await page.evaluate(() => {
    const sec = document.querySelector('section.sec')
    const rows = sec ? sec.querySelectorAll('.older-list li') : []
    return {
      rows: rows.length,
      first: rows[0] ? rows[0].innerText.replace(/\s+/g, ' ').trim().slice(0, 46) : '',
      overflowX: document.documentElement.scrollWidth > window.innerWidth + 2,
    }
  })
  await page.keyboard.press('Escape')
  await more.click()   // 收回去，后面的截图保持首屏原样
  await page.waitForTimeout(300)
}

// ---- 封面：必须是真图（解码成功），且走了后端静态地址 ----
out.covers = await page.$$eval('.work .shot img', (els) => els.map((i) => ({
  nat: i.naturalWidth + 'x' + i.naturalHeight,
  ratio: (i.getBoundingClientRect().width / i.getBoundingClientRect().height).toFixed(2),
  src: i.getAttribute('src').slice(0, 62),
})))
out.coversOk = out.covers.every((c) => !c.nat.startsWith('0x') && c.src.includes('/artifacts/'))
out.coverRatios = out.covers.reduce((m, c) => { m[c.ratio] = (m[c.ratio] || 0) + 1; return m }, {})
out.coverSrcBad = out.covers.filter((c) => !c.src.includes('/artifacts/')).map((c) => c.src)

// ---- 状态：chip 文案分布 + 每张卡都有状态 ----
out.states = await page.$$eval('.work', (els) => els.map((e) => ({
  title: (e.querySelector('.work-title') || {}).textContent.trim().slice(0, 24),
  chip: (e.querySelector('.work-foot .chip') || {}).textContent.trim(),
  meta: (e.querySelector('.work-meta') || {}).textContent.trim(),
  kind: (e.querySelector('.work-kind') || {}).textContent.trim(),
})))
out.everyCardHasChip = out.states.every((s) => s.chip.length > 0)

// ---- 计算样式：小字对比度 / 卡片圆角 / 无渐变阴影 ----
out.metrics = await page.evaluate(() => {
  const parse = (c) => { const m = String(c).match(/rgba?\(([^)]+)\)/); return m ? m[1].split(',').map(Number).slice(0, 3) : null }
  const lum = (rgb) => { const s = rgb.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }); return 0.2126 * s[0] + 0.7152 * s[1] + 0.0722 * s[2] }
  const ratio = (f, b) => { const a = lum(f), c = lum(b); return Math.round(((Math.max(a, c) + 0.05) / (Math.min(a, c) + 0.05)) * 100) / 100 }
  const q = (s) => document.querySelector(s)
  const card = q('.work')
  const grab = (sel, bgSel) => {
    const el = q(sel), bg = q(bgSel || '.work')
    if (!el || !bg) return null
    const f = parse(getComputedStyle(el).color), b = parse(getComputedStyle(bg).backgroundColor)
    return f && b ? ratio(f, b) : null
  }
  const shot = q('.shot')
  return {
    contrast: {
      title: grab('.work-title'),
      meta: grab('.work-meta'),
      lead: grab('.page-lead', '.page'),
      secNote: grab('.sec-note', '.sec'),
    },
    radius: card ? getComputedStyle(card).borderRadius : null,
    shadow: card ? getComputedStyle(card).boxShadow : null,
    gradientOnShell: /gradient/.test(getComputedStyle(document.body).backgroundImage),
    shotAspect: shot ? (shot.getBoundingClientRect().width / shot.getBoundingClientRect().height).toFixed(2) : null,
    overflowX: document.documentElement.scrollWidth > window.innerWidth + 2,
  }
})

await page.screenshot({ path: EVID + 'library-top.png' })

// ---- 点开一件「文章」：正文真的渲染出来了，右栏有状态 ----
const article = page.locator('.work').filter({ has: page.locator('.work-kind', { hasText: '读稿' }) }).first()
out.article = null
if (await article.count()) {
  await article.click()
  await page.waitForTimeout(3000)   // 图是 lazy 的，正文要等解码完再量
  out.article = await page.evaluate(() => {
    const box = document.querySelector('.dlg-box')
    if (!box) return null
    const reader = box.querySelector('.reader')
    const side = box.querySelector('.side')
    return {
      title: (box.querySelector('.dlg-title') || {}).textContent.slice(0, 30),
      headChip: (box.querySelector('.dlg-head .chip') || {}).textContent.trim(),
      chars: reader ? (reader.innerText || '').trim().length : 0,
      shots: box.querySelectorAll('.still img').length,
      shotsLoaded: Array.from(box.querySelectorAll('.still img')).every((i) => i.naturalWidth > 0),
      stateNote: (side && side.querySelector('.side-note') ? side.querySelector('.side-note').textContent : '').slice(0, 60),
      kv: side ? Array.from(side.querySelectorAll('.kv li')).map((l) => l.innerText.replace(/\s+/g, ' ').trim()) : [],
      acts: Array.from(box.querySelectorAll('.acts .btn')).map((b) => b.textContent.trim()),
      sibs: Array.from(box.querySelectorAll('.sibs .pill')).map((b) => b.textContent.trim()),
    }
  })
  await page.screenshot({ path: EVID + 'library-detail-article.png' })
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
  out.escCloses = (await page.locator('.dlg-box').count()) === 0
}

// ---- 点开一件「视频」：播放器拿到的是真 mp4（duration>0 才算真的能放） ----
const video = page.locator('.work').filter({ has: page.locator('.work-kind', { hasText: '看片' }) }).first()
out.video = null
if (await video.count()) {
  await video.click()
  await page.waitForTimeout(3000)
  out.video = await page.evaluate(async () => {
    const box = document.querySelector('.dlg-box')
    const v = box && box.querySelector('video.player')
    if (!v) return null
    if (v.readyState < 1) await new Promise((r) => { v.addEventListener('loadedmetadata', r, { once: true }); setTimeout(r, 4000) })
    return {
      src: String(v.getAttribute('src')).slice(0, 70),
      duration: Math.round(v.duration || 0),
      poster: String(v.getAttribute('poster') || '').slice(-38),
      headChip: box.querySelector('.dlg-head .chip') ? box.querySelector('.dlg-head .chip').textContent.trim() : '',
      sideNote: box.querySelector('.side-note') ? box.querySelector('.side-note').textContent.slice(0, 60) : '',
    }
  })
  await page.screenshot({ path: EVID + 'library-detail-video.png' })
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
}

// ---- 窄屏 ----
await page.setViewportSize({ width: 430, height: 900 })
await page.waitForTimeout(700)
out.narrow = await page.evaluate(() => ({
  overflowX: document.documentElement.scrollWidth > window.innerWidth + 2,
  cols: document.querySelector('.shelf') ? getComputedStyle(document.querySelector('.shelf')).gridTemplateColumns.split(' ').length : 0,
}))
await page.screenshot({ path: EVID + 'library-narrow.png' })

console.log(JSON.stringify(out, null, 1))
await browser.close()
