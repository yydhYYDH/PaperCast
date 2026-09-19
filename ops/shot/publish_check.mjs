// 作品库 → 「发布这一件」：验的是这条链路真的通了，且**一个字节都没真发出去**。
//
// 断言分三层：
//   1. 入口在（作品详情的动作区有「发布这一件」）；
//   2. 面板拿的是**真草稿**（标题/正文/配图都来自这次运行，不是占位符），
//      并且每个渠道的「能不能投」各有各的说法（小红书未登录、B 站缺视频…）；
//   3. 闸门是硬的：「仅存草稿」只落 export/ 不调发布接口；点「确认发布」必须先弹应用内确认框，
//      这里只点「再想想」，**绝不真的投递**（不可逆动作不能进自动化检查）。
import { chromium } from 'playwright'
import { existsSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const EVID = fileURLToPath(new URL('../../docs/evidence/', import.meta.url))
const BASE = process.env.PC_BASE || 'http://127.0.0.1:5178'

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
page.on('pageerror', (e) => out.errors.push('pageerror: ' + e.message.slice(0, 200)))
page.on('console', (m) => { if (m.type() === 'error') out.errors.push('console: ' + m.text().slice(0, 200)) })

/** 后端真的被调了几次、请求体里 confirmed 是什么 —— 接口层证据，不只是界面看着像 */
const calls = []
page.on('response', (r) => {
  const u = r.url()
  if (!/\/api\/runs\/[^/]+\/(drafts|publish)$/.test(u)) return
  const req = r.request()
  let body = null
  try { body = req.postDataJSON() } catch (e) { body = req.postData() }
  calls.push({
    path: u.replace(/^https?:\/\/127\.0\.0\.1:\d+/, ''),
    method: req.method(),
    status: r.status(),
    // 「仅存草稿」与「确认发布」走的是同一个接口，区别只在这个字段 —— 所以要盯它，不是盯路由
    confirmed: body && typeof body === 'object' ? body.confirmed : undefined,
    channelId: body && typeof body === 'object' ? body.channelId : undefined,
  })
})

await page.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 20000 })
await page.waitForTimeout(1500)
await page.getByText('作品库', { exact: true }).first().click()
await page.waitForTimeout(3000)

/** 逐张卡片试到面板出真草稿为止（作品库里有很多条运行，未必第一张就有文章产物） */
let opened = null
const cards = page.locator('#sec-zhihu .work, #sec-xhs .work, #sec-bilibili .work')
const total = await cards.count()
for (let i = 0; i < Math.min(total, 6); i += 1) {
  const card = cards.nth(i)
  if (!(await card.count())) continue
  const title = (await card.locator('.work-title').innerText().catch(() => '')).slice(0, 30)
  await card.click()
  await page.waitForTimeout(900)
  const entry = page.locator('.dlg-box .acts .btn.primary').first()
  if (!(await entry.count())) { await page.keyboard.press('Escape'); continue }
  await entry.click()
  await page.waitForTimeout(3500)

  const state = await page.evaluate(() => {
    const sheet = document.querySelector('.pub')
    if (!sheet) return { sheet: false }
    const title = sheet.querySelector('#pub-title')
    const body = sheet.querySelector('#pub-body')
    return {
      sheet: true,
      hasError: !!sheet.querySelector('.pub-note.err'),
      heading: (sheet.querySelector('.pub-title') || {}).textContent,
      channels: Array.from(sheet.querySelectorAll('.ch .ch-name')).map((n) => n.textContent.trim()),
      states: Array.from(sheet.querySelectorAll('.ch .ch-state')).map((n) => n.textContent.trim()),
      title: title ? title.value : '',
      bodyChars: body ? body.value.length : 0,
      tags: (sheet.querySelector('#pub-tags') || { value: '' }).value,
      shots: Array.from(sheet.querySelectorAll('.shots img')).map((i) => i.naturalWidth > 0).length,
      sourceNote: (sheet.querySelector('.head-row .panel-sub') || { textContent: '' }).textContent.trim(),
      canPublish: !!sheet.querySelector('.gate.ok'),
      gateText: (sheet.querySelector('.gate-line') || { textContent: '' }).textContent.trim().slice(0, 120),
      canDraft: !!Array.from(sheet.querySelectorAll('.gate button')).find((b) => b.textContent.includes('仅存草稿')),
    }
  })
  if (state.sheet && !state.hasError && state.title) { opened = { title, state, index: i }; break }
  // 这一件没有可发草稿：关掉面板，换下一件
  await page.keyboard.press('Escape')
  await page.waitForTimeout(600)
}

