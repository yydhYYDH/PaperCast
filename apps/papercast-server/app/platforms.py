"""平台渠道与登录态：把各内容平台的「账号 / 登录」收敛成前端能用的一种形状。

设计意图（对应 docs/TODO.md C1 的渠道抽象，R1 只落地最小可用版本）：
- 每个渠道一个 adapter，统一返回 state / account / detail / needs / login 方式；
- **没接通的渠道如实报 unconfigured / blocked，不假装可用**；
- 前端只跟本后端（:8000）对话，不直连 :18060 —— 少一处 CORS，也多一层闸门。

R1 真实可用的只有小红书（xiaohongshu-mcp，扫码登录 + cookies 落盘在 MCP 侧）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from .config import settings


class PlatformError(Exception):
    """渠道操作失败：由 main.py 翻译成 { error: { code, message } }。"""

    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


# --------------------------------------------------------------------------- #
# 渠道定义
# --------------------------------------------------------------------------- #

@dataclass
class Channel:
    id: str
    name: str
    kind: str  # mcp / openapi / cli
    login: str  # qrcode / env / cli / none
    state: str  # ready / login_required / offline / unconfigured / blocked
    account: str = ""
    detail: str = ""
    endpoint: str = ""
    needs: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    loginHint: str = ""

    def dump(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "login": self.login,
            "state": self.state,
            "account": self.account,
            "detail": self.detail,
            "endpoint": self.endpoint,
            "needs": list(self.needs),
            "capabilities": list(self.capabilities),
            "loginHint": self.loginHint,
        }


def _static_channels() -> list[Channel]:
    """不发网络请求的渠道（当前为空：三个渠道都要探测，公众号已按用户要求下线）。

    保留这个函数是为了让「加一个只靠配置判定的渠道」仍然有地方落 —— 返回空列表即无此类渠道。
    """
    return []


# --------------------------------------------------------------------------- #
# B 站（apps/bilibili-publisher，底层 biliup CLI）
# --------------------------------------------------------------------------- #

_BILI_CACHE: dict[str, Any] = {"at": 0.0, "data": None}


def _biliup_path() -> str:
    """biliup 可能装在 var/toolchains/bili-venv（不在 PATH 里），这里只用来做「装了没」的提示。"""
    ws = Path(__file__).resolve().parents[3]  # apps/papercast-server/app/platforms.py → 工作区根
    cand = ws / "var" / "toolchains" / "bili-venv" / "bin" / "biliup"
    return str(cand) if cand.is_file() else (shutil.which("biliup") or "")


async def _bilibili_probe() -> Channel:
    ch = Channel(
        id="bilibili",
        name="B 站",
        kind="cli",
        login="qrcode",  # biliup 的二维码：通道服务把终端那份也落成 qrcode.png，前端直接扫码
        state="offline",
        endpoint=settings.bilibili_publisher_base,
        needs=["横版 16:9 视频", "竖版封面", "分区 / 标签"],
        capabilities=["视频投稿"],
        loginHint="点「扫码登录」，用 B 站 App 扫二维码；底层是 biliup，凭据落在本机通道服务",
    )
    try:
        async with httpx.AsyncClient(timeout=40.0, trust_env=False) as cx:
            r = await cx.get(f"{settings.bilibili_publisher_base}/api/v1/login/status")
    except Exception as e:
        ch.detail = f"bilibili-publisher 不可达（{type(e).__name__}）：先 ./ops/start_all.sh bilibili"
        return ch

    payload = r.json() if r.content else {}
    data = payload.get("data") or {}
    if r.status_code != 200 or not payload.get("success"):
        ch.detail = (payload.get("error") or {}).get("message") or f"状态探测失败：HTTP {r.status_code}"
        return ch

    if data.get("is_logged_in"):
        ch.state = "ready"
        ch.account = data.get("username") or ""
        ch.detail = f"已登录：{ch.account or '未知账号'}"
    elif not data.get("biliup_available", True):
        ch.state = "unconfigured"
        where = _biliup_path()
        ch.detail = "通道服务在跑，但本机没找到 biliup" + (f"（已装：{where}）" if where else "")
        ch.loginHint = (
            "装 biliup：ops/start_all.sh 会带上 var/toolchains/bili-venv/bin/biliup；"
            "或手动 pip install biliup==1.2.4 后重启通道服务"
        )
    else:
        ch.state = "login_required"
        ch.detail = data.get("detail") or "通道服务在线，但 cookies 无效或缺失"
    return ch


async def _bilibili_cached(force: bool) -> Channel:
    now = time.time()
    if not force and _BILI_CACHE["data"] is not None and now - _BILI_CACHE["at"] < _CACHE_TTL:
        return _BILI_CACHE["data"]
    ch = await _bilibili_probe()
    _BILI_CACHE.update(at=now, data=ch)
    return ch


# --------------------------------------------------------------------------- #
# 小红书（xiaohongshu-mcp）
# --------------------------------------------------------------------------- #

_XHS_CACHE: dict[str, Any] = {"at": 0.0, "data": None}
_CACHE_TTL = 5.0  # MCP 每次探测都要开一次无头浏览器，前端轮询别把它打爆

_DUR_RE = re.compile(r"^(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?$")


def _parse_timeout_ms(text: str, fallback_ms: int = 240_000) -> int:
    """把 Go 的 Duration 字符串（"4m0s"）换成毫秒。"""
    m = _DUR_RE.match((text or "").strip())
    if not m:
        return fallback_ms
    minutes = int(m.group(1) or 0)
    seconds = float(m.group(2) or 0)
    total = int((minutes * 60 + seconds) * 1000)
    return total or fallback_ms


async def _xhs_probe() -> Channel:
    ch = Channel(
        id="xhs",
        name="小红书",
        kind="mcp",
        login="qrcode",
        state="offline",
        endpoint=settings.xhs_mcp_base,
        needs=["扫码登录", "6 张卡片图", "标题 ≤ 20 字"],
        capabilities=["图文发布", "话题标签"],
        loginHint="点「扫码登录」，用小红书 App 扫码；扫码成功后 cookies 自动落盘",
    )
    try:
        async with httpx.AsyncClient(timeout=8.0, trust_env=False) as cx:
            h = await cx.get(f"{settings.xhs_mcp_base}/health")
            if h.status_code != 200:
                ch.detail = f"MCP 健康检查返回 {h.status_code}"
                return ch
    except Exception as e:
        ch.detail = f"MCP 不可达（{type(e).__name__}）：先 ./ops/start_all.sh mcp"
        return ch

    ch.detail = "MCP 在线"
    try:
        async with httpx.AsyncClient(timeout=45.0, trust_env=False) as cx:
            r = await cx.get(f"{settings.xhs_mcp_base}/api/v1/login/status")
        data = (r.json() or {}).get("data") or {}
        if r.status_code == 200 and data.get("is_logged_in"):
            ch.state = "ready"
            ch.account = data.get("username") or ""
            ch.detail = f"已登录：{ch.account or '未知账号'}"
        else:
            ch.state = "login_required"
            ch.detail = "MCP 在线，但当前未登录（或登录已失效）"
    except Exception as e:
        ch.state = "login_required"
        ch.detail = f"登录态探测失败（{type(e).__name__}）：{e}"
    return ch


# --------------------------------------------------------------------------- #
# 知乎（apps/zhihu-publisher，HTTP 通道；transport=playwright）
# --------------------------------------------------------------------------- #

_ZHIHU_CACHE: dict[str, Any] = {"at": 0.0, "data": None}
_ZHIHU_TTL = 10.0  # 服务侧已有 20s 状态缓存，这里再缓一层，避免前端 5s 轮询打爆浏览器


def _zhihu_channel() -> Channel:
    return Channel(
        id="zhihu",
        name="知乎",
        kind="playwright",
        login="browser",
        state="offline",
        endpoint=settings.zhihu_publisher_base,
        needs=["桌面窗口人工登录（风控拦纯 HTTP 扫码）", "标题 + 纯文本正文"],
        capabilities=["文章发布", "话题标签"],
        loginHint="点「打开浏览器登录」→ 桌面弹出的窗口里扫码/账号登录（含人机验证）→ 状态自动变已登录；本机无显示时用 ./apps/zhihu-publisher/scripts/login-headed.sh",
    )


async def _zhihu_probe() -> Channel:
    ch = _zhihu_channel()
    try:
        async with httpx.AsyncClient(timeout=8.0, trust_env=False) as cx:
            h = await cx.get(f"{settings.zhihu_publisher_base}/health")
            if h.status_code != 200:
                ch.detail = f"zhihu-publisher 健康检查返回 {h.status_code}"
                return ch
    except Exception as e:
        ch.detail = f"zhihu-publisher 不可达（{type(e).__name__}）：先 ./ops/start_all.sh zhihu"
        return ch

    try:
        async with httpx.AsyncClient(timeout=60.0, trust_env=False) as cx:
            r = await cx.get(f"{settings.zhihu_publisher_base}/api/v1/login/status")
        data = (r.json() or {}).get("data") or {}
        if r.status_code == 200 and data.get("is_logged_in"):
            ch.state = "ready"
            ch.account = data.get("username") or ""
            token = data.get("account_token") or ""
            ch.detail = f"已登录：{ch.account or '未知账号'}" + (f"（{token}）" if token else "") + "；发布走浏览器自动化，闸门放行后才动凭证"
        else:
            ch.state = "login_required"
            ch.detail = "zhihu-publisher 在线，但当前未登录（点右侧按钮起桌面窗口登录）"
    except Exception as e:
        ch.state = "login_required"
        ch.detail = f"登录态探测失败（{type(e).__name__}）：{e}"
    return ch


async def _zhihu_cached(force: bool) -> Channel:
    now = time.time()
    if not force and _ZHIHU_CACHE["data"] is not None and now - _ZHIHU_CACHE["at"] < _ZHIHU_TTL:
        return _ZHIHU_CACHE["data"]
    ch = await _zhihu_probe()
    _ZHIHU_CACHE.update(at=now, data=ch)
    return ch


async def _probe(channel_id: str) -> Channel:
    if channel_id == "xhs":
        return await _xhs_probe()
    if channel_id == "zhihu":
        return await _zhihu_cached(force=True)
    if channel_id == "bilibili":
        return await _bilibili_cached(force=True)
    for ch in _static_channels():
        if ch.id == channel_id:
            return ch
    raise PlatformError(404, "CHANNEL_NOT_FOUND", f"未知渠道：{channel_id}")


async def list_channels(force: bool = False) -> list[dict[str, Any]]:
    """全部渠道状态。默认 5s 内复用缓存，避免前端轮询把 MCP 的浏览器探测打爆。"""
    now = time.time()
    if not force and _XHS_CACHE["data"] is not None and now - _XHS_CACHE["at"] < _CACHE_TTL:
        xhs = _XHS_CACHE["data"]
    else:
        xhs = await _xhs_probe()
        _XHS_CACHE.update(at=now, data=xhs)

    zhihu = await _zhihu_cached(force)
    bilibili = await _bilibili_cached(force)

    channels = [xhs, zhihu, bilibili, *_static_channels()]
    order = {"xhs": 0, "zhihu": 1, "bilibili": 2}
    channels.sort(key=lambda c: order.get(c.id, 99))
    return [c.dump() for c in channels]


async def get_channel(channel_id: str, force: bool = True) -> dict[str, Any]:
    if channel_id == "xhs" and not force:
        return next(c for c in await list_channels() if c["id"] == "xhs")
    return (await _probe(channel_id)).dump()


async def _bili_qrcode() -> dict[str, Any]:
    """取 B 站扫码二维码（biliup 把码落成通道服务 cwd 下的 qrcode.png）。

    取不到可用码时**顺手起一次 biliup login** —— 这样前端一个「扫码登录」动作就能闭环，
    不必让用户先去终端敲命令。biliup 自己会覆盖旧码，重复起是安全的（不像 MCP 会顶掉会话）。
    """
    base = settings.bilibili_publisher_base
    try:
        async with httpx.AsyncClient(timeout=60.0, trust_env=False) as cx:
            r = await cx.get(f"{base}/api/v1/login/qrcode")
            payload = r.json() if r.content else {}
            data = payload.get("data") or {}
            if not data.get("available"):
                started = await cx.post(f"{base}/api/v1/login/start")
                sp = started.json() if started.content else {}
                if started.status_code != 200 or not sp.get("success"):
                    err = sp.get("error") or {}
                    raise PlatformError(
                        started.status_code if started.status_code >= 400 else 502,
                        err.get("code") or "LOGIN_START_FAILED",
                        err.get("message") or f"启动 biliup 登录失败：HTTP {started.status_code}",
                    )
                for _ in range(12):  # biliup 要起浏览器会话再拿码，给它 ~24s
                    await asyncio.sleep(2.0)
                    r2 = await cx.get(f"{base}/api/v1/login/qrcode")
                    p2 = r2.json() if r2.content else {}
                    data = p2.get("data") or {}
                    if data.get("available"):
                        break
    except PlatformError:
        raise
    except Exception as e:
        raise PlatformError(502, "CHANNEL_UNREACHABLE",
                            f"bilibili-publisher 不可达（{type(e).__name__}）：先 ./ops/start_all.sh bilibili")

    if not data.get("available"):
        raise PlatformError(502, "QRCODE_FAILED",
                            data.get("hint") or "biliup 没能给出二维码；可在终端跑 biliup login 看它的输出")
    _BILI_CACHE.update(at=0.0, data=None)
    return {"img": data.get("img") or "", "age_sec": int(data.get("age_sec") or 0)}


async def login_qrcode(channel_id: str) -> dict[str, Any]:
    """取扫码登录二维码（Base64 data URL）。

    小红书：注意 MCP 侧语义 —— GET 一次就新建一个 4 分钟的后台等待会话，扫码成功即写 cookies；
    再取一次会关掉上一个会话，所以**同一时刻只允许一个二维码**，前端不要在轮询里重复取。

    B 站：底层 biliup 是「跑一次 login 出一张码」，所以这里允许顺手起一次（幂等，见 _bili_qrcode）。
    """
    if channel_id == "bilibili":
        bili = await _bili_qrcode()
        ttl_ms = max(0, 240_000 - bili["age_sec"] * 1000)
        return {
            "channelId": channel_id,
            "isLoggedIn": False,
            "img": bili["img"],
            "timeout": "4m0s",
            "expiresAt": int(time.time() * 1000) + ttl_ms,
            "account": "",
        }

    if channel_id != "xhs":
        raise PlatformError(400, "LOGIN_METHOD_UNSUPPORTED", f"{channel_id} 不支持扫码登录")

    try:
        async with httpx.AsyncClient(timeout=90.0, trust_env=False) as cx:
            r = await cx.get(f"{settings.xhs_mcp_base}/api/v1/login/qrcode")
    except Exception as e:
        raise PlatformError(502, "MCP_UNREACHABLE", f"小红书 MCP 不可达：{type(e).__name__}: {e}")

    payload = r.json() if r.content else {}
    if r.status_code != 200 or not payload.get("success"):
        msg = (payload.get("error") if isinstance(payload, dict) else None) or f"HTTP {r.status_code}"
        raise PlatformError(502, "QRCODE_FAILED", f"获取二维码失败：{msg}")

    data = payload.get("data") or {}
    timeout_text = data.get("timeout") or "4m0s"
    ttl_ms = _parse_timeout_ms(timeout_text) if not data.get("is_logged_in") else 0
    account = ""
    if data.get("is_logged_in"):
        try:
            ch = await _xhs_probe()
            account = ch.account
        except Exception:
            account = ""

    return {
        "channelId": channel_id,
        "isLoggedIn": bool(data.get("is_logged_in")),
        "img": data.get("img") or "",
        "timeout": timeout_text,
        "expiresAt": int(time.time() * 1000) + ttl_ms,
        "account": account,
    }


async def login_start(channel_id: str) -> dict[str, Any]:
    """起一次「非页内二维码」的登录流程。

    - 知乎：桌面浏览器窗口人工登录（风控会拦纯 HTTP 扫码，必须人在真实浏览器里完成）；
    - B 站：起 biliup login（二维码落在通道服务那边，前端再用 login/qrcode 取图）。

    调用后前端轮询 `GET /api/platforms/{id}`：检测到登录态即登录成功。
    """
    if channel_id == "bilibili":
        base = settings.bilibili_publisher_base
        try:
            async with httpx.AsyncClient(timeout=30.0, trust_env=False) as cx:
                r = await cx.post(f"{base}/api/v1/login/start")
        except Exception as e:
            raise PlatformError(502, "CHANNEL_UNREACHABLE",
                                f"bilibili-publisher 不可达（{type(e).__name__}）：先 ./ops/start_all.sh bilibili")
        payload = r.json() if r.content else {}
        if r.status_code != 200 or not payload.get("success"):
            err = payload.get("error") or {}
            raise PlatformError(
                r.status_code if r.status_code >= 400 else 502,
                err.get("code") or "LOGIN_START_FAILED",
                err.get("message") or f"启动 biliup 登录失败：HTTP {r.status_code}",
            )
        _BILI_CACHE.update(at=0.0, data=None)
        data = payload.get("data") or {}
        return {
            "channelId": channel_id,
            "method": "qrcode",
            "started": bool(data.get("started")),
            "pid": data.get("pid"),
            "hint": data.get("hint") or "biliup 已开始登录：点「扫码登录」取二维码",
        }

    if channel_id != "zhihu":
        raise PlatformError(400, "LOGIN_METHOD_UNSUPPORTED", f"{channel_id} 不支持启动登录流程")
    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as cx:
            r = await cx.post(f"{settings.zhihu_publisher_base}/api/v1/login/start")
    except Exception as e:
        raise PlatformError(502, "CHANNEL_UNREACHABLE", f"zhihu-publisher 不可达：{type(e).__name__}: {e}")

    payload = r.json() if r.content else {}
    if r.status_code != 200 or not payload.get("success"):
        err = payload.get("error") or {}
        raise PlatformError(
            r.status_code if r.status_code >= 400 else 502,
            err.get("code") or "LOGIN_START_FAILED",
            err.get("message") or f"启动登录窗口失败：HTTP {r.status_code}",
        )
    _ZHIHU_CACHE.update(at=0.0, data=None)
    data = payload.get("data") or {}
    return {
        "channelId": channel_id,
        "method": "browser",
        "started": bool(data.get("started")),
        "pid": data.get("pid"),
        "hint": data.get("hint") or "请在弹出的浏览器窗口里完成登录",
    }


async def publish(channel_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """真实投递（目前只接知乎）。**必须 confirmed=true**，否则服务侧直接拒绝。

    闸门语义：调用方（前端/发布阶段）只有在人工确认后才带上 confirmed；
    未确认时请改用 export_draft() 只落盘待发内容。
    """
    if channel_id != "zhihu":
        raise PlatformError(400, "PUBLISH_UNSUPPORTED", f"{channel_id} 的真实投递尚未接通，先出 export/")
    if not payload.get("confirmed"):
        raise PlatformError(409, "NOT_CONFIRMED", "发布不可逆：需要人工闸门确认（confirmed=true）后才执行")
    try:
        async with httpx.AsyncClient(timeout=300.0, trust_env=False) as cx:
            r = await cx.post(f"{settings.zhihu_publisher_base}/api/v1/publish", json=payload)
    except Exception as e:
        raise PlatformError(502, "CHANNEL_UNREACHABLE", f"zhihu-publisher 不可达：{type(e).__name__}: {e}")

    body = r.json() if r.content else {}
    if r.status_code != 200 or not body.get("success"):
        err = body.get("error") or {}
        raise PlatformError(
            r.status_code if r.status_code >= 400 else 502,
            err.get("code") or "PUBLISH_FAILED",
            err.get("message") or f"发布失败：HTTP {r.status_code}",
        )
    _ZHIHU_CACHE.update(at=0.0, data=None)
    return body.get("data") or {}


async def export_draft(channel_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """只落盘待发布内容（无副作用）。闸门未放行时走这条。"""
    if channel_id != "zhihu":
        raise PlatformError(400, "EXPORT_UNSUPPORTED", f"{channel_id} 暂不支持导出待发内容")
    try:
        async with httpx.AsyncClient(timeout=60.0, trust_env=False) as cx:
            r = await cx.post(f"{settings.zhihu_publisher_base}/api/v1/export", json=payload)
    except Exception as e:
        raise PlatformError(502, "CHANNEL_UNREACHABLE", f"zhihu-publisher 不可达：{type(e).__name__}: {e}")
    body = r.json() if r.content else {}
    if r.status_code != 200 or not body.get("success"):
        err = body.get("error") or {}
        raise PlatformError(r.status_code if r.status_code >= 400 else 502,
                            err.get("code") or "EXPORT_FAILED",
                            err.get("message") or f"导出失败：HTTP {r.status_code}")
    return body.get("data") or {}


# --------------------------------------------------------------------------- #
# 退出登录：把「本机凭证」真的删掉
#
# 三个渠道的凭证存放位置各不相同（2026-09-19 核对）：
#   - 知乎   var/secrets/zhihu/cookies.json          → 由 zhihu-publisher 的 DELETE 端点负责
#   - B 站   var/home/.bilibili/cookies.json         → biliup 的 HOME 位置，通道服务 + 这里各清一遍
#            var/artifacts/bilibili/cookies.json     （旧路径，兼容读，也要清）
#            bilibili-publisher 自己的 COOKIES_PATH  → 由它的 DELETE 端点负责
#   - 小红书 apps/xiaohongshu-mcp/cookies.json       → **MCP 没有清 cookie 的接口**（它的 /logout
#            是它自己的 HTTP 鉴权登出，与小红书账号无关），所以这里直接删文件；
#            路径优先级：COOKIES_PATH 环境变量 > 工作区里的组件目录。
# --------------------------------------------------------------------------- #


def _workspace() -> Path:
    return Path(__file__).resolve().parents[3]


def _xhs_cookie_path() -> Path:
    import os

    env = os.environ.get("COOKIES_PATH", "").strip()
    if env:
        return Path(env)
    return _workspace() / "apps" / "xiaohongshu-mcp" / "cookies.json"


def _xhs_profile_dir() -> Path:
    """小红书 MCP 的浏览器 profile —— **真正的登录态在这里**，不在 cookies.json 里。

    依据（2026-09-19 实测）：MCP 的 /api/v1/login/status 是真开一个浏览器访问
    xiaohongshu.com/explore、看 DOM 里有没有用户菜单，所以只删 cookies.json 它照样报「已登录」；
    而 MCP 没有清会话的 HTTP 接口（它的 POST /logout 只是它自己的 HTTP 鉴权登出）。
    因此这里连 profile 一起删，并把 MCP 重启一次 —— 重启顺带清掉进程内的 300s 状态缓存。
    """
    import os

    cache_root = os.environ.get("XDG_CACHE_HOME", "").strip()
    base = Path(cache_root) if cache_root else (_workspace() / "var" / "cache")
    return base / "xiaohongshu-mcp" / "browser"


def _restart_service(name: str) -> list[str]:
    """按 ops 脚本重启一个服务，返回输出行（失败不抛，由调用方看后续探测结果）。"""
    ws = _workspace()
    out: list[str] = []
    for script in ("stop_all.sh", "start_all.sh"):
        path = ws / "ops" / script
        if not path.is_file():
            out.append("缺少 " + str(path))
            continue
        try:
            proc = subprocess.run([str(path), name], capture_output=True, text=True, timeout=90, cwd=str(ws))
        except subprocess.TimeoutExpired:
            out.append(script + " " + name + " 超时")
            continue
        text = (proc.stdout or proc.stderr or "").strip()
        if text:
            out.append(text)
    return out


def _bili_cookie_paths() -> list[Path]:
    ws = _workspace()
    return [
        ws / "var" / "home" / ".bilibili" / "cookies.json",
        ws / "var" / "artifacts" / "bilibili" / "cookies.json",
    ]


def _unlink_all(paths: list[Path]) -> tuple[list[str], list[str]]:
    """删文件；返回 (删掉的, 本来就不在的)。删失败会抛 PlatformError，不静默。"""
    removed: list[str] = []
    missing: list[str] = []
    for path in paths:
        try:
            if path.is_file():
                path.unlink()
                removed.append(str(path))
            else:
                missing.append(str(path))
        except OSError as e:
            raise PlatformError(500, "LOGOUT_FAILED", f"删除 {path} 失败：{e}") from e
    return removed, missing


async def logout(channel_id: str) -> dict[str, Any]:
    """退出登录：删掉本机 cookies（不可逆，前端必须先经用户确认）。

    成功后立刻失效缓存 —— 否则前端下次探测还会看到「已登录」，用户会以为没生效。
    """
    if channel_id == "zhihu":
        try:
            async with httpx.AsyncClient(timeout=30.0, trust_env=False) as cx:
                r = await cx.delete(f"{settings.zhihu_publisher_base}/api/v1/login/cookies")
        except Exception as e:
            raise PlatformError(502, "CHANNEL_UNREACHABLE", f"zhihu-publisher 不可达：{type(e).__name__}: {e}")
        if r.status_code != 200:
            raise PlatformError(502, "LOGOUT_FAILED", f"退出登录失败：HTTP {r.status_code}")
        _ZHIHU_CACHE.update(at=0.0, data=None)
        return {"channelId": channel_id, "message": "已清除知乎登录态，下次发布前需在桌面窗口重新登录"}

    if channel_id == "bilibili":
        try:
            async with httpx.AsyncClient(timeout=30.0, trust_env=False) as cx:
                r = await cx.delete(f"{settings.bilibili_publisher_base}/api/v1/login/cookies")
        except Exception as e:
            raise PlatformError(502, "CHANNEL_UNREACHABLE",
                                f"bilibili-publisher 不可达：{type(e).__name__}: {e}")
        payload = r.json() if r.content else {}
        if r.status_code != 200 or not payload.get("success"):
            raise PlatformError(502, "LOGOUT_FAILED", f"退出登录失败：HTTP {r.status_code}")
        # 通道服务只清它自己那份；biliup 的 HOME 与旧路径也一起清，否则 B 站还会显示「已登录」
        removed, _missing = _unlink_all(_bili_cookie_paths())
        _BILI_CACHE.update(at=0.0, data=None)
        detail = "、".join([Path(p).as_posix() for p in removed]) or "通道服务侧凭证"
        return {"channelId": channel_id,
                "message": f"已清除 B 站登录态（{detail}）；下次投稿前需重新扫码登录"}

    if channel_id != "xhs":
        raise PlatformError(400, "LOGOUT_UNSUPPORTED", f"{channel_id} 不支持从本界面退出登录")
    cookie_path = _xhs_cookie_path()
    profile_dir = _xhs_profile_dir()
    removed, _missing = _unlink_all([cookie_path])
    profile_removed = profile_dir.is_dir()
    if profile_removed:
        shutil.rmtree(profile_dir, ignore_errors=False)
    if not removed and not profile_removed:
        _XHS_CACHE.update(at=0.0, data=None)
        return {"channelId": channel_id,
                "message": f"没有找到小红书凭证（{cookie_path}）与浏览器 profile（{profile_dir}）：当前就是未登录状态"}

    restart_log = _restart_service("mcp")
    _XHS_CACHE.update(at=0.0, data=None)

    # 如实回报退出的「结果」：重启后再探一次，不假设成功
    state, account = "unknown", ""
    try:
        ch = await _xhs_probe()
        state, account = ch.state, ch.account
    except Exception as e:
        state = f"探测失败（{type(e).__name__}）"

    what = []
    if removed:
        what.append("cookies.json")
    if profile_removed:
        what.append("浏览器 profile")
    message = "已清除小红书登录态（" + " + ".join(what) + "，已重启 MCP）；当前状态：" + state
    if state == "ready":
        message += "。仍显示已登录时，最彻底的做法是在手机端小红书「设置 → 账号与安全 → 登录设备管理」里踢掉本机"
    return {"channelId": channel_id, "message": message, "state": state, "account": account,
            "restartOutput": restart_log}
