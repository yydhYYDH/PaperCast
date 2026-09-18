"""渠道层的 HTTP 视图：GET /api/channels（渠道清单 + 真实就绪状态）。

与 app/platforms.py 的 /api/platforms 的区别：
- /api/platforms  = 账号视角（谁登录了、怎么登录）→ 「平台账号」页；
- /api/channels   = 投递视角（能不能投、投什么形态、缺什么）→ 发布阶段与设置页。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter

from ..config import settings
from ..platforms import PlatformError   # 与身份层共用同一套错误形状 {error:{code,message}}
from . import registry
from .base import Preflight

router = APIRouter(prefix="/api/channels", tags=["channels"])

_TTL = 15.0  # 探测会触达各通道服务（知乎要开浏览器），前端轮询别打太密
_CACHE: dict[str, Any] = {"at": 0.0, "data": None}


async def _snapshot(force: bool) -> list[dict[str, Any]]:
    now = time.time()
    if not force and _CACHE["data"] is not None and now - _CACHE["at"] < _TTL:
        return _CACHE["data"]

    channels = registry.build_all(settings)
    states = await asyncio.gather(*(ch.preflight() for ch in channels), return_exceptions=True)
    enabled = set(registry.enabled_ids(settings))

    out: list[dict[str, Any]] = []
    for channel, state in zip(channels, states):
        if isinstance(state, Exception):
            state = Preflight(
                state="offline", transport=channel.transport,
                detail=f"探测异常：{type(state).__name__}: {state}"[:200],
                hint=channel.restart_hint,
            )
        item = channel.describe()
        item.update(state.dump())
        item["enabled"] = channel.id in enabled
        out.append(item)

    _CACHE.update(at=now, data=out)
    return out


@router.get("")
async def list_channels(force: bool = False) -> list[dict[str, Any]]:
    """全部渠道及其实时就绪状态（默认 15s 内复用缓存）。"""
    return await _snapshot(force)


@router.get("/{channel_id}")
async def get_channel(channel_id: str, force: bool = True) -> dict[str, Any]:
    cid = registry.canonical(channel_id)
    for item in await _snapshot(force):
        if item["id"] == cid:
            return item
    raise PlatformError(404, "CHANNEL_NOT_FOUND",
                        f"未知渠道：{channel_id}（可用：{', '.join(c.id for c in registry.build_all(settings))}）")
