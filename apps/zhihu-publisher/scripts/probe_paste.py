"""只读探针 4：用剪贴板粘贴正文，看能不能一次性得到正确的段落/标题块。

为什么试这个：逐行 type + Enter 在**长段落**上会被编辑器吞掉换行（实测 54 行只得到 3 个块，
自检报「28 行没能断开」），而短样本的探针里一切正常。Draft.js 的粘贴处理会把多行纯文本
按换行拆成多个 block，所以粘贴可能一次就把结构做对，还比逐行敲快一个数量级。
**不点发布。**

用法：COOKIES_PATH=... PYTHONPATH=app:<zhihu-mcp> python scripts/probe_paste.py <正文文件>
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
OUT = ROOT.parents[1] / "var/artifacts/zhihu-probe"


def _measure(page) -> dict:
    return page.evaluate("""() => {
        const ed = document.querySelector('.public-DraftEditor-content, .DraftEditor-root');
        if (!ed) return {blocks: 0, headings: 0, listItems: 0, markerBlocks: 0, head: []};
        const blocks = Array.from(ed.querySelectorAll('[data-block="true"]'));
        const texts = blocks.map((b) => (b.innerText || '').replace(/\\n/g, ' ').trim());
        return {
            blocks: blocks.length,
            headings: blocks.filter((b) => (b.tagName || '').charAt(0) === 'H').length,
            listItems: blocks.filter((b) => b.tagName === 'LI').length,
            markerBlocks: texts.filter((t) => t.charAt(0) === '#' || t.indexOf('## ') >= 0).length,
            emptyBlocks: texts.filter((t) => !t).length,
            head: blocks.slice(0, 10).map((b) => b.tagName + ': ' + (b.innerText || '').replace(/\\n/g, ' ').slice(0, 30)),
        };
    }""")


def main() -> int:
    from browser.manager import create_browser  # type: ignore[import-not-found]

    src = Path(sys.argv[1])
    content = src.read_text(encoding="utf-8")
    facts: dict[str, object] = {"source": str(src), "chars": len(content), "newlines": content.count("\n")}
    OUT.mkdir(parents=True, exist_ok=True)

    with create_browser(headless=True) as (_b, context, page):
        page.set_default_timeout(20000)
        page.goto("https://zhuanlan.zhihu.com/write", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector(".public-DraftEditor-content", timeout=45000)
        page.wait_for_timeout(2500)

        ed = page.query_selector(".public-DraftEditor-content") or page.query_selector("[contenteditable='true']")
        ed.click()
        page.wait_for_timeout(300)
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        page.wait_for_timeout(800)

        try:
            context.grant_permissions(["clipboard-read", "clipboard-write"], origin="https://zhuanlan.zhihu.com")
        except Exception as exc:
            facts["grantError"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        wrote = page.evaluate("""async (t) => {
            try { await navigator.clipboard.writeText(t); return true; }
            catch (e) { return String(e); }
        }""", content)
        facts["clipboardWrite"] = wrote

        t0 = time.time()
        ed.click()
        page.wait_for_timeout(300)
        page.keyboard.press("Control+V")
        page.wait_for_timeout(4000)
        facts["pasteSeconds"] = round(time.time() - t0, 1)
        facts["afterPaste"] = _measure(page)
        page.screenshot(path=str(OUT / "paste.png"))

        # 策略 F：逐行敲，但**每行敲完后先停 0.4 秒再按 Enter**（怀疑 Enter 被 markdown 提交吞掉）
        ed.click()
        page.wait_for_timeout(300)
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        page.wait_for_timeout(800)
        t0 = time.time()
        lines = content.split("\n")
        for line in lines:
            if line.strip():
                page.keyboard.type(line, delay=3)
            page.wait_for_timeout(400)
            page.keyboard.press("Enter")
            page.wait_for_timeout(120)
        page.wait_for_timeout(2500)
        facts["typeWithPauseSeconds"] = round(time.time() - t0, 1)
        facts["afterTypeWithPause"] = _measure(page)
        page.screenshot(path=str(OUT / "type-with-pause.png"))

    (OUT / "paste-facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(facts, ensure_ascii=False, indent=1)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
