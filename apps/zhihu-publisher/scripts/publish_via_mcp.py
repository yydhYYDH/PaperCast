#!/usr/bin/env python3
"""通过 Douyh123/zhihu-mcp 的 MCP 工具发知乎文章（Playwright 通道，用 cookie 登录态）。

先跑 apps/zhihu-publisher/scripts/login_wait.py 拿到有效 cookie（含 z_c0），再执行本脚本。

用法:
    python publish_via_mcp.py --check                     # 查登录状态
    python publish_via_mcp.py --title T --file article.md # 发文章（Markdown 正文）
    python publish_via_mcp.py --title T --content "..." --tags A B --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

WS = Path(os.environ.get("PAPERCAST_WS") or Path(__file__).resolve().parents[3])
REPO = Path(os.environ.get("ZHIHU_MCP_REPO") or WS / "reference" / "upstream" / "zhihu-mcp")
os.environ.setdefault("COOKIES_PATH", str(WS / "var" / "secrets" / "zhihu" / "cookies.json"))
os.chdir(REPO)
sys.path.insert(0, str(REPO))


async def run(args) -> int:
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    # 上游 main.py 起的是 streamable-http 服务（不是 stdio），默认 127.0.0.1:18060/mcp
    url = os.environ.get("ZHIHU_MCP_URL", "http://127.0.0.1:18060/mcp")
    async with Client(StreamableHttpTransport(url)) as client:
        if args.check:
            result = await client.call_tool("check_login_status", {})
            print(result.content[0].text if result.content else result)
            return 0

        content = args.content
        if args.file:
            content = Path(args.file).read_text(encoding="utf-8")
        if not content:
            print("需要 --content 或 --file", file=sys.stderr)
            return 2

        print(f"标题: {args.title}")
        print(f"正文长度: {len(content)} 字")
        print(f"图片: {args.images or '无'}")
        print(f"话题: {args.tags or '无'}")
        if args.dry_run:
            print("dry-run: 未调用 publish_article")
            return 0

        result = await client.call_tool(
            "publish_article",
            {"title": args.title, "content": content,
             "images": args.images or None, "tags": args.tags or None},
        )
        print(result.content[0].text if result.content else result)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--title", default="")
    ap.add_argument("--content", default="")
    ap.add_argument("--file", default="")
    ap.add_argument("--images", nargs="*", default=[])
    ap.add_argument("--tags", nargs="*", default=[])
    ap.add_argument("--dry-run", action="store_true")
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