out.cases.push({ step: 'open', title: opened?.title ?? '', state: opened?.state ?? null })
if (!opened) throw new Error('六张卡片都没能打开发布面板（或都读不到草稿）')

// ---- 闸门一：仅存草稿 → 必须带 confirmed=false（后端只落 export/，不调发布接口） ----
const before = calls.length
await page.getByRole('button', { name: /仅存草稿/ }).first().click()
await page.waitForTimeout(4000)
const afterDraft = await page.evaluate(() => {
  const r = document.querySelector('.receipt')
  return { text: (r || {}).innerText ? r.innerText.slice(0, 220) : '', cls: r ? r.className : '' }
})
out.cases.push({ step: 'save-draft', receipt: afterDraft.text, cls: afterDraft.cls })
out.cases.push({ step: 'save-draft-http', calls: calls.slice(before) })

// ---- 闸门二：确认发布必须先弹应用内确认框；这里点「再想想」，不真投 ----
const gatePublish = page.locator('.gate button', { hasText: '确认发布' }).first()
if (await gatePublish.count()) {
  const beforeAsk = calls.length
  await gatePublish.click()
  await page.waitForTimeout(900)
  const ask = await page.evaluate(() => {
    const s = document.querySelector('.sheet')
    return s ? { title: s.querySelector('.sheet-title').textContent.trim(),
                 text: s.querySelector('.sheet-text').textContent.trim(),
                 buttons: Array.from(s.querySelectorAll('.sheet-foot .btn')).map((b) => b.textContent.trim()) } : null
  })
  out.cases.push({ step: 'confirm-dialog', ask, http: calls.slice(beforeAsk) })
  const cancel = page.locator('.sheet-foot button', { hasText: '再想想' }).first()
  if (await cancel.count()) await cancel.click()
  await page.waitForTimeout(800)
  const afterCancel = await page.evaluate(() => ({
    askClosed: !document.querySelector('.sheet'),
    // 取消之后绝不能出现**投递**回执（投递回执=真的走完了一次发布）。
    // 不能只看 `.receipt` 在不在：上一步「仅存草稿」是**有意**留回执的，那张是 `.receipt.draft`，
    // 留着它会给这条断言误报 FAIL（2026-09-19 修）。判据改成回执的性质。
    receipt: !!document.querySelector('.receipt.published, .receipt.failed, .receipt.blocked'),
    receiptCls: (document.querySelector('.receipt') || {}).className || '',
    sheetStillOpen: !!document.querySelector('.pub'),
  }))
  out.cases.push({ step: 'cancel', ...afterCancel })
  out.cases.push({ step: 'cancel-http', calls: calls.slice(beforeAsk) })
} else {
  out.cases.push({ step: 'confirm-dialog', skipped: '当前渠道不可投（面板正确地不给「确认发布」按钮）' })
}

await page.screenshot({ path: EVID + 'publish-sheet.png', fullPage: false })

