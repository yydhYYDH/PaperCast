// 逐类点开详情：海报/视频/长文/文本/数据，看详情里真的渲染出了什么
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

const out = { errors: [], cases: [] }
const browser = await chromium.launch({ executablePath: findShell(), args: ['--no-sandbox', '--disable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1720, height: 1180 } })
page.on('pageerror', (e) => out.errors.push('pageerror: ' + e.message))
page.on('console', (m) => { if (m.type() === 'error') out.errors.push('console: ' + m.text().slice(0, 160)) })

await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded', timeout: 20000 })
await page.waitForTimeout(1600)
await page.getByText('作品库', { exact: true }).first().click()
await page.waitForTimeout(1200)

const wanted = ['海报 / 图', '视频', '长文', '文本', '数据']
for (const tag of wanted) {
  const card = page.locator('.card').filter({ has: page.locator('.tag', { hasText: tag }) }).first()
  const n = await card.count()
  if (!n) { out.cases.push({ tag: tag, found: false }); continue }
  const title = await card.locator('.card-title').innerText()
  await card.locator('.card-title').click()
  await page.waitForTimeout(1400)
  const seen = await page.evaluate(() => {
    const box = document.querySelector('.dlg-box')
    if (!box) return null
    const body = box.querySelector('.dlg-body')
    const q = (s) => body.querySelectorAll(s).length
    const img = body.querySelector('img')
    const vid = body.querySelector('video')
    return {
      img: q('img'), video: q('video'), iframe: q('iframe'), pre: q('pre'), md: q('.md'), media: q('.media'), viewer: q('.poster, .article, .video-view, .panel'),
      imgNatural: img ? { w: img.naturalWidth, h: img.naturalHeight, src: img.getAttribute('src').slice(0, 60) } : null,
      videoSrc: vid ? String(vid.getAttribute('src')).slice(0, 60) : null,
      textChars: (body.innerText || '').trim().length,
      bodyH: Math.round(body.getBoundingClientRect().height),
    }
  })
  out.cases.push({ tag: tag, found: true, title: title.slice(0, 28), seen: seen })
  if (tag === '海报 / 图') await page.screenshot({ path: EVID + 'library-detail-poster.png' })
  if (tag === '长文') await page.screenshot({ path: EVID + 'library-detail-md.png' })
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
}
console.log(JSON.stringify(out, null, 1))
await browser.close()
