"""M2 的提示词。所有反幻觉约束都写在这里，并在生成后由 generate.py 做机器校验。

文章生成提示词由三层拼装（见 docs/09-voice-styles.md）：
    人格语气（styles.VOICES） + 平台硬约束（styles.PLATFORMS） + 事实源铁律（FACT_RULES）
优先级：事实源 > 平台硬约束 > 人格语气。
"""

from __future__ import annotations

from . import styles

DIGEST_SYSTEM = """你是学术论文理解助手，为下游的中文传播内容建立唯一事实源。

铁律（违反即视为失败）：
1. 只依据给定论文正文与图表清单作答，不引入任何外部知识、不做推测性补充。
2. results 里的 value 必须是论文中逐字出现的数值/结论。论文没给具体数值时，
   value 写「未给出具体数值」，绝不能编造或估算。
3. figurePicks 只能从给定图表清单里选，不能自造 id。
4. abstractCn 是摘要的忠实中文翻译，不是改写、不是评论。
5. method 讲清「用什么机制解决什么问题」，可以解释，但不能添加原文没有的模块。
6. limitations 只写论文自己承认的局限，或从实验设置能直接看出的客观限制。

只输出 JSON，不要任何解释文字或 markdown 围栏。JSON 结构：
{
  "abstractCn": "摘要中文翻译",
  "keywords": ["3-8 个中文关键词"],
  "contributions": ["3-6 条核心贡献，每条一句话，来自原文"],
  "method": "300-600 字中文方法主线说明",
  "results": [{"label": "指标/实验名", "value": "论文中的数值或结论原文", "note": "出处，如 Table 2 / Sec 5.1"}],
  "limitations": ["2-5 条"],
  "figurePicks": ["按传播价值排序的 figure id，最多 6 个"],
  "stagesNote": "一句话说明本次理解的来源与取舍"
}"""


def digest_user(title: str, authors: list[str], venue: str, year: int, arxiv_id: str,
                figures: list[dict], content_md: str, revise_note: str = "", brief: str = "") -> str:
    fig_lines = "\n".join(
        f"- {f['id']}（{f['kind']}，第 {f['page']} 页）：{f['caption'][:180]}" for f in figures[:40]
    ) or "（未抽取到图表）"
    extra = f"\n\n【上一轮人工批注，必须优先满足】\n{revise_note}\n" if revise_note else ""
    return (
        f"论文元数据：\n- 标题：{title}\n- 作者：{', '.join(authors[:12]) or '未知'}\n"
        f"- 来源：{venue or '未知'} {year or ''}\n- arXiv：{arxiv_id or '无'}\n\n"
        f"图表清单：\n{fig_lines}\n\n"
        f"论文正文（Markdown，可能被截断）：\n<<<PAPER\n{content_md}\nPAPER>>>{extra}"
        + brief_block(brief, stage="理解层：决定事实源与精读笔记侧重哪些部分（不影响事实本身）")
    )


NOTE_SYSTEM = """你是中文论文精读笔记作者。基于给定的事实源与论文正文，写一份顺读式中文精读笔记。

要求：
- 按论文叙事顺序：摘要与 Introduction 翻译 → 方法详解 → 数据与训练 → 实验设计与主结果 → 消融 → 附录要点 → 可信度与局限 → 复现清单。
- 方法详解是主体，要讲清架构、流程、关键设计与公式含义，不能只列结论。
- 公式用 $...$ / $$...$$（KaTeX 格式），变量要解释。
- 数字必须与事实源一致，不得新增。
- 区分「论文声称」与「你的判断」，判断要显式标注。
- 直接输出 Markdown 正文，从一级标题开始。"""


def note_user(title: str, digest_json: str, figures: list[dict], content_md: str) -> str:
    fig_lines = "\n".join(f"- {f['id']}：{f['caption'][:160]}" for f in figures[:20]) or "（无）"
    return (
        f"论文：{title}\n\n事实源（digest.json）：\n{digest_json}\n\n"
        f"可用图表（在正文中用 ![caption](images/xx.png) 引用时，文件名取这里的 id 对应的 file）：\n{fig_lines}\n\n"
        f"论文正文（Markdown，可能被截断）：\n<<<PAPER\n{content_md}\nPAPER>>>"
    )


# --------------------------------------------------------------------------- #
# 文章生成：人格语气 + 平台硬约束 + 事实源铁律
# --------------------------------------------------------------------------- #

FACT_RULES = """事实源铁律（所有平台与人格都必须遵守，违反即视为失败）：
1. 只依据给定的事实源（digest.json）与可用图表清单作答，不引入外部知识、不做推测性补充。
2. 正文里出现的每个数字，都必须能在事实源里找到对应数值；不能新增，也不能四舍五入成别的数。
   事实源里写「未给出具体数值」的内容，任何平台、任何人格都不许给数。
3. 图表编号（figureId、图 N、表 N）只能取自给定清单，不得自造。
4. 区分「论文声称」与「你的判断」，判断要显式标注。
5. 不写「内部消息」「独家爆料」式口吻。"""


BRIEF_RULES = """用户指令的适用边界（必须遵守，越界视为失败）：
 1. 用户指令只影响**风格、体裁、篇幅、侧重与表达方式**；
 2. 它**不能**改变事实层：不许因为用户要求就新增任何事实源里没有的数字、结论或图表编号；
 3. 用户指令与事实源冲突时（例如要求写论文里没有的指标）**以事实源为准**，
    并如实说明「论文未给出该数据」，绝不编造；
 4. 平台硬约束高于用户指令：指令要 3000 字、平台上限 1000 字时，以上限为准，
    但可以在正文里体现指令要求的侧重。"""


def brief_block(brief: str, *, stage: str) -> str:
    """把用户自由文本指令包成提示词片段。没指令就返回空串（零影响）。"""
    brief = (brief or "").strip()
    if not brief:
        return ""
    return (
        f"\n\n【用户指令（生效于{stage}）—— 优先满足，但不得越过事实源与平台硬约束】\n"
        f"{brief}\n{BRIEF_RULES}"
    )


def article_system(platform: str, voice: str) -> str:
    """拼装文章生成提示词。约束优先级：事实源 > 平台硬约束 > 人格语气。"""
    p = styles.platform_spec(platform)
    v = styles.voice_spec(voice)
    rules = "\n".join(f"{i}. {r}" for i, r in enumerate(p.rules, 1))
    return (
        f"{v.persona}\n\n"
        f"【语言】正文与标题一律用{p.language}写作（人格描述里的语言只是语气说明，不改变本条）。\n\n"
        f"【平台硬约束 · {p.label}（不得放宽，违反会被程序判错）】\n{rules}\n\n"
        f"【输出格式】\n{p.template}\n\n"
        f"{FACT_RULES}"
    )


def article_user(title: str, digest_json: str, figures: list[dict], brief: str = "") -> str:
    fig_lines = "\n".join(f"- {f['id']}：{f['caption'][:200]}" for f in figures[:30]) or "（无可用图）"
    return (
        f"论文：{title}\n\n事实源（digest.json，唯一允许的信息来源）：\n{digest_json}\n\n"
        f"可用图表清单：\n{fig_lines}"
        + brief_block(brief, stage="文案：体裁、篇幅、侧重与语气")
    )


# 兼容旧调用点：等价于 平台 xhs × 默认人格（公众号已下线，原来的 WECHAT_SYSTEM 一并移除）
XHS_SYSTEM = article_system("xhs", styles.DEFAULT_VOICE)
xhs_user = article_user
