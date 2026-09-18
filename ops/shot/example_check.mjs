// 验证 (a)(b)(c)：示例元数据对齐、文案修正、一键跑示例按钮在真后端下真的提交了 run
import { chromium } from 'playwright'
import { existsSync, readdirSync } from 'node:fs'

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
const page = await browser.newPage({ viewport: { width: 1720, height: 1200 } })
page.on('pageerror', (e) => out.errors.push('pageerror: ' + e.message))

let created = null
page.on('response', async (res) => {
  const u = res.url()
  if (res.request().method() !== 'POST' || !u.includes('/api/runs')) return
  if (u.includes('/cancel') || u.includes('/gate')) return
  try { created = { status: res.status(), body: await res.json() } } catch { created = { status: res.status() } }
})

await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded', timeout: 15000 })
await page.waitForSelector('.seg button', { timeout: 15000 })
await page.waitForTimeout(1500)

// (a) 输入预览里的元数据是否已对齐
const pv = page.locator('.preview').first()
out.previewText = ((await pv.textContent().catch(() => '')) || '').replace(/\s+/g, ' ').trim().slice(0, 180)
out.arxivPlaceholder = await page.locator('input.mono').first().getAttribute('placeholder').catch(() => null)

// (a) PDF 分段的过时文案
await page.locator('.seg button', { hasText: 'PDF 文件' }).first().click()
await page.waitForTimeout(400)
out.pdfHint = ((await page.locator('p.hint').first().textContent().catch(() => '')) || '').trim()
out.pdfDropText = ((await page.locator('.drop').first().textContent().catch(() => '')) || '').replace(/\s+/g, ' ').trim().slice(0, 90)
await page.locator('.seg button', { hasText: 'arXiv 链接' }).first().click()
await page.waitForTimeout(400)

// (b) 一键跑示例按钮
const btn = page.locator('button', { hasText: '用示例论文跑一遍' }).first()
out.runButtonCount = await page.locator('button', { hasText: '用示例论文跑一遍' }).count()
out.oldPrefillButtonGone = (await page.locator('button', { hasText: '用示例论文' }).count()) === out.runButtonCount
await page.screenshot({ path: 'var/scratch/example-button.png', fullPage: false })

if (out.runButtonCount) {
  await btn.click()
  for (let i = 0; i < 40 && !created; i++) await page.waitForTimeout(500)
  out.postRuns = created ? created.status : 'NO POST 观察到'
  out.createdRun = created && created.body ? { id: created.body.id, title: created.body.title, source: created.body.source, status: created.body.status } : null
}

// 立刻取消，避免真跑完整条流水线
if (created && created.body && created.body.id) {
  const res = await page.evaluate(async (id) => {
    const r = await fetch('http://127.0.0.1:8000/api/runs/' + id + '/cancel', { method: 'POST' })
    return r.status
  }, created.body.id)
  out.cancelStatus = res
}

console.log(JSON.stringify(out, null, 1))
await browser.close()
