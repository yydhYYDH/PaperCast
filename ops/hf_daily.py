#!/usr/bin/env python3
"""抓 HuggingFace Daily Papers → 拿到每篇的 arXiv 链接。

数据源：HuggingFace 的官方 JSON 接口（不是爬网页，结构稳定、无反爬）：
    https://huggingface.co/api/daily_papers?date=YYYY-MM-DD
每条里的 `paper.id` 就是 arXiv 编号，拼 `https://arxiv.org/abs/<id>` 即可。

用法：
    python3 ops/hf_daily.py                 # 最近一天（不传 date，HF 回最新）
    python3 ops/hf_daily.py 2026-09-24      # 指定日期
    python3 ops/hf_daily.py --json          # 输出 JSON（给别的程序吃）
    python3 ops/hf_daily.py 2026-09-24 --json > var/cache/hf-daily/2026-09-24.json

注意：本机要能出网（有 http_proxy 时 urllib 会走系统代理）。按日期缓存可避免每天重复打接口。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from typing import Any

API = "https://huggingface.co/api/daily_papers"
UA = "PaperCast/0.1 (HF daily papers intake; +https://github.com/yydhYYDH/PaperCast)"


def fetch(date: str | None = None, timeout: float = 30.0) -> list[dict[str, Any]]:
    url = API + (f"?date={date}" if date else "")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (固定 https 域名)
        data = json.load(resp)
    if not isinstance(data, list):
        raise RuntimeError(f"HF 返回的不是列表：{type(data).__name__}")
    return data


def rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """归一化成「我们能直接用来建 run」的形状，按赞数排序。"""
    out: list[dict[str, Any]] = []
    for it in items:
        p = it.get("paper") or {}
        aid = str(p.get("id") or "").strip()
        if not aid:
            continue
        out.append({
            "arxivId": aid,
            "title": p.get("title") or it.get("title") or "",
            "summary": p.get("summary") or it.get("summary") or "",
            "upvotes": p.get("upvotes"),
            "publishedAt": it.get("publishedAt") or p.get("publishedAt") or "",
            "authors": [a.get("name") for a in (p.get("authors") or []) if a.get("name")],
            "thumbnail": it.get("thumbnail") or "",
            "githubRepo": p.get("githubRepo") or "",
            # 直接能喂给 papercast 的 arXiv 链接
            "arxivUrl": f"https://arxiv.org/abs/{aid}",
            "pdfUrl": f"https://arxiv.org/pdf/{aid}",
        })
    out.sort(key=lambda x: -(x["upvotes"] or 0))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="HuggingFace Daily Papers → arXiv 链接")
    ap.add_argument("date", nargs="?", default=None, help="YYYY-MM-DD，留空取最新")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    try:
        papers = rows(fetch(args.date))
    except Exception as exc:
        print(f"抓取失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        print("（本机没网 / 代理没开时会这样；HF 需要能出网）", file=sys.stderr)
        return 1

    if args.json:
        json.dump({"date": args.date, "count": len(papers), "papers": papers},
                  sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 0

    label = args.date or "最新"
    print(f"# HuggingFace Daily Papers · {label} · {len(papers)} 篇\n")
    for i, p in enumerate(papers, 1):
        star = f"[{p['upvotes']}赞]" if p.get("upvotes") is not None else ""
        print(f"{i:2d}. {star} {p['title']}")
        print(f"    {p['arxivUrl']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
