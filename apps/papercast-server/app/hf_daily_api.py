"""HuggingFace Daily Papers（`GET /api/hf-daily`）—— 把当日的 HF 每日论文端给前端。

数据源是 HF 的官方 JSON 接口 `https://huggingface.co/api/daily_papers?date=YYYY-MM-DD`
（不是爬网页，结构稳定）。每条里的 `paper.id` 就是 arXiv 编号，拼 `https://arxiv.org/abs/<id>`
即可喂给我们的 intake。按日期缓存到 `var/cache/hf-daily/<date>.json`，避免一天里反复打接口。

抓不到时（没网/代理没开）**有旧缓存就回旧的并标 `stale`**，没有才报 502 —— 不假装拿到了新数据。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query

from .config import VAR_DIR

router = APIRouter(prefix="/api/hf-daily", tags=["hf-daily"])

API = "https://huggingface.co/api/daily_papers"
UA = "PaperCast/0.1 (HF daily papers intake; +https://github.com/yydhYYDH/PaperCast)"
CACHE_DIR = VAR_DIR / "cache" / "hf-daily"
TTL = 6 * 3600  # 一天的榜单基本不变；6 小时刷新一次即可


def _fetch(day: Optional[str], sort: str = "") -> list[dict[str, Any]]:
    # HF 同一接口支持两种榜：?sort=trending（趋势榜，忽略日期）或 ?date=YYYY-MM-DD（当日）。
    params: list[str] = []
    if sort:
        params.append(f"sort={sort}")
    if day and not sort:
        params.append(f"date={day}")
    url = API + ("?" + "&".join(params) if params else "")
    resp = httpx.get(url, headers={"User-Agent": UA}, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError(f"HF 返回的不是列表：{type(data).__name__}")
    return data


def _rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """归一化成「前端直接能渲染、也能直接建 run」的形状，按赞数排序。"""
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
            "upvotes": p.get("upvotes") if p.get("upvotes") is not None else it.get("upvotes"),
            "publishedAt": it.get("publishedAt") or p.get("publishedAt") or "",
            "authors": [a.get("name") for a in (p.get("authors") or []) if a.get("name")],
            "thumbnail": it.get("thumbnail") or "",
            "githubRepo": p.get("githubRepo") or "",
            "arxivUrl": f"https://arxiv.org/abs/{aid}",
            "pdfUrl": f"https://arxiv.org/pdf/{aid}",
        })
    out.sort(key=lambda x: -(x["upvotes"] or 0))
    return out


def papers(day: Optional[str] = None, *, sort: str = "", force: bool = False) -> dict[str, Any]:
    key = "trending" if sort == "trending" else (day or "latest")
    path = CACHE_DIR / f"{key}.json"
    if not force and path.is_file() and time.time() - path.stat().st_mtime < TTL:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass  # 缓存坏了就当没有，重新抓
    try:
        rows = _rows(_fetch(day, sort))
    except Exception as exc:
        if path.is_file():  # 有旧缓存：回旧的，如实标 stale + 原因
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["stale"] = True
                data["error"] = f"{type(exc).__name__}: {exc}"[:200]
                return data
            except Exception:
                pass
        raise HTTPException(status_code=502, detail=f"抓 HuggingFace 失败：{type(exc).__name__}: {exc}"[:200])
    data = {"date": ("" if sort == "trending" else (day or "")), "sort": sort,
            "fetchedAt": int(time.time()), "count": len(rows),
            "papers": rows, "stale": False, "error": ""}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


@router.get("")
def list_hf_daily(date: str = Query(""), sort: str = Query(""),
                  force: bool = Query(False)) -> dict[str, Any]:
    """HF Daily Papers。`date=YYYY-MM-DD` 取当日；`sort=trending` 取趋势榜（忽略日期）；
    两者都留空 = HF 的最新一批。"""
    sort = sort.strip().lower()
    if sort not in ("", "trending"):
        raise HTTPException(status_code=400, detail=f"不支持的 sort：{sort}（只认 trending）")
    return papers(date.strip() or None, sort=sort, force=force)
