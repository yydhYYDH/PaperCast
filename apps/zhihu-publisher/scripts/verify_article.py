"""只读核验：打开知乎文章页，数清「正文里到底有几张图、几个小标题」。

为什么不信回执和清单接口：清单里的 `image_urls` 是「文章配图」那个字段，正文里内嵌的图
它不统计（第一次核验时两条都显示 图 0，容易误判成「图没进去」）。真正的事实只能看渲染后的
文章页。**纯读，不改文章。**

用法：COOKIES_PATH=... PYTHONPATH=app:<zhihu-mcp> python scripts/verify_article.py <url> [--public]
`--public` 表示用未登录的干净上下文（验证它对外可见）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
OUT = ROOT.parents[1] / "var/artifacts/zhihu-verify"


def main() -> int:
    url = sys.argv[1]
    public = "--public" in sys.argv
    facts: dict[str, object] = {"url": url}

    OUT.mkdir(parents=True, exist_ok=True)
    if public:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3500)
            facts.update(_measure(page))
            page.screenshot(path=str(OUT / "public.png"))
            browser.close()
    else:
        from browser.manager import create_browser  # type: ignore[import-not-found]

        with create_browser(headless=True) as (_b, _ctx, page):
            page.set_default_timeout(30000)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3500)
            facts.update(_measure(page))
            page.screenshot(path=str(OUT / "logged-in.png"))

    # 文件名分模式：未登录那次拿到的是知乎「安全验证」页，混进同一个文件会污染证据
    name = "verify-public.json" if public else "verify-logged-in.json"
    (OUT / name).write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(facts, ensure_ascii=False, indent=1))
    return 0


def _measure(page) -> dict:
    return page.evaluate("""() => {
        const body = document.querySelector('.Post-RichText, .RichText, .ArticleItem-content, article') || document.body;
        const text = body.innerText || '';
        return {
            pageTitle: document.title,
            loggedIn: !!document.querySelector('.AppHeader-profile, .Avatar'),
            bodyChars: text.length,
            images: body.querySelectorAll('img').length,
            imageSrcs: Array.from(body.querySelectorAll('img')).slice(0, 6).map((i) => i.currentSrc || i.src),
            headings: body.querySelectorAll('h1, h2, h3').length,
            headingTexts: Array.from(body.querySelectorAll('h1, h2, h3')).slice(0, 8).map((h) => h.tagName + ':' + (h.innerText || '').slice(0, 24)),
            paragraphs: body.querySelectorAll('p').length,
            leftoverMarkers: (text.match(/^#{1,6} /gm) || []).length + text.split('## ').length - 1,
            headText: text.slice(0, 200),
        };
    }""")


if __name__ == "__main__":
    raise SystemExit(main())
