"""互动（P1）：**只读**评论/通知 + 起草回复（永远不发送）。

用户 2026-09-19 拍板：互动不新开第 7 个 agent，作为主 agent 的一项技能；并按风险分三步走
—— **P1 只读 + 起草（本文件）** → P2 逐条人工确认后才发送 → 全自动不做。

三条红线（改之前先读）：

1. **读的一律只读**。读路径只调 MCP 的三个只读路由：/api/v1/notifications/unread、
   /api/v1/notifications/list、以及（暂时没用到）/api/v1/feeds/detail。
   **写路径只有两条**，而且全都长在 reply_to_comment() 里、都要**逐条人工确认**：
   feeds/comment/reply（笔记页回评论）、notifications/reply（回「评论和@」里的评论）。
   **永远不调** feeds/comment（自己发评论）、feeds/like、feeds/favorite、notifications/like、
   publish*：点赞/收藏/发布不是「回话」，属于真正的对外动作，另走人工闸门那条链。
   而且写路径默认**关着**（见 SEND_ENV）：不显式打开开关，调用只会得到 SEND_DISABLED。
2. **MCP 每次调用都真开一次浏览器**（见 docs/xhs-account-safety.md），护栏预算是 30 次/10 分钟
   （apps/xiaohongshu-mcp/guard.go）。所以这里**没有轮询、没有后台刷新**：只有用户主动说一句
   「看看评论」才会发请求；一次动作最多两次调用（列表 + 未读数，未读数是尽力而为）。
3. **读不到就说读不到**。MCP 不可达 / 未登录 / 超预算，一律如实写进 gap 与 errors，
   **绝不返回「0 条评论」**假装读过了 —— 与 ops.py 的口径一致。

草稿要给人看、要留痕，所以落 var/interactions/drafts.jsonl（运行态、不入库）；真发出去的一条落
var/interactions/sent.jsonl —— 两份文件分开，谁是草稿、谁真发了，一眼可查（sent 恒为 true）。
P1（读 + 起草）的返回值里带 canSend: false；P2 的 reply 接口必须显式 confirmed=true 才动，
并且还要过 SEND_ENV 开关与每小时条数上限两道护栏。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from .config import settings
from .llm import LLMClient, LLMError
from .platforms import PlatformError

router = APIRouter(prefix="/api/interactions", tags=["interactions"])

#: 一次只读动作最多两次 MCP 调用（列表 + 未读数）
MCP_TIMEOUT_SEC = 60.0
DEFAULT_LIMIT = 10
MAX_LIMIT = 30

#: 界面上的来源说明：必须写清「只读」，别让人以为这里已经能自动回复了
SOURCE = "xiaohongshu-mcp /api/v1/notifications/*（只读，不发送）"

#: 草稿落盘位置（返回给前端时给相对路径，不暴露绝对路径）
DRAFTS_REL = "var/interactions/drafts.jsonl"
#: 真发出去一条就追加一行（与草稿分开，sent 恒为 true）
SENT_REL = "var/interactions/sent.jsonl"


def _drafts_path() -> Path:
    """var/runs 的兄弟目录 var/interactions/ —— 运行态，不入库。"""
    return Path(settings.data_dir).parent / "interactions" / "drafts.jsonl"


def _now_ms() -> int:
    return int(time.time() * 1000)


# --------------------------------------------------------------------------- #
# MCP 只读访问
# --------------------------------------------------------------------------- #


async def _mcp_get(path: str) -> Any:
    """MCP 只读 GET。异常与 MCP 自己报的错都翻成人话抛出去（由调用方如实记进 gap）。"""
    url = f"{settings.xhs_mcp_base}{path}"
    try:
        async with httpx.AsyncClient(timeout=MCP_TIMEOUT_SEC, trust_env=False) as cx:
            r = await cx.get(url)
    except Exception as e:
        raise PlatformError(
            502, "MCP_UNREACHABLE", f"小红书通道不可达（{type(e).__name__}）：先 ./ops/start_all.sh mcp"
        ) from e

    try:
        payload = r.json() or {}
    except Exception as e:  # MCP 返回了非 JSON（例如中间有反代页面）
        raise PlatformError(502, "MCP_BAD_RESPONSE", f"小红书通道返回的不是 JSON（HTTP {r.status_code}）") from e

    err = payload.get("error") if isinstance(payload.get("error"), dict) else None
    if r.status_code != 200 or not payload.get("success", True):
        msg = (err or {}).get("message") or payload.get("message") or f"HTTP {r.status_code}"
        code = (err or {}).get("code") or r.status_code
        raise PlatformError(
            502,
            "MCP_ERROR",
            f"小红书通道拒绝了这次读取：{msg}（{code}）—— 先去「平台账号」扫码登录，再回来说一句「看看评论」",
        )
    return payload.get("data")


def _unwrap(data: Any) -> Any:
    """MCP 的 HTTP 层把结果包了一层：{success, data: {data: <真结果>}}。

    _mcp_get 已经剥掉最外面那层；这里再兜一层（上游包几层都不怕，别让形状变化变成崩溃）。
    """
    while isinstance(data, dict) and list(data.keys()) == ["data"]:
        data = data["data"]
    return data


def normalize_notification(n: dict[str, Any]) -> dict[str, Any]:
    """一条通知 → 界面要的形状。字段名取自 MCP 的 xiaohongshu.NotificationItem。"""
    frm = n.get("from") if isinstance(n.get("from"), dict) else {}
    comment_id = str(n.get("comment_id") or "")
    text = str(n.get("comment_text") or "").strip()
    return {
        "id": str(n.get("id") or comment_id or ""),
        "kind": "comment" if comment_id else str(n.get("type") or "notice"),
        "author": str(frm.get("nickname") or ""),
        "authorId": str(frm.get("user_id") or ""),
        "text": text or str(n.get("title") or "").strip(),
        "workTitle": str(n.get("feed_title") or ""),
        "at": int(n.get("time") or 0),
        "liked": bool(n.get("liked")),
        "feedId": str(n.get("feed_id") or ""),
        # xsecToken 是**访问令牌**：只给后续 P2 的回复用，不写日志、不落 docs
        "xsecToken": str(n.get("feed_xsec_token") or ""),
        "commentId": comment_id,
        # 有评论 id 才有得回；注意 P1 只起草，canReply 不代表这里会发出去
        "canReply": bool(comment_id),
    }


async def list_interactions(limit: int = DEFAULT_LIMIT, with_unread: bool = False) -> dict[str, Any]:
    """读一次互动（只读）。任何一段读不到都如实说，并给下一步。

    with_unread 默认 False：未读数要**另开一次浏览器动作**，而列表本身已经证明登录态可用，
    所以对话里那条「看看评论」只花一次预算。真要三个分区的未读数时显式带上 ?unread=1。
    """
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    out: dict[str, Any] = {
        "fetchedAt": _now_ms(),
        "source": SOURCE,
        "stage": "P1",
        "canSend": False,
        "canSendNote": "这里只读和起草；发送要逐条确认（P2），现在一个字都不会发出去",
        "unread": None,
        "items": [],
        "filtered": 0,
        "errors": [],
        "gap": "",
    }

    try:
        data = _unwrap(await _mcp_get(f"/api/v1/notifications/list?tab=mentions&limit={limit}"))
        rows = (data or {}).get("items") or []
        out["items"] = [normalize_notification(n) for n in rows if isinstance(n, dict)]
        out["filtered"] = int((data or {}).get("filtered") or 0)
    except PlatformError as e:
        out["errors"].append(str(e))
        out["gap"] = f"读不到评论 —— {e}"

    # 未读数：按需、尽力而为。列表已经失败时不再多打一次（每一次都是真开浏览器）
    if with_unread and (out["items"] or not out["errors"]):
        try:
            out["unread"] = _unwrap(await _mcp_get("/api/v1/notifications/unread")) or None
        except PlatformError as e:
            out["errors"].append(str(e))

    if not out["items"] and not out["gap"]:
        extra = f" 其中 {out['filtered']} 条被平台侧过滤掉了（评论已删除或不可见）。" if out["filtered"] else ""
        out["gap"] = "这次没读到评论和@（也可能真的还没有人评论）。" + extra
    return out


# --------------------------------------------------------------------------- #
# 起草回复（只落盘，不发送）
# --------------------------------------------------------------------------- #

DRAFT_SYSTEM = """你在帮一位论文作者回复公开平台上的读者评论。只写草稿，作者会先看再决定发不发。

