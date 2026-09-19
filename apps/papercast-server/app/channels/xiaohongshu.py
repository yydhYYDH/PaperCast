"""小红书渠道：xiaohongshu-mcp（本机 :18060）。图文笔记 + 视频笔记。

平台规则留在 adapter 里（不散到编排层）：
- 标题计重 ≤ 38（与 M2 的 title_weight 同一套算法）；
- 图文笔记 1~18 张图；视频笔记走 publish_video；
- cookie 认进程 cwd（apps/xiaohongshu-mcp/cookies.json），所以 MCP 必须在该目录启动。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Delivery, HttpChannel, Materials, Preflight

TITLE_WEIGHT_LIMIT = 38
MAX_IMAGES = 18


class XiaohongshuChannel(HttpChannel):
    id = "xiaohongshu"
    name = "小红书"
    aliases = ("xhs",)
    capabilities = frozenset({"text", "images", "video"})
    # 小红书是竖版平台：成片优先用 9:16 的 video-vertical.mp4（这是 2026-09-19 之前
    # 靠 sorted() 的字典序偶然得到的结果，现在把它写明白，别让它再随文件名漂移）
    video_orientation = "portrait"
    # **默认发图文**（2026-09-19 定）：卡片组图是流水线的常规产物，成片是加项；
    # 而且实测视频笔记这条分支在 Windows 侧连续 3 次卡在"点发布"不落地，
    # 图文在 Linux 侧一次就成功。想发成片走 `POST /api/runs/{id}/publish/video`。
    default_media = "images"
    login_kind = "qrcode"
    transport = "mcp-http"
    why = "图文/视频笔记：MCP 开无头浏览器操作网页版，扫码登录"
    restart_hint = "./ops/start_all.sh mcp"

    @property
    def base_url(self) -> str:
        return self.settings.xhs_mcp_base

    def supports(self, m: Materials) -> tuple[bool, str]:
        if m.video is not None:
            miss = self.missing(m, video=True)
            return (False, f"缺{miss}") if miss else (True, "视频笔记")
        miss = self.missing(m, image=True)
        if miss:
            return False, f"缺{miss}（图文笔记至少 1 张图）"
        if len(m.images) > MAX_IMAGES:
            return False, f"图片 {len(m.images)} 张 > {MAX_IMAGES} 张（小红书上限）"
        from ..modules.generate import title_weight

        weight = title_weight(m.title)
        if weight > TITLE_WEIGHT_LIMIT:
            return False, f"标题计重 {weight} > {TITLE_WEIGHT_LIMIT}（小红书上限，先缩短标题）"
        return True, f"图文笔记（{len(m.images)} 张图 / 标题计重 {weight}）"

    async def preflight(self) -> Preflight:
        reachable, detail, _ = await self.health()
        if not reachable:
            return self.offline(detail)
        try:
            status, body = await self._request("GET", "/api/v1/login/status", timeout=self.probe_timeout)
        except Exception as exc:
            return self.login_required(f"登录态探测失败：{type(exc).__name__}: {exc}"[:200])
        data = body.get("data") or {}
        if status == 200 and data.get("is_logged_in"):
            account = str(data.get("username") or "")
            return Preflight(
                state="ready", reachable=True, account=account, transport=self.transport,
                detail=f"MCP 在线，已登录：{account or '未知账号'}",
                hint="",
            )
        return self.login_required(
            "MCP 在线，但当前未登录（或登录已失效）",
            "在「平台账号」页点扫码登录；注意 MCP 的 cookie 认启动目录（apps/xiaohongshu-mcp/）",
        )

    async def publish(self, m: Materials, *, confirmed: bool = False) -> Delivery:
        if not confirmed:
            return self.blocked_delivery("NOT_CONFIRMED", "发布不可逆：需要人工闸门放行（confirmed=true）")
        suitable, reason = self.supports(m)
        if not suitable:
            return Delivery(channel=self.id, status="blocked",
                            error={"code": "MATERIAL_UNSUITABLE", "message": reason})

        # 素材一律经 remote_path()：MCP 跑在 Windows 上时要把本机 Linux 路径换成它读得到的
        # 写法，否则它回一句「视频文件不存在或不可访问」，而且是在起浏览器之前就失败
        # （2026-09-19 实测：真发一条视频笔记就这么失败的，小红书侧零痕迹）。
        if m.video is not None:
            path, body = "/api/v1/publish_video", {
                "title": m.title, "content": m.body,
                "video": self.remote_path(m.video), "tags": m.tags,
            }
        else:
            path, body = "/api/v1/publish", {
                "title": m.title, "content": m.body,
                "images": [self.remote_path(p) for p in m.images],
                "tags": m.tags, "is_original": True,
            }
        try:
            status, data = await self._request("POST", path, timeout=self.publish_timeout, json=body)
        except Exception as exc:
            return Delivery(channel=self.id, status="failed", error={
                "code": "CHANNEL_UNREACHABLE",
                "message": f"{self.base_url} 不可达：{type(exc).__name__}: {exc}"[:300],
            })
        if status >= 400 or not data.get("success", False):
            err = self.error_of(status, data)
            if "登录" in err["message"]:
                err["code"] = "NOT_LOGGED_IN"
            return Delivery(channel=self.id, status="failed", error=err, raw=data)
        payload = data.get("data") or {}
        return Delivery(
            channel=self.id, status="published",
            remote_id=str(payload.get("note_id") or payload.get("noteId") or ""),
            url=str(payload.get("permlink") or payload.get("url") or ""),
            raw=payload,
        )

    def manual_steps(self, m: Materials, out: Path) -> str:
        if m.video is not None:
            return (
                "小红书（视频笔记）手动发布兜底：\n"
                "1. 打开小红书 App → 发布 → 视频；\n"
                f"2. 上传 {out.name}/video.mp4；\n"
                "3. 标题取 title.txt（计重 ≤ 38），正文取 content.txt（已含话题标签）；\n"
                "4. 先存草稿看过效果再发。\n"
            )
        return (
            "小红书（图文笔记）手动发布兜底：\n"
            "1. 打开小红书 App → 发布 → 图文；\n"
            "2. 图片按 p1.png / p2.png … 顺序上传（首图最重要）；\n"
            "3. 标题取 title.txt（计重 ≤ 38），正文取 content.txt（已含话题标签）；\n"
            "4. 先存草稿看过效果再发。\n"
        )
