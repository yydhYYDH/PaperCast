"""对话入口：POST /api/chat —— 用一句话问「这篇论文讲了什么 / 接下来做什么」。

设计约定（改之前先读）：

1. **事实源唯一**：回答只依据该运行已经落盘的 `run.json`、`understand/digest.json` 与产物清单，
   不联网、不臆测；事实源里没有的信息直接说没有，与其它模块的反幻觉口径一致。
2. **没配模型就明说**：没有 LLM 凭据时返回 400 `LLM_NOT_CONFIGURED`，前端据此提示去「设置」，
   不假装能聊。
3. **服务端不存会话**：多轮由前端把最近几轮一起传上来（`history`），后端只做一次补全 ——
   免得又多一份需要清理的状态。
4. 分工：本文件只负责「取上下文 + 组装提示词」，调用、重试、超时都在 `app/llm.py` 的 `LLMClient` 里。

挂载方式与 `app/config_api.py`、`app/channels/routes.py` 一致（APIRouter + 统一错误形状）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .config import settings
from .llm import LLMClient, LLMError
from .platforms import PlatformError

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 事实源长度上限：提示词里塞太多既慢又容易被无关内容带偏
MAX_CTX_CHARS = 6000
MAX_HISTORY_TURNS = 6

SYSTEM = """你是 PaperCast 的助手，陪用户把一篇论文变成大家看得懂的内容。
规则：
1. 只依据下面给你的「事实源」回答。事实源里没有的信息，直接说「这次运行里没有这条信息」，不要编。
2. 中文口语回答，简短（一般 3–6 句）。不要标题层级、不要表格、不要罗列小标题。
3. 被问到流程/下一步时，按这个顺序讲：取论文 → 读懂 → 写文章 → 做海报 → 剪视频 → 投放与运营；
   中间需要用户确认的地方（文章与海报成型后、真实发布前）要说明会停下来等确认。
4. 数字（页数、图片数、时长、字数）只引用事实源里出现过的，不要自己算、不要估。
5. 用户问与这篇论文无关的杂事，礼貌地说你只负责这件事，然后给一句能做的事。"""


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    runId: Optional[str] = None
    history: list[dict[str, str]] = Field(default_factory=list)


def _run_dir(run_id: str) -> Path:
    """只认 data_dir 下的直接子目录，避免路径穿越。"""
    if not run_id or "/" in run_id or ".." in run_id:
        raise PlatformError(400, "BAD_RUN_ID", f"运行 id 不合法：{run_id!r}")
    return Path(settings.data_dir) / run_id


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _facts(run_id: Optional[str]) -> tuple[str, dict[str, Any]]:
    """把一次运行的事实源压成一段文本；没有运行时给空事实源（聊天仍可用）。"""
    if not run_id:
        return "（用户还没有提交任何论文，事实源为空。）", {"runId": None, "hasDigest": False, "artifacts": 0}

    d = _run_dir(run_id)
    run = _read_json(d / "run.json") or {}
    digest = _read_json(d / "understand" / "digest.json") or {}

    lines: list[str] = []
    src = run.get("source") or {}
    title = run.get("title") or src.get("title") or "（未命名论文）"
    lines.append(f"论文：{title}")
    if src.get("authors"):
        lines.append("作者：" + "、".join(str(a) for a in src["authors"][:6]))
    if src.get("value"):
        lines.append(f"来源：{src.get('kind', '?')} / {src['value']}")

    stages = run.get("stages") or []
    state = "；".join(
        f"{(s.get('label') or s.get('id'))}={ {'pending': '未开始', 'running': '进行中', 'waiting': '等待用户确认', 'done': '已完成', 'failed': '失败', 'skipped': '跳过' }.get(s.get('status'), s.get('status')) }"
        for s in stages
    )
    if state:
        lines.append("六个环节的当前状态：" + state)

    arts: list[str] = []
    for s in stages:
        names = [str(a.get("label") or a.get("path") or "") for a in (s.get("artifacts") or [])]
        names = [n for n in names if n]
        if names:
            arts.append(f"{s.get('label') or s.get('id')}：" + "、".join(names[:6]))
    if arts:
        lines.append("已经产出的文件：" + "；".join(arts))

    if digest:
        if digest.get("title"):
            lines.append(f"（digest）标题：{digest['title']}")
        if digest.get("abstractCn"):
            lines.append("中文摘要：" + str(digest["abstractCn"]))
        if digest.get("contributions"):
            lines.append("主要贡献：" + "；".join(str(c) for c in digest["contributions"][:6]))
        if digest.get("method"):
            lines.append("方法：" + str(digest["method"]))
        results = digest.get("results") or []
        if results:
            lines.append(
                "结果：" + "；".join(f"{r.get('label')}={r.get('value')}（{r.get('note') or ''}）" for r in results[:8])
            )
        if digest.get("limitations"):
            lines.append("局限：" + "；".join(str(x) for x in digest["limitations"][:6]))
        if digest.get("figures"):
            lines.append("图：" + "；".join(str(f.get("caption") or f.get("id")) for f in digest["figures"][:8]))

    text = "\n".join(lines) if lines else "（这次运行还没有可读的事实源。）"
    if len(text) > MAX_CTX_CHARS:
        text = text[:MAX_CTX_CHARS] + "\n…（事实源过长，已截断）"
    return text, {"runId": run_id, "hasDigest": bool(digest), "artifacts": sum(len(s.get("artifacts") or []) for s in stages)}


@router.post("")
async def chat(req: ChatRequest) -> dict[str, Any]:
    """一问一答：带上当前运行的事实源，交给配置好的模型回答。"""
    client = LLMClient(settings)
    if not client.available:
        raise PlatformError(400, "LLM_NOT_CONFIGURED", "还没有配置模型（LLM_API_KEY / LLM_BASE_URL），先去「设置 → 模型与 API」填上")

    facts, meta = _facts(req.runId)

    turns = [f"{'用户' if m.get('role') != 'assistant' else '助手'}：{str(m.get('content') or '')[:500]}"
             for m in (req.history or [])[-MAX_HISTORY_TURNS * 2 :]]
    user = "【事实源】\n" + facts
    if turns:
        user += "\n\n【刚才的对话】\n" + "\n".join(turns)
    user += "\n\n【用户现在问】\n" + req.message

    try:
        reply = await client.chat(SYSTEM, user, temperature=0.4, retries=1)
    except LLMError as e:
        raise PlatformError(502, e.code, f"模型调用失败：{e}") from e

    return {"reply": reply.strip(), "model": settings.llm_model, "context": meta}
