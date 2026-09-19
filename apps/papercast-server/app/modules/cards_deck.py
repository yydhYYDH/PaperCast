"""小红书组图 provider：把已核过数字的 poster.spec 映射成 guizang 技能的 Editorial 版式组图。

**它在链路里的位置**：`poster_stage` 先用 `poster.py` 出确定性的渠道画布（会议海报 / 竖长图 /
知乎横版 / 封面），再（可选）用本模块把同一份 spec **重新排版成小红书 3:4 组图**。

**为什么是「重排」而不是「再调用一次 LLM」**：`poster.spec.json` 已经是 LLM 产出的、并且
逐条核过数字可回溯的内容（见 `poster_stage._sanitize`）。组图要的是同一批事实的另一种版式，
不是另一批内容。少一次 LLM 调用 = 少一处幻觉源、少一次等待，而且离线可复现。

**AGPL 边界（重要）**：视觉系统来自 `op7418/guizang-social-card-skill`（AGPL-3.0），
本仓库是 MIT 且公开发布，所以：
  · 技能的模板/CSS **不拷进本仓库**，只在运行时从用户级安装目录读（`ops/install_skills.sh` 装的
    `~/.agents/skills/guizang-social-card-skill`，可用 `GUIZANG_SKILL_DIR` 覆盖）；
  · 本文件里唯一的 CSS 是我们自己的**覆盖层**（字体栈、图卡底色、一处上游间距与其自身 QA 下限不一致）；
  · 技能没装 → 本 provider 直接不可用（fail-closed），阶段照常出确定性画布，不报错。

渲染与自检都走现成入口，不自造：
  · 出图：`ops/shot/render_social_deck.mjs`（我们自己的，逐个 `.poster` 节点截图）
  · 自检：技能自带的 `validate-social-deck.mjs`（R1 溢出 / R2 页脚相撞 / R4 最小字号 /
    R5 四横带密度 / R6 标题行数上限 / R9 标题与正文间距…）
"""

from __future__ import annotations

import html as html_mod
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

SKILL_NAME = "guizang-social-card-skill"
TEMPLATE_REL = Path("assets") / "template-editorial-card.html"
BG_SCRIPT_REL = Path("assets") / "magazine-bg-webgl.js"

# 技能里 <html data-theme> 支持的预设（见技能 references/theme-presets.md）
THEMES = ("indigo-porcelain", "ink-classic", "forest-ink", "kraft-paper", "dune", "midnight-ink")
DEFAULT_THEME = "indigo-porcelain"

# 组图页数上限：小红书单篇最多 18 张，我们按内容量一般 4-6 张
MAX_PAGES = 9
MAX_ITEMS_PER_PAGE = 4

# 字号 → 每行能放多少个「汉字宽度单位」（英文/数字按 0.55 计）。
# 依据：画布 1080、内容左右各留 88px → 可用 904px；h-display 124px、h-xl 88px、h-md 56px。
UNITS_PER_LINE = {"display": 6.6, "xl": 9.6, "md": 15.0}
TITLE_LINES = {"display": 2, "xl": 2}
# 标题放不下时的降级字号阶梯（先降字号，**绝不截字** —— 截出来的「罕见病诊断智…」比小一号难看十倍）
SIZE_LADDER = {"display": (124, 112, 100, 92, 84, 76), "xl": (88, 80, 72, 64, 58), "md": (56, 50, 44)}
AVAIL_PX = 880.0   # 1080 画布 - 左右各 88px 内边距 - 一点 letter-spacing 余量


def workspace_root() -> Path:
    """app/modules/cards_deck.py → 工作区根。"""
    return Path(__file__).resolve().parents[4]


