// 逐平台点开第一件：小红书要出真卡片 + 正文，知乎要出横版配图 + 正文，B 站要出能放的播放器。
// 断言只看「真的渲染出了什么」（图解码出来的像素、正文的字数、视频的时长），不看文件名的想当然。
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
page.on('pageerror', (e) => out.errors.push('pageerror: ' + e.message.slice(0, 160)))
page.on('console', (m) => { if (m.type() === 'error') out.errors.push('console: ' + m.text().slice(0, 160)) })

await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded', timeout: 20000 })
await page.waitForTimeout(1800)
await page.getByText('作品库', { exact: true }).first().click()
await page.waitForTimeout(2500)

// 每个平台的第一个板块里点开第一件，看这一件的真身
const WANT = [
  { id: 'sec-xhs', name: '小红书', wantStills: true, wantVideo: false },
  { id: 'sec-zhihu', name: '知乎', wantStills: false, wantVideo: false },
  { id: 'sec-bilibili', name: 'B 站', wantStills: false, wantVideo: true },
]

for (const w of WANT) {
  const card = page.locator('#' + w.id + ' .work').first()
  if (!(await card.count())) { out.cases.push({ platform: w.name, found: false }); continue }
  const title = (await card.locator('.work-title').innerText()).slice(0, 26)
  await card.click()
  await page.waitForTimeout(3200)
  const seen = await page.evaluate(async () => {
    const box = document.querySelector('.dlg-box')
    if (!box) return null
    const v = box.querySelector('video.player')
    if (v && v.readyState < 1) {
      await new Promise((r) => { v.addEventListener('loadedmetadata', r, { once: true }); setTimeout(r, 4000) })
    }
    const stills = Array.from(box.querySelectorAll('.still img'))
    return {
      chip: (box.querySelector('.dlg-head .chip') || {}).textContent.trim(),
      note: (box.querySelector('.side-note') || {}).textContent.slice(0, 54),
      readerChars: (box.querySelector('.reader') || { innerText: '' }).innerText.trim().length,
      stills: stills.length,
      stillsDecoded: stills.filter((i) => i.naturalWidth > 0).length,
      videoDuration: v ? Math.round(v.duration || 0) : 0,
      videoSrcOk: v ? String(v.getAttribute('src')).includes('/artifacts/') : null,
      acts: Array.from(box.querySelectorAll('.acts .btn')).map((b) => b.textContent.trim()),
    }
  })
  out.cases.push({ platform: w.name, found: true, title, expect: { stills: w.wantStills, video: w.wantVideo }, seen })
  await page.screenshot({ path: EVID + 'library-detail-' + w.id.replace('sec-', '') + '.png' })
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
}

// 判定：小红书要有解码出来的卡片，B 站要有秒数>0 的成片，三件都要有正文或成片
out.verdict = out.cases.map((c) => {
  if (!c.found) return c.platform + '：没找到这一件'
  const s = c.seen || {}
  if (c.expect.video) return c.platform + '：成片 ' + s.videoDuration + 's / src 走后端 ' + s.videoSrcOk
  return c.platform + '：正文 ' + s.readerChars + ' 字' + (c.expect.stills ? '、卡片 ' + s.stillsDecoded + '/' + s.stills + ' 张解码成功' : '')
})
console.log(JSON.stringify(out, null, 1))
await browser.close()
