// 「新开一个对话」核验：点完必须回到最开始那一屏 —— 旧运行的论文卡、六段进度卡、右栏
// 「谁在干活」名单全部收起来，输入框里的半截草稿也清掉；而正在跑 / 正等你确认的运行
// **不许**被收起来（它不会因为你换对话就停下，收起来等于让你错过那一下）。
//
// 用法：node ops/shot/new_thread_check.mjs        （需要前端 5178 与后端 8000 都在跑）
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
const browser = await chromium.launch({
  executablePath: findShell(),
  args: ['--no-sandbox', '--disable-gpu', '--no-proxy-server'],
})
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
const errors = []
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message.slice(0, 200)))
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 200)) })

await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded', timeout: 20000 })
await page.waitForSelector('.thread', { timeout: 15000 })
await page.waitForTimeout(2200)

/** 一屏的全部可判据：消息数、右栏那条论文、名单人数、是不是最初那句问候、toast 文本 */
async function snap() {
  return page.evaluate(() => {
    const txt = (el) => (el ? el.textContent.trim() : '')
    const body = document.body.innerText
    return {
      msgs: document.querySelectorAll('.thread [id^="m-"]').length,
      paper: txt(document.querySelector('.rail-side .paper')),
      roster: document.querySelectorAll('.rail-side .roster li').length,
      greet: txt(document.querySelector('.thread .inner')).includes('把论文丢进来就行'),
      draft: document.querySelector('.composer textarea, .box textarea')?.value ?? '',
      live: body.includes('先把它弄完再新开'),
    }
  })
}

const before = await snap()
await page.screenshot({ path: WS + '/docs/evidence/new-thread-before.png' })

// 先在输入框里打半截字：新开之后它不该留在"干净的一屏"里
await page.locator('textarea').first().fill('这句话不该留在新对话里')
const typed = await snap()          // 先证明这段字真的在这个 textarea 里，免得"清掉了"是假通过
await page.getByRole('button', { name: '新开一个对话' }).click()
await page.waitForSelector('.mask .sheet', { timeout: 5000 })
const askText = (await page.locator('.sheet-text').innerText()).replace(/\s+/g, ' ').trim()
await page.locator('.sheet-foot .btn.primary').click()   // okLabel = 「新开」
await page.waitForTimeout(1200)
const after = await snap()
await page.screenshot({ path: WS + '/docs/evidence/new-thread-clean.png' })

// 再挑一条「等你确认」的运行，试试点新开：必须被挡住
let guarded = null
// 状态文案见 utils.ts RUN_STATUS：waiting = 「待确认」
const liveItem = page.locator('.rail-side .item').filter({ hasText: '待确认' }).first()
if (await liveItem.count()) {
  await liveItem.click()
  await page.waitForTimeout(1200)
  const picked = await snap()
  await page.getByRole('button', { name: '新开一个对话' }).click()
  await page.waitForTimeout(900)
  const blocked = await snap()
  guarded = { picked: picked.paper, afterClick: blocked.paper, toast: blocked.live, dialog: await page.locator('.mask .sheet').count() }
  await page.screenshot({ path: WS + '/docs/evidence/new-thread-live-guard.png' })
}

const checks = [
  ['点之前是旧运行那一屏（消息 >1、右栏有论文名、名单有人）', before.msgs > 1 && before.paper !== '还没有开始' && before.roster > 0],
  ['半截草稿先确实存在过（证明下面的"清掉"不是假通过）', typed.draft === '这句话不该留在新对话里'],
  ['确认框说了会收起运行、也说了怎么点回来', askText.includes('运行历史')],
  ['点完只剩最初那句问候', after.greet === true && after.msgs === 1],
  ['右栏回到空态「还没有开始」', after.paper === '还没有开始'],
  ['右栏名单收起来了（0 人）', after.roster === 0],
  ['输入框里的半截草稿清掉了', after.draft === ''],
  ['真的选中了一条待确认的运行（挡拦分支被测到，不是空过）', !!guarded],
  ['在途运行被挡住：没弹确认框、运行还在、说了原因', !!guarded && guarded.dialog === 0 && guarded.afterClick === guarded.picked && guarded.toast === true],
  ['无控制台报错', errors.length === 0],
]

console.log('点之前:', JSON.stringify(before))
console.log('点之后:', JSON.stringify(after))
if (guarded) console.log('在途挡拦:', JSON.stringify(guarded))
let bad = 0
for (const [name, ok] of checks) { if (!ok) bad++; console.log((ok ? '  ✓ ' : '  ✗ ') + name) }
if (errors.length) console.log('控制台:', errors.join(' | '))
await browser.close()
console.log(bad ? '\n' + bad + ' 项没过' : '\n全部通过')
process.exit(bad ? 1 : 0)
