"""对话入口：POST /api/chat —— 用一句话问「这篇论文讲了什么 / 接下来做什么」。

设计约定（改之前先读）：

1. **事实源唯一**：回答只依据该运行已经落盘的 `run.json`、`understand/digest.json` 与产物清单，
   不联网、不臆测；事实源里没有的信息直接说没有，与其它模块的反幻觉口径一致。
2. **没配模型就明说**：没有 LLM 凭据时返回 400 `LLM_NOT_CONFIGURED`，前端据此提示去「设置」，
   不假装能聊。
3. **服务端不存会话**：多轮由前端把最近几轮一起传上来（`history`），后端只做一次补全 ——
   免得又多一份需要清理的状态。
4. 分工：本文件只负责「取上下文 + 组装提示词」，调用、重试、超时都在 `app/llm.py` 的 `LLMClient` 里。
5. **动作提案**（2026-09-19 新增，用户要求「可用对话的形式来发布任务」）：一句话除了回答，还可以
   变成一张**动作卡**（返回体里的 `action`），前端的对话里渲染成「一句话 + 一个动词按钮」，
   点了才真的执行。规则见下方「意图 → 动作提案」一节：**规则优先、模型兜底**，且**服务端零副作用**
   —— 这个端点永远只产出「打算做什么 + 参数」，不投递、不起停进程、不改任何东西。

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
from .models import GateOption, PaperRun, Stage, StageGate
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



# ---------- 意图 → 动作提案（「用对话发任务」的落点，2026-09-19） ----------
#
# 设计取舍（改之前先读）：
# 1. **规则优先、模型兜底**。能认出来的意图直接由代码给出一张动作卡：不花模型的钱、不受模型
#    当时状态影响 —— 没配模型时「重跑一遍 / 放行 / 看数据 / 重启服务」这些照样发得出去。
#    认不出来才落到下面的自由问答（那才是需要模型的地方）。
# 2. **服务端零副作用**。这里只产出「打算做什么 + 参数」，执行全在前端、由用户点那张卡触发。
#    所以这个端点永远不会因为一句话就投递、就停进程 —— 人工闸门不在这里被绕过。
# 3. 每个动作都带 risk：readonly（只读，前端可直接执行）/ local（动本机，要确认）/
#    public（真发到平台上，要确认）。
# 4. 文案口径与前端一致：说人话、不端后端术语、读不到就写读不到。

SERVICE_ALIASES: dict[str, tuple[str, ...]] = {
    "backend": ("后端", "backend"),
    "frontend": ("前端", "网页", "界面"),
    "mcp": ("小红书", "mcp", "xhs"),
    "zhihu": ("知乎", "zhihu"),
    "bilibili": ("b站", "b 站", "bilibili", "哔哩"),
}
SERVICE_LABEL = {
    "backend": "后端",
    "frontend": "前端界面",
    "mcp": "小红书通道",
    "zhihu": "知乎通道",
    "bilibili": "B 站通道",
}

STOP_WORDS = ("重启", "重新启动", "重起", "停掉", "停止", "关掉", "关一下", "别跑了")
START_WORDS = ("启动", "拉起", "起一下", "开起来")
GATE_WORDS = ("放行", "通过", "继续", "确认", "发布", "投递", "发出去", "草稿", "跳过", "不发布")
RERUN_WORDS = ("重跑", "重新跑", "再跑", "重来", "再来一遍", "重做", "重新做", "再走一遍")
METRIC_WORDS = ("数据", "效果", "表现", "多少", "几个", "播放", "点赞", "投币", "收藏",
                "浏览", "涨了", "互动数", "阅读量")
INTERACT_WORDS = ("评论", "回复", "通知", "私信", "回一下", "互动")


def _hit(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def _live_run(run_id: Optional[str]) -> Optional[PaperRun]:
    """取这次运行 —— **用界面看到的那一份**（后端内存 store 是唯一事实源）。

    为什么不直接读 run.json：盘上那份可能落后于内存（2026-09-19 实测遇到「盘上写着 failed、
    界面还停在等待放行」的漂移）。闸门这种动作必须对着界面所见的状态提，否则会递出一张
    早已不成立的卡片。延迟导入 main 只为避开与 main.py 模块级 include_router 的循环 ——
    真正执行发生在请求期，那时 main 早就装载完了。
    """
    if not run_id:
        return None
    try:
        from .main import store  # noqa: PLC0415

        run = store.get(run_id)
        if run is not None:
            return run
    except Exception:
        pass
    try:  # 兜底：store 不可用时退到盘上那份（只影响「有没有卡片」，不影响安全）
        data = _read_json(_run_dir(run_id) / "run.json")
        return PaperRun.model_validate(data) if isinstance(data, dict) else None
    except Exception:
        return None


def _meta(run_id: Optional[str], run: Optional[PaperRun]) -> dict[str, Any]:
    """给前端的轻量上下文（与模型那条路的 context 同形状）。"""
    stages = list(run.stages) if run else []
    return {
        "runId": run_id,
        "hasDigest": any(str(a.path or "").endswith("digest.json") for s in stages for a in s.artifacts),
        "artifacts": sum(len(s.artifacts) for s in stages),
    }


def _pending_gate(run: Optional[PaperRun]) -> Optional[Stage]:
    """这次运行里正在等用户点头的那一段（没有就 None）。"""
    for s in (run.stages if run else []):
        if s.status == "waiting" and s.gate and not s.gate.resolved:
            return s
    return None


def _choose_option(gate: StageGate, text: str) -> Optional[GateOption]:
    """把一句话对上闸门的某个选项：说草稿就草稿、说跳过就跳过，其余**默认第一个**（推荐项）。"""
    opts = list(gate.options or [])
    if not opts:
        return None
    want = None
    if _hit(text, ("草稿", "先别发", "不要发", "不真发", "只存")):
        want = "draft"
    elif _hit(text, ("跳过", "不发布", "不发", "算了", "别发")):
        want = "skip"
    if want:
        for o in opts:
            if o.id == want:
                return o
    return opts[0]


def _propose(text: str, run_id: Optional[str], run: Optional[PaperRun]) -> Optional[tuple[str, Optional[dict[str, Any]]]]:
    """一句话 →（要说的话, 动作）。认不出来返回 None，交给模型自由问答。

    返回动作时 **不调用模型**：这些话都是「我打算做什么」，由代码说最准，也不该被模型改写。
    """
    t = text.strip()
    if not t or len(t) > 300:
        return None

    # 1) 起停本机服务 —— 唯一直接动进程的动作，永远要确认；停/重启会中断在跑的运行
    if _hit(t, STOP_WORDS + START_WORDS):
        name = next((k for k, al in SERVICE_ALIASES.items() if _hit(t, al)), None)
        if name:
            if _hit(t, STOP_WORDS) and not _hit(t, ("重启", "重新启动", "重起")):
                action = "stop"
            elif _hit(t, ("重启", "重新启动", "重起")):
                action = "restart"
            else:
                action = "start"
            verb = {"start": "启动", "stop": "停掉", "restart": "重启"}[action]
            tail = "。这会同时断掉那段通道的登录与投递能力，所以必须你点头才做。" if action != "start" \
                else "。"
            return (
                f"{SERVICE_LABEL[name]}{verb}：走 ops/ 里的启停脚本真做一次{tail}",
                {
                    "kind": "service",
                    "title": f"要{verb}{SERVICE_LABEL[name]}吗？",
                    "detail": f"服务名 {name}，动作 {action}；用的是后端白名单接口，起停脚本来自 ops/。",
                    "params": {"name": name, "action": action},
                    "needsConfirm": True,
                    "confirmLabel": verb,
                    "risk": "local",
                },
            )

    # 2) 人工闸门：本地确实有在等放行的那一段，才给动作卡
    stage = _pending_gate(run)
    if stage and stage.gate and _hit(t, GATE_WORDS):
        gate = stage.gate
        opt = _choose_option(gate, t)
        if opt is not None:
            public = str(stage.id) == "publish" and opt.id == "continue"
            title = ("真的发出去吗？投递到平台之后撤回不了，我只会照上面的计划发一次。"
                     if public
                     else f"「{gate.label or stage.label}」按「{opt.label}」办吗？")
            return (
                (f"这一次选「{opt.label}」。真投递必须你点头，我不会自己发。") if public
                else (f"这一步在等你决定：「{gate.label or stage.label}」→「{opt.label}」。"),
                {
                    "kind": "gate",
                    "title": title,
                    "detail": str(gate.detail or "")[:900],
                    "params": {
                        "runId": run_id,
                        "stageId": str(stage.id),
                        "optionId": opt.id,
                        "optionLabel": opt.label,
                    },
                    "needsConfirm": True,
                    "confirmLabel": str(opt.label or "确认"),
                    "risk": "public" if public else "local",
                },
            )

    # 3) 把这次的论文原样再跑一遍
    if _hit(t, RERUN_WORDS):
        src = run.source if run else None
        if src and src.value:
            title = str(run.title or src.title or src.value)  # type: ignore[union-attr]
            return (
                f"把《{title}》原样再跑一遍。前一次有产物的话我不动它，新的一遍会另开一条记录。",
                {
                    "kind": "run",
                    "title": f"重跑《{title[:40]}》吗？",
                    "detail": "六段会从头再走一遍（十几分钟），中间仍然会在该你确认的地方停下来。",
                    "params": {"kind": str(src.kind), "value": src.value, "title": title},
                    "needsConfirm": True,
                    "confirmLabel": "重跑一遍",
                    "risk": "local",
                },
            )
        return ("要重跑得先有一篇论文：把链接粘进来，或者拖一份 PDF 进来说一句都行。", None)

    # 4) 运营数据（只读 → 不需要确认，前端直接取）
    if _hit(t, METRIC_WORDS):
        return (
            "我去各平台取一遍真实数字：B 站读公开接口，知乎要走已登录的浏览器，小红书那个每次都会真开一次浏览器 —— "
            "它慢，而且账号还在恢复期，我不会反复去撞它。取不到的我照实说，不会拿 0 顶替。",
            {
                "kind": "metrics",
                "title": "取一次运营数据",
                "detail": "只读各平台，不改任何东西。",
                # force=False：走后端 60s 缓存。force 一次就是**每个平台真探测一次**（小红书那条要真开浏览器），
                # 账号恢复期不做这种主动撞击，用户想看新数据时界面上还有「更新」可点。
                "params": {"force": False},
                "needsConfirm": False,
                "confirmLabel": "取一次",
                "risk": "readonly",
            },
        )

    # 5) 互动（评论/回复/通知）—— 本轮只做到「看得懂能发什么任务」，读与起草还在下一轮
    if _hit(t, INTERACT_WORDS):
        return (
            "看评论、起草回复这件事还没接上：本机的小红书通道其实有读评论和回复的工具，但后端故意没暴露，"
            "而且账号正在风控恢复期，我不会在这时候去撞它。已经排在下一步（只读评论 + 起草回复，不发送），"
            "今天先把「用对话发任务」做实。",
            None,
        )

    return None

@router.post("")
async def chat(req: ChatRequest) -> dict[str, Any]:
    """一问一答。认得出意图 → 给一张动作卡（不花模型）；认不出 → 带上事实源交给模型。"""
    run = _live_run(req.runId)
    proposed = _propose(req.message, req.runId, run)
    if proposed is not None:
        reply, action = proposed
        return {"reply": reply, "model": "rules", "context": _meta(req.runId, run), "action": action}

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

    return {"reply": reply.strip(), "model": settings.llm_model, "context": meta, "action": None}
