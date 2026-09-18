"""知乎渠道：apps/zhihu-publisher（本机 :18070，transport=playwright）。

为什么不让 backend 自己开浏览器：playwright 依赖重，且登录必须由人在**真实桌面窗口**完成
（知乎风控会拦纯 HTTP 扫码）。所以知乎也做成「独立进程 + HTTP」，与小红书、B 站同形。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Delivery, HttpChannel, Materials, Preflight


class ZhihuChannel(HttpChannel):
    id = "zhihu"
    name = "知乎"
    capabilities = frozenset({"text", "images"})
    login_kind = "browser"
    transport = "playwright-http"
    why = "长文（纯文本 + 配图）：独立进程开浏览器投递；登录需在桌面窗口人工完成"
    restart_hint = "./ops/start_all.sh zhihu"

    @property
    def base_url(self) -> str:
        return self.settings.zhihu_publisher_base

    def supports(self, m: Materials) -> tuple[bool, str]:
        miss = self.missing(m)
        if miss:
            return False, f"缺{miss}"
        note = f"长文（{len(m.body)} 字"
        note += f" + {len(m.images)} 张配图）" if m.images else "，无配图）"
        if m.video is not None:
            note += "；视频通道未接，只投文字与配图"
        return True, note

    def compose_body(self, m: Materials) -> str:
        # 知乎正文里堆 # 话题不合适，改成一行「本文标签」；来源单独一行
        body = m.body.strip()
        if m.source:
            body += f"\n\n参考资料：{m.source}"
        if m.tags:
            body += "\n\n本文标签：" + "、".join(m.tags)
        return body + "\n"

    async def preflight(self) -> Preflight:
        reachable, detail, _ = await self.health()
        if not reachable:
            return self.offline(detail)
        try:
            status, body = await self._request("GET", "/api/v1/login/status", timeout=90.0)
        except Exception as exc:
            return self.login_required(f"登录态探测失败：{type(exc).__name__}: {exc}"[:200])
        data = body.get("data") or {}
        if status == 200 and data.get("is_logged_in"):
            account = str(data.get("username") or "")
            token = str(data.get("account_token") or "")
            return Preflight(
                state="ready", reachable=True, account=account, transport=self.transport,
                detail=f"通道在线，已登录：{account or '未知账号'}" + (f"（{token}）" if token else ""),
            )
        return self.login_required(
            "通道在线，但当前未登录",
            "在「平台账号」页点「打开浏览器登录」，在弹出的桌面窗口完成登录（含人机验证）；"
            "无显示环境时执行 ./apps/zhihu-publisher/scripts/login-headed.sh",
        )

    async def remote_export(self, m: Materials, out: Path) -> dict[str, Any] | None:
        """知乎通道自带 export（会额外落一份 var/artifacts/zhihu/export/<runId>/）。"""
        payload = {
            "title": m.title, "content": m.body, "tags": m.tags,
            "images": [str(p) for p in m.images], "run_id": m.run_id,
        }
        try:
            status, body = await self._request("POST", "/api/v1/export", timeout=60.0, json=payload)
        except Exception as exc:
            return {"ok": False, "error": f"通道不可达：{type(exc).__name__}: {exc}"[:200]}
        if status >= 400 or not body.get("success"):
            return {"ok": False, "error": self.error_of(status, body)}
        data = body.get("data") or {}
        return {"ok": True, "dir": data.get("dir") or "", "files": data.get("files") or []}

    async def publish(self, m: Materials, *, confirmed: bool = False) -> Delivery:
        if not confirmed:
            return self.blocked_delivery("NOT_CONFIRMED", "发布不可逆：需要人工闸门放行（confirmed=true）")
        suitable, reason = self.supports(m)
        if not suitable:
            return Delivery(channel=self.id, status="blocked",
                            error={"code": "MATERIAL_UNSUITABLE", "message": reason})
        payload = {
            "title": m.title,
            "content": self.compose_body(m),
            "tags": m.tags,
            "images": [str(p) for p in m.images],
            "run_id": m.run_id,
            "confirmed": True,
            "confirm_account": getattr(self.settings, "publish_confirm_account", "") or "",
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
            account=str(data.get("account") or ""),
            raw=data,
        )

    def manual_steps(self, m: Materials, out: Path) -> str:
        return (
            "知乎（文章）手动发布兜底：\n"
            "1. 打开 https://zhuanlan.zhihu.com/write；\n"
            f"2. 标题取 {out.name}/title.txt，正文取 {out.name}/content.txt（纯文本更稳，避免公式）；\n"
            "3. 配图按 p1.png / p2.png … 顺序插入；\n"
            "4. 标签在「设置 → 话题」里选（tags.txt 里是关键词）。\n"
        )