def skill_dir() -> Optional[Path]:
    """技能安装目录：GUIZANG_SKILL_DIR > $SKILLS_ROOT/<name> > ~/.agents/skills/<name>。"""
    cands: list[Path] = []
    env = (os.environ.get("GUIZANG_SKILL_DIR") or "").strip()
    if env:
        cands.append(Path(env).expanduser())
    root = (os.environ.get("SKILLS_ROOT") or "").strip()
    if root:
        cands.append(Path(root).expanduser() / SKILL_NAME)
    cands.append(Path.home() / ".agents" / "skills" / SKILL_NAME)
    cands.append(Path.home() / ".dsh" / "skills" / SKILL_NAME)
    for c in cands:
        if (c / "SKILL.md").is_file() and (c / TEMPLATE_REL).is_file():
            return c
    return None


def available() -> bool:
    return skill_dir() is not None


def enabled(mode: str) -> bool:
    """mode: on / off / auto（auto = 装了技能才跑）。"""
    m = (mode or "auto").strip().lower()
    if m in ("off", "0", "false", "no"):
        return False
    if m in ("on", "1", "true", "yes"):
        return True
    return available()


# ---------------------------------------------------------------- 纯文本工具

def _esc(text: Any) -> str:
    return html_mod.escape(str(text if text is not None else ""), quote=True)


def units(text: str) -> float:
    """按显示宽度折算：CJK/全角 1 个单位，ASCII 0.55。"""
    total = 0.0
    for ch in str(text):
        total += 1.0 if ord(ch) > 0x2E80 else 0.55
    return total


def wrap_lines(text: str, per_line: float, max_lines: int) -> list[str]:
    """把一句话切成不超过 max_lines 行、每行不超过 per_line 个宽度单位。"""
    text = re.sub(r"\s+", " ", str(text or "").strip())
    if not text:
        return []
    lines: list[str] = []
    cur = ""
    cur_u = 0.0
    for ch in text:
        w = 1.0 if ord(ch) > 0x2E80 else 0.55
        if cur and cur_u + w > per_line:
            lines.append(cur)
            cur, cur_u = ch, w
            if len(lines) == max_lines:
                break
        else:
            cur += ch
            cur_u += w
    if len(lines) < max_lines and cur:
        lines.append(cur)
    rest = text[len("".join(lines)):]
    if rest.strip():
        # 截断了：最后一行补省略号（宁可少字，也不做三行大标题 —— 校验器的 R6 会判失败）
        lines[-1] = lines[-1].rstrip("，,、。;； ") + "…"
    return lines


def _wrap_no_cut(text: str, per_line: float) -> list[str]:
    """只换行、不截断（与 wrap_lines 的区别：这里的超出由调用方降字号解决）。"""
    text = re.sub(r"\s+", " ", str(text or "").strip())
    lines: list[str] = []
    cur, cur_u = "", 0.0
    for ch in text:
        w = 1.0 if ord(ch) > 0x2E80 else 0.55
        if cur and cur_u + w > per_line:
            lines.append(cur)
            cur, cur_u = ch, w
        else:
            cur += ch
            cur_u += w
    if cur:
        lines.append(cur)
    return [l for l in lines if l.strip()]


def clause_trim(text: str, per_line: float, max_lines: int) -> str:
    """从句尾按标点往前砍，直到能在 max_lines 行内排下 —— 宁可少一个从句，也不做三行标题、
    更不截半个词（技能 R4 的建议原文就是「cut copy instead of shrinking type」）。"""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(_wrap_no_cut(text, per_line)) <= max_lines:
        return text
    parts = re.split(r"(?<=[，,、；;。：:])", text)
    while len(parts) > 1:
        parts.pop()
        cand = "".join(parts).rstrip("，,、；;。：: ")
        if cand and len(_wrap_no_cut(cand, per_line)) <= max_lines:
            return cand
    return text


def title_html(text: str, kind: str = "xl", *, max_lines: Optional[int] = None) -> str:
    """标题：先按设计字号排，排不下就整档降字号（返回值不含字号，见 fit_title）。"""
    size, lines = fit_title(text, kind, max_lines=max_lines)
    return "<br>".join(_esc(l) for l in lines) or _esc(text)