// ==== 阶段二：渠道就绪分支 —— 「确认发布」必须先弹确认框 ====
//
// 现在四个渠道都没登录/服务没起，所以「确认发布」按钮本来就不该出现（阶段一已证）；但这才是
// 核心闸门，不能不验。做法：**不**去拉起知乎服务（那是另一条轨道的事），只让浏览器替换
// /drafts 的响应（把知乎标成已登录），并把 /publish 拦下回一份合成回执 —— 这样后端全程收不到
// 任何请求，而「点确认发布 → 先弹确认框 → 取消 → 再确认」走的是真前端代码与真状态机。
const API = process.env.PC_API || 'http://127.0.0.1:8000'
const DEMO = 'run_x0demo0001'
const real = await fetch(`${API}/api/runs/${DEMO}/drafts`).then((r) => r.json())
const stub = {
  ...real,
  channels: real.channels.map((c) => (c.channelId === 'zhihu'
    ? { ...c, state: 'ready', account: 'YYDH', ready: true, detail: '', hint: '', reason: '' }
    : c)),
}
const sent = []
const SYNTH = {
  channelId: 'zhihu', channelName: '知乎', status: 'published',
  url: 'https://zhuanlan.zhihu.com/p/DEMO', remoteId: 'DEMO', account: 'YYDH', error: null,
  files: ['article.md', 'cover.png'], exportDir: '/tmp/demo/export', exportError: '',
  receipt: { channel: 'zhihu', status: 'published' },
  receiptUrl: `/artifacts/${DEMO}/publish/direct/zhihu/receipt.json`,
  note: '', warnings: [],
}
await page.route('**/api/runs/*/drafts', (route) =>
  route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(stub) }))
await page.route('**/api/runs/*/publish', (route) => {
  sent.push(route.request().postDataJSON())
  return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SYNTH) })
})

// 重开面板（这次读到的是上面那份 stub），换到知乎
await page.keyboard.press('Escape')          // 先关掉阶段一那个面板，否则它盖着货架点不动卡片
await page.waitForTimeout(800)
await cards.nth(opened.index).click()
await page.waitForTimeout(800)
await page.locator('.dlg-box .acts .btn.primary').first().click()
await page.waitForTimeout(1600)
await page.locator('.ch', { hasText: '知乎' }).first().click()
await page.waitForTimeout(500)
const ready = await page.evaluate(() => {
  const s = document.querySelector('.pub')
  return {
    canPublish: !!s?.querySelector('.gate.ok'),
    publishBtn: !!Array.from(s?.querySelectorAll('.gate button') ?? []).find((b) => b.textContent.includes('确认发布')),
    gateText: (s?.querySelector('.gate-line') || {}).textContent?.trim().slice(0, 90),
  }
})
out.cases.push({ step: 'ready-channel', ...ready })

const askState = () => page.evaluate(() => {
  const s = document.querySelector('.sheet')
  return s ? { title: s.querySelector('.sheet-title').textContent.trim(),
               text: s.querySelector('.sheet-text').textContent.trim(),
               buttons: Array.from(s.querySelectorAll('.sheet-foot .btn')).map((b) => b.textContent.trim()) } : null
})
const clickGatePublish = async () => {
  await page.locator('.gate button', { hasText: '确认发布' }).first().click()
  await page.waitForTimeout(900)
}

if (ready.canPublish) {
  // 1) 点「确认发布」→ 必须先弹确认框，且此时一个请求都不许发出去
  await clickGatePublish()
  const ask = await askState()
  out.cases.push({ step: 'ready-confirm-dialog', ask, sentBeforeOK: sent.length })

  // 2) 取消 → 依然一个字节没发
  const cancelReady = page.locator('.sheet-foot button', { hasText: '再想想' }).first()
  if (await cancelReady.count()) await cancelReady.click()
  await page.waitForTimeout(700)
  out.cases.push({
    step: 'ready-cancel', sent: sent.length,
    receipt: await page.evaluate(() => !!document.querySelector('.receipt')),
  })

  // 3) 再点一次并确认：这次 /publish 被拦下，验请求体与「发布成功」回执的渲染
  await clickGatePublish()
  await page.locator('.sheet-foot button', { hasText: '确认发布' }).first().click()
  await page.waitForTimeout(2200)
  out.cases.push({
    step: 'ready-confirmed', sentBody: sent,
    receipt: await page.evaluate(() => {
      const r = document.querySelector('.receipt')
      return r ? { cls: r.className, text: r.innerText.slice(0, 220), link: !!r.querySelector('a.link') } : null
    }),
  })
  await page.screenshot({ path: EVID + 'publish-sheet-ready.png', fullPage: false })
} else {
  out.cases.push({ step: 'ready-channel-skipped', why: 'stub 没把知乎标成就绪' })
}

await page.unroute('**/api/runs/*/drafts')
await page.unroute('**/api/runs/*/publish')

