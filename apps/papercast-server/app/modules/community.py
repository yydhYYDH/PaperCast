"""社区运营：选社区 + 每个社区一版投放文案 + 互动口径 +（有真实投递时的）数据复盘。

对应总纲里的「社区运营 Agent」。**挂载在 publish 阶段尾部**（该阶段的名字本来就是「发布与运营」），
不新增 stage —— 前端 6 个 stage 的位置是契约，凭空多一个阶段前端会渲染不出来。

三条与其它模块一致的原则：
1. 论文事实只认 digest（understand 的产物），不重新理解论文；
2. 文案里的数字必须在事实源里能检索到，检索不到就如实标出来，不编；
3. 数据复盘只认真实回执（var/runs + var/artifacts 里的投递记录）与通道服务的只读接口，
   取不到就说取不到（ops.metrics 会把 source 一起带回来）。

只读依赖：app/ops.py（跨模块复用它读渠道数据，不自己发网络请求）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .. import ops as ops_mod, prompts as prompts_mod

PLAN_SYSTEM = """你是学术传播的社区运营编辑。给你一篇论文的事实源（digest）和已经写好的投放素材，
你要给出**社区投放计划**：选哪些社区、每个社区说什么、怎么说、发完怎么互动。

硬约束：
1. 只使用 digest 与素材里出现过的事实和数字。**一个数字都不许编**，也不要换算量纲。
2. 每个社区的文案要**按该社区自己的规矩改写**：Reddit/Hacker News 讨厌硬广、X 单帖 280 字符、
   知乎要结论前置、小红书要短句加话题标签 —— 不要把同一段话复制到所有社区。
3. 每条草稿都要能直接复制粘贴发布（不要写占位符式的空话，除链接用 [link]）。
4. 区分「论文声称」与「我的判断」，判断要显式标注。
5. 不要写「独家爆料」「内部消息」这类口吻。

只输出 JSON：
{
  "communities": [
    {
      "name": "Reddit r/MachineLearning",
      "kind": "学术社区 | 垂直社区 | 社交平台 | 中文社区",
      "language": "en | zh",
      "audience": "这个社区里是谁在看",
      "angle": "针对这群人，这篇论文的哪个点最值得讲（一句话）",
      "draftTitle": "标题（按该社区习惯，HN 不用感叹号，知乎要结论前置）",
      "draftBody": "可直接发布的正文（该社区的篇幅与口吻；X/LinkedIn 就是一条条编号帖）",
      "rules": "该社区必须遵守的规矩（自己写清楚，比如不直接贴链接、要放 TL;DR）",
      "bestTime": "建议投放时间",
      "risk": "可能被踩/被删的原因与规避方式"
    }
  ],
  "interaction": {
    "replyStrategy": ["发出去后 2 小时内要盯的评论类型与回复口径"],
    "watchMetrics": ["该盯哪些指标，以及什么数值算异常"],
    "escalation": "什么情况下要停下来改文案/撤稿"
  }
}

给 4-6 个社区，必须覆盖：至少 1 个学术社区、至少 2 个不同语言的社区（中英各至少 1）、
至少 1 个「帖子型」社交平台（X 或 LinkedIn）。"""

PLAN_USER = """论文：{title}
来源：{venue} {year}

【事实源 digest】
{digest}

【已备好的素材（标题 / 正文节选 / 标签 / 图与视频）】
{材料}

【渠道账号现状（只有这些渠道我们能直接投）】
{channels}