def fit_title(text: str, kind: str = "xl", *, max_lines: Optional[int] = None) -> tuple[int, list[str]]:
    """挑字号：**先按设计字号砍从句，砍不动再整档降字号**（同技能的 R4 建议）。

    返回 (字号, 分行结果)。标题永远不会被截成半个词 —— 上一版对「可追溯推理的罕见病诊断智能体」
    直接吐出「罕见病诊断智…」，比小一号字难看得多。
    """
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    lim = max_lines or TITLE_LINES.get(kind, 2)
    ladder = SIZE_LADDER.get(kind, SIZE_LADDER["xl"])
    design = ladder[0]
    lines = _wrap_no_cut(text, AVAIL_PX / design)
    if len(lines) <= lim:
        return design, lines
    trimmed = clause_trim(text, AVAIL_PX / design, lim)
    lines = _wrap_no_cut(trimmed, AVAIL_PX / design)
    if len(lines) <= lim:
        return design, lines
    for size in ladder[1:]:
        lines = _wrap_no_cut(trimmed, AVAIL_PX / size)
        if len(lines) <= lim:
            return size, lines
    size = ladder[-1]
    return size, _wrap_no_cut(clause_trim(trimmed, AVAIL_PX / size, lim), AVAIL_PX / size)


def dedupe_parts(*parts: Any) -> list[str]:
    """`Nature · VOL 651 · 2026` 与 `Nature` 拼在一起会读成两个 Nature —— 互为子串的只留长的那个。"""
    out: list[str] = []
    for raw in parts:
        p = str(raw or "").strip(" ·")
        if not p:
            continue
        low = p.lower()
        if any(low in o.lower() or o.lower() in low for o in out):
            if any(len(low) > len(o) for o in out) and not any(low in o.lower() for o in out):
                out = [o for o in out if o.lower() not in low]
                out.append(p)
            continue
        out.append(p)
    return out


def seq_items(items: list[Any], *, limit: int = MAX_ITEMS_PER_PAGE) -> list[str]:
    out: list[str] = []
    for it in items:
        s = re.sub(r"\s+", " ", str(it or "")).strip(" -·•\t")
        if s:
            out.append(s)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- 页面装配

def _fig_src(page_fig: dict[str, Any], figures_dir: Path) -> Optional[Path]:
    name = str((page_fig or {}).get("file") or "").strip()
    if not name:
        return None
    cand = Path(name)
    if not cand.is_absolute():
        cand = Path(figures_dir) / name
    return cand if cand.is_file() else None


def _copy_asset(src: Path, assets: Path) -> str:
    assets.mkdir(parents=True, exist_ok=True)
    dst = assets / src.name
    if not dst.exists() or dst.stat().st_size != src.stat().st_size:
        shutil.copy2(src, dst)
    return f"assets/{src.name}"


def _bullet_rows(items: list[str], start: int = 1) -> str:
    rows = []
    for i, it in enumerate(items, start):
        rows.append(
            '      <div class="ledger-row">\n'
            f'        <span class="ledger-nb">{i:02d}</span>\n'
            f'        <span class="ledger-title">{_esc(it)}</span>\n'
            '        <span></span>\n'
            "      </div>"
        )
    return "\n".join(rows)


def _page(*, pid: str, kicker: str, title: Optional[str], title_kind: str, body_html: str,
          strip: list[str], title_size: Optional[int] = None) -> str:
    head = ""
    if kicker:
        head += f'        <p class="kicker">{_esc(kicker)}</p>\n'
    if title:
        style = f' style="font-size:{title_size}px"' if title_size else ""
        head += f'        <h2 class="h-{title_kind}"{style}>{title}</h2>\n'
    foot = "\n".join(f"        <span>{_esc(s)}</span>" for s in strip if s)
    return (
        f'    <section class="poster xhs" id="{_esc(pid)}">\n'
        '      <canvas class="mag-bg" data-bg="ink-flow"></canvas>\n'
        '      <div class="grain"></div>\n'
        '      <div class="content stack gap-3" style="padding-bottom:172px">\n'
        f"{head}{body_html}\n"
        "      </div>\n"
        '      <div class="issue-strip">\n'
        f"{foot}\n"
        "      </div>\n"
        "    </section>"
    )


