"""运营维护：服务健康与起停、日志尾巴、以及「发出去的内容现在怎么样了」的运营数据。

三条硬约束（与 docs 里其它模块一致）：
1. **数据来源必须写清楚**：每个数字都带 source，取不到就如实说取不到，不猜；
2. **起停只碰本工作区自己的服务**：白名单固定为 backend/frontend/mcp/zhihu/bilibili，
   一律通过 ops/start_all.sh、ops/stop_all.sh 执行（不自己拼命令行，避免绕开 ops 的端口/日志约定）；
3. **不改任何素材**：本模块只读 var/ 与各通道服务的 HTTP 接口，唯一的写动作是起停服务。

各平台能拿到什么（2026-09-19 实测）：
- B 站：公开 `x/web-interface/view` 接口 → 播放/点赞/投币/收藏/评论/弹幕/分享，不需要登录；
- 知乎：channel 服务的 /api/v1/stats（用已登录浏览器抓正文页的赞同数 / 评论数），浏览量不对外；
- 小红书：MCP /api/v1/user/me → 账号级粉丝/获赞；**单篇浏览量在创作者中心，MCP 未覆盖**。
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from .config import settings

WS = Path(__file__).resolve().parents[3]


class OpsError(Exception):
    """运营操作失败：由 main.py 翻译成 { error: { code, message } }。"""

    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


# --------------------------------------------------------------------------- #
# 服务
# --------------------------------------------------------------------------- #

SERVICES: tuple[tuple[str, str, int, str], ...] = (
    ("backend", "后端 API", 8000, "/api/health"),
    ("frontend", "前端 (vite)", 5178, ""),
    ("mcp", "小红书 MCP", 18060, "/health"),
    ("zhihu", "知乎通道", 18070, "/health"),
    ("bilibili", "B 站通道", 18080, "/health"),
)
SERVICE_MAP = {name: (label, port, path) for name, label, port, path in SERVICES}


def _listening(port: int) -> bool:
    """用 TCP 连接判断端口是否在听（比解析 ss/netstat 更稳，也不需要额外权限）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _pid(name: str) -> Optional[int]:
    pid_file = WS / "var" / "pids" / f"{name}.pid"
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except Exception:
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def _log_info(name: str) -> dict[str, Any]:
    path = WS / "var" / "logs" / f"{name}.log"
    if not path.is_file():
        return {"path": str(path), "exists": False, "size": 0, "updatedAt": 0}
    stat = path.stat()
    return {"path": str(path), "exists": True, "size": stat.st_size,
            "updatedAt": int(stat.st_mtime * 1000)}


async def _health(port: int, path: str) -> dict[str, Any]:
    if not path:
        return {"probed": False, "ok": None, "detail": "无 HTTP 健康接口（前端静态服务）"}
    url = f"http://127.0.0.1:{port}{path}"
    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=6.0, trust_env=False) as cx:
            r = await cx.get(url)
        return {"probed": True, "ok": r.status_code < 400, "status": r.status_code,
                "elapsedMs": int((time.time() - started) * 1000), "detail": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"probed": True, "ok": False, "detail": f"{type(e).__name__}: {e}"[:200],
                "elapsedMs": int((time.time() - started) * 1000)}


async def services() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, label, port, path in SERVICES:
        up = _listening(port)
        pid = _pid(name)
        health = await _health(port, path) if up else {"probed": False, "ok": False, "detail": "端口未监听"}
        out.append({
            "name": name, "label": label, "port": port, "up": up, "pid": pid,
            "url": f"http://127.0.0.1:{port}",
            "health": health, "log": _log_info(name),
            "restartHint": f"./ops/start_all.sh {name}" if name != "backend" else "./ops/start_all.sh backend",
        })
    return out


def logs(name: str, lines: int = 200, grep: str = "") -> dict[str, Any]:
    if name not in SERVICE_MAP:
        raise OpsError(404, "SERVICE_NOT_FOUND", f"未知服务：{name}")
    lines = max(1, min(int(lines), 2000))
    path = WS / "var" / "logs" / f"{name}.log"
    if not path.is_file():
        raise OpsError(404, "LOG_NOT_FOUND", f"没有日志文件：{path}")
    tail: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if grep and grep not in line:
                continue
            tail.append(line.rstrip("\n"))
    kept = tail[-lines:]
    return {"name": name, "path": str(path), "lines": kept, "matched": len(tail),
            "size": path.stat().st_size, "truncated": len(tail) > len(kept)}