【正文原文（数字回溯以它为准）】
{content}
"""

NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _plan_facts(plan: dict[str, Any]) -> str:
    """把计划里所有会被发布的文字拼起来，用于数字回溯。"""
    parts: list[str] = []
    for c in plan.get("communities") or []:
        for k in ("name", "audience", "angle", "draftTitle", "draftBody", "rules", "bestTime", "risk"):
            parts.append(str(c.get(k) or ""))
    it = plan.get("interaction") or {}
    parts.extend(str(x) for x in (it.get("replyStrategy") or []))
    parts.extend(str(x) for x in (it.get("watchMetrics") or []))
    parts.append(str(it.get("escalation") or ""))
    return "\n".join(parts)


def render_markdown(plan: dict[str, Any], *, title: str, stats: dict[str, Any]) -> str:
    """确定性拼装人读版本（与卡片/海报一致：模型只出 JSON，排版由程序拼）。"""
    L = [f"# 社区投放计划 · {title}", ""]
    L.append(f"共 {len(plan.get('communities') or [])} 个社区。以下文案由模型按各社区规矩改写，数字均已回溯校验。")
    L.append("")
    for i, c in enumerate(plan.get("communities") or [], 1):
        L += [
            f"## {i}. {c.get('name', '')}（{c.get('kind', '')} · {c.get('language', '')}）",
            "",
            f"- **给谁看**：{c.get('audience', '')}",
            f"- **切入角度**：{c.get('angle', '')}",
            f"- **建议时间**：{c.get('bestTime', '')}",
            f"- **社区规矩**：{c.get('rules', '')}",
            f"- **风险与规避**：{c.get('risk', '')}",
            "",
            f"**标题**：{c.get('draftTitle', '')}",
            "",
            "**正文**：",
            "",
            str(c.get("draftBody") or "").strip(),
            "",
            "---",
            "",
        ]
    it = plan.get("interaction") or {}
    L += ["## 互动与复盘", "", "**发出去之后怎么回**："]
    L += [f"- {x}" for x in (it.get("replyStrategy") or [])] or ["- （模型未给出）"]
    L += ["", "**盯哪些指标**："]
    L += [f"- {x}" for x in (it.get("watchMetrics") or [])] or ["- （模型未给出）"]
    L += ["", f"**止损条件**：{it.get('escalation', '（模型未给出）')}", ""]
    L += ["## 已发布数据（真实回执，取不到就说取不到）", ""]
    if stats.get("available"):
        L += [f"- {k}：{v}" for k, v in (stats.get("lines") or {}).items()]
        L.append(f"- 数据来源：{stats.get('source', '')}")
    else:
        L.append(f"- 本项目前没有可读回的真实投递数据：{stats.get('reason', '未投递或通道未在线')}")
    L.append("")
    return "\n".join(L)


async def _stats_snapshot(ctx) -> dict[str, Any]:
    """读真实投递数据做复盘。只走 ops.py 的只读接口，取不到就如实说。"""
    try:
        data = await ops_mod.metrics()
    except Exception as e:  # 通道没在线 / 网络不通都不该让运营计划失败
        return {"available": False, "reason": f"{type(e).__name__}: {str(e)[:120]}"}
    items = []
    if isinstance(data, dict):
        for key in ("items", "published", "runs"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
    if not items:
        return {"available": False, "reason": "渠道接口没有返回任何已投递条目（可能还没投过东西）"}
    lines: dict[str, Any] = {}
    for it in items[:6]:
        if not isinstance(it, dict):
            continue
        name = it.get("title") or it.get("name") or it.get("channel") or "未命名"
        bits = [f"{k}={it[k]}" for k in ("views", "likes", "coins", "favorites", "comments", "danmaku", "votes") if it.get(k) is not None]
        lines[str(name)[:40]] = "，".join(bits) or "接口没给数字"
    return {"available": bool(lines), "lines": lines, "source": "ops.metrics（B 站公开接口 / 知乎通道 / 小红书 MCP）"}


async def run_community(ctx, materials: Any, receipts: dict[str, Any], published: list[str]) -> dict[str, Any]:
    """在 publish 阶段尾部生成社区投放计划，并登记产物与检查项。"""
    run_dir = ctx.store.dir(ctx.run.id)
    digest_path = run_dir / "understand" / "digest.json"
    if not digest_path.is_file():
        raise RuntimeError("缺少 understand/digest.json，社区计划只认既有事实源")
    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    content = ""
    intake_md = run_dir / "intake" / "content.md"
    if intake_md.is_file():
        content = intake_md.read_text(encoding="utf-8")

    ready = [c for c in (receipts or {})]
    channels = "\n".join(
        f"- {cid}：{receipts[cid].get('channelName', cid)}（{receipts[cid].get('status', '未知状态')}）"
        for cid in ready
    ) or "（本轮没有任何渠道进入投递流程）"
    if published:
        channels += "\n已真实投递：" + "、".join(published)

    材料 = (
        f"标题：{materials.title}\n"
        f"正文节选：\n{materials.body[:3000]}\n\n"
        f"标签：{'、'.join(materials.tags)}\n"
        f"图 {len(materials.images)} 张；视频：{materials.video.name if materials.video else '无'}"
    )

    ctx.log("info", "社区运营：生成社区投放计划（选社区 + 每社区一版文案）…")
    user = PLAN_USER.format(
        title=digest.get("title") or ctx.run.title,
        venue=digest.get("venue") or "",
        year=digest.get("year") or "",
        digest=json.dumps(digest, ensure_ascii=False, indent=1)[:12000],
        材料=材料,
        channels=channels,
        content=content[:40000],
    ) + prompts_mod.brief_block(
        (getattr(getattr(ctx.run, "config", None), "brief", "") or "").strip(),
        stage="社区运营：社区选择偏好与文案风格",
    )
    # 6 个社区 × 完整成稿文案是很长的 JSON，一次 10k token 会被截断成非法 JSON
    # （2026-09-19 实测：输出停在 "kind": "中文社区"，整段解析失败）。
    # 所以第一次给足预算，第二次**主动缩小体量**（3 个社区 + 短文案），而不是同样再要一遍。
    plan: dict[str, Any] | None = None
    last_err = ""
    for attempt, budget in enumerate((16000, 12000)):
        ask = user if attempt == 0 else (
            user
            + "\n\n上一次输出被截断了。这次只给 **3 个社区**，每个 draftBody 不超过 300 字，"
            + "interaction 只写 1 条 replyStrategy、1 条 watchMetrics、1 句 escalation；"
            + "务必输出完整且合法的 JSON（不要省略尾部括号）。"
        )
        try:
            raw = await ctx.llm.chat_json(PLAN_SYSTEM, ask, max_tokens=budget)
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:140]}"
            ctx.log("warn", f"社区计划第 {attempt + 1} 次生成失败（max_tokens={budget}）：{last_err}")
            continue
        if isinstance(raw, dict) and raw.get("communities"):
            plan = raw
            if attempt:
                ctx.log("warn", "缩小体量后生成了社区计划（社区数少于 6 个属预期）")
            break
        last_err = "模型没有给出任何社区（communities 为空）"
    if plan is None:
        raise RuntimeError(f"两次都没能生成合法的社区计划：{last_err}")

    # 数字回溯：与 M2 同一套口径 —— 回溯不了就如实标出来，不删也不假装没问题
    flat = re.sub(r"[\s,，]", "", json.dumps(digest, ensure_ascii=False) + content)
    bad: list[str] = []
    for c in plan["communities"]:
        for field in ("draftTitle", "draftBody", "angle"):
            for n in NUM_RE.findall(str(c.get(field) or "")):
                if n not in flat and n not in bad:
                    bad.append(n)

    stats = await _stats_snapshot(ctx)
    (ctx.work / "community.plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    (ctx.work / "community.md").write_text(
        render_markdown(plan, title=digest.get("title") or ctx.run.title, stats=stats), encoding="utf-8")

    comms = plan["communities"]
    langs = {str(c.get("language") or "").strip().lower() for c in comms}
    kinds = " ".join(str(c.get("kind") or "") for c in comms)
    drafts = [str(c.get("draftBody") or "").strip() for c in comms]
    misses = [str(c.get("name") or "?") for c, d in zip(comms, drafts) if len(d) < 60]
    no_rules = [str(c.get("name") or "?") for c in comms if not str(c.get("rules") or "").strip()]

    ctx.check("社区覆盖", "pass" if len(comms) >= 4 and "en" in langs and "zh" in langs else "fail",
              f"{len(comms)} 个社区（语言 {'/'.join(sorted(x for x in langs if x))}）；是否含学术社区：{'学术社区' in kinds}")
    ctx.check("草稿可用", "pass" if not misses else "fail",
              f"{len(drafts)} 份草稿都可直接发布" if not misses else "草稿过短，需补写：" + "、".join(misses[:3]))
    ctx.check("社区规矩", "pass" if not no_rules else "fail",
              "每个社区都写清了该社区的投放规矩" if not no_rules else "没写规矩：" + "、".join(no_rules[:3]))
    ctx.check("数字可回溯", "pass" if not bad else "run",
              "社区文案里的数字都能在事实源里找到" if not bad else f"有 {len(bad)} 个数字未能回溯（{bad[:4]}），发布前人工看一眼")
    ctx.check("投递数据复盘", "pass" if stats.get("available") else "run",
              f"读到 {len(stats.get('lines') or {})} 条真实投递数据（{stats.get('source', '')}）"
              if stats.get("available") else f"暂无可读回数据：{stats.get('reason', '')}")

    ctx.artifact("markdown", "社区投放计划（含每个社区的成稿文案）", "community.md", preview=True,
                 meta={"communities": len(comms)})
    ctx.artifact("json", "社区投放计划（结构化）", "community.plan.json", preview=False)
    ctx.log("ok", f"社区运营完成：{len(comms)} 个社区 / {sum(len(d) for d in drafts)} 字成稿文案")
    return plan
