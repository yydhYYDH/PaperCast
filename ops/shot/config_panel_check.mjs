// 「设置 → 模型与 API」面板核验：是否真渲染、密钥是否只显示打码、探针是否真能通。
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
const page = await browser.newPage({ viewport: { width: 1720, height: 1400 } })
page.on('pageerror', (e) => out.errors.push('pageerror: ' + e.message))
page.on('console', (m) => { if (m.type() === 'error') out.errors.push('console: ' + m.text().slice(0, 150)) })
page.on('response', async (res) => {
  if (res.url().includes('/api/config')) out.configCalls = (out.configCalls || []).concat(res.status() + ' ' + res.request().method() + ' ' + res.url().replace(/^.*8000/, ''))
})

await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded', timeout: 15000 })
await page.waitForTimeout(1200)
// 导航项文案是「引擎与环境」（id=settings，走 Pinia 切视图，不是路由）
const nav = page.locator('.rail .item', { hasText: '引擎与环境' }).first()
if (await nav.count()) await nav.click()
else out.errors.push('导航里没有「引擎与环境」')
await page.waitForTimeout(2500)

const panel = page.locator('section.panel', { hasText: '模型与 API' }).first()
out.panelFound = (await panel.count()) > 0
out.groupTitles = await panel.locator('.group-title').allTextContents()
out.editableRows = await panel.locator('.cfg-row').count()
out.readonlyRows = await panel.locator('.ro-item').count()
const keyInput = panel.locator('input[type=password]').first()
out.secretInputType = await keyInput.getAttribute('type').catch(() => null)
out.secretPlaceholder = (await keyInput.getAttribute('placeholder').catch(() => null)) || null
out.secretValueIsEmpty = (await keyInput.inputValue().catch(() => 'x')) === ''
out.sourceChips = (await panel.locator('.cfg-row .chip').allTextContents()).slice(0, 8)
out.baseUrlValue = await panel.locator('input[type=text]').first().inputValue().catch(() => null)
out.hasLoadError = (await page.locator('text=读取失败').count()) > 0
await page.screenshot({ path: 'var/scratch/model-api-panel.png', fullPage: true })

// 点「测试连接」
const probeBtn = panel.locator('button', { hasText: '测试连接' }).first()
if (await probeBtn.count()) {
  await probeBtn.click()
  await page.waitForTimeout(12000)
  const probe = panel.locator('.probe').first()
  out.probeVisible = (await probe.count()) > 0
  out.probeText = ((await probe.textContent().catch(() => '')) || '').replace(/\s+/g, ' ').trim().slice(0, 160)
} else out.errors.push('没找到「测试连接」按钮')

// --save-test：走一遍界面的「改值 → 保存 → 还原」，验证脏值追踪与写入回显
if (process.argv.includes('--save-test')) {
  const row = panel.locator('.cfg-row', { hasText: 'LLM_TIMEOUT_SEC' }).first()
  const input = row.locator('input').first()
  const saveBtn = panel.locator('button', { hasText: '保存' }).first()
  await input.fill('900')
  await page.waitForTimeout(300)
  out.dirtyChipBeforeSave = ((await panel.locator('.chip.warn').first().textContent().catch(() => '')) || '').trim()
  await saveBtn.click()
  await page.waitForTimeout(4000)
  out.saveMessage = ((await panel.locator('.ok-line').first().textContent().catch(() => '')) || '').replace(/\s+/g, ' ').trim()
  out.timeoutAfterSave = await input.inputValue().catch(() => null)
  // 还原：清空该字段再保存（非密钥项留空 = 删除该键，回落默认值）
  await input.fill('')
  await saveBtn.click()
  await page.waitForTimeout(4000)
  out.revertMessage = ((await panel.locator('.ok-line').first().textContent().catch(() => '')) || '').replace(/\s+/g, ' ').trim()
  out.timeoutAfterRevert = await input.inputValue().catch(() => null)
}

console.log(JSON.stringify(out, null, 1))
await browser.close()