def _assets_to_cover(cover: dict[str, Any]) -> dict[str, Any]:
    """无 cover spec 时，用主 spec 的字段凑一份封面（不新增事实）。"""
    return {
        "kicker": cover.get("kicker") or "",
        "title": cover.get("title") or "",
        "subtitle": cover.get("subtitle") or "",
        "teaser": cover.get("teaser") or {},
    }


def plan_pages(spec: dict[str, Any], cover: Optional[dict[str, Any]], digest: dict[str, Any],
               *, max_items: int = MAX_ITEMS_PER_PAGE) -> list[dict[str, Any]]:
    """spec → 组图页面计划（纯函数，不碰文件系统）。返回 [{kind, kicker, title, ...}]。"""
    pages: list[dict[str, Any]] = []
    cv = cover or {}
    pages.append({
        "kind": "cover",
        "kicker": cv.get("kicker") or spec.get("kicker") or "",
        "title": cv.get("title") or spec.get("title") or "",
        "subtitle": cv.get("subtitle") or spec.get("subtitle") or "",
        "teaser": cv.get("teaser") or spec.get("teaser") or {},
        "chips": (cv.get("chips") or spec.get("chips") or [])[:3],
        "venue": spec.get("venue") or "",
    })

    block_no = 0
    for col in spec.get("columns") or []:
        for blk in col if isinstance(col, list) else [col]:
            if not isinstance(blk, dict):
                continue
            block_no += 1
            if blk.get("kind") == "figure":
                pages.append({
                    "kind": "figure",
                    "kicker": f"证据 · 图 {blk.get('number') or block_no}",
                    "title": blk.get("caption") or "",
                    "figure": {"file": blk.get("file"), "number": blk.get("number")},
                })
            else:
                items = seq_items(blk.get("items") or blk.get("items_tall") or [], limit=max_items)
                if not items:
                    continue
                pages.append({
                    "kind": "panel",
                    "kicker": "要点 · 论文里的事实",
                    "title": blk.get("title") or "要点",
                    "items": items,
                })

    lims = [str(x) for x in (digest.get("limitations") or []) if str(x).strip()][:3]
    if lims:
        pages.append({"kind": "closing", "kicker": "判断 · 边界", "title": "别把它当结论，把它当线索",
                      "items": lims})
    return pages[:MAX_PAGES]


