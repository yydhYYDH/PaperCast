"""知乎发布通道服务（HTTP）——给 PaperCast 后端/前端用的稳定接口。

设计动机（对齐 apps/xiaohongshu-mcp 的定位）：
- 浏览器自动化依赖重（playwright），不进 backend venv；backend 只按 HTTP 调本服务；
- 复用只读上游 reference/upstream/zhihu-mcp 的 ZhihuService，不改上游代码；
- 登录走「有头浏览器人工登录」（知乎风控会拦纯 HTTP 扫码），登录态 cookies 落 var/；
- **发布是不可逆动作**：本服务的 /publish 必须带 confirmed=true 才执行；
  不带时可走 /export 只产出待发布内容（对应「闸门未放行只出 export/」的约定）。

接口契约（前端/后端都只看这一份）：
  GET    /health                      -> {"status":"ok"}
  GET    /api/v1/login/status         -> {"success", "data":{is_logged_in, username, cookies_path}}
  POST   /api/v1/login/start          -> {"success", "data":{started, pid, hint}}   # 需要桌面窗口
  DELETE /api/v1/login/cookies        -> {"success", "data":{deleted}}              # 清登录态
  POST   /api/v1/export               -> {"success", "data":{dir, files[]}}          # 只落盘，不发布
  POST   /api/v1/publish              -> {"success", "data":{url, title, publishedAt}}  # 必须 confirmed=true
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

WS = Path(os.environ.get("PAPERCAST_WS") or Path(__file__).resolve().parents[3])
REPO = Path(os.environ.get("ZHIHU_MCP_REPO") or WS / "reference" / "upstream" / "zhihu-mcp")
def _default_cookies() -> Path:
    """cookies 是凭证 → 默认 var/secrets/（规范见 docs/conventions.md §5）；
    早期放在 var/artifacts/ 的那份仍兼容读，避免迁移当天掉登录态。"""
    secrets = WS / "var" / "secrets" / "zhihu" / "cookies.json"
    legacy = WS / "var" / "artifacts" / "zhihu" / "cookies.json"
    if secrets.is_file() or not legacy.is_file():
        return secrets
    return legacy


COOKIES_PATH = Path(os.environ.get("COOKIES_PATH") or _default_cookies())
LOGIN_SCRIPT = Path(os.environ.get("ZHIHU_LOGIN_SCRIPT") or WS / "apps" / "zhihu-publisher" / "scripts" / "login_wait.py")
LOGIN_PYTHON = Path(os.environ.get("ZHIHU_PYTHON") or WS / "var" / "toolchains" / "zhihu-mcp-venv" / "bin" / "python")
EXPORT_ROOT = Path(os.environ.get("ZHIHU_EXPORT_ROOT") or WS / "var" / "artifacts" / "zhihu" / "export")
LOGIN_TIMEOUT = int(os.environ.get("ZHIHU_LOGIN_TIMEOUT", "900"))

os.environ.setdefault("COOKIES_PATH", str(COOKIES_PATH))
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / ".cache" / "ms-playwright"))

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

app = FastAPI(title="zhihu-publisher", version="0.1.0")

# 上游 ZhihuService 用的是 Playwright **同步** API，且每次探测都要开一次浏览器：
# 必须丢到线程里执行（不能在事件循环里直接跑），并用锁串行化，避免并发开多个浏览器。
_BROWSER_LOCK = asyncio.Lock()

# 上游 check_login_status 只返回「已登录用户」这类占位名，真实账号名要打 /api/v4/me。
# 探测一次要开一次浏览器，所以状态缓存 20s、账号名缓存 10min，避免前端轮询把浏览器打爆。
_STATE_TTL = float(os.environ.get("ZHIHU_STATE_TTL", "20"))
_ACCOUNT_TTL = float(os.environ.get("ZHIHU_ACCOUNT_TTL", "600"))
_STATE_CACHE: dict[str, Any] = {"at": 0.0, "data": None}
_ACCOUNT_CACHE: dict[str, Any] = {"at": 0.0, "data": None}


# --------------------------------------------------------------------------- #
# 错误形状：与后端 { error: { code, message } } 一致
# --------------------------------------------------------------------------- #

class ChannelError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@app.exception_handler(ChannelError)
async def _channel_error(_request, exc: ChannelError):
    return JSONResponse(
        status_code=exc.status,
        content={"success": False, "error": {"code": exc.code, "message": exc.message}},
    )


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #

def _service():
    """延迟导入上游 ZhihuService（导入时会检查依赖，放函数里便于报错清晰）。"""
    try:
        from zhihu.service import ZhihuService  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover
        raise ChannelError(503, "UPSTREAM_UNAVAILABLE", f"zhihu-mcp 依赖不可用：{exc}") from exc
    return ZhihuService()


def _cookie_names() -> list[str]:
    if not COOKIES_PATH.is_file():
        return []
    try:
        data = json.loads(COOKIES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    return sorted({c.get("name", "") for c in data if isinstance(c, dict)})


def _login_state() -> dict[str, Any]:
    """登录态：以 cookies 里有没有 z_c0 为第一判据，再让浏览器确认一次。"""
    names = _cookie_names()
    cookies_ok = "z_c0" in names
    username = ""
    if cookies_ok:
        try:
            info = _service().check_login_status(headless=True)
            cookies_ok = bool(info.get("logged_in"))
            username = str(info.get("username") or "")
        except Exception as exc:
            raise ChannelError(502, "PROBE_FAILED", f"登录态探测失败：{exc}") from exc
        if cookies_ok:
            acct = _account()
            username = acct["name"] or acct["url_token"] or username
            account_token = acct["url_token"]
        else:
            account_token = ""
    else:
        account_token = ""
    return {
        "is_logged_in": cookies_ok,
        "username": username,
        "account_token": account_token,
        "cookies_path": str(COOKIES_PATH),
        "cookie_count": len(_cookie_names()),
    }


def _account() -> dict[str, str]:
    """取真实账号（昵称 + url_token）：打 /api/v4/me，结果缓存 10 分钟。"""
    now = time.time()
    if _ACCOUNT_CACHE["data"] and now - _ACCOUNT_CACHE["at"] < _ACCOUNT_TTL:
        return _ACCOUNT_CACHE["data"]
    info = {"name": "", "url_token": ""}
    try:
        from browser.manager import create_browser  # type: ignore[import-not-found]

        with create_browser(headless=True) as (_br, _ctx, page):
            page.goto("https://www.zhihu.com/api/v4/me", wait_until="domcontentloaded")
            raw = page.inner_text("body")
        data = json.loads(raw)
        info = {"name": str(data.get("name") or ""), "url_token": str(data.get("url_token") or "")}
    except Exception:
        pass
    if info["name"] or info["url_token"]:
        _ACCOUNT_CACHE.update(at=now, data=info)
    return info


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# 健康与登录
# --------------------------------------------------------------------------- #

@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "zhihu-publisher",
        "repo": str(REPO),
        "cookies": {"path": str(COOKIES_PATH), "exists": COOKIES_PATH.is_file()},
    }


@app.get("/api/v1/login/status")
async def login_status(force: bool = False) -> dict[str, Any]:
    now = time.time()
    if not force and _STATE_CACHE["data"] and now - _STATE_CACHE["at"] < _STATE_TTL:
        return {"success": True, "data": {**_STATE_CACHE["data"], "cached": True}}
    async with _BROWSER_LOCK:
        data = await asyncio.to_thread(_login_state)
    _STATE_CACHE.update(at=now, data=data)
    return {"success": True, "data": {**data, "cached": False}}


@app.get("/api/v1/stats")
async def stats(url: str) -> dict[str, Any]:
    """读一篇已发布内容的运营数据（赞同数 / 评论数）。

    走的是**已登录的浏览器**去抓正文页，不碰知乎开放平台（那边要 APP_SECRET）。
    浏览量知乎不对外开放（只在创作者中心可见），所以这里只回赞同数与评论数 —— 拿不到就不写。
    """
    if not url.startswith("http"):
        raise ChannelError(400, "BAD_URL", "需要完整的文章 URL")
    async with _BROWSER_LOCK:
        try:
            detail = await asyncio.to_thread(_service().get_feed_detail, url, False, 1, True)
        except Exception as exc:
            raise ChannelError(502, "STATS_FAILED", f"抓取运营数据失败：{exc}") from exc
    if not isinstance(detail, dict) or not detail:
        raise ChannelError(502, "STATS_EMPTY", "没抓到正文数据（可能未登录或页面结构变了）")
    return {"success": True, "data": {
        "url": detail.get("url") or url,
        "title": detail.get("title") or "",
        "author": detail.get("author") or "",
        "votes": detail.get("votes") or "0",
        "comments": detail.get("comment_count") or "0",
        "fetchedAt": _now(),
        "transport": "playwright",
    }}


@app.post("/api/v1/login/start")
async def login_start() -> dict[str, Any]:
    """起一个有头浏览器等你人工登录（知乎风控会拦纯 HTTP 扫码）。

    返回后前端应轮询 /api/v1/login/status；cookies 在检测到 z_c0 时自动落盘。
    """
    if "DISPLAY" not in os.environ and "WAYLAND_DISPLAY" not in os.environ:
        raise ChannelError(
            409,
            "NO_DISPLAY",
            "本机没有可见显示（DISPLAY/WAYLAND_DISPLAY 均未设置），无法弹出登录窗口；"
            "请在桌面终端执行 ./apps/zhihu-publisher/scripts/login-headed.sh",
        )
    if not LOGIN_SCRIPT.is_file() or not LOGIN_PYTHON.is_file():
        raise ChannelError(503, "LOGIN_HELPER_MISSING", f"缺少登录脚本或解释器：{LOGIN_SCRIPT} / {LOGIN_PYTHON}")

    env = {**os.environ, "COOKIES_PATH": str(COOKIES_PATH), "LOGIN_TIMEOUT": str(LOGIN_TIMEOUT)}
    proc = subprocess.Popen(  # noqa: S603
        [str(LOGIN_PYTHON), str(LOGIN_SCRIPT)],
        cwd=str(REPO), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    return {
        "success": True,
        "data": {
            "started": True,
            "pid": proc.pid,
            "hint": "桌面上已弹出浏览器窗口，请扫码或账号密码登录（含人机验证）；登录成功后本接口状态会变为已登录",
        },
    }


@app.delete("/api/v1/login/cookies")
async def login_clear() -> dict[str, Any]:
    existed = COOKIES_PATH.is_file()
    if existed:
        COOKIES_PATH.unlink()
    return {"success": True, "data": {"deleted": existed, "cookies_path": str(COOKIES_PATH)}}


# --------------------------------------------------------------------------- #
# 发布：先 export（无副作用），再 publish（必须显式确认）
# --------------------------------------------------------------------------- #

class DraftBody(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    images: list[str] = []
    tags: list[str] = []
    run_id: Optional[str] = None


class PublishBody(DraftBody):
    confirmed: bool = False
    confirm_account: str = ""


def _export(body: DraftBody) -> dict[str, Any]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = EXPORT_ROOT / (body.run_id or stamp)
    out.mkdir(parents=True, exist_ok=True)
    (out / "zhihu_article.md").write_text(
        f"# {body.title}\n\n{body.content}\n", encoding="utf-8"
    )
    (out / "zhihu_publish_request.json").write_text(
        json.dumps(
            {
                "channel": "zhihu",
                "transport": "playwright",
                "title": body.title,
                "content": body.content,
                "images": body.images,
                "tags": body.tags,
                "preparedAt": _now(),
                "note": "本文件是待发布内容；真实发布需 POST /api/v1/publish 且 confirmed=true",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"dir": str(out), "files": sorted(p.name for p in out.iterdir())}


@app.post("/api/v1/export")
async def export_draft(body: DraftBody) -> dict[str, Any]:
    return {"success": True, "data": _export(body)}


@app.post("/api/v1/publish")
async def publish(body: PublishBody) -> dict[str, Any]:
    if not body.confirmed:
        raise ChannelError(409, "NOT_CONFIRMED", "发布是不可逆动作：必须显式传 confirmed=true（人工闸门放行后）")

    async with _BROWSER_LOCK:
        state = await asyncio.to_thread(_login_state)
    if not state["is_logged_in"]:
        raise ChannelError(401, "NOT_LOGGED_IN", "知乎未登录或登录态失效，请先在桌面窗口登录")

    if body.confirm_account and body.confirm_account != (state["username"] or ""):
        raise ChannelError(
            409,
            "ACCOUNT_MISMATCH",
            f"确认账号 {body.confirm_account} 与当前登录账号 {state['username'] or '未知'} 不一致，拒绝发布",
        )

    async with _BROWSER_LOCK:
        result = await asyncio.to_thread(
            _service().publish_article,
            body.title, body.content, body.images or None, body.tags or None, True,
        )
    if not result.get("success"):
        raise ChannelError(502, "PUBLISH_FAILED", str(result.get("message") or "发布失败"))

    data = {
        "url": result.get("url") or "",
        "title": body.title,
        "publishedAt": _now(),
        "account": state["username"],
        "transport": "playwright",
        "upstreamMessage": result.get("message") or "",
    }
    if body.run_id:
        receipt = EXPORT_ROOT / body.run_id / "zhihu_receipt.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({"channel": "zhihu", "status": "published", **data}, ensure_ascii=False, indent=2), encoding="utf-8")
        data["receipt"] = str(receipt)
    return {"success": True, "data": data}
