"""只读探针 3：正文怎么输入才会产生「换行/段落块」。

背景：2026-09-19 第一次真发布（以及后来的逐行输入）都把 markdown 的换行吃掉了 ——
正文变成一整段，`##` 原样挤在句子中间。源字符串本身是好的（53 个换行），所以问题在
「键盘输入方式」。这里在同一页里依次试四种策略，直接量 `[data-block]` 的个数与 innerText，
用事实决定用哪种。**不点发布。**

用法：COOKIES_PATH=... PYTHONPATH=app:<zhihu-mcp> python scripts/probe_typing.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
OUT = ROOT.parents[1] / "var/artifacts/zhihu-probe"

SAMPLE = "## 标题甲\n\n正文乙的一段话。\n\n- 列表丙\n"
# 真数据的第一行是 `# 标题`（H1）。怀疑：知乎把首行 H1 当成「文章标题」处理，
# 之后这个块就吞掉 Enter —— 整篇文本被压进一个块。用同样的短样本验证。
SAMPLE_H1 = "# 甲标题\n\n## 乙小节\n\n正文丙。\n\n- 丁\n"


def _measure(page) -> dict:
    return page.evaluate("""() => {
        const ed = document.querySelector('.public-DraftEditor-content, .DraftEditor-root');
        if (!ed) return {blocks: 0, text: '', tags: []};
        const blocks = ed.querySelectorAll('[data-block="true"]');
        return {
            blocks: blocks.length,
            headings: ed.querySelectorAll('h1, h2, h3').length,
            text: (ed.innerText || '').slice(0, 160),
            tags: Array.from(blocks).slice(0, 6).map((b) => b.tagName + ':' + (b.innerText || '').slice(0, 14)),
        };
    }""")


def _clear(page) -> None:
    ed = page.query_selector(".public-DraftEditor-content") or page.query_selector("[contenteditable='true']")
    ed.click()
    page.wait_for_timeout(300)
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.wait_for_timeout(600)


def main() -> int:
    from browser.manager import create_browser  # type: ignore[import-not-found]

    facts: dict[str, object] = {}
    OUT.mkdir(parents=True, exist_ok=True)
    with create_browser(headless=True) as (_b, _ctx, page):
        page.set_default_timeout(20000)
        page.goto("https://zhuanlan.zhihu.com/write", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector(".public-DraftEditor-content", timeout=45000)
        page.wait_for_timeout(2500)

        # A：逐行 type + Enter
        _clear(page)
        for line in SAMPLE.split("\n"):
            if line:
                page.keyboard.type(line, delay=3)
            page.keyboard.press("Enter")
            page.wait_for_timeout(60)
        page.wait_for_timeout(1500)
        facts["A_type_plus_enter"] = _measure(page)
        page.screenshot(path=str(OUT / "typing-A.png"))

        # A2：首行带 # 的真结构（逐行 type + Enter）
        _clear(page)
        for line in SAMPLE_H1.split("\n"):
            if line:
                page.keyboard.type(line, delay=3)
            page.keyboard.press("Enter")
            page.wait_for_timeout(60)
        page.wait_for_timeout(1500)
        facts["A2_leading_hash_type_enter"] = _measure(page)

        # B：逐行 type + Shift+Enter
        _clear(page)
        for line in SAMPLE.split("\n"):
            if line:
                page.keyboard.type(line, delay=3)
            page.keyboard.press("Shift+Enter")
            page.wait_for_timeout(60)
        page.wait_for_timeout(1500)
        facts["B_type_plus_shift_enter"] = _measure(page)

        # C：整段 insert_text（含 \n）
        _clear(page)
        page.keyboard.insert_text(SAMPLE)
        page.wait_for_timeout(1500)
        facts["C_insert_text_all"] = _measure(page)

        # D：逐行 insert_text + Enter
        _clear(page)
        for line in SAMPLE.split("\n"):
            if line:
                page.keyboard.insert_text(line)
            page.keyboard.press("Enter")
            page.wait_for_timeout(60)
        page.wait_for_timeout(1500)
        facts["D_insert_text_plus_enter"] = _measure(page)
        page.screenshot(path=str(OUT / "typing-D.png"))

    (OUT / "typing-facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
    for key, val in facts.items():
        print(f"{key}: blocks={val.get('blocks')} headings={val.get('headings')} tags={val.get('tags')}")
        print(f"   text={val.get('text')!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