def build_html(pages: list[dict[str, Any]], figures_dir: Path, out_dir: Path, *,
               theme: str = DEFAULT_THEME, template: Path, note: str = "") -> dict[str, Any]:
    """把页面计划写成 index.html（模板来自技能安装目录，CSS 不落仓库）。"""
    theme = theme if theme in THEMES else DEFAULT_THEME
    tpl = Path(template).read_text(encoding="utf-8")
    # 主题是白名单常量，但仍走替换而不是拼接 —— 将来手滑传了别的字符串也注入不进 CSS
    tpl = re.sub(r'(<html\b[^>]*\bdata-theme=")[^"]*(")', rf"\g<1>{theme}\g<2>", tpl, count=1)

    override = """  <style>
    /* 本工作区唯一的中文字体是 Microsoft YaHei（没有中文衬线体），模板的 --serif-zh
       只列了 Noto Serif SC / Songti / STSong —— 一个都不存在，浏览器会回退到 DejaVu Serif，
       中英混排会跳变。这里把中文族显式指到雅黑，拉丁走 DejaVu Serif（本机唯一的衬线体）。
       装了 Noto Serif CJK 的机器可以删掉这一段。 */
    :root {
      --serif-zh: "Microsoft YaHei", "DejaVu Serif", serif;
      --serif-en: "DejaVu Serif", "Microsoft YaHei", serif;
      --sans-zh: "Microsoft YaHei", "DejaVu Sans", sans-serif;
      --mono: "DejaVu Sans Mono", ui-monospace, "SF Mono", Consolas, monospace;
    }
    /* 论文图表按「不裁剪、不拉伸」用 fit-contain，模板的 --paper-2 底色会留灰边；
       图表是证据，直接浮在纸面上更干净。 */
    .frame-img.fit-contain { background: transparent; }
    /* 上游模板的 .pipeline-v .step-title 间距 8px < 它自己 QA 的 16px 下限（R9 会 WARN）。 */
    .pipeline-v .step-title { margin-bottom: 18px; }
    /* 要点只有 3 条时，模板的 .ledger 会把内容挤在上半页、下半页留一大片空
       （技能自己的 R5 密度门是量「元素占位」不是量「墨迹」，抓不到）。让行均分撑满整页，
       行高下限 118px 来自技能 M08 Tall Ledger 的配方，上限 260px 防稀疏页被拉得发虚。 */
    .ledger { flex: 1 1 auto; justify-content: stretch; }
    .ledger-row { flex: 1 1 auto; align-items: center; min-height: 118px; max-height: 260px; }
  </style>
</head>"""
    tpl = tpl.replace("</head>", override)

    assets_dir = Path(out_dir) / "assets"
    used = 0
    sections: list[str] = []
    n = len(pages)
    for i, pg in enumerate(pages, start=1):
        pid = f"xhs-{i:02d}"
        strip = [f"{i:02d} / {n:02d}", "—", "PaperCast 论文速读"]
        if pg["kind"] == "cover":
            fig_html = ""
            src = _fig_src(pg.get("teaser") or {}, figures_dir)
            if src:
                rel = _copy_asset(src, assets_dir)
                used += 1
                fig_html = (
                    '        <figure class="frame-img r-16x10 fit-contain">\n'
                    f'          <img src="{_esc(rel)}" alt="{_esc(pg["title"])}">\n'
                    "        </figure>\n"
                )
            if pg.get("chips"):
                fig_html += (
                    '        <div class="row gap-2">'
                    + "".join(f'<span class="label">{_esc(c)}</span>' for c in pg["chips"])
                    + "</div>\n"
                )
            if pg.get("subtitle"):
                fig_html += f'        <p class="lead">{_esc(pg["subtitle"])}</p>\n'
            size, lines = fit_title(pg["title"], "display")
            head_kicker = " · ".join(dedupe_parts(pg.get("kicker"), pg.get("venue"), "PaperCast 论文速读"))
            body = (
                f'        <p class="kicker">{_esc(head_kicker)}</p>\n'
                f'        <h1 class="h-display" style="font-size:{size}px">'
                + "<br>".join(_esc(l) for l in lines) + "</h1>\n"
                + fig_html
            )
            sections.append(_page(pid=pid, kicker="", title=None, title_kind="xl", body_html=body,
                                  strip=strip))
        elif pg["kind"] == "figure":
            _size, _lines = fit_title(pg.get("title") or "", "xl")
            src = _fig_src(pg.get("figure") or {}, figures_dir)
            if not src:
                continue
            rel = _copy_asset(src, assets_dir)
            used += 1
            cap = pg.get("figure", {}).get("number")
            # 图卡页让画框撑满剩余高度：模板按 16:10 定高，图卡页下方会空出四分之一页。
            # 只用 style 去掉 aspect-ratio、"图本身"仍走 contain —— 不裁剪、不拉伸。
            body = (
                '        <figure class="frame-img fit-contain"'
                ' style="flex:1 1 auto;aspect-ratio:auto;min-height:0">\n'
                f'          <img src="{_esc(rel)}" alt="{_esc(pg.get("title"))}">\n'
                "        </figure>\n"
                + (f'        <p class="img-cap">Fig. {_esc(cap)}</p>\n' if cap else "")
            )
            sections.append(_page(pid=pid, kicker=pg["kicker"],
                                  title="<br>".join(_esc(l) for l in _lines),
                                  title_kind="xl", title_size=_size,
                                  body_html=body, strip=strip))
        elif pg["kind"] == "closing":
            blocks = []
            for it in pg.get("items") or []:
                _s, lines = fit_title(it, "md", max_lines=2)
                head = lines[0] if lines else it
                rest = "".join(lines[1:])
                blocks.append(
                    "        <div>\n"
                    f'          <h3 class="h-md">{_esc(head)}</h3>\n'
                    f'          <p class="body">{_esc(rest or "")}</p>\n'
                    "        </div>"
                )
            body = "\n".join(blocks) + '\n        <hr class="rule">\n'
            body += f'        <p class="meta">{_esc(note or "见原文")}</p>\n'
            msize, mlines = fit_title(pg["title"], "md")
            sections.append(_page(pid=pid, kicker=pg["kicker"],
                                  title="<br>".join(_esc(l) for l in mlines), title_kind="md",
                                  title_size=msize, body_html=body, strip=strip))
        else:  # panel
            psize, plines = fit_title(pg.get("title") or "", "xl")
            body = '        <div class="ledger">\n' + _bullet_rows(pg.get("items") or []) + "\n        </div>\n"
            sections.append(_page(pid=pid, kicker=pg["kicker"],
                                  title="<br>".join(_esc(l) for l in plines), title_kind="xl",
                                  title_size=psize, body_html=body, strip=strip))

    i = tpl.index('<main class="sheet">')
    j = tpl.index("</main>")
    out_html = tpl[:i] + '<main class="sheet">\n\n' + "\n\n".join(sections) + "\n  </main>" + tpl[j + len("</main>"):]

    out_dir = Path(out_dir)
    (out_dir / "index.html").write_text(out_html, encoding="utf-8")
    bg = Path(template).parent / BG_SCRIPT_REL.name
    if bg.is_file():
        _copy_asset(bg, assets_dir)
    return {"pages": len(sections), "assets": used, "html": str(out_dir / "index.html")}


