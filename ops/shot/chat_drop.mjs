import { chromium } from 'playwright'
import { existsSync, readdirSync } from 'node:fs'
function findShell() {
  const base = process.env.HOME + '/.cache/ms-playwright'
  for (const d of existsSync(base) ? readdirSync(base) : []) {
    const p = base + '/' + d + '/chrome-headless-shell-linux64/chrome-headless-shell'
    if (d.startsWith('chromium_headless_shell') && existsSync(p)) return p
  }
}
const browser = await chromium.launch({ executablePath: findShell(), args: ['--no-sandbox', '--disable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
await page.goto('http://127.0.0.1:5178/', { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.chat-page', { timeout: 15000 })
await page.waitForTimeout(1500)
const res = await page.evaluate(async () => {
  const el = document.querySelector('.chat-page')
  el.dispatchEvent(new DragEvent('dragenter', { bubbles: true, dataTransfer: new DataTransfer() }))
  await new Promise((r) => setTimeout(r, 120))
  const shown = document.querySelectorAll('.drop').length
  el.dispatchEvent(new DragEvent('dragleave', { bubbles: true, dataTransfer: new DataTransfer() }))
  await new Promise((r) => setTimeout(r, 120))
  return {
    overlayOnDrag: shown,
    overlayAfterLeave: document.querySelectorAll('.drop').length,
    fileInput: !!document.querySelector('input[type=file][accept*=pdf]'),
    placeholder: document.querySelector('textarea')?.getAttribute('placeholder'),
  }
})
console.log(JSON.stringify(res, null, 1))
await browser.close()