def service_action(name: str, action: str) -> dict[str, Any]:
    if name not in SERVICE_MAP:
        raise OpsError(404, "SERVICE_NOT_FOUND", f"未知服务：{name}")
    if action not in ("start", "stop", "restart"):
        raise OpsError(400, "BAD_ACTION", f"不支持的动作：{action}（只支持 start / stop / restart）")
    script = WS / "ops" / ("start_all.sh" if action in ("start", "restart") else "stop_all.sh")
    if not script.is_file():
        raise OpsError(500, "OPS_SCRIPT_MISSING", f"找不到 ops 脚本：{script}")
    steps: list[list[str]] = []
    if action == "restart":
        steps.append([str(WS / "ops" / "stop_all.sh"), name])
    steps.append([str(script), name])
    output: list[str] = []
    for cmd in steps:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90, cwd=str(WS))
        except subprocess.TimeoutExpired:
            raise OpsError(504, "OPS_TIMEOUT", f"{' '.join(cmd)} 超时（90s）")
        output.append((proc.stdout or "").strip())
        output.append((proc.stderr or "").strip())
    time.sleep(1.2)  # 给服务一点起来的时间，前端刷新时状态更接近真实
    return {"service": name, "action": action, "output": "\n".join(x for x in output if x)}


# --------------------------------------------------------------------------- #
# 运营数据：从本机产物里发现「发出去过什么」，再向各平台要真实数字
# --------------------------------------------------------------------------- #

_BV_RE = re.compile(r"BV[0-9A-Za-z]{10}")
_ZHIHU_RE = re.compile(r"https?://zhuanlan\.zhihu\.com/p/\d+")
_BILI_API = "https://api.bilibili.com/x/web-interface/view"

_METRICS_CACHE: dict[str, Any] = {"at": 0.0, "data": None}
_METRICS_TTL = 60.0


def _scan_published() -> dict[str, list[dict[str, Any]]]:
    """扫 var/runs 与 var/artifacts，找出真实投递过的条目（只认回执/上传结果，不猜）。"""
    found: dict[str, list[dict[str, Any]]] = {"bilibili": [], "zhihu": [], "xiaohongshu": []}
    seen: set[str] = set()
    roots = [WS / "var" / "runs", WS / "var" / "artifacts"]
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.json"):
            if "export" in path.parts and path.name not in ("zhihu_receipt.json",):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if len(text) > 2_000_000:
                continue
            for m in _BV_RE.finditer(text):
                bv = m.group(0)
                if bv in seen:
                    continue
                seen.add(bv)
                found["bilibili"].append({"id": bv, "url": f"https://www.bilibili.com/video/{bv}",
                                          "source": str(path.relative_to(WS))})
            for m in _ZHIHU_RE.finditer(text):
                url = m.group(0)
                if url in seen:
                    continue
                seen.add(url)
                found["zhihu"].append({"id": url.rsplit("/", 1)[-1], "url": url,
                                       "source": str(path.relative_to(WS))})
    return found


async def _bilibili_items(seed: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=15.0, trust_env=False,
                                 headers={"User-Agent": "Mozilla/5.0 (PaperCast ops)"}) as cx:
        for entry in seed:
            try:
                r = await cx.get(_BILI_API, params={"bvid": entry["id"]})
                body = r.json()
            except Exception as e:
                errors.append(f"{entry['id']}: {type(e).__name__}")
                continue
            data = body.get("data") if isinstance(body, dict) else None
            if not data:
                errors.append(f"{entry['id']}: {body.get('message') if isinstance(body, dict) else 'bad response'}")
                continue
            stat = data.get("stat") or {}
            items.append({
                "id": entry["id"], "url": data.get("short_link_v2") or entry["url"],
                "title": data.get("title") or entry["id"],
                "author": (data.get("owner") or {}).get("name", ""),
                "publishedAt": int(data.get("pubdate") or 0) * 1000,
                "stats": {"view": stat.get("view"), "like": stat.get("like"), "coin": stat.get("coin"),
                          "favorite": stat.get("favorite"), "reply": stat.get("reply"),
                          "danmaku": stat.get("danmaku"), "share": stat.get("share")},
                "source": entry["source"],
            })
    return {"items": items, "errors": errors}


