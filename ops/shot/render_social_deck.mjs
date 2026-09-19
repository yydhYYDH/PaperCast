#!/usr/bin/env node
/*
 * ops/shot/render_social_deck.mjs —— 把「单文件 HTML 社交卡片 deck」渲染成一组 PNG。
 *
 * 用法:
 *   node ops/shot/render_social_deck.mjs <task-dir|index.html> [--out <dir>] [--scale 2] [--only id,id]
 *
 * 为什么有这个脚本（而不是让每个会话自己写截图脚本）：
 *   小红书组图类技能（guizang-social-card-skill，见 ops/install_skills.sh）约定「一个 index.html
 *   里放多个 <section class="poster xhs">，逐个截 PNG」，但**上游不带渲染脚本**，只带
 *   一个自检脚本 validate-social-deck.mjs。这里把「渲染」这一步固定下来：
 *   输出尺寸 = 该节点的 CSS 尺寸 × --scale（默认 2，够小红书高清），文件名 = 节点的 id（缺 id 用序号），
 *   产物默认落到 <task-dir>/output/。确定性、可复现、可进 CI。
 *
 * 为什么放在 ops/shot/ 而不是 ops/ 根：它 import "playwright"，而 playwright 装在 ops/shot/node_modules
 * （ESM 的裸名 import 不认 NODE_PATH，所以脚本必须放在 node_modules 旁边）。
 *
 * 与同目录 render.mjs 的分工：那个渲染「一张已知像素尺寸的整页」（后端 poster 用），
 * 这个渲染「一页里的多个卡片节点」（社交组图用）。
 *
 * 输出: 单行 JSON {ok, task, out, scale, count, frames:[{id,w,h,path,bytes}]}
 * 退出码: 0 成功 / 2 参数或渲染失败 / 3 一个卡片节点都没找到
 */
import { chromium } from 'playwright'
import { existsSync, mkdirSync, statSync } from 'node:fs'
import { readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import path from 'node:path'
import process from 'node:process'

function parseArgs(argv) {
  const o = { target: '', out: '', scale: 2, only: [] }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    const next = () => argv[++i]
    if (a === '--out') o.out = next()
    else if (a === '--scale') o.scale = Number(next())
    else if (a === '--only') o.only = String(next()).split(',').map((s) => s.trim()).filter(Boolean)
    else if (a === '-h' || a === '--help') { process.stdout.write('see header comment\n'); process.exit(0) }
    else if (!a.startsWith('--') && !o.target) o.target = a
    else { process.stderr.write('unknown arg: ' + a + '\n'); process.exit(2) }
  }
  if (!o.target) { process.stderr.write('usage: node ops/render_social_deck.mjs <task-dir|index.html>\n'); process.exit(2) }
  return o
}

// 浏览器：优先 chrome-headless-shell（本机完整 chrome 起不来，见 docs/07 §5）
function findBrowser() {
  const env = process.env.SHOT_CHROME || ''
  if (env && existsSync(env)) return env
  const root = path.join(homedir(), '.cache', 'ms-playwright')
  if (!existsSync(root)) return ''
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
      if (existsSync(p)) cands.push({ p, rank, ver: Number((/-([0-9]+)/.exec(dir) || [0, 0])[1]) })
    }
  }
  if (!cands.length) return ''
  cands.sort((a, b) => a.rank - b.rank || b.ver - a.ver)
  return cands[0].p
}

const args = parseArgs(process.argv.slice(2))
const abs = path.resolve(args.target)
const htmlPath = statSync(abs).isDirectory() ? path.join(abs, 'index.html') : abs
if (!existsSync(htmlPath)) {
  process.stdout.write(JSON.stringify({ ok: false, error: 'not found: ' + htmlPath }) + '\n')
  process.exit(2)
}
const taskDir = path.dirname(htmlPath)
const outDir = path.resolve(args.out || path.join(taskDir, 'output'))
mkdirSync(outDir, { recursive: true })

const browserPath = findBrowser()
if (!browserPath) {
  process.stdout.write(JSON.stringify({ ok: false, error: 'no chromium found; run: npx playwright install chromium' }) + '\n')
  process.exit(2)
}

const browser = await chromium.launch({
  executablePath: browserPath,
  args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--font-render-hinting=none',
         '--force-color-profile=srgb', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
})

try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 }, deviceScaleFactor: args.scale })
  await page.goto('file://' + htmlPath, { waitUntil: 'load', timeout: 60000 })
  await page.evaluate(async () => {
    if (document.fonts && document.fonts.ready) await document.fonts.ready
    await Promise.all(Array.from(document.images).map((im) => (im.complete ? null : new Promise((r) => { im.onload = r; im.onerror = r }))))
  })
  await page.waitForTimeout(400)

  const nodes = await page.$$('section.poster, section.cover, .poster, .cover')
  const frames = []
  let i = 0
  for (const node of nodes) {
    const id = (await node.getAttribute('id')) || `frame-${String(++i).padStart(2, '0')}`
    if (args.only.length && !args.only.includes(id)) continue
    const box = await node.boundingBox()
    if (!box || box.width < 200 || box.height < 200) continue   // 跳过隐藏/占位节点
    const file = path.join(outDir, `${id}.png`)
    await node.screenshot({ path: file })
    const st = statSync(file)
    frames.push({ id, w: Math.round(box.width), h: Math.round(box.height), path: file, bytes: st.size })
  }
  if (!frames.length) {
    process.stdout.write(JSON.stringify({ ok: false, error: '没找到卡片节点（.poster/.cover）', html: htmlPath }) + '\n')
    process.exitCode = 3
  } else {
    process.stdout.write(JSON.stringify({
      ok: true, task: taskDir, out: outDir, scale: args.scale, count: frames.length, frames,
    }) + '\n')
  }
} catch (e) {
  process.stdout.write(JSON.stringify({ ok: false, error: String((e && e.message) || e) }) + '\n')
  process.exitCode = 2
} finally {
  await browser.close()
}
