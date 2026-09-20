"""小红书渠道 ↔ MCP 响应的字段契约（纯离线，不连任何服务）。

背景（2026-09-20）：MCP 的 /api/v1/publish 成功时只回 title/content/images/status，
里面**没有任何笔记标识**，而后端本来就在读 noteId/permlink/url —— 于是回执里永远没有链接，
界面上「已发布」却看不到原文，用户会以为没发出去。

现在 MCP 会回 noteId / noteUrl（发布成功后它去「我的笔记」按标题找回刚发出去那条），
这个文件钉住字段映射，免得以后又漂移；旧字段名也留着兼容。
"""

from __future__ import annotations

import asyncio
import types
from pathlib import Path
from typing import Any

import pytest

from app.channels.base import Materials
from app.channels.xiaohongshu import XiaohongshuChannel

NOTE_URL = "https://www.xiaohongshu.com/explore/abc123?xsec_token=t&xsec_source=pc_feed"


def _channel(payload: dict[str, Any]) -> XiaohongshuChannel:
    """渠道 + 一个不触网的替身 _request：只把 MCP 的响应体塞回去。"""
    channel = XiaohongshuChannel(types.SimpleNamespace(xhs_mcp_base="http://127.0.0.1:18060"))

    async def fake_request(method: str, path: str, *, timeout: float, **kw: Any) -> tuple[int, dict[str, Any]]:
        return 200, {"success": True, "data": payload}

    channel._request = fake_request  # type: ignore[method-assign]
    return channel


def _materials() -> Materials:
    return Materials(
        title="把夏普比率做成可微层",
        body="正文",
        tags=["稀疏组合优化"],
        images=[Path("/tmp/p1.jpg")],
        run_id="run_test",
    )


def test_note_id_and_url_land_in_delivery() -> None:
    d = asyncio.run(_channel({"noteId": "abc123", "noteUrl": NOTE_URL}).publish(_materials(), confirmed=True))
    assert d.status == "published"
    assert d.remote_id == "abc123"
    assert d.url == NOTE_URL


def test_legacy_field_names_still_map() -> None:
    """改之前 MCP 只回 note_id/permlink（其实一直没回）—— 两种写法都要认。"""
    d = asyncio.run(_channel({"note_id": "old1", "permlink": NOTE_URL}).publish(_materials(), confirmed=True))
    assert (d.remote_id, d.url) == ("old1", NOTE_URL)


def test_missing_note_fields_stay_empty_not_faked() -> None:
    """MCP 没给出笔记标识时（列表还没刷新出来）宁可留空，不许编一个地址。"""
    d = asyncio.run(_channel({"status": "发布完成"}).publish(_materials(), confirmed=True))
    assert d.status == "published"
    assert (d.remote_id, d.url) == ("", "")
