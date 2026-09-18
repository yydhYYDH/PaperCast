#!/usr/bin/env node
// ops/shot/render.mjs —— 通用 HTML → PNG 渲染器（横切 B 渲染底座）
// 与 shot.mjs 的分工：shot.mjs 是「把 dashboard 截一遍」的一次性脚本，
// 本文件是可被其它组件调用的稳定入口：给定 HTML + 目标像素，出 PNG，并做几何自检。
//
// 用法:
//   node render.mjs --html <path> --out <png> [--width 2304] [--height 1728]
//                   [--full] [--check] [--timeout 30000]
// 输出: 单行 JSON {ok, out, width, height, panels:[...], images:[...], overflow:[...], brokenImages:[...]}
// 退出码: 0 成功 / 2 参数或渲染失败 / 3 几何自检不通过（--check 且确有溢出或缺图）

import { chromium } from 'playwright'
import { existsSync, mkdirSync, readdirSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import path from 'node:path'
import process from 'node:process'

function parseArgs(argv) {
  const o = { html: '', out: '', width: 0, height: 0, full: false, check: false, timeout: 30000, chrome: '' }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    const next = () => argv[++i]
    if (a === '--html') o.html = next()
    else if (a === '--out') o.out = next()
    else if (a === '--width') o.width = Number(next())
    else if (a === '--height') o.height = Number(next())
    else if (a === '--full') o.full = true
    else if (a === '--check') o.check = true
    else if (a === '--timeout') o.timeout = Number(next())
    else if (a === '--chrome') o.chrome = next()
    else if (a === '-h' || a === '--help') { process.stdout.write('see header comment\n'); process.exit(0) }
    else { process.stderr.write('unknown arg: ' + a + '\n'); process.exit(2) }
  }
  if (!o.html || !o.out) { process.stderr.write('--html and --out are required\n'); process.exit(2) }
  return o
}

// 浏览器可执行文件：显式参数 > 环境变量 > Playwright 缓存里版本号最大的那个
function findBrowser(explicit) {
  const env = explicit || process.env.SHOT_CHROME || ''
  if (env && existsSync(env)) return env
  const root = path.join(homedir(), '.cache', 'ms-playwright')
  if (!existsSync(root)) return ''
  // 优先级：headless_shell 优先（本机实测完整 chrome 起不来：crashpad 报 --database is required）
  const rels = [
    ['chrome-headless-shell-linux64/chrome-headless-shell', 0],
    ['chrome-linux/headless_shell', 0],
    ['chrome-linux/chrome', 1],
    ['chrome-linux64/chrome', 1],
  ]
  const cands = []
  for (const dir of readdirSync(root)) {
    for (const [rel, rank] of rels) {
      const p = path.join(root, dir, rel)
      if (existsSync(p)) cands.push({ p, dir, rank, ver: Number((/-([0-9]+)/.exec(dir) || [0, 0])[1]) })
    }
  }
  if (!cands.length) return ''
  cands.sort((a, b) => a.rank - b.rank || b.ver - a.ver)
  return cands[0].p
}

const args = parseArgs(process.argv.slice(2))
const browserPath = findBrowser(args.chrome)
if (!browserPath) { process.stdout.write(JSON.stringify({ ok: false, error: 'no chromium found; run: playwright install chromium' }) + '\n'); process.exit(2) }

const htmlPath = path.resolve(args.html)
if (!existsSync(htmlPath)) { process.stdout.write(JSON.stringify({ ok: false, error: 'html not found: ' + htmlPath }) + '\n'); process.exit(2) }
const outPath = path.resolve(args.out)
mkdirSync(path.dirname(outPath), { recursive: true })

const browser = await chromium.launch({
  executablePath: browserPath,
  args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--font-render-hinting=none', '--force-color-profile=srgb'],
})

let result
try {
  // 视口 = 目标像素（--full 时只定宽度，高度按内容长）
  const page = await browser.newPage({
    viewport: { width: args.width || 1280, height: args.height || 900 },
    deviceScaleFactor: 1,
  })
  await page.goto('file://' + htmlPath, { waitUntil: 'load', timeout: args.timeout })
  await page.evaluate(async () => {
    if (document.fonts && document.fonts.ready) await document.fonts.ready
    await Promise.all(Array.from(document.images).map((im) => im.complete ? null : new Promise((r) => { im.onload = r; im.onerror = r })))
  })
  await page.waitForTimeout(250)

  // 自检：带 data-panel 的容器是否内容溢出；图片是否加载失败
  const probe = await page.evaluate(() => {
    const panels = Array.from(document.querySelectorAll('[data-panel]')).map((el) => {
      const r = el.getBoundingClientRect()
      const overflowY = el.scrollHeight - el.clientHeight
      const overflowX = el.scrollWidth - el.clientWidth
      return {
        name: el.getAttribute('data-panel') || '',
        x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
        scrollH: el.scrollHeight, clientH: el.clientHeight,
        overflowY, overflowX,
      }
    })
    const images = Array.from(document.images).map((im) => ({
      src: im.getAttribute('src') || '', natural: im.naturalWidth + 'x' + im.naturalHeight,
      box: Math.round(im.getBoundingClientRect().width) + 'x' + Math.round(im.getBoundingClientRect().height),
    }))
    return {
      panels, images,
      docH: document.documentElement.scrollHeight,
      docW: document.documentElement.scrollWidth,
      bodyBg: getComputedStyle(document.body).backgroundColor,
    }
  })

  await page.screenshot({ path: outPath, fullPage: args.full })
  result = { ok: true, out: outPath, browser: browserPath, html: htmlPath, ...probe }
  result.overflow = probe.panels.filter((p) => p.overflowY > 2 || p.overflowX > 2)
  result.brokenImages = probe.images.filter((i) => i.natural === '0x0')
  await page.close()
} catch (e) {
  await browser.close()
  process.stdout.write(JSON.stringify({ ok: false, error: String(e && e.message || e) }) + '\n')
  process.exit(2)
}
await browser.close()

process.stdout.write(JSON.stringify(result) + '\n')
if (args.check && (result.overflow.length || result.brokenImages.length)) process.exit(3)