// ---- 结论 ----
const bad = []
if (out.errors.length) bad.push(`控制台/页面报错 ${out.errors.length} 条`)
if (!opened.state.channels.length) bad.push('渠道列表是空的')
if (!opened.state.canDraft) bad.push('没有「仅存草稿」按钮')
if (opened.state.bodyChars < 50) bad.push(`正文字数可疑：${opened.state.bodyChars}`)
const published = (calls) => (calls || []).find((c) => c.path.endsWith('/publish') && c.confirmed !== false)
const draftCalls = out.cases.find((c) => c.step === 'save-draft-http')?.calls ?? []
if (!draftCalls.some((c) => c.path.endsWith('/publish') && c.confirmed === false)) {
  bad.push('「仅存草稿」没有带 confirmed=false 调后端')
}
if (published(draftCalls)) bad.push('「仅存草稿」竟然带了 confirmed=true（会真发出去）')
const draftReceipt = out.cases.find((c) => c.step === 'save-draft')
if (!/只存了草稿|没有投出去|没有调用发布接口|投不了/.test(draftReceipt?.receipt ?? '')) {
  bad.push('「仅存草稿」没有给出可读的回执')
}
const confirmCase = out.cases.find((c) => c.step === 'confirm-dialog')
if (confirmCase?.ask) {
  if (!/不可撤销/.test(confirmCase.ask.text)) bad.push('确认框没说清不可逆')
  if (!confirmCase.ask.buttons.includes('确认发布')) bad.push('确认框的主按钮不是「确认发布」')
  if ((confirmCase.http ?? []).length) bad.push('还没确认就调了发布接口')
  const canceled = out.cases.find((c) => c.step === 'cancel')
  if (canceled?.receipt) bad.push('点了「再想想」却出现了投递回执')
  if ((out.cases.find((c) => c.step === 'cancel-http')?.calls ?? []).length) bad.push('点了「再想想」还是调了后端')
}
const draftNote = draftReceipt?.receipt ?? ''
if (!draftNote) bad.push('「仅存草稿」连一行回执都没有（静默失败）')

// 阶段二的硬断言：确认闸门在这条分支上必须真的挡得住
const readyCase = out.cases.find((c) => c.step === 'ready-channel')
if (readyCase?.canPublish) {
  const ask2 = out.cases.find((c) => c.step === 'ready-confirm-dialog')
  if (!ask2?.ask) bad.push('渠道就绪时点「确认发布」没弹确认框（可能直接发了）')
  if ((ask2?.sentBeforeOK ?? 0) !== 0) bad.push('确认框还没点，发布请求就已经发出去了')
  if (!/不可撤销/.test(ask2?.ask?.text ?? '')) bad.push('确认框没写清「不可撤销」')
  if ((out.cases.find((c) => c.step === 'ready-cancel')?.sent ?? -1) !== 0) bad.push('点了「再想想」仍然发了请求')
  const confirmed = out.cases.find((c) => c.step === 'ready-confirmed')
  const body = confirmed?.sentBody?.[0]
  if (!body) bad.push('确认之后没有发出发布请求')
  else {
    if (body.confirmed !== true) bad.push(`确认之后请求体里 confirmed 不是 true（实际 ${body.confirmed}）`)
    if (body.channelId !== 'zhihu') bad.push(`请求投错渠道：${body.channelId}`)
    if (body.confirmAccount !== 'YYDH') bad.push(`没把账号带上（换了号会误发到别人账号），实际 ${body.confirmAccount}`)
  }
  if (!/已发布/.test(confirmed?.receipt?.text ?? '')) bad.push('发布成功后没有回执卡')
  if (!confirmed?.receipt?.link) bad.push('发布成功后回执里没有链接')
} else {
  bad.push('渠道就绪分支没验到（stub 失效），核心闸门等于没证')
}

console.log(JSON.stringify({ ...out, bad }, null, 2))
await browser.close()
if (bad.length) { console.error('FAIL: ' + bad.join(' | ')); process.exit(1) }
console.log('OK: 发布链路可用，且没有真的投递任何内容')
