"""渠道注册表：id/别名解析、按配置启用、给 M3 与 /api/channels 提供统一入口。

新增一个平台只需要三步：
1. 写一个 Channel 子类（放本包下，参照 bilibili.py）；
2. 在 BUILTIN 里登记；
3. 有通道服务的，在 docs/conventions.md 的端口表里给它一个本机端口；
   只出素材包的（material_only=True，如 x.py）没有服务，跳过第 3 步。
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from .base import Channel
from .bilibili import BilibiliChannel
from .x import XChannel
from .xiaohongshu import XiaohongshuChannel
from .zhihu import ZhihuChannel

# 三个真渠道 + x（material-only：只出素材包、不接投递，见 x.py）
BUILTIN: tuple[type[Channel], ...] = (XiaohongshuChannel, ZhihuChannel, BilibiliChannel, XChannel)

# 渠道 id 与别名 → 规范 id。前端的「平台账号」页用 xhs，run 配置里写 xiaohongshu，都认。
ALIASES: dict[str, str] = {}
for _cls in BUILTIN:
    ALIASES[_cls.id] = _cls.id
    for _alias in _cls.aliases:
        ALIASES[_alias] = _cls.id


def canonical(channel_id: str) -> str:
    key = (channel_id or "").strip().lower()
    return ALIASES.get(key, key)


def canonical_all(channel_ids: Iterable[str]) -> list[str]:
    out: list[str] = []
    for cid in channel_ids:
        cid = canonical(cid)
        if cid and cid not in out:
            out.append(cid)
    return out


def class_of(channel_id: str) -> Optional[type[Channel]]:
    """按 id / 别名取渠道**类** —— 类级元信息（名字、能力、成片朝向）不需要 settings。

    别为了问一句「这个平台要横版还是竖版」去构造渠道实例：那要 settings，还会把
    「构造失败」和「没这个渠道」混成一件事（构造抛错被吞掉时，调用方拿到的是默认值，
    看上去一切正常 —— 这种假绿正是 2026-09-19 那次竖版投稿的来源之一）。
    """
    cid = canonical(channel_id)
    for cls in BUILTIN:
        if cls.id == cid:
            return cls
    return None


def orientation_of(channel_id: str) -> str:
    """这个渠道成片要横版(landscape)还是竖版(portrait)。未知渠道按横版（母版）。"""
    return str(getattr(class_of(channel_id), "video_orientation", "landscape") or "landscape")


def default_media_of(channel_id: str) -> str:
    """这个渠道没特别指定时发什么形态：images（图文）还是 video（成片）。

    未知渠道按 `images`：图文是流水线的常规产物，成片是加项，拿不准时错误要偏保守
    （多发一条卡片组图，比误发一条成片更容易收拾）。
    """
    return str(getattr(class_of(channel_id), "default_media", "images") or "images")


def build_all(settings: Any) -> list[Channel]:
    """构造全部内置渠道（不探测、不触网）。"""
    return [cls(settings) for cls in BUILTIN]


def enabled_ids(settings: Any) -> list[str]:
    """配置里启用的渠道（PAPERCAST_CHANNELS，默认三个全开）。"""
    raw = getattr(settings, "channels", None) or [cls.id for cls in BUILTIN]
    return canonical_all(raw)


def get(settings: Any, channel_id: str) -> Optional[Channel]:
    cid = canonical(channel_id)
    for ch in build_all(settings):
        if ch.id == cid:
            return ch
    return None


def resolve_targets(settings: Any, targets: Optional[Iterable[str]]) -> tuple[list[Channel], list[dict[str, str]]]:
    """把 run.config.publish.targets 解析成渠道实例。

    返回 (渠道列表, 问题列表)。**未知或被停用的目标不静默丢弃** —— 它们会作为问题返回，
    由 M3 写进 stage.checks，让人在 dashboard 上看见「你配的渠道没生效」。
    """
    wanted = canonical_all(targets or [])
    if not wanted:
        wanted = enabled_ids(settings)

    enabled = set(enabled_ids(settings))
    channels: list[Channel] = []
    problems: list[dict[str, str]] = []
    for cid in wanted:
        if cid not in {cls.id for cls in BUILTIN}:
            problems.append({"id": cid, "reason": "unknown", "message": f"未知渠道：{cid}"})
            continue
        if cid not in enabled:
            problems.append({"id": cid, "reason": "disabled", "message": f"渠道已停用：{cid}（改 PAPERCAST_CHANNELS 可启用）"})
            continue
        channel = get(settings, cid)
        if channel is not None:
            channels.append(channel)
    return channels, problems
