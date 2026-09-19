"""poster 阶段编排：digest → LLM 写 poster.spec.json → poster.py 渲染多画布 → 产物 + 几何闸门。

**为什么单独一个文件**：渲染器在 `app/modules/poster.py`（已提交，由另一条轨道维护，含二分字号、
几何自检、封面版式等 560 行）。本文件只做「把它接进 pipeline」的编排。分成两个文件是为了让
「版式实现」和「阶段编排」的改动互不冲突；渲染器稳定后可以合并进 poster.py。

对应总纲里的「可视化 Agent」：把论文核心图表做成**科普版**（会议海报 / 竖长图 / 视频封面），
而不是把原图直接搬运。

反幻觉约束（与 M2 一致）：spec 里出现的任何数字都必须能在 digest 或论文原文里检索到，
检索不到就**丢掉那一块/那条**并记日志，不允许为了版面好看而编数字。
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from .. import prompts as prompts_mod
from . import cards_deck
from . import poster as renderer

SPEC_SYSTEM = """你是学术传播的视觉设计编辑。给你一篇论文的事实源（digest）和它可用的原图，
你要输出一份**版面描述 JSON**（spec），交给确定性的排版器渲染成海报与信息图。

你只负责「放什么」，不负责「怎么排」（字号、栏宽、间距由排版器自己算，做不好它会报溢出并让你减内容）。

硬约束：
1. 只使用 digest 与原文里出现过的事实、数字、指标名。**一个数字都不许编**；拿不准就不写数字。
2. 中文表达，不要 markdown 符号，不要在正文里写 LaTeX/公式。
3. 每栏 1-2 个块，总块数 4-6 个。窄画布（3:4）装不下三栏和长条目，所以：
   - 次要的块标 `"sizes": ["wide"]`（只在宽画布出现）；
   - 需要精简版条目的块，额外写 `items_tall`（给竖版用的短条目）。
4. 图片只能从给定清单里选（写 `file` 字段，值必须是清单里的文件名）。

只输出 JSON，结构如下：
{
  "title": "论文标题（可中文，保留英文原名）",
  "kicker": "会议或来源，如 arXiv 2510.05096",
  "subtitle": "一句话结论（中文，40 字内）",
  "authors": ["作者1", "作者2"],
  "affiliation": "单位",
  "venue": "会议/期刊/来源",
  "chips": ["关键词1", "关键词2", "关键词3"],
  "teaser": {"file": "fig-1.png", "caption": "中文图注（一句话）"},
  "columns": [
    [{"kind": "panel", "title": "问题", "items": ["要点1", "要点2"]},
     {"kind": "panel", "title": "数据", "items": ["要点"], "sizes": ["wide"]}],
    [{"kind": "figure", "file": "fig-2.png", "number": "2", "caption": "中文图注"}],
    [{"kind": "panel", "title": "结果", "items": ["要点1"], "items_tall": ["更短的要点"]}]
  ],
  "footer": "素材：arXiv xxxx · 图 1、图 2"
}

另外再输出一份**封面** spec（同一内容，版式更少更醒目，供视频封面用）：
{"cover": {"layout": "cover", "kicker": "...", "title": "短标题（15 字内）", "subtitle": "副标题（40 字内）",
           "chips": ["a", "b", "c"], "teaser": {"file": "fig-1.png"}, "footer": "..."}}

最终只输出：{"spec": {...}, "cover": {...}}"""

SPEC_USER = """论文：{title}
来源：{venue} · {year}
作者：{authors}

【事实源 digest】
{digest}

【可用的原图清单（file 只能取这里的文件名）】
{figures}

