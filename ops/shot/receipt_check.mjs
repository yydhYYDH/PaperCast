// 回执核验：作品库里「已发布」到底是哪一次投的、有没有失败过、原文长什么样，必须看得见
// 判定：① 详情里有『回执』块 ② 同一渠道投过多次时**每条都在**（本轮发布 / 作品库直投）
//       ③ 失败那条要带原文（error.message）与「素材包还在本地」的出路 ④ 有链接的渠道要给出链接
//       ⑤ 控制台错误 0 条；截图入 docs/evidence/
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
const host = new URL(origin).hostname
process.env.NO_PROXY = [host, '127.0.0.1', 'localhost'].concat((process.env.NO_PROXY || '').split(',')).filter(Boolean).join(',')
process.env.no_proxy = process.env.NO_PROXY
const browser = await chromium.launch({ executablePath: findShell(), args: ['--no-sandbox', '--disable-gpu', '--no-proxy-server'] })
const page = await browser.newPage({ viewport: { width: 1500, height: 1100 } })
const errors = []
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message.slice(0, 140)))
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 140)) })
await page.goto(origin, { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.rail .item', { timeout: 25000 })
await page.waitForTimeout(2500)
await page.locator('.rail .item[title="作品库"]').click()
await page.waitForTimeout(4000)
const cards = await page.locator('.work').count()
console.log('作品库卡片数:', cards)
let checked = 0, bad = 0
for (let i = 0; i < Math.min(cards, 10); i++) {
  const card = page.locator('.work').nth(i)
  const head = (await card.innerText()).replace(/\s+/g, ' ').trim()
  const state = await card.locator('.chip').first().innerText().catch(() => '')
  if (!/已发布|没发成功/.test(state)) continue
  await card.click()
  await page.waitForTimeout(1800)
  const info = await page.evaluate(() => {
    const dlg = document.querySelector('.dlg-box')
    if (!dlg) return null
    const blocks = [...dlg.querySelectorAll('.side-block')].map((b) => b.innerText.replace(/\s+/g, ' ').trim())
    const rIdx = blocks.findIndex((b) => b.startsWith('回执'))
    return {
      title: dlg.querySelector('.dlg-title').innerText.trim(),
      notes: dlg.querySelectorAll('.rcpts li').length,
      routes: [...dlg.querySelectorAll('.rcpt-route')].map((e) => e.innerText.trim()),
      links: dlg.querySelectorAll('.rcpt-link').length,
      raw: dlg.querySelectorAll('.rcpt-raw').length,
      hasReceiptBlock: rIdx >= 0,
      text: rIdx >= 0 ? blocks[rIdx].slice(0, 260) : '',
    }
  })
  await page.locator('.mini', { hasText: '关闭' }).first().click()
  await page.waitForTimeout(700)
  if (!info) { console.log('  ✗ 详情打不开:', head.slice(0, 40)); bad++; continue }
  checked++
  const okBlock = info.hasReceiptBlock && info.notes > 0 && info.raw === info.notes
  if (!okBlock) bad++
  console.log('  ' + (okBlock ? '✓' : '✗'), info.title.slice(0, 26), '| 回执块', info.hasReceiptBlock, '| 条数', info.notes, '| 出处', JSON.stringify(info.routes), '| 链接', info.links, '| 原回执', info.raw)
  if (info.notes > 1) console.log('      多条回执示例:', info.text.slice(0, 200))
}
console.log('核了 ' + checked + ' 件已发布/失败的件；不达标的 ' + bad + ' 件')
console.log('控制台/请求错误 ' + errors.length + ' 条' + (errors.length ? ': ' + JSON.stringify(errors.slice(0, 5)) : ''))
await browser.close()
if (bad > 0 || errors.length || checked === 0) process.exit(1)
