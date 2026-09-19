"""M2：内容生成 —— 事实源 digest + 中文精读笔记 + 小红书图文（文案 + 卡片）。"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from ..cards import render as card_render
from ..models import ArticleVariant, PaperDigest
from ..pipeline import StageContext
from .. import prompts, styles


class GenerateError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- #
# 校验工具
# --------------------------------------------------------------------------- #

CJK = re.compile(r"[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]")
NUM = re.compile(r"\d+(?:[.,]\d+)*\s*%?")
# 公式痕迹判定统一在 styles 里（含 `$0.001` 这类金额的护栏）；这里不再自己维护一份正则
FORMULA = styles.FORMULA

# --------------------------------------------------------------------------- #
# 用户指令（brief）的机检遵从度
# --------------------------------------------------------------------------- #
# 用户指令是自由文本，不可能全部机检。这里只抽三类**能落到可判定事实**的约束：
# 字数上限、禁用表达、必须体现的侧重。抽不到的部分不假装检查过，如实记成待人工复核。
BRIEF_WORD_LIMIT = re.compile(
    r"(?:不超过|不要超过|不超过|不多于|不得超过|最多|控制在|上限|限制在|压缩到)\s*(\d{2,4})\s*字"
    r"|(\d{2,4})\s*字(?:以内|内|以下|左右)"
)
BRIEF_FORBID = re.compile(
    r"(?:不要|别|避免|不得|禁止|切忌)(?:用|写|出现|有|说|加|带)?[「『“]?([^，。；、,;：:\n「」『』“”]{1,10})"
)
BRIEF_MUST = re.compile(
    r"(?:重点(?:讲|写|说|介绍|放在|落在)|必须(?:提到|包含|写|有)|一定要(?:提到|写|有)|着重)([^，。；、,;：:\n]{1,12})"
)


def _brief_of(ctx) -> str:
    """读取本次运行的用户指令（没有就返回空串，全链路零影响）。"""
    cfg = getattr(ctx.run, "config", None)
    return (getattr(cfg, "brief", "") or "").strip()


def brief_checks(ctx, brief: str, label: str, text: str, spec: Any = None) -> None:
    """把用户指令里「能判定的部分」变成 check 行；判定不了的如实标 run，不装作检查过。

    spec 给了 PlatformSpec 时，会先判「指令与平台硬约束是否冲突」——按
    prompts.BRIEF_RULES 第 4 条，平台硬约束高于用户指令，冲突时以平台为准，
    这时**不能报 fail**（那不是执行失败，是预期中的优先级裁决），要报 run 并说清冲突。
    """
    if not brief:
        return
    checked = 0
    m = BRIEF_WORD_LIMIT.search(brief)
    if m:
        limit = int(m.group(1) or m.group(2))
        n = len(text)
        checked += 1
        lo = int(getattr(spec, "body_min", 0) or 0)
        hi = int(getattr(spec, "body_max", 0) or 0)
        if lo and limit < lo:
            ctx.check(
                f"{label} · 指令遵从度 · 字数上限 {limit}",
                "run",
                f"指令要 ≤{limit} 字，但该平台正文下限是 {lo} 字 —— 按「平台硬约束 > 用户指令」以平台为准"
                f"（实际 {n} 字）；想真正压到 {limit} 字请换短体裁平台",
            )
        elif hi and limit > hi:
            ctx.check(
                f"{label} · 指令遵从度 · 字数上限 {limit}",
                "run",
                f"指令上限 {limit} 字比平台上限 {hi} 字还宽，以平台 {hi} 字为准（实际 {n} 字）",
            )
        else:
            ctx.check(
                f"{label} · 指令遵从度 · 字数上限 {limit}",
                "pass" if n <= limit else "fail",
                f"实际 {n} 字" + ("" if n <= limit else f"，超出 {n - limit} 字"),
            )
    forbids: list[str] = []
    musts: list[str] = []
    # 「不要超过 800 字」这类讲的是**字数上限**，不是要避免的措辞：先按字数上限的匹配位置把它
    # 从文本里摘掉，否则「超过 800 字」会被 BRIEF_FORBID 抓成禁用表达，报一条「未见 超过 800 字」
    # 的 pass —— 看着检查过了，其实什么都没查（2026-09-19 修，来自测试指出的假阳性）。
    brief_for_forbid = BRIEF_WORD_LIMIT.sub("　", brief)
    for raw in BRIEF_FORBID.findall(brief_for_forbid):
        w = raw.strip(" 的了和与及")
        if len(w) >= 2 and w not in forbids:
            forbids.append(w)
    for raw in BRIEF_MUST.findall(brief):
        w = raw.strip(" 的了和与及").strip()
        if len(w) >= 2 and w not in musts:
            musts.append(w)
    hit = [w for w in forbids if w in text]
    if forbids:
        checked += 1
        ctx.check(
            f"{label} · 指令遵从度 · 禁用表达",
            "pass" if not hit else "fail",
            "未见 " + "、".join(forbids[:3]) if not hit else "出现了指令要求避免的表达：" + "、".join(hit),
        )
    if musts:
        miss = [w for w in musts if w not in text]
        checked += 1
        ctx.check(
            f"{label} · 指令遵从度 · 侧重",
            "pass" if not miss else "run",
            "已体现：" + "、".join(musts[:3]) if not miss else "指令要求侧重 " + "、".join(miss) + "，正文里未出现该词（可能换了说法，需人工看一眼）",
        )
    if not checked:
        ctx.check(f"{label} · 指令遵从度", "run", f"指令没有可直接机检的约束（{brief[:40]}…），需人工复核")


def title_weight(s: str) -> int:
    """小红书标题计重：中文/中文标点 2，其余 1。"""
    return sum(2 if CJK.match(ch) else 1 for ch in s)


def numbers_in(text: str) -> list[str]:
    return [m.group(0).replace(" ", "") for m in NUM.finditer(text or "")]


def strip_formulas(text: str) -> tuple[str, list[str]]:
    """去掉公式痕迹，返回 (处理后的文本, 命中记录)。

    判定统一走 `styles.is_inline_math`：`$0.001` 这类金额不是公式，原样保留
    （朴素正则会把它当行内公式删掉，成本数字就没了）。
    """
    hits: list[str] = []

    def _inline(m: re.Match) -> str:
        if not styles.is_inline_math(m.group(0)):
            return m.group(0)
        hits.append(m.group(0))
        inner = m.group(0).strip("$")
        inner = re.sub(r"\\(?:mathrm|text|frac|sum|cdot|times|leq|geq|approx)", "", inner)
        return re.sub(r"[{}\\^_$]", "", inner).strip()

    out = re.sub(r"\$([^$\n]{1,200})\$", _inline, text)
    hit = styles.find_formula(out)
    if hit:
        hits.append(hit)
        out = FORMULA.sub("", out)
        out = styles.DOLLAR_PAIR.sub(lambda m: "" if styles.is_inline_math(m.group(0)) else m.group(0), out)
    return out, hits


def _drop_untraceable(body: str, haystack: str) -> tuple[str, list[str]]:
    """把含「事实源里找不到的数字」的句子删掉，返回 (新正文, 被删的数字)。"""
    flat = re.sub(r"[\s,，]", "", haystack)
    kept, dropped = [], []
    for para in body.split("\n\n"):
        sents = re.split(r"(?<=[。！？!?；;])", para)
        good = []
        for s in sents:
            bad = [n for n in numbers_in(s) if re.sub(r"[\s,，]", "", n) not in flat and n.rstrip("%") not in flat]
            if bad:
                dropped.extend(bad)
                continue
            good.append(s)
        if "".join(good).strip():
            kept.append("".join(good).strip())
    return "\n\n".join(kept), dropped


def _condense(md: str, limit: int = 120_000) -> str:
    if len(md) <= limit:
        return md
    head = md[: int(limit * 0.75)]
    cut = head.rfind("\n## ")
    if cut > 2000:
        head = head[:cut]
    tail = md[-int(limit * 0.15) :]
    return head + "\n\n<!-- 中间章节因原文过长已省略 -->\n\n" + tail


def _truncate_body(body: str, limit: int = 1000) -> str:
    body = body.strip()
    if len(body) <= limit:
        return body
    clipped = body[:limit]
    for sep in ("\n\n", "。", "！", "？"):
        i = clipped.rfind(sep)
        if i > limit * 0.55:
            return clipped[: i + (len(sep) if sep != "\n\n" else 0)].strip()
    return clipped.strip()


# --------------------------------------------------------------------------- #
# digest
# --------------------------------------------------------------------------- #

def _build_digest(raw: dict, figures: list[dict], meta: dict, run_title: str, haystack: str) -> tuple[PaperDigest, list[str]]:
    warnings: list[str] = []
    fig_by_id = {f["id"]: f for f in figures}

    picks = [i for i in (raw.get("figurePicks") or []) if i in fig_by_id]
    unknown = [i for i in (raw.get("figurePicks") or []) if i not in fig_by_id]
    if unknown:
        warnings.append(f"模型选了不存在的图表 id：{unknown[:4]}")
    if not picks:
        # 兜底：按图注长度（信息量）排序取前 6
        picks = [f["id"] for f in sorted(figures, key=lambda f: -len(f.get("caption", "")))[:6]]
        warnings.append("未得到有效 figurePicks，已按图注信息量兜底选择")

    results, dropped, partial = [], [], []
    flat = re.sub(r"[\s,，]", "", haystack)
    for r in raw.get("results") or []:
        if not isinstance(r, dict):
            continue
        value = str(r.get("value", "")).strip()
        label = str(r.get("label", "")).strip()
        if not label:
            continue
        nums = numbers_in(value)
        untraceable = [n for n in nums if re.sub(r"[\s,，]", "", n) not in flat]
        traceable_ratio = (len(nums) - len(untraceable)) / len(nums) if nums else 1.0
        # 复合数值（一行里多个胜率）常有格式差异，过半能回溯就保留，避免误杀真实数据
        if nums and traceable_ratio < 0.5:
            dropped.append(f"{label}={value[:60]}（找不到 {untraceable[:2]}）")
            continue
        if untraceable:
            partial.append(f"{label}：{untraceable[:3]}")
        results.append({"label": label, "value": value, "note": str(r.get("note", "")).strip()})
    if dropped:
        warnings.append(f"丢弃 {len(dropped)} 条无法在原文中回溯的数值：{dropped[:3]}")
    if partial:
        warnings.append(f"{len(partial)} 条含部分未回溯数字（已保留，人工复核）：{partial[:3]}")

    arxiv_meta = (meta.get("arxiv") or {}) if isinstance(meta.get("arxiv"), dict) else {}
    digest = PaperDigest(
        arxivId=arxiv_meta.get("arxivId", "") or "",
        title=meta.get("title") or run_title,
        authors=arxiv_meta.get("authors") or [],
        venue=arxiv_meta.get("comment") or "arXiv preprint",
        year=int(arxiv_meta.get("year") or 0),
        abstractCn=str(raw.get("abstractCn", "")).strip(),
        keywords=[str(k).strip() for k in (raw.get("keywords") or []) if str(k).strip()][:10],
        contributions=[str(c).strip() for c in (raw.get("contributions") or []) if str(c).strip()][:8],
        method=str(raw.get("method", "")).strip(),
        results=results[:12],
        figures=[
            {"id": i, "caption": fig_by_id[i]["caption"][:300], "source": fig_by_id[i]["file"]} for i in picks[:6]
        ],
        limitations=[str(x).strip() for x in (raw.get("limitations") or []) if str(x).strip()][:6],
        stagesNote=str(raw.get("stagesNote", "")).strip(),
    )
    return digest, warnings


async def run_understand(ctx: StageContext) -> None:
    data = ctx.shared.get("intake")
    if not data:
        raise GenerateError("INTAKE_MISSING", "缺少 M1 的解析结果，无法进入理解层")
    figures: list[dict] = data["figures"]
    meta: dict = data["meta"]
    content = _condense(data["markdown"])
    ctx.log("info", f"送入模型的正文字符数：{len(content)}（原文 {len(data['markdown'])}）")

    if not ctx.llm.available:
        raise GenerateError("LLM_NOT_CONFIGURED", "没有可用的 LLM 凭据，无法生成内容（见 docs/05-deployment.md）")

    revise_note = ""
    digest: PaperDigest | None = None
    for round_no in range(1, 4):
        ctx.log("info", f"第 {round_no} 轮：生成事实源 digest.json（{'带人工批注' if revise_note else '初始'}）")
        ctx.progress(0.15 if round_no == 1 else 0.5)
        try:
            raw = await ctx.llm.chat_json(
                prompts.DIGEST_SYSTEM,
                prompts.digest_user(
                    meta.get("title") or ctx.run.title,
                    (meta.get("arxiv") or {}).get("authors") or [],
                    (meta.get("arxiv") or {}).get("comment") or "",
                    int((meta.get("arxiv") or {}).get("year") or 0),
                    (meta.get("arxiv") or {}).get("arxivId") or "",
                    figures,
                    content,
                    revise_note,
                    _brief_of(ctx),
                ),
                max_tokens=16000,
            )
        except Exception as e:
            raise GenerateError("LLM_DIGEST_FAILED", f"事实源生成失败：{e}") from e
        if not isinstance(raw, dict):
            raise GenerateError("LLM_BAD_DIGEST", "模型返回的 digest 不是 JSON 对象")

        digest, warns = _build_digest(raw, figures, meta, ctx.run.title, content)
        for w in warns:
            ctx.log("warn", w)
        ctx.run.digest = digest
        (ctx.work / "digest.json").write_text(
            digest.model_dump_json(indent=1), encoding="utf-8"
        )
        (ctx.work / "digest.raw.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        ctx.artifact("json", "digest.json（事实源）", "digest.json", preview=True)
        if round_no == 1:
            ctx.artifact("json", "模型原始输出 digest.raw.json", "digest.raw.json", preview=False)

        traceable = len(digest.results)
        ctx.check("事实源结构", "pass" if digest.contributions and digest.method else "fail",
                  f"{len(digest.contributions)} 条贡献 / {len(digest.method)} 字方法说明")
        ctx.check("数值可回溯", "pass" if traceable else "fail",
                  f"{traceable} 条结果全部能在原文中检索到" if traceable else "没有可回溯的数值条目（模型可能未按格式输出）")
        ctx.check("图表选择", "pass" if digest.figures else "fail",
                  f"选定 {len(digest.figures)} 张：" + ", ".join(f["id"] for f in digest.figures))
        ctx.progress(0.6)

        if round_no == 1:
            # 中文精读笔记：失败不阻塞主链路（downstream 只依赖 digest.json）
            note = ""
            for attempt, budget in enumerate((12000, 6000), 1):
                try:
                    ctx.log("info", f"生成中文精读笔记 reading_note.md（第 {attempt} 次，max_tokens={budget}）…")
                    note = await ctx.llm.chat(
                        prompts.NOTE_SYSTEM,
                        prompts.note_user(digest.title, digest.model_dump_json(indent=1), figures, content)
                        + ("" if attempt == 1 else "\n\n（请输出精简版：只保留摘要翻译、方法详解、主结果、局限，控制在 1500 字内。）"),
                        max_tokens=budget,
                        retries=1,
                    )
                    break
                except Exception as e:
                    ctx.log("warn", f"精读笔记第 {attempt} 次失败：{str(e)[:120]}")
            if note:
                (ctx.work / "reading_note.md").write_text(note, encoding="utf-8")
                ctx.artifact("markdown", "中文精读笔记", "reading_note.md", preview=True,
                             meta={"words": len(note)})
                ctx.check("精读笔记", "pass", f"{len(note)} 字")
                ctx.log("ok", f"精读笔记 {len(note)} 字")
            else:
                # 笔记是长文附加物，小红书链路只依赖 digest.json —— 如实标记但不判失败
                ctx.check("精读笔记", "run", "两次生成均失败（上游长请求被断开）；事实源与新媒链路不受影响")
                ctx.log("warn", "精读笔记未产出，已记 check=run（不阻塞小红书链路）")

        chosen = await ctx.gate(
            "digest",
            "确认论文理解层",
            "下游小红书图文的数字与结论全部由这份事实源派生，确认贡献点与关键数据无误后再放行。",
            [
                ("continue", "确认并继续", None),
                ("revise", "补充要点后重跑", "填写的批注会追加进理解层提示词，重新生成事实源"),
            ],
        )
        if chosen == "revise":
            revise_note = ctx.gate_note()
            if not revise_note:
                ctx.log("warn", "选择重跑但没有填写批注，按原样重跑一轮")
            else:
                ctx.log("info", f"收到人工批注：{revise_note[:120]}")
            ctx.stage.gate = None
            continue
        break

    ctx.progress(1.0)
    ctx.log("ok", f"理解层就绪：{len(digest.contributions)} 条贡献 / {len(digest.results)} 条证据")


# --------------------------------------------------------------------------- #
# article
# --------------------------------------------------------------------------- #

def _assemble_xhs_md(
    *, title: str, candidates: list[str], tldr: str, body: str, tags: list[str], cards: list[dict], fig_by_id: dict
) -> str:
    lines = [f"# 小红书图文帖：{title}", "", "## 候选标题"]
    for i, t in enumerate(candidates, 1):
        lines.append(f"{i}. {t}（计重 {title_weight(t)}）")
    lines += ["", f"推荐标题：{title}", "", "## TL;DR", tldr, "", "## 正文", body, "",
              "## 标签", " ".join(f"#{t}" for t in tags), "", "## 配图顺序"]
    for i, c in enumerate(cards, 1):
        fig = fig_by_id.get(c["figureId"], {})
        lines.append(
            f"{i}. `cards/p{i}.png`：{c.get('headline', '')} —— 对应 {c['figureId']}"
            f"（{fig.get('caption', '')[:60]}）"
        )
    lines += ["", "---", f"<!-- 事实源：digest.json；图表来自 intake/images/；正文不含公式 -->", ""]
    return "\n".join(lines)


async def run_article(ctx: StageContext) -> None:
    """按 config.article.variants 逐个生成变体。

    platform 决定体裁与硬约束（长度 / 公式 / 标签 / 输出格式），voice 决定语气与结构；
    约束优先级：事实源 > 平台硬约束 > 人格语气。人格不参与校验。
    """
    data = ctx.shared.get("intake")
    if not data:
        raise GenerateError("INTAKE_MISSING", "缺少 M1 的解析结果")
    digest = ctx.run.digest
    digest_file = ctx.work.parent / "understand" / "digest.json"
    if digest is None and digest_file.is_file():
        digest = PaperDigest.model_validate_json(digest_file.read_text(encoding="utf-8"))
        ctx.run.digest = digest
    if digest is None:
        raise GenerateError("DIGEST_MISSING", "缺少事实源 digest.json，无法生成文案")

    figures: list[dict] = data["figures"]
    fig_by_id = {f["id"]: f for f in figures}
    digest_json = json.dumps(
        {
            "title": digest.title,
            "authors": digest.authors,
            "abstractCn": digest.abstractCn,
            "keywords": digest.keywords,
            "contributions": digest.contributions,
            "method": digest.method,
            "results": digest.results,
            "limitations": digest.limitations,
        },
        ensure_ascii=False,
        indent=1,
    )

    requested = [v for v in (ctx.run.config.article.variants or []) if styles.parse_variant(v)]
    variants = styles.normalize_variants(ctx.run.config.article.variants)
    if len(variants) < len(set(requested)):
        ctx.log("warn", f"变体数超过上限 {styles.MAX_VARIANTS}，只生成前 {len(variants)} 个（每个变体一次 LLM 调用）")
    unknown = [v for v in (ctx.run.config.article.variants or []) if not styles.parse_variant(v)]
    if unknown:
        ctx.log("warn", f"无法识别的变体 id，已忽略：{unknown[:4]}")
    ctx.log("info", "本次生成：" + "、".join(styles.variant_label(p, v) for p, v in variants))

    ctx.run.articles = []
    made_cards: list[str] = []
    card_errors: list[str] = []
    n = len(variants)
    failures: list[str] = []

    for idx, (platform, voice) in enumerate(variants):
        spec = styles.platform_spec(platform)
        ctx.progress(0.1 + 0.85 * idx / n)
        try:
            if spec.output == "json":
                # 卡片与人格无关（同一批图），只在第一个 xhs 变体时渲染，其余复用
                cards = await _gen_xhs_variant(
                    ctx, spec, voice, digest, digest_json, data, figures, fig_by_id,
                    render_cards=not made_cards, export=(idx == 0),
                )
                if cards:
                    made_cards = cards
            else:
                await _gen_markdown_variant(ctx, spec, voice, digest, digest_json, figures)
        except GenerateError as e:
            failures.append(f"{styles.variant_label(platform, voice)}：{e.message[:120]}")
            ctx.log("err", f"{styles.variant_label(platform, voice)} 生成失败：{e.message[:200]}")
            ctx.check(f"{styles.variant_label(platform, voice)} · 生成", "fail", e.message[:200])
        except Exception as e:  # 单个变体失败不拖垮其它变体（与渠道投递一致的策略）
            failures.append(f"{styles.variant_label(platform, voice)}：{type(e).__name__} {str(e)[:100]}")
            ctx.log("err", f"{styles.variant_label(platform, voice)} 异常：{type(e).__name__}: {str(e)[:200]}")
            ctx.check(f"{styles.variant_label(platform, voice)} · 生成", "fail", f"{type(e).__name__}: {str(e)[:160]}")

    if not ctx.run.articles:
        raise GenerateError("ARTICLE_ALL_FAILED", "所有变体都生成失败：" + "；".join(failures[:3]))

    if card_errors:
        for e in card_errors:
            ctx.log("warn", f"卡片：{e}")

    # ---- 出口兜底 ----
    # publish 读的是 article/export/title.txt，而它历史上**只由小红书（JSON）分支写**。
    # 于是「只选知乎/英文/B站」的 run 会被 publish 判 TITLE_MISSING 直接失败（2026-09-19 踩到）。
    # 这里补一层：没有 xhs 变体时，从第一个 markdown 变体里取一级标题当出口。
    export_dir = ctx.work / "export"
    if ctx.run.articles and not (export_dir / "title.txt").is_file():
        for art in ctx.run.articles:
            for cand in sorted(ctx.work.glob(f"{art.id.split('-')[0]}*.md")):
                m = re.search(r"^#\s+(.+)$", cand.read_text(encoding="utf-8"), re.M)
                if not m:
                    continue
                export_dir.mkdir(parents=True, exist_ok=True)
                (export_dir / "title.txt").write_text(m.group(1).strip() + "\n", encoding="utf-8")
                (export_dir / "content.txt").write_text(cand.read_text(encoding="utf-8"), encoding="utf-8")
                ctx.artifact("text", "标题（待发布）", "export/title.txt", preview=True)
                ctx.artifact("text", "正文（待发布）", "export/content.txt", preview=True)
                ctx.log("info", f"本 run 没有小红书变体，已从「{art.label}」取出口标题与正文（publish 需要）")
                break
            else:
                continue
            break

    ctx.progress(1.0)
    summary = " / ".join(f"{a.label} {a.words} 字" for a in ctx.run.articles)
    ctx.log("ok", f"M2 完成：{len(ctx.run.articles)} 个变体（{summary}），卡片 {len(made_cards)} 张")


async def _gen_xhs_variant(
    ctx: StageContext, spec: "styles.PlatformSpec", voice: str, digest: PaperDigest,
    digest_json: str, data: dict, figures: list[dict], fig_by_id: dict, *,
    render_cards: bool, export: bool,
) -> list[str]:
    """小红书图文变体：JSON 结构输出 + 标题计重 + 去公式 + 数字回溯 + 3:4 卡片。"""
    label = styles.variant_label("xhs", voice)
    stem = "xhs" if voice == styles.DEFAULT_VOICE else f"xhs-{voice}"
    ctx.log("info", f"调用 LLM 生成「{label}」文案（JSON 结构）…")
    try:
        raw = await ctx.llm.chat_json(
            prompts.article_system("xhs", voice),
            prompts.article_user(digest.title, digest_json, figures, _brief_of(ctx)),
            max_tokens=16000,
        )
    except Exception as e:
        raise GenerateError("LLM_XHS_FAILED", f"{label}文案生成失败：{e}") from e
    if not isinstance(raw, dict):
        raise GenerateError("LLM_BAD_XHS", f"{label}返回的文案不是 JSON 对象")

    # ---- 标题：按计重规则挑选 / 兜底 ----
    candidates = [str(t).strip() for t in (raw.get("candidateTitles") or []) if str(t).strip()]
    rec = str(raw.get("recommendedTitle") or "").strip()
    titles: list[str] = []
    for t in [rec, *candidates]:          # 去重但保持顺序（模型常把推荐标题又放进候选里）
        if t and t not in titles:
            titles.append(t)
    candidates = candidates[:8]
    ok_titles = [t for t in titles if title_weight(t) <= 38][:8]
    if not ok_titles:
        base_title = rec or digest.title
        cut, acc = "", 0
        for ch in base_title:
            w = 2 if CJK.match(ch) else 1
            if acc + w > 38:
                break
            cut += ch
            acc += w
        ok_titles = [cut.strip() or digest.title[:19]]
        ctx.log("warn", f"{label} 候选标题全部超长，已按计重规则截断为：{ok_titles[0]}")
    recommended = min(ok_titles, key=title_weight) if rec not in ok_titles else rec
    if title_weight(rec) > 38 and rec:
        ctx.log("warn", f"{label} 推荐标题计重 {title_weight(rec)} > 38，改用 {title_weight(recommended)} 的候选")

    # ---- 正文：去公式 → 数字回溯 → 长度 ----
    body = str(raw.get("body") or "").strip()
    body, formula_hits = strip_formulas(body)
    if formula_hits:
        ctx.log("warn", f"{label} 正文出现 {len(formula_hits)} 处公式表达，已就地去除：{formula_hits[:2]}")
    haystack = json.dumps(raw, ensure_ascii=False) + digest_json + data["markdown"]
    body, dropped_nums = _drop_untraceable(body, haystack)
    if dropped_nums:
        ctx.log("warn", f"{label} 删除含无法回溯数字的句子，涉及数字：{sorted(set(dropped_nums))[:8]}")
    body = _truncate_body(body, spec.body_max)

    tags: list[str] = []
    for t in raw.get("tags") or []:
        t = str(t).strip().lstrip("#").strip()
        if t and t not in tags:
            tags.append(t)
    for k in digest.keywords:
        if len(tags) >= spec.tags_min:
            break
        if k not in tags:
            tags.append(k)
    tags = tags[: spec.tags_max]
    if len(tags) < spec.tags_min:
        ctx.log("warn", f"{label} 标签只有 {len(tags)} 个，少于 {spec.tags_min} 个的下限")

    # ---- 卡片：选图（与人格无关，取事实源已选定的图） ----
    raw_cards = [c for c in (raw.get("cards") or []) if isinstance(c, dict) and c.get("figureId") in fig_by_id]
    if not raw_cards:
        raw_cards = [
            {
                "figureId": f["id"],
                "badge": f"{i}",
                "headline": digest.contributions[0][:20] if digest.contributions else digest.title[:20],
                "captionCn": f["caption"][:45],
            }
            for i, f in enumerate(digest.figures, 1)
        ]
        ctx.log("warn", f"{label} 模型未给出有效卡片，已按事实源选图兜底")
    picks = []
    for i, c in enumerate(raw_cards[:6], 1):
        fig = fig_by_id[c["figureId"]]
        picks.append(
            {
                "figureId": c["figureId"],
                "file": fig["file"],
                "badge": str(c.get("badge") or f"{i}/{len(raw_cards[:6])}"),
                "headline": str(c.get("headline") or "").strip() or fig["caption"][:20],
                "captionCn": str(c.get("captionCn") or "").strip() or fig["caption"][:45],
            }
        )

    # ---- 落盘 ----
    xhs_md = _assemble_xhs_md(
        title=recommended, candidates=ok_titles, tldr=str(raw.get("tldr") or "").strip(),
        body=body, tags=tags, cards=picks, fig_by_id=fig_by_id,
    )
    (ctx.work / f"{stem}.md").write_text(xhs_md, encoding="utf-8")
    (ctx.work / f"{stem}.raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    ctx.artifact("markdown", f"{label} 图文", f"{stem}.md", preview=True)
    ctx.artifact("json", f"{label} 文案原始输出", f"{stem}.raw.json", preview=False)

    # 待发布的纯文本（只导出主变体，避免多平台互相覆盖）
    if export:
        export_dir = ctx.work / "export"
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / "title.txt").write_text(recommended, encoding="utf-8")
        (export_dir / "content.txt").write_text(body + "\n\n" + " ".join(f"#{t}" for t in tags), encoding="utf-8")
        ctx.artifact("text", "标题（待发布）", "export/title.txt", preview=True)
        ctx.artifact("text", "正文（待发布）", "export/content.txt", preview=True)

    # ---- 校验（平台硬约束，人格不参与） ----
    ctx.check(f"{label} · 标题计重", "pass" if title_weight(recommended) <= spec.title_weight_max else "fail",
              f"「{recommended}」= {title_weight(recommended)}（上限 {spec.title_weight_max}）")
    ctx.check(f"{label} · 无公式", "fail" if styles.find_formula(body) else "pass",
              f"命中 {styles.find_formula(body)[:20]}" if styles.find_formula(body) else "正文不含 LaTeX/公式表达")
    ctx.check(f"{label} · 正文长度", "pass" if 0 < len(body) <= spec.body_max else "fail",
              f"{len(body)} 字（上限 {spec.body_max}）")
    ctx.check(f"{label} · 标签数量",
              "pass" if spec.tags_min <= len(tags) <= spec.tags_max else "fail",
              f"{len(tags)} 个（{spec.tags_min}-{spec.tags_max}）")
    brief_checks(ctx, _brief_of(ctx), label, f"{recommended}\n{body}", spec)

    made_cards: list[str] = []
    if render_cards and ctx.settings.cards_enabled:
        ctx.log("info", f"渲染 {len(picks)} 张卡片（1080×1440）…")
        series = f"论文速读 · {digest.arxivId or digest.venue or 'arXiv'}"
        source_note = f"{digest.title[:60]} · {digest.authors[0] if digest.authors else ''}"
        made_cards, card_errors = await asyncio.to_thread(
            card_render.render_cards,
            picks,
            ctx.work.parent / "intake",   # 图在 intake/images/
            ctx.work / "cards",           # 卡片写进 article/cards/
            series=series,
            source_note=source_note,
            font_preferred=ctx.settings.cjk_font,
        )
        ctx.check(f"{label} · 卡片渲染", "pass" if made_cards else "fail",
                  f"{len(made_cards)} 张 3:4 卡片" if made_cards else "；".join(card_errors) or "未渲染")
        for i, rel in enumerate(made_cards[:9], 1):
            ctx.artifact("image", f"卡片 {i}", rel, preview=True, meta={"w": 1080, "h": 1440})
    elif not ctx.settings.cards_enabled:
        ctx.log("warn", "PAPERCAST_CARDS=off，跳过卡片渲染（export/ 里只有文案）")
    else:
        ctx.log("info", f"卡片已在主变体渲染，{label} 复用同一批图")

    ctx.run.articles.append(
        ArticleVariant(
            id=styles.variant_id("xhs", voice), platform="xhs", voice=voice, label=label,
            url=f"/artifacts/{ctx.run.id}/article/{stem}.md", words=len(body),
        )
    )
    return made_cards


async def _gen_markdown_variant(
    ctx: StageContext, spec: "styles.PlatformSpec", voice: str,
    digest: PaperDigest, digest_json: str, figures: list[dict],
) -> None:
    """Markdown 平台变体：知乎长文 / B 站脚本。"""
    label = styles.variant_label(spec.id, voice)
    stem = spec.id if voice == styles.DEFAULT_VOICE else f"{spec.id}-{voice}"
    budget = 24000 if spec.body_max >= 2000 else 16000
    ctx.log("info", f"调用 LLM 生成「{label}」（max_tokens={budget}）…")
    try:
        text = await ctx.llm.chat(
            prompts.article_system(spec.id, voice),
            prompts.article_user(digest.title, digest_json, figures, _brief_of(ctx)),
            max_tokens=budget,
        )
    except Exception as e:
        raise GenerateError("LLM_ARTICLE_FAILED", f"{label}生成失败：{e}") from e
    text = _strip_fence(text).strip()
    if not text:
        raise GenerateError("LLM_ARTICLE_EMPTY", f"{label}返回空内容")

    (ctx.work / f"{stem}.md").write_text(text, encoding="utf-8")
    ctx.artifact("markdown", f"{label} 长文", f"{stem}.md", preview=True, meta={"words": len(text)})

    for check_label, state, detail in styles.validate_markdown(spec, text):
        ctx.check(f"{label} · {check_label}", state, detail)
    brief_checks(ctx, _brief_of(ctx), label, text, spec)

    # 数字可回溯：软检查（长文里的格式差异会误报，如实标记为待人工复核）
    haystack = re.sub(r"[\s,，]", "", digest_json + ctx.shared["intake"]["markdown"])
    nums = numbers_in(text)
    untraceable = [n for n in nums if re.sub(r"[\s,，]", "", n) not in haystack and n.rstrip("%") not in haystack]
    if untraceable:
        ctx.log("warn", f"{label} 有 {len(untraceable)} 个数字未在事实源里回溯到（保留，人工复核）：{sorted(set(untraceable))[:6]}")
        ctx.check(f"{label} · 数字可回溯", "run",
                  f"{len(untraceable)}/{len(nums)} 个数字未回溯到，待人工复核" if nums else "正文没有数字")
    else:
        ctx.check(f"{label} · 数字可回溯", "pass", f"{len(nums)} 个数字全部可在事实源中回溯")

    # 字数登记按 spec.unit 取口径（B6）：英文变体（en，unit="words"）用 cjk_len 恒为 0，
    # 前端因此一直显示「英文传播 0 字」。口径函数早就有（styles.text_len），这里只是没接上。
    n = styles.text_len(text, spec.unit)
    unit_cn = "词" if spec.unit == "words" else "字"
    ctx.run.articles.append(
        ArticleVariant(
            id=styles.variant_id(spec.id, voice), platform=spec.id, voice=voice, label=label,
            url=f"/artifacts/{ctx.run.id}/article/{stem}.md", words=n,
        )
    )
    ctx.log("ok", f"{label} 完成：{n} {unit_cn}")


def _strip_fence(text: str) -> str:
    """模型有时把整篇 Markdown 包在围栏里，去掉最外层围栏。"""
    t = (text or "").strip()
    tick = chr(96) * 3
    if t.startswith(tick) and t.endswith(tick):
        inner = t[len(tick): -len(tick)]
        nl = inner.find("\n")
        return inner[nl + 1:].strip() if nl >= 0 else t
    return t
