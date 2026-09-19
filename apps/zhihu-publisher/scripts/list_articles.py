"""只读：列出当前登录账号在知乎上的文章（标题 / 链接 / 时间）。

为什么需要：知乎上游的发布接口**从不返回文章链接**，回执里 url 只能是空的；而「发到哪了」
是用户最需要知道的。这里用同一个已登录浏览器上下文打知乎自己的接口，把最近的文章列出来。
**纯读，不发不回滚任何东西。**

用法（apps/zhihu-publisher 里）：
    COOKIES_PATH=... PYTHONPATH=app:<zhihu-mcp> python scripts/list_articles.py [数量]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))


def main() -> int:
    from browser.manager import create_browser  # type: ignore[import-not-found]

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    out: dict[str, object] = {}
    with create_browser(headless=True) as (_b, _ctx, page):
        page.goto("https://www.zhihu.com/api/v4/me", wait_until="domcontentloaded", timeout=30000)
        me = json.loads(page.inner_text("body"))
        out["account"] = {"name": me.get("name"), "url_token": me.get("url_token")}
        token = me.get("url_token") or ""
        page.goto(
            f"https://www.zhihu.com/api/v4/members/{token}/articles?limit={limit}&offset=0&sort_by=created",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        data = json.loads(page.inner_text("body"))
        items = []
        for it in data.get("data") or []:
            items.append({
                "title": it.get("title"),
                "url": it.get("url"),
                "created": it.get("created"),
                "updated": it.get("updated"),
                "votes": it.get("voteup_count"),
                "comments": it.get("comment_count"),
                "imageCount": len(it.get("image_urls") or []),
                "id": it.get("id"),
            })
        out["total"] = data.get("paging", {}).get("totals")
        out["articles"] = items

    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