规则：
1. 中文口语，1-3 句，一般 20-80 字；不要小标题、不要表格、不要表情符号。
2. 对方是提问就正面回答；是夸奖就简短接住；是质疑就说清事实、不争不辩。
3. 不许编：不引用任何数字、结论、图表，也不做时间承诺（不要写「下周更新」「马上补实验」这类）。
   拿不准的就说「我确认一下再回你」。
4. 不要营销腔，不要「感谢支持」「点赞关注」「一键三连」这种空话，不要套近乎。
5. 只输出 JSON：{"reply": "要发的回复草稿", "why": "一句话说明这么回的理由"}"""


class DraftRequest(BaseModel):
    commentText: str = Field(min_length=1, max_length=1000)
    author: str = Field(default="", max_length=80)
    workTitle: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=500)

    @field_validator("commentText")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("评论内容不能为空")
        return v.strip()


def _save_draft(rec: dict[str, Any]) -> None:
    p = _drafts_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


@router.get("")
async def get_interactions(limit: int = DEFAULT_LIMIT, unread: bool = False) -> dict[str, Any]:
    """一次只读：小红书「评论和@」（unread=1 时附带未读数）。**不会**发任何东西出去。"""
    return await list_interactions(limit, with_unread=unread)


@router.post("/draft")
async def draft_reply(req: DraftRequest) -> dict[str, Any]:
    """给一条评论起草回复。**只落盘，不发送** —— 发送是 P2，且必须逐条确认。"""
    client = LLMClient(settings)
    if not client.available:
        raise PlatformError(
            400, "LLM_NOT_CONFIGURED", "还没有配置模型（LLM_API_KEY / LLM_BASE_URL），先去「设置 → 模型与 API」填上"
        )

    bits = [f"评论者：{req.author or '（未署名）'}"]
    if req.workTitle:
        bits.append(f"他评论的是这篇：{req.workTitle}")
    bits.append(f"评论原文：{req.commentText}")
    if req.note:
        bits.append(f"作者补充的口径：{req.note}")
    user = "\n".join(bits) + "\n\n请给出 JSON 草稿。"

    try:
        raw = await client.chat_json(DRAFT_SYSTEM, user, max_tokens=1024, retries=1)
    except LLMError as e:
        raise PlatformError(502, e.code, f"模型调用失败：{e}") from e

    obj = raw if isinstance(raw, dict) else {}
    reply = str(obj.get("reply") or "").strip()
    if not reply:
        raise PlatformError(502, "DRAFT_EMPTY", "模型这次没写出可用的草稿，再点一次试试")

    rec = {
        "id": f"draft_{int(time.time() * 1000)}",
        "at": _now_ms(),
        "author": req.author,
        "workTitle": req.workTitle,
        "commentText": req.commentText,
        "reply": reply,
        "why": str(obj.get("why") or "").strip(),
        "model": settings.llm_model,
        "stage": "P1",
        "sent": False,
    }
    saved = DRAFTS_REL
    try:
        _save_draft(rec)
    except OSError as e:
        # 落盘失败不该把草稿弄丢：如实说没存下来，但草稿原文照样交给用户
        saved = ""
        rec["saveError"] = f"{type(e).__name__}: {e}"

    return {
        "draft": rec,
        "savedTo": saved,
        "stage": "P1",
        "canSend": False,
        "canSendNote": "草稿只落盘、没发出去。发送那一步（P2）要逐条确认，现在一个字都不会发。",
    }


# --------------------------------------------------------------------------- #
# P2：逐条确认之后才真发（默认**关**着）
#
# 「直接发出去」这种事只有一条路：reply_to_comment()。它要同时满足四个条件才会动手：
#   1) 请求体里 confirmed=true（用户在对话里点了那张卡，且过了应用内确认框）；
#   2) SEND_ENV 开关打开（默认关 —— 代码可以先上，手不能先动）；
#   3) 目标明确（笔记页回评论要 feedId+xsecToken；回「评论和@」要 commentId）；
#   4) 没超过 SEND_CAP_PER_HOUR。
# 缺任何一条都抛错，并且错误码要能让前端说清楚「为什么没发」。
# --------------------------------------------------------------------------- #

#: 真发出去的开关（默认关）。打开方式：.env 里写 PAPERCAST_INTERACTIONS_SEND=1，重启后端。
SEND_ENV = "PAPERCAST_INTERACTIONS_SEND"
#: 一小时内最多真发几条（护栏：循环 / 误触都不该变成刷屏）
SEND_CAP_PER_HOUR = 20

#: 两条允许的写路由，对应两种回法
REPLY_VIA_COMMENT = "/api/v1/feeds/comment/reply"          # 笔记页回某条评论
REPLY_VIA_NOTIFICATION = "/api/v1/notifications/reply"     # 回「评论和@」里的一条

#: 进程内发送时间戳，用于限速（重启即清零 —— 这只是护栏，不是账本，账本在 sent.jsonl）
_SENT_AT: list[float] = []


def send_enabled() -> bool:
    return (os.environ.get(SEND_ENV) or "").strip().lower() in ("1", "true", "yes", "on")


class ReplyRequest(BaseModel):
    """真发一条回复。字段都来自「读到的评论」或「刚起草的那句」，前端不自己拼。"""

    content: str = Field(min_length=1, max_length=1000)
    commentId: str = Field(default="", max_length=120)
    feedId: str = Field(default="", max_length=120)
    xsecToken: str = Field(default="", max_length=400)
    userId: str = Field(default="", max_length=120)
    draftId: str = Field(default="", max_length=120)
    #: 必须显式为 true：少写/写错都当没确认，直接拒
    confirmed: bool = False

    @field_validator("content")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("回复内容不能为空")
        return v.strip()


async def _mcp_post(path: str, payload: dict[str, Any]) -> Any:
    """MCP 写路由调用（只有 reply_to_comment 会用）。错误一律翻成人话。"""
    if path not in (REPLY_VIA_COMMENT, REPLY_VIA_NOTIFICATION):
        # 兜底：万一以后有人拿着这个函数去调别的写路由，这里直接拦住
        raise PlatformError(500, "WRITE_ROUTE_NOT_ALLOWED", f"这个写路由不在允许清单里：{path}")
    url = f"{settings.xhs_mcp_base}{path}"
    try:
        async with httpx.AsyncClient(timeout=MCP_TIMEOUT_SEC, trust_env=False) as cx:
            r = await cx.post(url, json=payload)
    except Exception as e:
        raise PlatformError(502, "MCP_UNREACHABLE", f"小红书通道不可达（{type(e).__name__}）：先 ./ops/start_all.sh mcp") from e

    try:
        body = r.json() or {}
    except Exception as e:
        raise PlatformError(502, "MCP_BAD_RESPONSE", f"小红书通道返回的不是 JSON（HTTP {r.status_code}）") from e

    err = body.get("error") if isinstance(body.get("error"), dict) else None
    if r.status_code != 200 or not body.get("success", True):
        msg = (err or {}).get("message") or body.get("message") or f"HTTP {r.status_code}"
        code = (err or {}).get("code") or r.status_code
        # 这里**不要**说「已发出」：平台侧到底发没发以 MCP 的回答为准
        raise PlatformError(502, "MCP_REPLY_FAILED", f"小红书通道没回成功：{msg}（{code}）")
    return _unwrap(body.get("data"))


def _append_jsonl(path: Path, rec: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _sent_path() -> Path:
    return Path(settings.data_dir).parent / "interactions" / "sent.jsonl"


def _rate_check(now: float) -> None:
    _SENT_AT[:] = [t for t in _SENT_AT if now - t < 3600]
    if len(_SENT_AT) >= SEND_CAP_PER_HOUR:
        raise PlatformError(
            429,
            "SEND_RATE_LIMITED",
            f"这一小时已经替你发了 {len(_SENT_AT)} 条，先停一停（上限 {SEND_CAP_PER_HOUR} 条/小时）。"
            "要接着发，等一会儿再说。",
        )


@router.post("/reply")
async def reply_to_comment(req: ReplyRequest) -> dict[str, Any]:
    """把一条**已经起草好、你也点过确认**的回复真发出去（P2）。

    这里是全项目唯一会替人「说话」的地方，所以护栏比别处都多：显式 confirmed + 开关 + 目标 + 限速。
    """
    if not req.confirmed:
        raise PlatformError(400, "CONFIRM_REQUIRED", "这一步要你点了确认才会发（confirmed=true），先看清楚再点")

    if not send_enabled():
        raise PlatformError(
            403,
            "SEND_DISABLED",
            "发送开关没打开（默认关）：要我真的替你发，先在 .env 里加 "
            f"{SEND_ENV}=1 再重启后端 —— 这一步故意留给你点头，账号还在恢复期。",
        )

    if req.feedId and req.xsecToken:
        path, payload = REPLY_VIA_COMMENT, {"feed_id": req.feedId, "xsec_token": req.xsecToken, "content": req.content}
        if req.commentId:
            payload["comment_id"] = req.commentId
        if req.userId:
            payload["user_id"] = req.userId
        target = "comment"
    elif req.commentId:
        path, payload = REPLY_VIA_NOTIFICATION, {"comment_id": req.commentId, "content": req.content}
        target = "notification"
    else:
        raise PlatformError(400, "NO_TARGET", "不知道要回哪一条：这条评论缺 feed_id/xsec_token 也缺 comment_id，回去重读一遍评论再试")

    _rate_check(time.time())
    await _mcp_post(path, payload)
    _SENT_AT.append(time.time())

    rec = {
        "id": f"sent_{int(time.time() * 1000)}",
        "at": _now_ms(),
        "content": req.content,
        "commentId": req.commentId,
        "feedId": req.feedId,
        "draftId": req.draftId,
        "target": target,
        "stage": "P2",
        # sent 恒为 true：这个文件里只有真发出去的
        "sent": True,
    }
    saved = SENT_REL
    try:
        _append_jsonl(_sent_path(), rec)
    except OSError as e:
        # 发出去了但没记下来 —— 如实说（不能因为记账失败就说没发）
        saved = ""
        rec["saveError"] = f"{type(e).__name__}: {e}"

    return {
        "sent": True,
        "at": rec["at"],
        "content": req.content,
        "target": target,
        "savedTo": saved,
        "stage": "P2",
        "note": "已经发出去了。发出去就撤不回来 —— 要改只能回一条补充说明。",
    }


def send_routes() -> tuple[str, ...]:
    """自检用：允许调用的写路由**只有这两条**（回评论 / 回通知）。"""
    return (REPLY_VIA_COMMENT, REPLY_VIA_NOTIFICATION)


def write_routes_are_disallowed() -> tuple[str, ...]:
    """自检用：**永远不许调**的 MCP 路由（不是「回话」，是真对外动作：发帖、点赞、收藏）。"""
    return (
        "/api/v1/feeds/comment",
        "/api/v1/notifications/like",
        "/api/v1/feeds/like",
        "/api/v1/feeds/favorite",
        "/api/v1/publish",
        "/api/v1/publish_video",
    )
