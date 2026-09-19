// X（推特）平台验收：作品库里 X 必须**自成一块**（不是并进「英文」或「跨平台」），
// 它的稿子是英文 thread、状态来自真实回执，详情弹层要说清「只出素材包、不会真发」。
//
// 前置：后端已有带 en 变体的 run（例如 run_720e83bdae91）。截图入 docs/evidence/。
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
}

const out = { errors: [], fail: [] }
const check = (label, cond, detail = '') => {
  out[label] = cond ? '✓' : '✗ ' + detail
  if (!cond) out.fail.push(label + ' —— ' + detail)
}

const browser = await chromium.launch({ executablePath: findShell(), args: ['--no-sandbox', '--disable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1720, height: 1180 } })
page.on('pageerror', (e) => out.errors.push('pageerror: ' + e.message))
page.on('console', (m) => { if (m.type() === 'error') out.errors.push('console: ' + m.text().slice(0, 200)) })

await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded', timeout: 20000 })
await page.waitForTimeout(1500)
await page.getByText('作品库', { exact: true }).first().click({ timeout: 8000 })
await page.waitForTimeout(2500)

const sec = page.locator('#sec-x')
const exists = (await sec.count()) > 0
check('作品库里有 X 独立板块（#sec-x）', exists, '找不到 #sec-x')
if (!exists) { console.log(JSON.stringify(out, null, 1)); await browser.close(); process.exit(1) }

const title = (await sec.locator('.panel-title').first().innerText()).trim()
const unit = (await sec.locator('.sec-unit').first().innerText()).trim()
const note = (await sec.locator('.sec-note').first().innerText()).trim()
const cards = await sec.locator('.work').count()
const chips = await sec.locator('.work .work-foot .chip').allInnerTexts()
check('X 板块标题是「X（推特）」', title.includes('X'), title)
check('量词按 thread 说', unit.includes('thread'), unit)
check('每张卡都有状态', chips.length === cards, `${chips.length}/${cards}`)
check('状态词是人话（已发布/等你确认/存了草稿/还没发…）', chips.every((c) => !/undefined|draft|published/.test(c)), JSON.stringify(chips))
out.section = { title, unit, note, cards, chips }

await sec.scrollIntoViewIfNeeded()
await page.waitForTimeout(1000)
await sec.screenshot({ path: EVID + 'library-x-section.png' })

// 有「存了草稿」的那一件（X 素材包已落盘）→ 点开看详情怎么说
const draft = sec.locator('.work').filter({ has: page.locator('.chip', { hasText: '存了草稿' }) }).first()
if (await draft.count()) {
  await draft.click()
  await page.waitForTimeout(1500)
  const info = await page.evaluate(() => {
    const box = document.querySelector('.dlg-box')
    if (!box) return null
    const reader = box.querySelector('.reader')
    const side = box.querySelector('.side')
    return {
      title: (box.querySelector('.dlg-title') || {}).textContent.trim(),
      chip: (box.querySelector('.dlg-head .chip') || {}).textContent.trim(),
      note: (side && side.querySelector('.side-note') ? side.querySelector('.side-note').textContent : '').trim(),
      kv: Array.from(side.querySelectorAll('.kv li')).map((l) => l.innerText.replace(/\s+/g, ' ').trim()),
      head: (reader ? reader.innerText : '').slice(0, 90).replace(/\s+/g, ' '),
      chars: reader ? reader.innerText.length : 0,
      sibs: Array.from(box.querySelectorAll('.sibs .pill')).map((b) => b.textContent.trim()),
    }
  })
  out.detail = info
  check('详情里有正文（英文 thread 读得出来）', !!info && info.chars > 200, info ? String(info.chars) : 'no dialog')
  check('英文 thread 是英文字母为主', !!info && /[A-Za-z]{4}/.test(info.head), info ? info.head : '')
  check('详情右栏说清这份稿子还没真发出去', !!info && /素材包|不真发|不会真的发|草稿/.test(info.note), info ? info.note : '')
  await page.screenshot({ path: EVID + 'library-x-detail.png' })
} else {
  out.detail = null
  check('有「存了草稿」的 X 卡片（示例：隔离跑一遍 M3）', false, '这一页没有 X 草稿卡，详情没验到')
}

check('控制台 0 错误', out.errors.length === 0, JSON.stringify(out.errors).slice(0, 200))
console.log(JSON.stringify(out, null, 1))
await browser.close()
process.exit(out.fail.length ? 1 : 0)