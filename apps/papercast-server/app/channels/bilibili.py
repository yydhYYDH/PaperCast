"""B 站渠道：apps/bilibili-publisher（本机 :18080，底层用 biliup CLI）。

biliup 与本机登录态的现状（2026-09-19 实测）：biliup 装在 `var/toolchains/bili-venv`（不在 PATH 里，
通道服务自己回退查找），凭证由 biliup 自管在 `var/home/.bilibili/cookies.json`（HOME 重定向），
账号 YYDH54 → 渠道状态 ready；**但真实投稿还没跑过**，第一次投递仍要人工盯。

B 站是**视频投稿**：素材必须有 video 阶段的成片。本轮 video 阶段多为 skipped，
所以这个渠道最常见的状态是「素材不适用 → 只出 export 素材包」，而不是假装能发。
凭证是 cookies（SESSDATA 等），放 var/secrets/bilibili/ 或 biliup 自管的 var/home/.bilibili/
（投递中转才写 var/artifacts/bilibili/，见 docs/conventions.md §4）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Delivery, HttpChannel, Materials, Preflight

TITLE_LIMIT = 80          # B 站稿件标题上限（字符）
DEFAULT_TID = 188         # 分区：科技 → 计算机技术（投稿页当前口径，可在通道服务里覆盖）
DESC_LIMIT = 2000


class BilibiliChannel(HttpChannel):
    id = "bilibili"
    name = "B站"
    capabilities = frozenset({"text", "video", "images"})
    login_kind = "cookies"
    transport = "biliup-http"
    why = "视频投稿（横版 16:9）：成片 + 封面 + 简介交给本机通道服务调 biliup 投递"
    restart_hint = "./ops/start_all.sh bilibili"
    publish_timeout = 2400.0   # 视频上传以分钟计：biliup 分片上传，超时给足

    @property
    def base_url(self) -> str:
        return self.settings.bilibili_publisher_base

    def supports(self, m: Materials) -> tuple[bool, str]:
        if m.video is None:
            return False, "缺视频：B 站是视频投稿，需要 video 阶段产出成片（当前只出素材包）"
        miss = self.missing(m, video=True)
        if miss:
            return False, f"缺{miss}"
        if len(m.title) > TITLE_LIMIT:
            return False, f"标题 {len(m.title)} 字 > {TITLE_LIMIT} 字（B 站上限）"
        note = f"视频投稿（{m.video.name}"
        note += f" / 封面 {'有' if m.cover else '无'}"
        note += f" / {len(m.tags)} 个标签）"
        return True, note

    def compose_body(self, m: Materials) -> str:
        desc = m.body.strip()
        if m.source:
            desc += f"\n\n论文来源：{m.source}"
        if m.tags:
            desc += "\n\n标签：" + "、".join(m.tags)
        return desc[:DESC_LIMIT] + "\n"

    async def preflight(self) -> Preflight:
        reachable, detail, _ = await self.health()
        if not reachable:
            return self.offline(detail)
        try:
            status, body = await self._request("GET", "/api/v1/login/status", timeout=self.probe_timeout)
        except Exception as exc:
            return self.login_required(f"登录态探测失败：{type(exc).__name__}: {exc}"[:200])
        data = body.get("data") or {}
        if not data.get("biliup_available", True):
            return Preflight(
                state="unconfigured", reachable=True, transport=self.transport,
                detail="通道在线，但本机没装 biliup",
                hint="本工作区把 biliup 装在 var/toolchains/bili-venv（不在 PATH 里，通道服务会自动找）"
                     "；装好后跑 ops/biliup_login_pty.py 或 POST /api/v1/login/start 扫码",
            )
        if status == 200 and data.get("is_logged_in"):
            account = str(data.get("username") or "")
            return Preflight(
                state="ready", reachable=True, account=account, transport=self.transport,
                detail=f"通道在线，已登录：{account or '未知账号'}（biliup={data.get('biliup') or '内置'}）",
            )
        return self.login_required(
            "通道在线，但没有可用的 B 站登录态（cookies）",
            "先跑 ops/biliup_login_pty.py（或 POST /api/v1/login/start）扫码登录，"
            "或把含 SESSDATA 的 cookies.json 放到 var/secrets/bilibili/",
        )

    async def publish(self, m: Materials, *, confirmed: bool = False) -> Delivery:
        if not confirmed:
            return self.blocked_delivery("NOT_CONFIRMED", "发布不可逆：需要人工闸门放行（confirmed=true）")
        suitable, reason = self.supports(m)
        if not suitable:
            return Delivery(channel=self.id, status="blocked",
                            error={"code": "MATERIAL_UNSUITABLE", "message": reason})
        payload = {
            "title": m.title,
            "desc": self.compose_body(m),
            "tags": m.tags,
            "video": str(m.video),
            "cover": str(m.cover) if m.cover else "",
            "tid": int(m.extra.get("tid") or DEFAULT_TID),
            "run_id": m.run_id,
            "confirmed": True,
        }
        try:
            status, body = await self._request("POST", "/api/v1/publish", timeout=self.publish_timeout, json=payload)
        except Exception as exc:
            return Delivery(channel=self.id, status="failed", error={
                "code": "CHANNEL_UNREACHABLE",
                "message": f"{self.base_url} 不可达：{type(exc).__name__}: {exc}"[:300],
            })
        if status >= 400 or not body.get("success"):
            return Delivery(channel=self.id, status="failed", error=self.error_of(status, body), raw=body)
        data = body.get("data") or {}
        return Delivery(
            channel=self.id, status="published",
            url=str(data.get("url") or ""),
            remote_id=str(data.get("bvid") or ""),
            raw=data,
        )

    async def remote_export(self, m: Materials, out: Path) -> dict[str, Any] | None:
        payload = {
            "title": m.title, "desc": self.compose_body(m), "tags": m.tags,
            "video": str(m.video) if m.video else "",
            "cover": str(m.cover) if m.cover else "", "run_id": m.run_id,
        }
        try:
            status, body = await self._request("POST", "/api/v1/export", timeout=60.0, json=payload)
        except Exception as exc:
            return {"ok": False, "error": f"通道不可达：{type(exc).__name__}: {exc}"[:200]}
        if status >= 400 or not body.get("success"):
            return {"ok": False, "error": self.error_of(status, body)}
        return {"ok": True, **(body.get("data") or {})}

    def manual_steps(self, m: Materials, out: Path) -> str:
        video = "video.mp4" if m.video is not None else "（本轮没有成片：先在 video 阶段产出，或手动放一个 mp4 进来）"
        return (
            "B 站（视频投稿）手动兜底：\n"
            "1. 打开 https://member.bilibili.com/platform/upload/video/frame；\n"
            f"2. 上传 {out.name}/{video}（横版 16:9）；\n"
            f"3. 标题取 title.txt（≤ {TITLE_LIMIT} 字），简介取 content.txt（≤ {DESC_LIMIT} 字）；\n"
            f"4. 封面用 cover.png（没有就用视频首帧）；分区建议：科技 → 计算机技术（tid={DEFAULT_TID}，以投稿页当前为准）；\n"
            "5. 标签用 tags.txt；先存草稿确认无误再投。\n"
        )
