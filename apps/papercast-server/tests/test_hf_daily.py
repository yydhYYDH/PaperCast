"""HuggingFace Daily Papers（app/hf_daily_api.py）：归一化、排序、缓存、抓不到时的降级。

不联网：monkeypatch `_fetch` 与缓存目录到 tmp_path。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import hf_daily_api as hf


RAW = [
    {"paper": {"id": "2609.11111", "title": "低赞的", "upvotes": 3,
               "authors": [{"name": "A"}, {"name": "B"}], "summary": "s1"},
     "publishedAt": "2026-09-24T00:00:00Z", "thumbnail": "t1"},
    {"paper": {"id": "2609.22222", "title": "高赞的", "upvotes": 20,
               "authors": [{"name": "C"}], "summary": "s2", "githubRepo": "https://github.com/x/y"},
     "publishedAt": "2026-09-23T00:00:00Z", "thumbnail": "t2"},
    {"paper": {"id": "", "title": "没 id 的"}, "publishedAt": ""},   # 缺 id → 丢弃
]


@pytest.fixture
def cache_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(hf, "CACHE_DIR", tmp_path / "hf-daily")
    return hf.CACHE_DIR


def test_rows_normalize_and_sort():
    rows = hf._rows(RAW)
    assert [r["arxivId"] for r in rows] == ["2609.22222", "2609.11111"]      # 按赞降序
    top = rows[0]
    assert top["arxivUrl"] == "https://arxiv.org/abs/2609.22222"
    assert top["pdfUrl"] == "https://arxiv.org/pdf/2609.22222"
    assert top["authors"] == ["C"] and top["githubRepo"].endswith("/x/y")


def test_papers_fetches_and_caches(monkeypatch, cache_dir):
    calls = {"n": 0}

    def fake_fetch(day, sort=""):
        calls["n"] += 1
        return RAW

    monkeypatch.setattr(hf, "_fetch", fake_fetch)
    first = hf.papers("2026-09-24", force=True)
    assert first["count"] == 2 and first["stale"] is False
    assert (cache_dir / "2026-09-24.json").is_file()
    # 第二次走缓存，不再抓
    second = hf.papers("2026-09-24")
    assert second["count"] == 2 and calls["n"] == 1


def test_stale_fallback_when_fetch_fails(monkeypatch, cache_dir):
    monkeypatch.setattr(hf, "_fetch", lambda day, sort="": RAW)
    hf.papers("2026-09-24", force=True)          # 先写好缓存

    def boom(day, sort=""):
        raise RuntimeError("no network")

    monkeypatch.setattr(hf, "_fetch", boom)
    data = hf.papers("2026-09-24", force=True)    # force 绕过缓存 → 抓失败 → 回旧缓存
    assert data["count"] == 2 and data["stale"] is True and "no network" in data["error"]


def test_502_when_fetch_fails_and_no_cache(monkeypatch, cache_dir):
    monkeypatch.setattr(hf, "_fetch", lambda day, sort="": (_ for _ in ()).throw(RuntimeError("down")))
    with pytest.raises(HTTPException) as e:
        hf.papers("1999-01-01", force=True)
    assert e.value.status_code == 502


def test_trending_sort_uses_its_own_cache(monkeypatch, cache_dir):
    """sort=trending 走趋势榜、单独缓存（和日期榜不串）。"""
    seen = {}

    def fake_fetch(day, sort=""):
        seen["day"], seen["sort"] = day, sort
        return RAW

    monkeypatch.setattr(hf, "_fetch", fake_fetch)
    d = hf.papers(None, sort="trending", force=True)
    assert seen == {"day": None, "sort": "trending"}
    assert d["sort"] == "trending" and d["date"] == ""
    assert (cache_dir / "trending.json").is_file()
