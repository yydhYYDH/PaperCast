"""定时发布：排期时间的纯函数校验（不联网、不起渠道）。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.channels.base import Materials
from app.channels.xiaohongshu import XiaohongshuChannel
from app.config import settings
from app.direct_publish import _normalize_schedule


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


def test_schedule_accepts_1h_to_14d():
    iso, why = _normalize_schedule(_iso(timedelta(hours=2)))
    assert why == ""
    assert iso  # 归一化后仍是可解析的 ISO


def test_schedule_rejects_too_soon():
    iso, why = _normalize_schedule(_iso(timedelta(minutes=30)))
    assert iso == ""
    assert "1 小时" in why


def test_schedule_rejects_too_far():
    iso, why = _normalize_schedule(_iso(timedelta(days=15)))
    assert iso == ""
    assert "14 天" in why


def test_schedule_rejects_bad_format():
    iso, why = _normalize_schedule("明天下午三点")
    assert iso == ""
    assert "格式" in why


def test_schedule_naive_local_time_is_accepted():
    # 无时区按本机时区补全；本机时间 +2 小时一定在合法窗口内
    naive = (datetime.now() + timedelta(hours=2)).replace(microsecond=0)
    iso, why = _normalize_schedule(naive.isoformat())
    assert why == ""
    assert iso


def test_xhs_passes_schedule_at_to_mcp(monkeypatch, tmp_path: Path):
    """排期字符串必须原样进 MCP 请求体；不排期时请求体里不该有 schedule_at。

    本仓不引 pytest-asyncio，异步用例用 asyncio.run()（见 tests/test_arxiv.py）。
    """
    ch = XiaohongshuChannel(settings)
    seen: dict = {}

    async def fake_request(method, path, *, timeout, **kw):
        seen["path"] = path
        seen["body"] = kw.get("json") or {}
        return 200, {"success": True, "data": {"noteId": "n1"}}

    monkeypatch.setattr(ch, "_request", fake_request)

    img = tmp_path / "p1.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    when = "2026-10-17T18:00:00+08:00"

    async def run():
        m = Materials(title="测试标题", body="正文", tags=["a"], images=[img], schedule_at=when)
        delivery = await ch.publish(m, confirmed=True)
        assert delivery.status == "published"
        assert seen["path"] == "/api/v1/publish"
        assert seen["body"]["schedule_at"] == when

        # 不排期：请求里不应出现 schedule_at
        seen.pop("body", None)
        m2 = Materials(title="测试标题", body="正文", tags=["a"], images=[img])
        await ch.publish(m2, confirmed=True)
        assert "schedule_at" not in seen["body"]

    asyncio.run(run())