def build(spec: dict[str, Any], cover: Optional[dict[str, Any]], digest: dict[str, Any],
          figures_dir: Path | str, out_dir: Path | str, *, theme: str = DEFAULT_THEME,
          max_items: int = MAX_ITEMS_PER_PAGE, keep_pages: Optional[int] = None,
          note: str = "") -> dict[str, Any]:
    """完整装配：spec → 页面计划 → index.html（+ assets/ + deck.plan.json）。"""
    sd = skill_dir()
    if not sd:
        raise FileNotFoundError(
            f"技能未安装：{SKILL_NAME}（跑 ./ops/install_skills.sh，或用 GUIZANG_SKILL_DIR 指到技能目录）"
        )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = plan_pages(spec, cover, digest, max_items=max_items)
    if keep_pages:
        pages = pages[:keep_pages]
    info = build_html(pages, Path(figures_dir), out_dir, theme=theme,
                      template=sd / TEMPLATE_REL, note=note)
    (out_dir / "deck.plan.json").write_text(
        json.dumps({"theme": theme, "pages": pages, "note": note}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    info.update({"ok": True, "skill": str(sd), "theme": theme,
                 "max_items": max_items, "plan": pages})
    return info


# ---------------------------------------------------------------- 渲染 / 自检

def renderer_script() -> Path:
    return workspace_root() / "ops" / "shot" / "render_social_deck.mjs"


def _json_tail(stdout: str) -> dict[str, Any]:
    for raw in reversed((stdout or "").strip().splitlines()):
        raw = raw.strip()
        if raw.startswith("{"):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                continue
    return {}


def _to_jpeg(frames: list[dict[str, Any]], *, quality: int = 88) -> int:
    """给每张组图 PNG 落一份 JPEG 侧车（q88、**不抽色**），返回成功的张数。

    为什么要有 JPEG：小红书原生口径就是 1080×1440，上传后平台还会再压一遍；动辄 20MB 的
    2x PNG 换不到可见的清晰度，反而让上传更容易超时。subsampling=0（4:4:4）是关键——
    关掉色度抽样，中文/英文细笔画才不会发毛，文本页也能用 JPEG。
    PNG 仍然保留，当可编辑母版；投递取 JPEG（见 publish._deck_images / poster_stage）。
    """
    from PIL import Image  # 只在真要转的时候才 import（组图关闭时不该被 Pillow 拖住）

    n = 0
    for fr in frames:
        src = Path(str(fr.get("path") or ""))
        if not src.is_file():
            continue
        dst = src.with_suffix(".jpg")
        try:
            Image.open(src).convert("RGB").save(
                dst, "JPEG", quality=quality, optimize=True, subsampling=0)
        except OSError:
            continue
        fr["jpeg"] = str(dst)
        fr["jpegBytes"] = dst.stat().st_size
        n += 1
    return n


def render(out_dir: Path | str, *, scale: int = 1, jpeg: bool = True, quality: int = 88,
           node: str = "node", timeout: int = 300) -> dict[str, Any]:
    """渲染组图。scale=1 就是小红书原生口径 1080×1440（2026-09-19 从 2 改回 1）。

    画布字号本来就是按 1080 宽排的，2x 只是像素翻倍、体积翻 3 倍、且多出 20MB 的上传负担；
    JPEG 侧车（jpeg=True）才是给渠道用的那份。
    """
    script = renderer_script()
    if not script.is_file():
        raise FileNotFoundError(f"组图渲染入口不存在：{script}")
    proc = subprocess.run(
        [node, str(script), str(out_dir), "--scale", str(scale)],
        capture_output=True, text=True, timeout=timeout,
    )
    info = _json_tail(proc.stdout or "")
    if not info:
        raise RuntimeError(f"渲染器无 JSON 输出（exit={proc.returncode}）：{(proc.stderr or '')[-300:]}")
    info["exit"] = proc.returncode
    info["scale"] = scale
    if jpeg and info.get("ok"):
        info["jpegs"] = _to_jpeg(info.get("frames") or [], quality=quality)
    return info


SUMMARY_RE = re.compile(r"sections:\s*(\d+)\s*·\s*(\d+)\s*clean\s*·\s*(\d+)\s*fails\s*·\s*(\d+)\s*warns")
RULE_RE = re.compile(r"R(\d+)=(\d+)")
DETAIL_RE = re.compile(r"^\s*(FAIL|WARN)\s*·\s*(R\d+)\s+(.*)$")


def parse_validate(stdout: str) -> dict[str, Any]:
    """解技能自检的输出：摘要行 + 每条 FAIL/WARN。"""
    out: dict[str, Any] = {"sections": 0, "clean": 0, "fails": 0, "warns": 0, "rules": {}, "details": []}
    m = SUMMARY_RE.search(stdout or "")
    if m:
        out.update(sections=int(m.group(1)), clean=int(m.group(2)),
                   fails=int(m.group(3)), warns=int(m.group(4)))
    for line in (stdout or "").splitlines():
        if line.strip().startswith("rules:"):
            out["rules"] = {f"R{k}": int(v) for k, v in RULE_RE.findall(line)}
        d = DETAIL_RE.match(line)
        if d:
            out["details"].append({"level": d.group(1), "rule": d.group(2), "text": d.group(3).strip()})
    return out


def validate(out_dir: Path | str, *, node: str = "node", timeout: int = 300) -> dict[str, Any]:
    sd = skill_dir()
    if not sd:
        raise FileNotFoundError(f"技能未安装：{SKILL_NAME}")
    script = sd / "validate-social-deck.mjs"
    if not script.is_file():
        raise FileNotFoundError(f"技能里没有自检脚本：{script}")
    proc = subprocess.run([node, str(script), str(out_dir)], capture_output=True, text=True, timeout=timeout)
    info = parse_validate(proc.stdout or "")
    info["exit"] = proc.returncode
    info["stderr"] = (proc.stderr or "")[-300:]
    return info