async def _zhihu_items(seed: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=180.0, trust_env=False) as cx:
            for entry in seed:
                try:
                    r = await cx.get(f"{settings.zhihu_publisher_base}/api/v1/stats",
                                     params={"url": entry["url"]})
                    body = r.json()
                except Exception as e:
                    errors.append(f"{entry['id']}: {type(e).__name__}")
                    continue
                if r.status_code != 200 or not body.get("success"):
                    errors.append(f"{entry['id']}: {(body.get('error') or {}).get('message') or r.status_code}")
                    continue
                data = body.get("data") or {}
                items.append({
                    "id": entry["id"], "url": entry["url"],
                    "title": data.get("title") or entry["id"],
                    "author": data.get("author") or "",
                    "publishedAt": 0,
                    "stats": {"like": data.get("votes"), "reply": data.get("comments")},
                    "source": entry["source"],
                })
    except Exception as e:
        errors.append(f"zhihu-publisher 不可达：{type(e).__name__}")
    return {"items": items, "errors": errors}


async def _xhs_account() -> dict[str, Any]:
    """账号级数据（粉丝 / 获赞 / 收藏）。MCP 的 /api/v1/user/me 是 GET，而且每次真开一次浏览器，很慢。

    未登录时 MCP 会直接 500 —— 这里翻译成一句人话，别把它当成「数字为零」。
    """
    base = settings.xhs_mcp_base
    try:
        async with httpx.AsyncClient(timeout=150.0, trust_env=False) as cx:
            status = await cx.get(f"{base}/api/v1/login/status")
            body_status = status.json() if status.content else {}
            logged = bool(((body_status.get("data") or {}) if isinstance(body_status, dict) else {}).get("is_logged_in"))
            if status.status_code < 400 and not logged:
                return {"available": False, "detail": "小红书 MCP 报告未登录：先去「平台账号」扫码，再回来刷数据"}
            r = await cx.get(f"{base}/api/v1/user/me")
    except Exception as e:
        return {"available": False, "detail": f"MCP 不可达（{type(e).__name__}）"}
    body = r.json() if r.content else {}
    if r.status_code != 200 or not body.get("success"):
        detail = str(body.get("message") or f"MCP 返回 HTTP {r.status_code}")
        if r.status_code >= 500:
            detail = f"MCP 返回 {r.status_code}（未登录或浏览器启动失败）：{detail}"
        return {"available": False, "detail": detail[:200]}
    return {"available": True, "raw": body.get("data")}


def _sum(items: list[dict[str, Any]], key: str) -> int:
    total = 0
    for it in items:
        value = (it.get("stats") or {}).get(key)
        if isinstance(value, (int, float)):
            total += int(value)
    return total


async def metrics(force: bool = False) -> dict[str, Any]:
    now = time.time()
    if not force and _METRICS_CACHE["data"] is not None and now - _METRICS_CACHE["at"] < _METRICS_TTL:
        return _METRICS_CACHE["data"]

    seed = _scan_published()
    bili = await _bilibili_items(seed["bilibili"])
    zhihu = await _zhihu_items(seed["zhihu"])
    xhs = await _xhs_account()

    channels: list[dict[str, Any]] = [
        {
            "id": "bilibili", "name": "B 站", "kind": "video",
            "source": "公开 view 接口（api.bilibili.com/x/web-interface/view）",
            "items": bili["items"], "errors": bili["errors"],
            "totals": {k: _sum(bili["items"], k) for k in ("view", "like", "coin", "favorite", "reply", "danmaku", "share")},
            "gap": "" if bili["items"] else "本机还没发现投递成功的 B 站稿件（var/runs/**/video/upload_result.json）",
        },
        {
            "id": "zhihu", "name": "知乎", "kind": "article",
            "source": "zhihu-publisher /api/v1/stats（已登录浏览器抓正文页赞同 / 评论数）",
            "items": zhihu["items"], "errors": zhihu["errors"],
            "totals": {"like": _sum(zhihu["items"], "like"), "reply": _sum(zhihu["items"], "reply")},
            "gap": "浏览量知乎不对外提供（只在创作者中心可见）",
        },
    ]

    xhs_item: dict[str, Any] = {
        "id": "xiaohongshu", "name": "小红书", "kind": "note",
        "source": "xiaohongshu-mcp /api/v1/user/me（账号级）",
        "items": [], "errors": [] if xhs.get("available") else [xhs.get("detail", "")],
        "totals": {},
        "gap": "单篇浏览量在创作者中心，MCP 未覆盖；未登录时账号级数据也拿不到",
    }
    if xhs.get("available") and isinstance(xhs.get("raw"), dict):
        raw = xhs["raw"]
        stats = raw.get("stats") if isinstance(raw.get("stats"), dict) else raw
        xhs_item["account"] = {"name": raw.get("nickname") or raw.get("name") or "",
                               "raw": {k: v for k, v in list(stats.items())[:12]}}
    channels.append(xhs_item)

    data = {"fetchedAt": int(time.time() * 1000), "channels": channels}
    _METRICS_CACHE.update(at=now, data=data)
    return data
