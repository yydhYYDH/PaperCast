// 编辑风格改版核验：页头/字体/配色/确认框/气泡/各页面渲染 + 控制台错误
import { chromium } from 'playwright'
import { existsSync, readdirSync } from 'node:fs'
function findShell() {
  const base = process.env.HOME + '/.cache/ms-playwright'
  for (const d of existsSync(base) ? readdirSync(base) : []) {
    const p = base + '/' + d + '/chrome-headless-shell-linux64/chrome-headless-shell'
    if (d.startsWith('chromium_headless_shell') && existsSync(p)) return p
  }
}
const WS = new URL('../../', import.meta.url).pathname.replace(/\/$/, '')
const browser = await chromium.launch({ executablePath: findShell(), args: ['--no-sandbox', '--disable-gpu', '--no-proxy-server'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
const errors = []
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message.slice(0, 200)))
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 200)) })
await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded', timeout: 20000 })
await page.waitForSelector('.rail .item', { timeout: 15000 })
await page.waitForTimeout(2500)

const theme = await page.evaluate(() => {
  const cs = getComputedStyle(document.documentElement)
  const title = document.querySelector('.page-title')
  return {
    canvas: cs.getPropertyValue('--canvas').trim(),
    bodyBg: getComputedStyle(document.body).backgroundColor,
    titleFont: title ? getComputedStyle(title).fontFamily.slice(0, 60) : null,
    titleText: title ? title.textContent.trim() : null,
    lead: document.querySelector('.page-lead')?.textContent.trim().slice(0, 50) ?? null,
    railBg: getComputedStyle(document.querySelector('.rail')).backgroundColor,
    navLabels: [...document.querySelectorAll('.rail .item .txt')].map((e) => e.textContent.trim()),
    topHasAdapter: document.body.innerText.includes('adapter'),
  }
})
await page.screenshot({ path: WS + '/docs/evidence/ui-workbench.png' })

const visit = async (title, file) => {
  await page.locator('.rail .item[title="' + title + '"]').click()
  await page.waitForTimeout(2200)
  const shot = WS + '/docs/evidence/' + file
  await page.screenshot({ path: shot })
  return { title: await page.locator('.page-title').first().textContent().catch(() => null), panels: await page.locator('.panel').count() }
}

const pages = []
pages.push(await visit('平台账号', 'ui-platforms.png'))

// 退出登录：只打开确认框再取消（不动真实凭证）
// 没有「已登录」的渠道时跳过这一步 —— 这台机器上登录态会变，
// 整条核验不该因为「此刻谁都没登录」而崩在第一个页面。
let dialog = { skipped: '此刻没有已登录的渠道，退出登录确认框没法验' }
if (await page.locator('.ch.ready .btn.danger').count()) {
  await page.locator('.ch.ready .btn.danger').first().click()
  await page.waitForSelector('.sheet', { timeout: 8000 })
  await page.waitForTimeout(400)
  dialog = {
    title: await page.locator('.sheet-title').innerText().catch(() => null),
    text: (await page.locator('.sheet-text').innerText().catch(() => '')).slice(0, 80),
    noWindowConfirm: true,
  }
  await page.screenshot({ path: WS + '/docs/evidence/ui-logout-confirm.png' })
  await page.locator('.sheet-foot .btn').first().click()
  await page.waitForTimeout(600)
  dialog.closedAfterCancel = (await page.locator('.sheet').count()) === 0
}

pages.push(await visit('运营维护', 'ui-ops.png'))
// 更新数据 → 应出现回执气泡
await page.locator('.page-head .btn', { hasText: '更新数据' }).click()
await page.waitForSelector('.toast', { timeout: 240000 })
const toast = await page.locator('.toast').first().innerText().catch(() => null)
await page.screenshot({ path: WS + '/docs/evidence/ui-ops-toast.png' })
// 运营页改成「只留结论」后：服务默认收起，要点展开条；日志再点一次才出现。
// 更细的断言在 ops_conclusion_check.mjs，这里只保证入口仍然点得通、有回执。
await page.locator('.fold').click()
await page.waitForTimeout(800)
const serviceRows = await page.locator('.lines li').count()
await page.locator('.btn.ghost', { hasText: '看日志' }).last().click()
await page.waitForTimeout(1500)
const services = { serviceRows, logbox: await page.locator('.logbox').count() }
await page.screenshot({ path: WS + '/docs/evidence/ui-ops-services.png' })

pages.push(await visit('运行记录', 'ui-runs.png'))
pages.push(await visit('作品库', 'ui-library.png'))
pages.push(await visit('设置', 'ui-settings.png'))

// 窄屏（投影仪 / 笔记本外接屏）
await page.setViewportSize({ width: 1180, height: 860 })
await page.locator('.rail .item[title="工作台"]').click()
await page.waitForTimeout(1500)
await page.screenshot({ path: WS + '/docs/evidence/ui-narrow.png' })

console.log(JSON.stringify({ theme, dialog, toast, services, pages, errors }, null, 1))
await browser.close()
