"""只读探针 2：图片**上传到弹窗**之后，弹窗里到底要点什么才能插进正文。

只做「开弹窗 → 塞 1 张图 → 看弹窗怎么变」，**不点发布、不碰正文内容**。
（本轮踩的坑：对弹窗里的 input set_input_files 之后，图片进的是弹窗的上传队列，
还需要在弹窗里确认/插入，编辑器里的图片数才会变。这里把按钮文案量清楚再写代码。）

用法（apps/zhihu-publisher 里）：
    COOKIES_PATH=... PYTHONPATH=app:<zhihu-mcp> python scripts/probe_image_upload.py <图片路径>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
OUT = ROOT.parents[1] / "var/artifacts/zhihu-probe"


def main() -> int:
    from browser.manager import create_browser  # type: ignore[import-not-found]

    img = Path(sys.argv[1] if len(sys.argv) > 1 else "")
    facts: dict[str, object] = {"image": str(img), "exists": img.is_file()}
    OUT.mkdir(parents=True, exist_ok=True)

    with create_browser(headless=True) as (_b, _ctx, page):
        page.set_default_timeout(20000)
        page.goto("https://zhuanlan.zhihu.com/write", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("textarea[placeholder*='标题'], .public-DraftEditor-content", timeout=45000)
        page.wait_for_timeout(2500)

        page.query_selector('button[aria-label*="图片"]').click(timeout=8000)
        page.wait_for_timeout(2500)
        inp = page.query_selector('[class*="Modal"] input[type=file][accept*="image"]') \
            or page.query_selector("input[type=file][accept='image/*']")
        facts["inputFound"] = inp is not None
        if inp is not None and img.is_file():
            inp.set_input_files(str(img))
            page.wait_for_timeout(2000)
            facts["modalRightAfterUpload"] = page.evaluate("""() => {
                const m = document.querySelector('.Modal-inner') || document.querySelector('[class*="Modal"]');
                return m ? {
                    text: (m.innerText || '').slice(0, 300),
                    imgs: m.querySelectorAll('img').length,
                    buttons: Array.from(m.querySelectorAll('button')).map(b => (b.innerText || '').trim()).filter(Boolean),
                } : null;
            }""")
            facts["editorImagesRightAfterUpload"] = page.evaluate("""() => document.querySelectorAll(
                '.public-DraftEditor-content img, .public-DraftEditor-content figure, [class*="imageContainer"]'
            ).length""")
            page.screenshot(path=str(OUT / "after-upload.png"))
            # 再等一会儿：上传有往返，也许自己就插入并关弹窗了
            page.wait_for_timeout(12000)
            facts["after12s"] = page.evaluate("""() => ({
                modalStillOpen: !!document.querySelector('.Modal-inner'),
                modalText: ((document.querySelector('.Modal-inner') || {}).innerText || '').slice(0, 200),
                editorImages: document.querySelectorAll(
                    '.public-DraftEditor-content img, .public-DraftEditor-content figure, [class*="imageContainer"]'
                ).length,
                allButtons: Array.from(document.querySelectorAll('button')).map(b => (b.innerText || '').trim())
                    .filter(t => t && t.length < 10).slice(0, 40),
            })""")
            page.screenshot(path=str(OUT / "after-upload-12s.png"))

    (OUT / "upload-facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(facts, ensure_ascii=False, indent=1)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
