"""只读探针：把知乎写作页的真实 DOM 事实打出来（**绝不输入文字、绝不发布**）。

为什么需要它：2026-09-19 修「配图/标签发不上去」时，我按上游选择器猜了两轮都没猜中
（上游是 click + expect_file_chooser，我们直接 set_input_files；标签不在正文区，在左下角
「发布设置」里）。猜选择器 = 把不可逆动作押在猜测上，所以先量现场。

用法（在 apps/zhihu-publisher 里，用 zhihu-mcp venv）：
    COOKIES_PATH=... PYTHONPATH=app:<zhihu-mcp> python scripts/probe_write_page.py
产出：stdout 的 JSON + var/artifacts/zhihu-probe/*.png。任何真实发布都不在这里发生。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
OUT = ROOT.parents[1] / "var/artifacts/zhihu-probe"


def _dump(page, facts: dict, name: str) -> None:
    # 任何一处 DOM 结构意外都不该让整次探针白跑（上一版就崩在 SVG 的 className 上）
    try:
        facts[name] = page.evaluate("""() => ({
        url: location.href,
        title: document.title,
        hasTitleBox: !!document.querySelector("textarea[placeholder*='标题'], .WriteIndex-titleInput"),
        hasEditor: !!document.querySelector('.public-DraftEditor-content, [contenteditable="true"]'),
        fileInputs: Array.from(document.querySelectorAll('input[type=file]')).map(i => ({
            id: i.id, cls: (i.getAttribute('class') || '').slice(0, 60), accept: i.accept,
            hidden: i.offsetParent === null, inModal: !!i.closest('[class*=Modal]')
        })),
        buttons: Array.from(document.querySelectorAll('button')).map(b => ({
            t: (b.innerText || '').trim().slice(0, 20), a: b.getAttribute('aria-label') || ''
        })).filter(b => b.t || b.a).slice(0, 60),
        placeholders: Array.from(document.querySelectorAll('input, textarea')).map(i => (
            i.placeholder || ''
        )).filter(Boolean).slice(0, 30),
        modals: Array.from(document.querySelectorAll('[class*="Modal"]')).map(m => ({
            cls: (m.getAttribute('class') || '').slice(0, 80), text: (m.innerText || '').slice(0, 80)
        })).slice(0, 5),
    })""")
    except Exception as exc:
        facts[name] = {"dumpError": f"{type(exc).__name__}: {str(exc)[:160]}"}


def main() -> int:
    from browser.manager import create_browser  # type: ignore[import-not-found]

    facts: dict[str, object] = {}
    OUT.mkdir(parents=True, exist_ok=True)
    with create_browser(headless=True) as (_b, _ctx, page):
        page.set_default_timeout(20000)
        page.goto("https://zhuanlan.zhihu.com/write", wait_until="domcontentloaded", timeout=60000)
        # 等真正的编辑器出现（SPA 要时间；上次 3 秒不够，量到的是空白页）
        try:
            page.wait_for_selector("textarea[placeholder*='标题'], .public-DraftEditor-content", timeout=45000)
            facts["editorAppeared"] = True
        except Exception as exc:
            facts["editorAppeared"] = False
            facts["waitError"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        page.wait_for_timeout(3000)
        _dump(page, facts, "atLoad")
        page.screenshot(path=str(OUT / "load.png"))

        # 点「图片」：只是打开上传弹窗，不上传任何文件
        btn = page.query_selector('button[aria-label*="图片"]') or page.query_selector('button:has-text("图片")')
        facts["imageButton"] = bool(btn)
        if btn is not None:
            btn.click(timeout=8000)
            page.wait_for_timeout(2500)
            _dump(page, facts, "afterImageClick")
            page.screenshot(path=str(OUT / "image-modal.png"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(1200)

        # 打开左下角「发布设置」，找标签输入框
        settings = None
        for el in page.query_selector_all("button, div[role=button], span"):
            try:
                if "发布设置" in (el.inner_text() or ""):
                    settings = el
                    break
            except Exception:
                continue
        facts["settingsButton"] = bool(settings)
        if settings is not None:
            settings.click(timeout=8000)
            page.wait_for_timeout(2000)
            _dump(page, facts, "afterSettings")
            page.screenshot(path=str(OUT / "settings-open.png"))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"facts -> {OUT / 'facts.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