【论文正文节选（数字回溯时以它为准）】
{content}
"""

PRESETS_RENDER: list[tuple[str, str, str, str]] = [
    # (preset, 输出名, 用哪份 spec, 说明)
    # 顺序 = 掉档顺序：信息流先出（小红书首图在最前），够不着再往后掉。
    ("xhs-cover", "poster-xhs-cover", "cover", "小红书首图 1080×1440（3:4 封面：大标题 + 主图 + 标签）"),
    ("xhs-long", "poster-xhs-long", "spec", "小红书/知乎竖长图 1080×2400"),
    ("zhihu", "poster-zhihu", "spec", "知乎正文横版 1600×1200"),
    ("bili-cover", "poster-bili-cover", "cover", "B 站视频封面 1920×1080"),
    ("conf", "poster", "spec", "会议海报 48×36in（打印/存档）"),
]

# 画布归属的平台。前端作品库按命名记号推平台（`src/data/library.ts` 的 platformOf），
# 同时一直想要后端给 meta.platform —— 这里补上，省得它继续猜文件名。
PRESET_PLATFORM: dict[str, str] = {
    "xhs-cover": "xhs", "xhs-long": "xhs", "zhihu": "zhihu", "bili-cover": "bilibili", "conf": "generic",
}

NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> list[str]:
    return NUM_RE.findall(text or "")


def _spec_text(spec: dict[str, Any]) -> str:
    """把 spec 里所有会渲染成文字的部分拼起来，用于数字回溯。"""
    parts: list[str] = []
    for key in ("title", "subtitle", "kicker", "venue", "affiliation", "footer"):
        parts.append(str(spec.get(key) or ""))
    parts.extend(str(x) for x in (spec.get("authors") or []))
    parts.extend(str(x) for x in (spec.get("chips") or []))
    teaser = spec.get("teaser") or {}
    parts.append(str(teaser.get("caption") or ""))
    for col in spec.get("columns") or []:
        for b in col:
            parts.append(str(b.get("title") or ""))
            parts.append(str(b.get("caption") or ""))
            parts.append(str(b.get("text") or ""))
            parts.extend(str(x) for x in (b.get("items") or []))
            parts.extend(str(x) for x in (b.get("items_tall") or []))
    return "\n".join(parts)


def _available_figures(intake_dir: Path) -> list[dict[str, Any]]:
    """列 intake 里真实存在的图（figures.json 是解析产物，以磁盘为准）。"""
    out: list[dict[str, Any]] = []
    idx_path = intake_dir / "figures.json"
    meta: dict[str, dict] = {}
    if idx_path.is_file():
        try:
            data = json.loads(idx_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = []
        # figures.json 是 list（app/modules/intake.py 写的是 [f.as_dict(), ...]）；
        # 兼容 dict 形态的旧产物，免得换个版本就崩。
        items = data if isinstance(data, list) else (data.get("figures") or data.get("items") or [])
        for f in items:
            if isinstance(f, dict) and f.get("file"):
                meta[Path(f["file"]).name] = f
    img_dir = intake_dir / "images"
    if img_dir.is_dir():
        for p in sorted(img_dir.glob("*.png")):
            m = meta.get(p.name, {})
            out.append({
                "file": p.name,
                "caption": (m.get("caption") or "")[:120],
                "kind": m.get("kind") or m.get("type") or "",
            })
    return out


def _digest_of(ctx) -> dict[str, Any]:
    """digest 是 understand 阶段的产物，poster 从 run 目录读（唯一事实源，不重新理解）。"""
    p = ctx.work.parent / "understand" / "digest.json"
    if not p.is_file():
        raise RuntimeError("找不到 understand/digest.json —— poster 只认既有事实源，不自己重新理解论文")
    return json.loads(p.read_text(encoding="utf-8"))


def _sanitize(data: dict[str, Any], figures: list[dict[str, Any]], haystack: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """把模型给的 spec 收敛成「引用都真实存在 + 数字都能回溯」的版本。

    纯函数：不改调用方传进来的对象（只对顶层 dict() 浅拷贝时，栏目/块仍是调用方的对象，
    被丢掉的 items 会就地删掉原 dict —— 2026-09-19 修，与 _trim_spec 的语义对齐）。
    """
    data = copy.deepcopy(data)
    names = {f["file"] for f in figures}
    dropped: list[str] = []
    bad_numbers: list[str] = []
    flat = re.sub(r"[\s,，]", "", haystack)

    def num_ok(text: str) -> bool:
        bad = [n for n in _numbers(text) if n not in flat]
        if bad:
            bad_numbers.extend(bad[:2])
            return False
        return True

    spec = dict(data or {})
    spec["title"] = str(spec.get("title") or "").strip()
    if not spec["title"]:
        raise ValueError("spec 缺 title")
    spec["columns"] = spec.get("columns") or []

    teaser = spec.get("teaser")
    if isinstance(teaser, dict):
        if Path(str(teaser.get("file") or "")).name not in names:
            dropped.append(f"teaser 引用了不存在的图：{teaser.get('file')}")
            spec.pop("teaser")
        elif not num_ok(str(teaser.get("caption") or "")):
            dropped.append("teaser 图注含无法回溯的数字，已去掉图注")
            teaser.pop("caption", None)

    cols: list[list[dict[str, Any]]] = []
    for col in spec["columns"]:
        keep: list[dict[str, Any]] = []
        for b in col or []:
            if not isinstance(b, dict):
                continue
            if b.get("kind") == "figure":
                if Path(str(b.get("file") or "")).name not in names:
                    dropped.append(f"块引用了不存在的图：{b.get('file')}")
                    continue
                b["file"] = Path(str(b["file"])).name
                if not num_ok(f"{b.get('number') or ''} {b.get('caption') or ''}"):
                    dropped.append("图注含无法回溯的数字，已去掉图注")
                    b.pop("caption", None)
            else:
                for key in ("items", "items_tall"):
                    if b.get(key):
                        kept = [str(x) for x in b[key] if num_ok(str(x))]
                        if len(kept) != len(b[key]):
                            dropped.append("有条目含无法回溯的数字，已丢掉该条目")
                        b[key] = kept
                if b.get("text") and not num_ok(str(b["text"])):
                    dropped.append("段落含无法回溯的数字，已丢掉该段")
                    b.pop("text", None)
                if not (b.get("items") or b.get("text")):
                    dropped.append(f"块「{b.get('title')}」被清空，已移除")
                    continue
            keep.append(b)
        if keep:
            cols.append(keep)
    spec["columns"] = cols
    if not cols:
        raise ValueError("所有栏目都被清空了（多半是图片引用全部不存在）")

    stats = {"dropped": dropped, "bad_numbers": sorted(set(bad_numbers))}
    return spec, stats


async def _write_spec(ctx, digest: dict[str, Any], figures: list[dict[str, Any]], content: str) -> tuple[dict, dict, dict]:
    """让模型写 spec 与封面 spec；校验不过就带着错误再要一次。"""
    fig_lines = "\n".join(
        f"- {f['file']}" + (f"（{f['kind']}）" if f["kind"] else "") + (f" 原图注：{f['caption']}" if f["caption"] else "")
        for f in figures
    ) or "（这篇论文没有可用原图，请全部用文字块，不要引用图）"
    authors = digest.get("authors") or []
    user = SPEC_USER.format(
        title=digest.get("title") or ctx.run.title,
        venue=digest.get("venue") or "",
        year=digest.get("year") or "",
        authors="、".join(authors[:6]) if isinstance(authors, list) else str(authors),
        digest=json.dumps(digest, ensure_ascii=False, indent=1)[:14000],
        figures=fig_lines,
        content=(content or "")[:60000],
    ) + prompts_mod.brief_block(
        (getattr(getattr(ctx.run, "config", None), "brief", "") or "").strip(),
        stage="海报/信息图：篇幅、侧重与语气（不影响版面规则）",
    )
    haystack = json.dumps(digest, ensure_ascii=False) + "\n" + (content or "")

    last_err = ""
    for attempt in (1, 2):
        ask = user if attempt == 1 else user + f"\n\n上一次的输出有问题：{last_err}\n请修正后重新输出完整 JSON。"
        raw = await ctx.llm.chat_json(SPEC_SYSTEM, ask, max_tokens=8000)
        try:
            spec_src = raw.get("spec") if isinstance(raw.get("spec"), dict) else raw
            cover_src = raw.get("cover") if isinstance(raw.get("cover"), dict) else {}
            spec, stats = _sanitize(spec_src, figures, haystack)
            cover = dict(cover_src or {})
            if cover:
                cover["layout"] = "cover"
                cover.setdefault("title", spec.get("title", "")[:40])
                cover.setdefault("chips", (spec.get("chips") or [])[:4])
                t = cover.get("teaser")
                if isinstance(t, dict) and Path(str(t.get("file") or "")).name not in {f["file"] for f in figures}:
                    cover.pop("teaser", None)
                cover.setdefault("footer", spec.get("footer") or "")
            return spec, cover, stats
        except Exception as e:  # 校验失败：带上原因重来一次
            last_err = f"{type(e).__name__}: {e}"
            ctx.log("warn", f"spec 第 {attempt} 次校验未过：{last_err}")
    raise RuntimeError(f"两次都没能生成可用的 spec：{last_err}")


def _trim_spec(spec: dict[str, Any], drop_n: int) -> dict[str, Any]:
    """砍掉 N 个「最次要」的块：从最后一栏往前，先丢纯文字块，图块留到最后。

    这是 docs/07 那条结论的机械化：窄画布上**必须减内容**，不是把字缩到看不清。
    """
    out = json.loads(json.dumps(spec))
    for _ in range(max(0, drop_n)):
        best: Optional[tuple[int, int, bool]] = None  # (栏序号, 块序号, 是图块) —— 越小越先丢
        for ci, col in enumerate(out.get("columns") or []):
            for bi, b in enumerate(col or []):
                key = (ci, bi, b.get("kind") == "figure")
                if best is None or key > best:
                    best = key
        if best is None:
            break
        ci, bi, _ = best
        if len(out["columns"][ci]) <= 1 and len(out["columns"]) == 1:
            break  # 最后一栏的最后一个块，再丢就空了
        out["columns"][ci].pop(bi)
        out["columns"] = [c for c in out["columns"] if c]
    return out


async def _render_with_budget(
    ctx, spec_path: Path, out_dir: Path, preset: str, out_name: str, figs_arg: str, note: str,
) -> dict[str, Any]:
    """按渠道渲染；装不下就按优先级减块重试（最多 3 次），并把「砍了什么」如实记进日志。"""
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    last: dict[str, Any] = {}
    for drop in (0, 1, 2, 3):
        use = spec if drop == 0 else _trim_spec(spec, drop)
        path = spec_path if drop == 0 else (out_dir / f"poster.spec.{preset}.trim{drop}.json")
        if drop:
            path.write_text(json.dumps(use, ensure_ascii=False, indent=1), encoding="utf-8")
        rep = await asyncio.to_thread(
            renderer.make_poster, path, out_dir, preset=preset, out_name=out_name, figures_dir=figs_arg, fit=True,
        )
        rep["dropped_blocks"] = drop
        last = rep
        if rep.get("ok"):
            if drop:
                ctx.log("warn", f"{note} 装不下，砍掉 {drop} 个次要块后通过（版面已存 poster.spec.{preset}.trim{drop}.json）")
            return rep
        blocks = sum(len(c) for c in (use.get("columns") or []))
        if blocks <= 2 and not use.get("layout") == "cover":
            break  # 再减就没内容了，如实失败
    return last


DECK_KIND_CN = {"cover": "封面", "panel": "要点", "figure": "证据", "closing": "判断"}


def deck_artifact_rel(frame: dict[str, Any], out_dir: Path) -> str:
    """组图 PNG 相对 poster/ 的登记路径。

    2026-09-19 修的真 bug：这里原来硬写 `f"cards/{id}.png"`，而渲染器（`ops/shot/render_social_deck.mjs`）
    落的是 `cards/output/*.png` —— 于是 7 张组图在阶段里全部登记成「缺失」（真跑 run_77d2410986e6 实测：
    渲染 JSON 说 ok、7 张文件都在磁盘上，阶段产物却一个都点不开）。

    优先用渲染器自己报的绝对路径反推（它是唯一事实源），取不到才退到技能约定的 output/ 子目录。
    """
    path = str(frame.get("path") or "").strip()
    if path:
        try:
            return Path(path).resolve().relative_to(Path(out_dir).resolve()).as_posix()
        except (ValueError, OSError):
            pass
    return f"cards/output/{frame.get('id', '')}.png"


def deck_deliverable_rel(rel: str, out_dir: Path) -> str:
    """组图登记/投递用哪一份：有 JPEG 侧车就用 JPEG。

    PNG 是按 1080×1440 渲染出来的母版（可编辑、体积大），JPEG 侧车（q88、不抽色）才是
    真正要上传的那份 —— 同一张图 PNG ~900KB vs JPEG ~300KB，平台还会再压一遍。
    """
    p = Path(str(rel))
    if p.suffix.lower() == ".png":
        cand = p.with_suffix(".jpg")
        if (Path(out_dir) / cand).is_file():
            return cand.as_posix()
    return p.as_posix()


async def _run_deck(ctx, spec: dict[str, Any], cover: Optional[dict[str, Any]], digest: dict[str, Any],
                    figs_arg: str, out_dir: Path) -> None:
    """小红书组图：把同一份（已核过数字的）spec 用 guizang 技能重排成 3:4 组图。

    fail-closed 的三条边界：① 开关 off / 技能没装 → 记一条 run 状态、**不报 fail**（渠道画布照常交付）；
    ② 装配或渲染异常 → 记 fail，但不动已经渲染好的画布；③ 自检有 FAIL → 先减内容重排（最多 2 次），
    仍不过才如实记 fail —— 并把「砍了什么」写进日志。
    """
    mode = str(getattr(ctx.settings, "poster_deck", "auto") or "auto")
    if not cards_deck.enabled(mode):
        why = ("已关闭（PAPERCAST_POSTER_DECK=off）" if mode.lower() in ("off", "0", "false", "no")
               else "技能未安装（跑 ./ops/install_skills.sh 装 guizang-social-card-skill）")
        ctx.log("info", f"小红书组图跳过：{why}")
        ctx.check("小红书组图（guizang 技能）", "run", f"跳过：{why}")
        return

    deck_dir = out_dir / "cards"
    figures_dir = figs_arg.split(os.pathsep)[0]
    note = f"{spec.get('venue') or ''} · {spec.get('title') or ''}".strip(" ·")
    ctx.log("info", f"用 guizang 技能重排小红书组图（技能：{cards_deck.skill_dir()}）…")

    last: dict[str, Any] = {}
    for attempt, (max_items, keep) in enumerate(((4, None), (3, None), (3, 3))):
        try:
            built = await asyncio.to_thread(
                cards_deck.build, spec, cover, digest, figures_dir, deck_dir,
                max_items=max_items, keep_pages=keep, note=note,
            )
            rep = await asyncio.to_thread(cards_deck.render, deck_dir, scale=1)
            chk = await asyncio.to_thread(cards_deck.validate, deck_dir)
        except Exception as e:
            ctx.log("warn", f"小红书组图失败：{type(e).__name__}: {str(e)[:160]}")
            ctx.check("小红书组图（guizang 技能）", "fail", f"{type(e).__name__}: {str(e)[:140]}")
            return
        last = {"built": built, "render": rep, "check": chk, "attempt": attempt,
                "max_items": max_items, "keep": keep}
        if chk.get("fails", 0) == 0 and rep.get("ok"):
            break
        bad = [d for d in chk.get("details") or [] if d["level"] == "FAIL"][:2]
        if attempt < 2:
            ctx.log("warn", f"组图自检不过（{chk.get('fails')} fail），减内容重排：{bad}")

    built, rep, chk = last["built"], last["render"], last["check"]
    if last["attempt"]:
        ctx.log("warn", f"组图第 {last['attempt'] + 1} 次尝试才通过（每页要点 {last['max_items']} 条"
                        + (f"、只留前 {last['keep']} 页" if last["keep"] else "") + "）")

    frames = rep.get("frames") or []
    plan = built.get("plan") or []
    missing: list[str] = []
    for i, fr in enumerate(frames):
        kind = (plan[i] or {}).get("kind") if i < len(plan) else ""
        label = f"小红书组图 {i + 1}/{len(frames)}" + (f" · {DECK_KIND_CN.get(kind, '')}" if kind else "")
        rel = deck_deliverable_rel(deck_artifact_rel(fr, out_dir), out_dir)
        if not (out_dir / rel).is_file():
            missing.append(rel)
        # 尺寸取渲染器报的实际像素（scale=1 时就是 1080×1440，别再手写 ×2）
        ctx.artifact("image", label, rel, preview=True,
                     meta={"width": int(fr.get("w", 0)), "height": int(fr.get("h", 0)),
                           "bytes": int(fr.get("jpegBytes") or fr.get("bytes") or 0),
                           "preset": "guizang-deck", "platform": "xhs", "theme": built.get("theme")})
    ctx.artifact("html", "组图预览（技能模板渲染的 index.html）", "cards/index.html", preview=True)

    warns, fails = chk.get("warns", 0), chk.get("fails", 0)
    detail = f"{len(frames)} 张 · 技能自检 {chk.get('sections', 0)} 张里 {chk.get('clean', 0)} 张 clean · {fails} fail · {warns} warn"
    if fails or warns:
        first = (chk.get("details") or [{}])[0]
        detail += f" · 首条：{first.get('rule', '')} {first.get('text', '')[:80]}"
    detail += f" · 主题 {built.get('theme')}"
    if missing:
        # 渲染器说 ok、登记的路径却找不到文件 —— 这条以前会被判 pass（真跑踩到过），现在如实报 fail
        detail += f" · {len(missing)} 张登记后找不到文件：{missing[:2]}"
    ctx.check("小红书组图（guizang 技能）", "pass" if (fails == 0 and rep.get("ok") and frames and not missing) else "fail",
              detail if frames else "没有渲染出任何组图")


async def run_poster(ctx) -> None:
    """poster 阶段：digest → spec → 按渠道渲染多张画布。"""
    intake = ctx.shared.get("intake") or {}
    content = intake.get("markdown") or ""
    intake_dir = Path(intake.get("work") or (ctx.work.parent / "intake"))

    ctx.log("info", "读取事实源 digest.json（不重新理解论文）…")
    digest = _digest_of(ctx)
    figures = _available_figures(intake_dir)
    ctx.log("info", f"可用原图 {len(figures)} 张；调用 LLM 写版面描述…")

    spec, cover, stats = await _write_spec(ctx, digest, figures, content)
    if stats["dropped"]:
        ctx.log("warn", f"收敛 spec：丢弃 {len(stats['dropped'])} 处（{stats['dropped'][:2]}）")

    out_dir = ctx.work
    src_spec = out_dir / "poster.spec.json"
    src_spec.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    specs = {"spec": src_spec}
    if cover:
        p = out_dir / "poster.spec.cover.json"
        p.write_text(json.dumps(cover, ensure_ascii=False, indent=1), encoding="utf-8")
        specs["cover"] = p

    # 图可能分散在两处：论文原图在 intake/images；AI 生成的 hero 在 poster/（千问出图，可选）
    figs_arg = os.pathsep.join([str(intake_dir / "images"), str(out_dir)])

    reports: list[dict[str, Any]] = []
    preview_html: Optional[str] = None
    for preset, out_name, which, note in PRESETS_RENDER:
        if which not in specs:
            continue
        ctx.log("info", f"渲染 {note}（preset={preset}）…")
        try:
            rep = await _render_with_budget(ctx, specs[which], out_dir, preset, out_name, figs_arg, note)
        except Exception as e:
            ctx.log("warn", f"{note} 渲染失败：{type(e).__name__}: {str(e)[:160]}")
            ctx.check(f"画布 · {note}", "fail", f"{type(e).__name__}: {str(e)[:140]}")
            continue
        rep["note"] = note
        rep["preset_out_name"] = out_name
        reports.append(rep)
        state = "pass" if rep.get("ok") else "fail"
        detail = (
            f"{rep.get('px') or (rep.get('width'), rep.get('height'))} · 正文 {rep.get('body_px', 0):.1f}px · "
            f"scale {rep.get('scale')} · 溢出 {len(rep.get('overflow') or [])} 处"
        )
        if rep.get("dropped_blocks"):
            detail += f" · 已按优先级砍掉 {rep['dropped_blocks']} 个次要块"
        ctx.check(f"画布 · {note}", state, detail if rep.get("ok") else detail + f" —— {rep.get('reason', '存在溢出')}")
        ctx.artifact(
            "image", f"{note}", f"{out_name}.png", preview=True,
            meta={
                "width": rep.get("width"), "height": rep.get("height"),
                "preset": preset, "platform": PRESET_PLATFORM.get(preset, "generic"),
            },
        )
        if preview_html is None:      # 第一张画布（小红书首图）的 HTML 给查看器当预览
            preview_html = out_name
        ctx.progress(min(0.95, 0.15 + 0.8 * len(reports) / max(1, len(PRESETS_RENDER))))

    # 组图（可选）：同一份 spec 再用 guizang 技能重排成小红书 3:4 组图。
    # 放在画布之后登记产物，是为了让查看器的「第一张 png / 第一个 html」仍是渠道画布（poster-xhs-cover）。
    await _run_deck(ctx, spec, cover, digest, figs_arg, out_dir)

    # 查看器（PosterViewer）按 kind==='html' 找预览；以前只登记 PNG，于是界面上永远是「尚未产出」。
    if preview_html:
        ctx.artifact("html", "首图预览（可读可改的 HTML 原文）", f"{preview_html}.html", preview=True)
    ctx.artifact("json", "版面描述 poster.spec.json（可复现、可换后端重排）", "poster.spec.json", preview=False)
    if cover:
        ctx.artifact("json", "封面版面描述", "poster.spec.cover.json", preview=False)

    ok_reports = [r for r in reports if r.get("ok")]
    broken = sorted({b for r in reports for b in (r.get("broken_images") or [])})
    ctx.check("几何闸门", "pass" if reports and len(ok_reports) == len(reports) else ("run" if not reports else "fail"),
              f"{len(ok_reports)}/{len(reports)} 张画布无溢出" if reports else "没有成功渲染的画布")
    ctx.check("图片引用", "pass" if not broken else "fail",
              "全部引用图都渲染成功" if not broken else f"有 {len(broken)} 张图没渲染出来：{broken[:3]}")
    ctx.check("数字可回溯", "pass" if not stats["bad_numbers"] else "run",
              "spec 里的数字都能在 digest/原文找到" if not stats["bad_numbers"]
              else f"已丢弃含无法回溯数字的内容 {stats['bad_numbers'][:4]}")
    if not reports:
        raise RuntimeError("poster 一张画布都没渲染出来，检查 ops/shot/render.mjs 与 chrome-headless-shell 是否可用")

    ctx.progress(1.0)
    ctx.log("ok", f"poster 完成：{len(reports)} 张画布 / 共 {len(figures)} 张原图可选")


