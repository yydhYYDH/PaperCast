"""M3：发布 —— 小红书（xiaohongshu-mcp），人工闸门之后才真实投递。

默认行为是「准备」而不是「发出去」：闸门之前只做可逆的事（准备 export/、探测 MCP 状态）。
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Optional

import httpx

from ..pipeline import StageContext
from .generate import title_weight


class PublishError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# 本机服务必须绕开 http_proxy，否则会被代理吃掉（本机实测过）
def _client(timeout: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, trust_env=False)


def _read_xhs_export(article_dir: Path) -> dict:
    """从 M2 的 export/ 读待发布内容；缺失时从 xhs.md 兜底解析。"""
    title_file = article_dir / "export" / "title.txt"
    content_file = article_dir / "export" / "content.txt"
    out: dict[str, Any] = {"title": "", "content": "", "tags": [], "images": []}
    if title_file.is_file():
        out["title"] = title_file.read_text(encoding="utf-8").strip()
    if content_file.is_file():
        raw = content_file.read_text(encoding="utf-8").strip()
        m = re.search(r"((?:^|\s)#[^\s#]+(?:\s+#[^\s#]+)*)\s*$", raw)
        if m:
            out["tags"] = [t.lstrip("#") for t in m.group(1).split() if t.startswith("#")]
            raw = raw[: m.start()].strip()
        out["content"] = raw
    if not out["title"] or not out["content"]:
        md = article_dir / "xhs.md"
        if md.is_file():
            text = md.read_text(encoding="utf-8")
            if not out["title"]:
                m = re.search(r"^推荐标题：(.+)$", text, re.M)
                out["title"] = (m.group(1).strip() if m else "") or ""
            if not out["content"]:
                m = re.search(r"## 正文\n(.*?)\n## 标签", text, re.S)
                out["content"] = (m.group(1).strip() if m else "")
            if not out["tags"]:
                m = re.search(r"## 标签\n(.+)$", text, re.M)
                out["tags"] = [t.lstrip("#") for t in (m.group(1).split() if m else []) if t.startswith("#")]
    for c in sorted((article_dir / "cards").glob("p*.png")):
        out["images"].append(str(c.resolve()))
    return out


async def _mcp_state(ctx: StageContext) -> dict:
    """探测 xiaohongshu-mcp：健康 + 登录态。"""
    state: dict[str, Any] = {"reachable": False, "loggedIn": False, "account": "", "error": "", "qrcode": ""}
    base_url = ctx.settings.xhs_mcp_base
    try:
        async with _client(10.0) as cx:
            h = await cx.get(f"{base_url}/health")
            state["reachable"] = h.status_code == 200 and bool(h.json().get("success"))
    except Exception as e:
        state["error"] = f"{type(e).__name__}: {e}"
        return state
    try:
        async with _client(20.0) as cx:
            r = await cx.get(f"{base_url}/api/v1/login/status")
            data = (r.json() or {}).get("data") or {}
            state["loggedIn"] = bool(data.get("is_logged_in"))
            state["account"] = data.get("username") or ""
    except Exception as e:
        state["error"] = f"login/status: {type(e).__name__}: {e}"
    return state


async def _publish_xhs(ctx: StageContext, payload: dict, state: dict) -> dict:
    base_url = ctx.settings.xhs_mcp_base
    body = {
        "title": payload["title"],
        "content": payload["content"],
        "images": payload["images"],
        "tags": payload["tags"],
        "is_original": True,
    }
    async with _client(180.0) as cx:
        resp = await cx.post(f"{base_url}/api/v1/publish", json=body)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:500]}
    if resp.status_code >= 400 or not data.get("success", False):
        code = (data.get("error") or {}).get("code") or f"HTTP_{resp.status_code}"
        msg = (data.get("error") or {}).get("message") or data.get("message") or "发布失败"
        if "登录" in str(msg):
            code = "NOT_LOGGED_IN"
        return {"ok": False, "code": code, "message": str(msg), "raw": data}
    return {"ok": True, "raw": data, "data": data.get("data")}


async def run_publish(ctx: StageContext) -> None:
    run_dir = ctx.store.dir(ctx.run.id)
    article_dir = run_dir / "article"
    if not article_dir.is_dir():
        raise PublishError("ARTICLE_MISSING", "缺少 M2 的文章产物，无法发布")

    payload = _read_xhs_export(article_dir)
    ctx.log("info", f"待发布：标题「{payload['title']}」/ 正文 {len(payload['content'])} 字 / {len(payload['images'])} 张图")

    # ---- 图片兜底：卡片没渲染出来就用 M1 抽的论文原图 ----
    if not payload["images"]:
        fallback = sorted((run_dir / "intake" / "images").glob("fig-*.png"))[:6]
        payload["images"] = [str(p.resolve()) for p in fallback]
        if payload["images"]:
            ctx.log("warn", f"卡片图缺失，回退到论文原图 {len(payload['images'])} 张")
    if not payload["images"]:
        raise PublishError("IMAGE_EMPTY", "没有任何可发布的图片（卡片与原图都缺失）")

    # ---- 本地预检：标题计重 / 图片可读 ----
    weight = title_weight(payload["title"])
    if not payload["title"]:
        raise PublishError("TITLE_MISSING", "标题为空，拒绝发布")
    if weight > 38:
        raise PublishError("TITLE_TOO_LONG", f"标题计重 {weight} > 38，发布前本地拦截（不浪费一次失败请求）")
    payload["images"] = [p for p in payload["images"] if Path(p).is_file()]
    if not payload["images"]:
        raise PublishError("IMAGE_EMPTY", "图片路径全部不可读")

    # ---- export/ 落盘（MCP 掉线也能手动发） ----
    export = ctx.work / "export"
    export.mkdir(parents=True, exist_ok=True)
    (export / "title.txt").write_text(payload["title"], encoding="utf-8")
    (export / "content.txt").write_text(
        payload["content"] + "\n\n" + " ".join(f"#{t}" for t in payload["tags"]), encoding="utf-8"
    )
    for i, img in enumerate(payload["images"], 1):
        try:
            shutil.copyfile(img, export / f"p{i}.png")
        except OSError as e:
            ctx.log("warn", f"导出图片失败：{img}: {e}")
    (ctx.work / "ready.json").write_text(
        json.dumps(payload | {"images": [Path(p).name for p in payload["images"]]}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    (ctx.work / "export" / "README.txt").write_text(
        "MCP 不可用时的手动发布兜底：\n"
        "1. 打开小红书 → 发布图文；\n"
        "2. 图片按 p1.png / p2.png … 顺序上传；\n"
        "3. 标题取 title.txt，正文取 content.txt（已含话题标签）。\n",
        encoding="utf-8",
    )
    ctx.artifact("json", "待发布清单 ready.json", "ready.json", preview=True)
    ctx.artifact("text", "标题（发布用）", "export/title.txt", preview=True)
    ctx.artifact("text", "正文（发布用）", "export/content.txt", preview=True)
    ctx.log("ok", f"export/ 已就绪（{len(payload['images'])} 张图），即使 MCP 掉线也能手动发布")

    # ---- 探测 MCP ----
    state = await _mcp_state(ctx)
    if state["reachable"]:
        ctx.log("ok", f"xiaohongshu-mcp 健康检查通过：{ctx.settings.xhs_mcp_base}")
    else:
        ctx.log("warn", f"xiaohongshu-mcp 不可达（{state['error'][:120]}）；可用 export/ 手动发布")
    if state["reachable"]:
        if state["loggedIn"]:
            ctx.log("ok", f"小红书登录态正常：账号 {state['account']}")
        else:
            ctx.log("warn", "小红书未登录，继续发布会失败；请先在 MCP 侧扫码登录")
    ctx.check("MCP 可用性", "pass" if state["reachable"] else "fail",
              f"{ctx.settings.xhs_mcp_base} 健康" if state["reachable"] else f"不可达：{state['error'][:80]}")
    ctx.check("登录态", "pass" if state["loggedIn"] else "fail",
              f"账号 {state['account']}" if state["loggedIn"] else "未登录（发布会被拒绝）")
    ctx.check("发布素材", "pass", f"{len(payload['images'])} 张图 / {len(payload['content'])} 字 / 标题计重 {weight}")

    # ---- 闸门 ----
    detail = (
        f"即将投递到小红书（xiaohongshu-mcp {ctx.settings.xhs_mcp_base}，"
        f"账号 {state['account'] or '未登录'}）：标题「{payload['title']}」，"
        f"{len(payload['images'])} 张图，正文 {len(payload['content'])} 字。"
        if state["reachable"] and state["loggedIn"]
        else f"MCP 当前不可用（{state['error'][:60] or '未登录'}）；选择「确认发布」会失败并写入回执，「仅存草稿」只会准备 export/。"
    )
    chosen = await ctx.gate(
        "publish-gate",
        "发布前人工闸门",
        detail,
        [
            ("continue", "确认发布", None),
            ("draft", "仅存草稿", "只准备 export/，不调发布接口"),
            ("skip", "本轮不发布", None),
        ],
    )

    receipt: dict[str, Any] = {
        "channel": "xiaohongshu",
        "optionId": chosen,
        "title": payload["title"],
        "imageCount": len(payload["images"]),
        "contentChars": len(payload["content"]),
        "tags": payload["tags"],
        "mcp": {"base": ctx.settings.xhs_mcp_base, "reachable": state["reachable"],
                "loggedIn": state["loggedIn"], "account": state["account"]},
        "at": __import__("time").time(),
    }

    if chosen == "skip":
        receipt["status"] = "skipped"
        ctx.log("warn", "本轮不发布：仅保留 export/")
    elif chosen == "draft":
        receipt["status"] = "draft"
        ctx.log("warn", "仅存草稿：素材已备好，未调用发布接口")
    else:
        if not state["reachable"]:
            receipt.update(status="failed", error={
                "code": "MCP_UNREACHABLE",
                "message": f"{ctx.settings.xhs_mcp_base} 不可达；启动命令：cd xiaohongshu-mcp && ./xiaohongshu-mcp -port :18060",
            })
            ctx.log("err", "发布失败：MCP 不可达（export/ 仍可用）")
        elif not state["loggedIn"]:
            receipt.update(status="failed", error={"code": "NOT_LOGGED_IN", "message": "小红书未登录，请先扫码登录后重试"})
            ctx.log("err", "发布失败：未登录（不重试、不绕过风控）")
        else:
            ctx.log("info", f"调用 xiaohongshu-mcp 发布（{len(payload['images'])} 张图）…")
            result = await _publish_xhs(ctx, payload, state)
            if result["ok"]:
                data = result.get("data") or {}
                receipt.update(
                    status="published",
                    noteId=str(data.get("note_id") or data.get("noteId") or ""),
                    permlink=str(data.get("permlink") or data.get("url") or ""),
                    raw=data,
                )
                ctx.log("ok", f"发布成功：{receipt.get('permlink') or receipt.get('noteId') or '已提交'}")
            else:
                receipt.update(status="failed", error={"code": result["code"], "message": result["message"]},
                               raw=result.get("raw"))
                ctx.log("err", f"发布失败：{result['code']} {result['message'][:160]}")

    (ctx.work / "xhs_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=1), encoding="utf-8")
    ctx.artifact("json", "小红书发布回执", "xhs_receipt.json", preview=True,
                 meta={"status": receipt["status"]})

    status = receipt["status"]
    if status == "published":
        ctx.check("发布结果", "pass", receipt.get("permlink") or receipt.get("noteId") or "已提交")
        ctx.log("ok", "M3 完成：已发布")
    elif status in ("draft", "skipped"):
        ctx.check("发布结果", "run", f"{status}（素材在 export/）")
        ctx.stage.status = "done"
        ctx.log("ok", f"M3 完成：{status}")
    else:
        ctx.check("发布结果", "fail", (receipt.get("error") or {}).get("message", "")[:120])
        # 不把整条运行判死：素材可用，人工处理即可
        ctx.log("warn", "M3 未发出：按设计失败不静默重试，请人工处理或改用手动发布")
