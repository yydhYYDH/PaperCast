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

# 组图页数上限。小红书单篇最多 18 张；这里留 12 是给「多放原图」让路
# （2026-09-26：原来 9 张上限 + 只有 1 张原图，7 页组图里 6 页是纯文字）。
MAX_PAGES = 12
MAX_ITEMS_PER_PAGE = 4
#: 组图里最多用几张**不同的论文原图**（含 LLM 自己选的那几张 + 封面 teaser 不算）。
#: 2026-09-26 用户要求：小红书组图里要多放原图，29 张源图（6 fig + 23 table）只出 1 张太浪费。
MAX_FIGURE_PAGES = 6
#: 低于这个像素尺寸的图不进组图：1080 宽的画布上放大一张 200px 的图只会糊成噪点。
MIN_FIG_PX = 320
#: 只收 fig-*（figure），不收 table-*：表格在 3:4 竖图里字太小、看不清，
#: 而 fig-* 是架构图/流程图这类信息密度高的证据图。
FIG_FILE_RE = re.compile(r"^fig-\d+\.[a-z]+$", re.I)
#: 封面主图的画框比例。16:10 在 904px 宽下占 565px —— 内容区（1076px）的一半还多，
#: 留给副标题只有 1.5 行，于是「痛点→方法→结果」根本写不下（实测 SpeakerMem 的副标题
#: 已经超出内容区 18px）。压到 16:9（508px）腾出 57px，配合标题 112→100 省的 25px，
#: 副标题能放 4 行 ≈ 130 字，够写完整一句「痛点→方法→结果」。
#: 用 16:9 而不是 21:9：论文原图实测比例 1.27–2.18（fig-4 是 2.18，fig-1/2/3 只有 1.4），
#: 21:9 会把 1.4 的架构图压成一条看不清的窄带。
COVER_FIG_RATIO = "16x9"

# 字号 → 每行能放多少个「汉字宽度单位」（西文/数字按 ASCII_EM 计，见 units）。
# 依据：画布 1080、内容左右各留 88px → 可用 904px；h-display 112px、h-xl 88px、h-md 56px。
UNITS_PER_LINE = {"display": 880.0 / 112, "xl": 880.0 / 88, "md": 880.0 / 56}
TITLE_LINES = {"display": 2, "xl": 2}
# 标题放不下时的降级字号阶梯（先降字号，**绝不截字** —— 截出来的「罕见病诊断智…」比小一号难看十倍）。
# display 顶档 100（原 124 → 112 → 100）：封面大标题两轮收小。第一轮 124→112 修的是
# 「SpeakerMem-R1：双轨记忆」断成三行落单字母（R6 WARN）；第二轮 112→100 是为了给
# 副标题腾出 4 行的空间（主图 16:10→16:9 只腾 57px，标题再让 25px 才够写完整一句）。
SIZE_LADDER = {"display": (100, 92, 84, 76, 68, 60), "xl": (88, 80, 72, 64, 58), "md": (56, 50, 44)}
AVAIL_PX = 880.0   # 1080 画布 - 左右各 88px 内边距 - 一点 letter-spacing 余量
#: 一个「汉字宽度单位」= 1.0em。ASCII 用实测值而非拍脑袋的 0.55：
#: Noto Serif SC 缺失、实际回退到 DejaVu Serif 时，124px 下 13 个字符的
#: 「SpeakerMem-R1」实测 1083px → 0.672em/字（含 .04em 字距）。0.55 会把
#: 「SpeakerMem-R」估成「装得下」（实际 999px > 可用 904px），于是 fit_title 预测
#: 2 行、浏览器渲 3 行，落单一个「R」。宁可高估一点走降字号，也不预测「装得下」。
ASCII_EM = 0.67
#: 各级标题的 letter-spacing（em/字），取自技能模板的 CSS：.h-display .04em、.h-xl .03em、.h-md .02em。
#: **必须计入宽度模型**：字距是「每字」累加的，字符越多越致命。88px 下 10 个汉字的字距就有
#: 26.4px，而 AVAIL_PX 只留了 24px 余量 —— 于是模型算 880px「装得下」、浏览器算 906px 装不下，
#: 再折一次变三行（run_f308d04cf07a 的「注意力修补：结构比内容更关键」就是这么挂的 R6）。
TRACK_EM = {"display": 0.04, "xl": 0.03, "md": 0.02}
#: 行首禁则：这些字符不能起一行（避头尾）。只在**仍能装下**时才留在上一行。
NO_LINE_START = "，。、；：？！）〕］｝〉》」』】…—～·%‰,.;:?!)]}"
#: 行尾禁则：这些字符不能收在一行末尾。
NO_LINE_END = "（〔［｛〈《「『【([{"
#: 西文单词与数字连写：连字符是合法断点（可断在「SpeakerMem-」后），但词内不断。
_WORD_RE = re.compile(r"[0-9A-Za-z]+[-\u2010\u2013\u2014]?")
#: **整个强调区间是不可断的原子，但只限短区间。** 踩过的坑（2026-09-26）：
#: `==62.33%==` 逐字换行时被断成「==62」+「.33%==」分到两行，而 inline() 是**逐行**跑的，
#: `==` 开合不在同一行就匹配不上 —— 页面上直接印出字面的 `==62 .33%==`。
#: 上限 EMPH_ATOM_MAX 是另一半：整段加粗（60 字）若也当原子，就成了一条断不开的长行、
#: 直接溢出画布。提示词本来就要求「只标短语、不套整句」，这里只兜住不听话的情况。
EMPH_ATOM_MAX = 24
_EMPH_ATOM_RE = re.compile(r"\*\*.{1,%d}?\*\*|==.{1,%d}?==" % (EMPH_ATOM_MAX, EMPH_ATOM_MAX), re.S)


def line_units(text: str, track: float = 0.0) -> float:
    """一行实际占多宽：字形前进宽度 + 每字 letter-spacing。

    `track` 是 em/字（见 TRACK_EM）。不看字距就会系统性低估长行 —— 而低估的代价
    是「模型说装得下、浏览器说装不下」，行数与实际不符，坏图直接发出去。
    强调记号不占像素，先剥掉（plain）。
    """
    body = plain(text)
    return units(body) + track * len(body)


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

#: 行内强调记号：**粗体** 与 ==底色高亮==。
#: 只认这两个（小红书信息流里最常见的两种强调），且**只由 inline() 转成固定标签** ——
#: 模型给的是纯文本，永远不允许它注入任意 HTML。
EMPH_BOLD = "**"
EMPH_MARK = "=="
_EMPH_RE = re.compile(r"\*\*(.+?)\*\*|==(.+?)==", re.S)
_MARKUP_ONLY_RE = re.compile(r"\*\*|==")


def _esc(text: Any) -> str:
    return html_mod.escape(str(text if text is not None else ""), quote=True)


def plain(text: Any) -> str:
    """去掉强调记号，只留字面文本 —— 量宽度时必须用它（`==` 不占像素）。"""
    return _MARKUP_ONLY_RE.sub("", str(text if text is not None else ""))


def inline(text: Any) -> str:
    """转义后把 **粗体** / ==底色== 换成固定标签。

    顺序是**先转义、再替换**，且只吐 `<strong>` / `<mark class="hl">` 两个标签：
    记号本身不含 `<`，所以转义不会破坏它们；而替换用的模板是硬编码的，
    捕获组又是**已经转义过**的内容 —— 模型给不出可执行的 HTML。

    末尾还有一道**兜底**：把没配上的残留记号删掉。短强调区间已被 `_tokenize` 当成原子、
    不会跨行断开；但整段加粗（>EMPH_ATOM_MAX）仍可能断开，那时就宁可丢掉强调效果，
    也不能让字面的 `**` / `==` 印到卡片上（页面上出现 `==62 .33%==` 是最丢人的一种坏图）。
    """
    out = _esc(text)
    out = _EMPH_RE.sub(
        lambda m: (f"<strong>{m.group(1)}</strong>" if m.group(1) is not None
                   else f'<mark class="hl">{m.group(2)}</mark>'),
        out,
    )
    return _MARKUP_ONLY_RE.sub("", out)


def _char_units(ch: str) -> float:
    """单字宽度（单位 = em）。CJK/全角 1.0，西文与数字用实测的 ASCII_EM。"""
    return 1.0 if ord(ch) > 0x2E80 else ASCII_EM


def units(text: str) -> float:
    """按显示宽度折算：CJK/全角 1 个单位，ASCII ASCII_EM 个。忽略强调记号。"""
    return sum(_char_units(ch) for ch in plain(text))


def wrap_lines(text: str, per_line: float, max_lines: int) -> list[str]:
    """把一句话切成不超过 max_lines 行、每行不超过 per_line 个宽度单位。"""
    text = re.sub(r"\s+", " ", str(text or "").strip())
    if not text:
        return []
    lines: list[str] = []
    cur = ""
    cur_u = 0.0
    for ch in text:
        w = _char_units(ch)
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


def _tokenize(text: str) -> list[str]:
    """切成「不可再分的排版单元」。

    西文单词与数字连成一个 token（不在词内断行），但**连字符是合法断点** ——
    「SpeakerMem-R1」切成「SpeakerMem-」+「R1」，所以封面标题能断在连字符后，
    而不会像逐字贪心那样断成「SpeakerMem」/「R1：…」（把产品名拆两半）。
    CJK 逐字成 token（中文任意位置都可断）。标点单独成 token，由避头尾规则处理。
    强调记号（`**`、`==`）也单独成 token：**必须留在流里**，否则换行后的行会丢掉记号、
    末尾的 inline() 就渲染不出加粗/底色了（它们在 line_units 里按 0 宽算）。
    """
    out: list[str] = []
    i = 0
    while i < len(text):
        emph = _EMPH_ATOM_RE.match(text, i)
        if emph:
            out.append(emph.group(0))
            i = emph.end()
            continue
        m = _WORD_RE.match(text, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        out.append(text[i])
        i += 1
    return out


def _wrap_no_cut(text: str, per_line: float, track: float = 0.0) -> list[str]:
    """只换行、不截断（与 wrap_lines 的区别：这里的超出由调用方降字号解决）。

    按 token 贪心换行，并做两件中英混排该做的事：
      · 避头 —— 标点不另起一行，但**只有仍能装下**才留在上一行；装不下就宁可让它起行
        （溢出比标点起行难看得多，浏览器也会把超宽的行再折一次，反而更糟）；
      · 避尾 —— 上一行末尾是开引号/开括号时，把它带下去。

    `track` 是每字 letter-spacing（em），要算进每行宽度，见 line_units。
    """
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    lines: list[str] = []
    cur, cur_u = "", 0.0
    for tok in _tokenize(text):
        w = line_units(tok, track)
        if cur and cur_u + w > per_line:
            # 避头：标点不另起一行。允许**悬挂**（超出 per_line 一点）—— CJK 排版里
            # 标点挂出边界是标准做法；早先为了「绝不溢出」直接放弃避头，结果
            # SpeakerMem 的要点页标题第二行以「：」开头（避头铁律 visibly 破掉）。
            # 悬挂上限 1.5em：超出这个量就不是「标点挂一下」而是排版算错了。
            if tok[0] in NO_LINE_START and cur_u + w <= per_line + 1.5:
                cur += tok
                cur_u += w
                continue
            if cur[-1] in NO_LINE_END:           # 开引号/开括号不留在行尾
                moved = cur[-1] + tok
                lines.append(cur[:-1])
                cur, cur_u = moved, line_units(moved, track)
                continue
            lines.append(cur)
            cur, cur_u = tok, w
        else:
            cur += tok
            cur_u += w
    if cur:
        lines.append(cur)
    return [l for l in lines if l.strip()]



def clause_trim(text: str, per_line: float, max_lines: int, track: float = 0.0) -> str:
    """从句尾按标点往前砍，直到能在 max_lines 行内排下 —— 宁可少一个从句，也不做三行标题、
    更不截半个词（技能 R4 的建议原文就是「cut copy instead of shrinking type」）。"""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(_wrap_no_cut(text, per_line, track)) <= max_lines:
        return text
    parts = re.split(r"(?<=[，,、；;。：:])", text)
    while len(parts) > 1:
        parts.pop()
        cand = "".join(parts).rstrip("，,、；;。：: ")
        if cand and len(_wrap_no_cut(cand, per_line, track)) <= max_lines:
            return cand
    return text


def title_html(text: str, kind: str = "xl", *, max_lines: Optional[int] = None) -> str:
    """标题：先按设计字号排，排不下就整档降字号（返回值不含字号，见 fit_title）。"""
    size, lines = fit_title(text, kind, max_lines=max_lines)
    return "<br>".join(_esc(l) for l in lines) or _esc(text)


def _fits(lines: list[str], per_line: float, track: float = 0.0) -> bool:
    """每一行都必须真的装得下 —— 只看行数会漏掉「单词本身就超宽」的情况。

    这是 2026-09-26 那次封面三行标题的第二道保险：112px 顶档下「SpeakerMem-」连字距一起
    算都还超一点时，宁可降到下一档，也不要交出一个「模型说两行、浏览器渲三行」的断法。
    **溢出必须判为不可用**。
    """
    return all(line_units(l, track) <= per_line + 1e-9 for l in lines)


def fit_title(text: str, kind: str = "xl", *, max_lines: Optional[int] = None) -> tuple[int, list[str]]:
    """挑字号：**先按设计字号砍从句，砍不动再整档降字号**（同技能的 R4 建议）。

    返回 (字号, 分行结果)。标题永远不会被截成半个词 —— 上一版对「可追溯推理的罕见病诊断智能体」
    直接吐出「罕见病诊断智…」，比小一号字难看得多。

    字号合法的条件有两条，缺一不可：**行数不超上限**且**每一行都装得下**（见 _fits）。
    宽度按 line_units 算，含该级的 letter-spacing（TRACK_EM）。
    """
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    lim = max_lines or TITLE_LINES.get(kind, 2)
    ladder = SIZE_LADDER.get(kind, SIZE_LADDER["xl"])
    track = TRACK_EM.get(kind, 0.0)
    design = ladder[0]
    lines = _wrap_no_cut(text, AVAIL_PX / design, track)
    if len(lines) <= lim and _fits(lines, AVAIL_PX / design, track):
        return design, lines
    trimmed = clause_trim(text, AVAIL_PX / design, lim, track)
    lines = _wrap_no_cut(trimmed, AVAIL_PX / design, track)
    if len(lines) <= lim and _fits(lines, AVAIL_PX / design, track):
        return design, lines
    for size in ladder[1:]:
        lines = _wrap_no_cut(trimmed, AVAIL_PX / size, track)
        if len(lines) <= lim and _fits(lines, AVAIL_PX / size, track):
            return size, lines
    size = ladder[-1]
    return size, _wrap_no_cut(clause_trim(trimmed, AVAIL_PX / size, lim, track), AVAIL_PX / size, track)


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


#: 要点清单（.ledger）能占的净高。实测：内容区 1076px 减去 kicker 27、标题（1-2 行）、
#: stack 行距与 3 条分隔线，留给行本身约 950px。**按条数均分**就是每行的上限 ——
#: 之前写死 260px（3 条时下面空 200px），改成 330px 又让 4 条直接顶穿内容区、
#: R2 判「ledger-title 压到页脚」FAIL，把整组图触发减内容重排砍掉一半。
#: 算出来的值写进 `--row-max`，由 CSS 消费：条数一变高度自动跟着变。
LEDGER_BUDGET_PX = 950.0
LEDGER_ROW_MIN_PX = 118
LEDGER_ROW_CEIL_PX = 330


def _row_max_px(n: int) -> int:
    """n 条要点时每行的高度上限（px）。3 条≈316、4 条≈237，都不会越界。"""
    if n <= 0:
        return LEDGER_ROW_CEIL_PX
    return max(LEDGER_ROW_MIN_PX, min(LEDGER_ROW_CEIL_PX, int(LEDGER_BUDGET_PX / n)))


def _bullet_rows(items: list[str], start: int = 1) -> str:
    rows = []
    for i, it in enumerate(items, start):
        rows.append(
            '      <div class="ledger-row">\n'
            f'        <span class="ledger-nb">{i:02d}</span>\n'
            f'        <span class="ledger-title">{inline(it)}</span>\n'
            '        <span></span>\n'
            "      </div>"
        )
    return "\n".join(rows)


#: 只会分类、不传递任何信息的「标签式标题」。2026-09-26 用户打回的就是这类：
#: 「两个瓶颈」「三个提升」—— 读者读完只知道这篇论文分了几块，不知道难点是什么。
LABEL_TITLES = {
    "问题", "数据", "结果", "方法", "实验", "消融", "结论", "背景", "挑战", "概览",
    "要点", "分析", "总结", "本文", "工作", "贡献", "优势", "提升", "瓶颈", "发现",
    "证据", "判断", "边界", "解读", "速读", "论文", "介绍", "内容", "部分", "维度",
}
#: 「关键/核心/主要 + 名词」是指路牌，不是判断：「关键结果」只是说"看这里"。
_LABEL_POINTER_RE = re.compile(r"^(?:关键|核心|主要|以上|如下|如下所示|具体|详细)")
#: 「数量词 + 名词」也算标签：「两个瓶颈」「三项提升」「几条结论」。
_LABEL_COUNT_RE = re.compile(
    r"^\s*[一二三四五六七八九十两半几\d]+\s*(?:个|条|项|种|类|点|步|组|大|种)?\s*"
    r"(?:瓶颈|问题|提升|结论|发现|方法|要点|贡献|优势|挑战|局限|实验|结果|分析|总结|维度|方面|部分|点)\s*$"
)
#: 冒号后半句里出现这些词，才算「有判断」。用来把「方法：双轨写入 + 查询组合」（纯描述）
#: 和「方法：双轨记忆解决归因」（有判断）区分开。
CLAIM_HINT_RE = re.compile(
    r"因为|所以|但|却|仍|更|难|易|记不住|记错|丢失|解决|超过|优于|翻倍|退化|恢复|不如|掩盖|暴露|代价"
)


def label_like(title: str) -> bool:
    """这个标题是不是「只有分类、没有判断」？

    用来兜住 LLM 不听话的情况：提示词已经要求标题是「一句能站住的判断」，
    但模型仍会写「两个瓶颈」「方法：双轨写入 + 查询组合」（2026-09-26 实测两种都出现过）。

    三种形态都要认：
      1. 整词标签：问题 / 数据 / 结果 / 方法 / 实验 / 消融…
      2. 「数量词 + 名词」：两个瓶颈 / 5个问题 / 三项提升
      3. **「标签：内容」前缀**：方法：双轨写入 + 查询组合 —— 前半截是标签，
         整句就不算判断句。冒号后若还看得出判断（「方法：双轨记忆解决归因」）就不算。
    """
    t = re.sub(r"\s+", "", str(title or ""))
    if not t:
        return True
    if t in LABEL_TITLES:
        return True
    if _LABEL_COUNT_RE.match(t):
        return True
    if _LABEL_POINTER_RE.match(t):
        return True
    # 「标签：内容」前缀（2026-09-26 实测「方法：双轨写入 + 查询组合」也是标签）
    m = re.match(r"^([^：:]{1,6})[：:](.+)$", t)
    if m and m.group(1) in LABEL_TITLES:
        # 冒号后若看得出判断就放过：「方法：双轨记忆解决归因」是判断，「方法：双轨写入」不是
        if not CLAIM_HINT_RE.search(m.group(2)):
            return True
    return False


def _clause_head(item: str) -> str:
    """取一条要点里「冒号前」的那截小标签 —— 它通常本身就是一句判断。

    实测（2026-09-26）：要点常写成「标签：解释」的结构，冒号前那截就是现成的标题 ——
    「消息归因与关系理解：谁说了什么、每条陈述涉及谁」→ 「消息归因与关系理解」（9 字，88px 一行）；
    「提出叠加线性假设：两条流被线性组合后…」→「提出叠加线性假设」（8 字）。
    没有标点就退而取整条。**只在括号外断句**（见 _BRACKET_OPEN 的坑）。
    """
    s = re.sub(r"\s+", " ", str(item or "")).strip()
    depth = 0
    for i, ch in enumerate(s):
        if ch in _BRACKET_OPEN:
            depth += 1
        elif ch in _BRACKET_CLOSE:
            depth = max(0, depth - 1)
        elif depth == 0 and ch in "：:，,；;":
            return s[:i].strip()
    return s


#: 括号对：`_clause_head` 只在括号外断句。
#: 踩过的坑（2026-09-26）：「EverMemBench 公开排行榜取得 62.33%（1,496/2,400），为最新…」在
#: 括号内那个「,」处被断开 → 切出「EverMemBench 公开排行榜取得 62.33%（1」，
#: 尾巴上一个没关的「（」直接印在卡片标题上。
_BRACKET_OPEN = "（(【[〔「『《"
_BRACKET_CLOSE = "）)】]〕」』》"

#: 标题候选的否决条件（实测踩到的坏例子都栽在这里）：
#:  - 「GroupMemBench 47.9%、SocialMemBench 69.2%、EverMemBench 61.9%」→ 纯指标清单
#:  - 「EverMemBench 公开排行榜取得 62.33%（1」→ 尾巴挂着没关的括号
#:  - 「305 题受控评测」→ 以数字结尾，像数据项不像判断
#: 尾巴这组的括号**不能加 ?**：`(?:（|\()$` 一旦写成 `[（(]?$` 就成了「可选括号 + 行尾」，
#: 在任何字符串末尾都匹配**空串** —— 于是所有候选全被否掉，兜底彻底失效（实测踩过）。
_TITLE_BAD_TAIL_RE = re.compile(r"[%％\d）)】\]」』、，,。.：:；;]|(?:（|\()\s*$")
_TITLE_METRIC_RE = re.compile(r"(?:%|％).*(?:%|％)")



def _title_candidate_ok(head: str, per_line: float) -> bool:
    """这截小标签能不能当标题。门槛要比「看起来像一句话」严得多。"""
    if not (3 <= len(head) <= 16):
        return False
    if sum(1 for ch in head if ord(ch) > 0x2E80) < 2:   # 至少两个汉字；纯数字/纯西文不算判断
        return False
    if _TITLE_BAD_TAIL_RE.search(head):                 # 尾巴是数字/百分号/标点/没关的括号
        return False
    if _TITLE_METRIC_RE.search(head):                   # 两个以上百分号 = 指标清单
        return False
    return line_units(head, TRACK_EM["xl"]) <= per_line


def _strip_head(item: str, head: str) -> str:
    """把要点开头那段已经被提成标题的标签去掉，只留解释。

    「消息归因与关系理解：谁说了什么、每条陈述涉及谁」在标题已经写了「消息归因与关系理解」
    之后，要点里再出现一遍就是同一句话说了两次。去掉前缀后是
    标题「消息归因与关系理解」+ 要点「谁说了什么、每条陈述涉及谁」—— 标题 + 解释，
    而不是标题 + 它的复制品。只在**完全同前缀**时才动，别误伤只是碰巧开头相近的要点。
    """
    s = re.sub(r"\s+", " ", str(item or "")).strip()
    if not head or not s.startswith(head):
        return s
    rest = s[len(head):].lstrip()
    return rest.lstrip("：:，,；;、") if rest else s


def informative_title(title: str, items: list[str], *, design: Optional[int] = None) -> str:
    """标题是标签式（「两个瓶颈」「方法：…」）时，从要点里切一个小标签顶上。

    2026-09-26 修掉的两个坏实现：
      ① `fit_caption(第一条要点)` → 标题变成第 1 条的**截断版**，同一张卡上同一句话说两遍；
      ② 兜底循环**完全没有质量门槛**（`if head:` 就收），于是
         「System 1 逐字轨道不使用语言模型」「GroupMemBench 47.9%」这种实现细节或
         纯指标清单被当成标题印到卡片上 —— 比「关键结果」这种无聊标签更糟。

    现在：只接受通过 `_title_candidate_ok` 的短标签，按**要点顺序取第一个**合格的
    （阅读顺序 = 模型自己的强调顺序）；一个都不过就**原样保留原标题**，绝不硬塞更差的。
    """
    if not label_like(title):
        return str(title or "")
    per_line = AVAIL_PX / (design or SIZE_LADDER["xl"][0])
    for it in items or []:
        head = _clause_head(it)
        if _title_candidate_ok(head, per_line):
            return head
    return str(title or "")

    kind = "xl"
    design = design or SIZE_LADDER[kind][0]
    per_line = AVAIL_PX / design
    for it in items or []:
        head = _clause_head(it)
        if 3 <= len(head) <= 16 and line_units(head, TRACK_EM[kind]) <= per_line:
            return head
    for it in items or []:
        head = _clause_head(it)
        if head:
            _size, lines = fit_title(head, kind)     # 降字号保证不截断
            return "".join(lines)
    return str(title or "")


#: 收尾页留给「限制条目」的净高预算。实测：内容区 1076px（1440 - 上下 96 - 页脚留白 172）
#: 减去 kicker 27、标题 66、stack 行距 2×~54、rule、meta 24、容器内边距 2×20 ≈ 780px。
#: 取 700 留一点余量 —— 顶到边界就会触发 R2「meta 压到页脚」FAIL，进而被减内容重排
#: 把整组图砍到 3 页（2026-09-26 实测 run_f308d04cf07a）。
LIM_BUDGET_PX = 700.0
#: 限制条目的行高（与 CSS `.limits .lim { line-height }` 必须一致，否则算出来的高度是假的）
LIM_LINE_H = 1.42
#: 收尾页至少留几条限制 —— 少于 2 条就失去了「别把它当结论」的意义
LIM_MIN_ITEMS = 2


def short_note(note: Any) -> str:
    """出处行只留**来源**，不留论文标题。

    原来传进来的是 `venue · 论文标题`，而这张卡是 .meta（大写、拉开字距的 mono）——
    一整篇英文标题变成 3 行全大写、压在页面最下面，比页脚条还重。论文标题封面已经有了，
    这里只该写「来自哪儿」：arXiv 2609.29845 / Nature 651。
    """
    raw = re.sub(r"\s+", " ", str(note or "")).strip(" ·")
    if not raw:
        return ""
    head = re.split(r"[·|]", raw, maxsplit=1)[0].strip()
    return head if head else raw[:40]


#: 提示词禁止的第三人称自称。用户 2026-09-26 明确要求：不要「本文」「作者」，
#: 用方法/模型名当主语。提示词是软约束 —— 这里做确定性兜底。
SELF_REF_RE = re.compile(r"本文|该论文|本论文|本工作|这篇论文|作者(?:们)?|我们")


#: 中文方法名要在这些助词/连词处断开 —— 「双轨记忆的写入与查询」的方法名是「双轨记忆」，
#: 不是「双轨记忆的写入与」。贪心取 8 个字会得到一个读不通的半截短语。
_CJK_NAME_STOP = "的地得了着过和与或是在把用对为能可不没也很更再又从到让使得比等但却只"


def method_name(title: str) -> str:
    """从标题里取方法/模型名当主语：优先开头的西文词（SpeakerMem-R1、Transformer），
    没有西文就取标题里第一个中文短语（双轨记忆、叠加线性），到助词处为止。"""
    t = re.sub(r"\s+", " ", str(title or "")).strip()
    m = re.match(r"[A-Za-z0-9][A-Za-z0-9\-\.]{2,}", t)
    if m:
        return m.group(0)
    m = re.match(r"[一-鿿]{2,8}", t)
    if not m:
        return ""
    run = m.group(0)
    cut = next((i for i, ch in enumerate(run) if ch in _CJK_NAME_STOP), len(run))
    return run[:cut] if cut >= 2 else run


def de_selfref(text: str, name: str) -> tuple[str, bool]:
    """把「本文/该论文/作者/我们」换成方法名。返回 (改写后的文本, 是否动过)。

    换不出方法名时**只删词不硬塞主语**：「本文提出一种双轨记忆」→「提出一种双轨记忆」
    读起来残缺，但比留着「本文」强；提示词会给出方法名，所以这只是个兜底。
    """
    raw = str(text or "")
    if not SELF_REF_RE.search(raw):
        return raw, False
    out = SELF_REF_RE.sub(name, raw) if name else SELF_REF_RE.sub("", raw)
    return re.sub(r"\s{2,}", " ", out).strip(), True


#: 封面副标题（.lead）能占的高度。实测布局：chips 底 1082 → 内容区底 1268 = 150px
#: （标题 100px×2 行=212、主图 16:9=509、chips 24、gap 36×4，都已定死）。
#: 28px/行高 1.55 = 43.4px 一行 → 150px 只放得下 3 行（96 字）。第 4 行会超出 23px。
#: 注意技能校验器**抓不到这个溢出**（它只查 .h-xl/.foot 等），实测副标题超 18px 仍报
#: 0 fail 0 warn —— 所以行数必须在这里自己算死。
LEAD_BUDGET_PX = 150.0
LEAD_SIZES = (28, 26, 24)
LEAD_TRACK = 0.0          # .lead 没设 letter-spacing


def fit_lead(text: str, budget_px: float = LEAD_BUDGET_PX) -> tuple[int, str]:
    """封面副标题：按 28→26→24 逐级缩字号，直到整段排得进预算；都不行就在句号处截断。

    为什么不只靠提示词约束字数：超出的后果是静默的（校验器不报、页面上看着"就那样"），
    而封面是唯一会被截图分享的一页。宁可字小一号，也不能掉出内容区。
    """
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw:
        return LEAD_SIZES[0], ""
    per_line = AVAIL_PX / LEAD_SIZES[0] * 1.0   # units per line at 28px
    for size in LEAD_SIZES:
        pl = AVAIL_PX / size
        lines = _wrap_no_cut(raw, pl, LEAD_TRACK)
        if len(lines) * size * 1.55 <= budget_px:
            return size, "<br>".join(inline(l) for l in lines)
    # 最小号仍放不下：按句子截断（保留第一句 + 省略号），标点比断在半截词上好看
    size = LEAD_SIZES[-1]
    pl = AVAIL_PX / size
    max_lines = max(1, int(budget_px // (size * 1.55)))
    kept, cur, cur_u, used = [], "", 0.0, 0
    for tok in _tokenize(raw):
        w = units(tok)
        if cur and cur_u + w > pl:
            if used + 1 >= max_lines:
                break
            kept.append(cur)
            cur, cur_u = tok, w
            used += 1
        else:
            cur += tok
            cur_u += w
    if cur and used + 1 <= max_lines:
        kept.append(cur)
    out = "".join(kept).strip().rstrip("，,、；;")
    return size, inline(out) + "…" if out else size, inline(raw)


def _img_aspect(path: Path) -> Optional[tuple[int, int]]:
    """读原图尺寸，给画框一个正确的 aspect-ratio。读不到就返回 None（退回 flex:1）。"""
    try:
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
        return (w, h) if w > 0 and h > 0 else None
    except Exception:
        return None


def _caption_title(raw: str, *, max_lines: int = 3) -> str:
    """没有中文说明时的退化路径：把英文图注**断在句号**上，别断在半截词。

    原来是按 token 贪心截断，于是印出过「Memory-path and hierarchy ablations. Labels
    show accuracy…」这种半句话 —— 既外语、又断在半截。改成：
      ① 先按句号切，取够长的前几句；
      ② 句号不够长才按词边界兜底，并明确标出这是英文原注。
    """
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text:
        return ""
    sentences = [s for s in re.split(r"(?<=[.!?。！？])\s+", text) if s.strip()]
    if sentences:
        # 一句一句往里加，加到行数上限为止 —— 固定取 2 句会超预算然后又被截成半句
        # （实测取到「…Labels show accuracy and change from the best full dual-track
        #   result.」共 4 行，截完变成「…Labels show accuracy…」）。
        kept: list[str] = []
        for sent in sentences:
            cand = _fit_or_none(" ".join(kept + [sent]).strip(), max_lines)
            if cand is None:
                break
            kept.append(sent)
        if kept:
            return _fit_or_none(" ".join(kept).strip(), max_lines) or " ".join(kept)
    return fit_caption(text, "md", max_lines=max_lines) or text


def _fit_or_none(text: str, max_lines: int) -> Optional[str]:
    """整段放得进 max_lines 就原样返回，放不下返回 None（由调用方决定取舍）。"""
    lines = _wrap_no_cut(text, AVAIL_PX / SIZE_LADDER["md"][0], TRACK_EM["md"])
    return text if len(lines) <= max_lines else None


def uniform_fit(items: list[str], kind: str = "md", *, max_lines: int = 3,
                budget_px: Optional[float] = None,
                min_items: int = 1) -> tuple[int, list[list[str]]]:
    """给一整页的同級条目挑**同一个**字号，并保证整页排得下。

    为什么不能各挑各的：收尾页的 limitations 是**整句**，不是标题。原来每条各自
    `fit_title(...)` 再把第 1 行当 `.h-md`（56px）、其余当 `.body`（24px），于是同一页上
    「系统假设名册、source/owner」是 56px 大字、紧跟的「归因与时间识别可靠；别名」缩成 24px
    —— 一页里两种字号跳来跳去（2026-09-26 用户报「最后一页字体大小不统一」）。
    而且 `max_lines=2` 会把句子**静默截断**：「…仍然困难（论文 Limitations）。」整段丢了。

    选法：从顶档往下试，取**总高度不超预算**的第一档。预算有两种口径：
      · `budget_px` 给了就用像素（收尾页必须用这个 —— 行数与像素不是一回事，
        44px 的 12 行是 750px，56px 的 9 行也是 750px 上下，用行数判会挑错字号）；
      · 没给就用行数（max_lines × 条数）。
    一档都放不下时，**从末尾开始少放几条**（至少留 min_items 条）—— 宁可少一条边界，
    也不把字号压到看不清、也不静默截字。返回的 lines 长度就是实际展示的条数。
    """
    items = [str(x) for x in items if str(x or "").strip()]
    if not items:
        return SIZE_LADDER.get(kind, SIZE_LADDER["md"])[0], []
    track = TRACK_EM.get(kind, 0.0)
    ladder = SIZE_LADDER.get(kind, SIZE_LADDER["md"])
    keep = len(items)

    def fits(subset: list[str], size: int) -> bool:
        total = sum(max(1, len(_wrap_no_cut(it, AVAIL_PX / size, track))) for it in subset)
        if budget_px is not None:
            return total * size * LIM_LINE_H <= budget_px
        return total <= max_lines * len(subset)

    while keep >= max(1, min_items):
        subset = items[:keep]
        chosen: Optional[tuple[int, list[list[str]]]] = None
        for size in ladder:
            if fits(subset, size):
                chosen = (size, [_wrap_no_cut(it, AVAIL_PX / size, track) or [it] for it in subset])
                break
        if chosen:
            return chosen
        keep -= 1
    size = ladder[-1]
    subset = items[:max(1, min_items)]
    return size, [_wrap_no_cut(it, AVAIL_PX / size, track) or [it] for it in subset]


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


#: 图注前缀（"Figure 3: ..." / "Fig. 3." / "表 1："）—— kicker 已经写了「证据 · fig-3」，
#: 页面下方还有 "Fig. 3" 图注，再留一遍就是三处重复。剥掉。
_CAPTION_PREFIX_RE = re.compile(
    r"^\s*(figure|fig\.?|table|tab\.?|algorithm|listing|scheme)\s*\.?\s*\d*\s*[:：.、\-]?\s*",
    re.I,
)


def fit_caption(cap: str, kind: str = "xl", *, max_lines: int = 2) -> str:
    """把论文图注压成一条短标题（≤max_lines 行），在词边界截断并加省略号。

    为什么不能直接用 `clause_trim`：它是给**中文长标题**砍从句的，保留的是前缀。
    英文图注 "Figure 1: A multi-party group chat is not a flat message stream: ..." 的
    第一个从句就是 "Figure 1" —— 砍完只剩 "Figure 1"，等于没标题（2026-09-26 实测）。
    图注要的是「摘要」，不是「开头」，所以这里按 token 贪心截到行数上限为止。
    """
    cap = re.sub(r"\s+", " ", str(cap or "")).strip()
    if not cap:
        return ""
    per_line = AVAIL_PX / SIZE_LADDER.get(kind, SIZE_LADDER["xl"])[0]
    track = TRACK_EM.get(kind, 0.0)
    kept: list[str] = []
    cur, cur_u, lines = "", 0.0, 1
    for tok in _tokenize(cap):
        w = line_units(tok, track)
        if cur and cur_u + w > per_line:
            if lines >= max_lines:
                break
            kept.append(cur)
            lines += 1
            cur, cur_u = tok, w
        else:
            cur += tok
            cur_u += w
    if cur and lines <= max_lines:
        kept.append(cur)
    out = "".join(kept).strip().rstrip(" ,;、，")
    return out + "…" if len("".join(kept)) < len(cap.replace(" ", "")) else out


def _fig_name(entry: dict[str, Any]) -> str:
    return Path(str(entry.get("source") or entry.get("file") or "")).name


def _figure_no(entry: dict[str, Any]) -> str:
    """从 fig-3.png / fig-12.png 里取出「3」「12」当图号（图注要显示它）。"""
    m = re.search(r"(\d+)", _fig_name(entry))
    return m.group(1) if m else ""


def pick_figure_pages(digest: dict[str, Any], figures_dir: Path | str, *,
                      exclude: Optional[set[str]] = None,
                      limit: int = MAX_FIGURE_PAGES) -> list[dict[str, Any]]:
    """从 digest 里挑出**还没被用过**的原图，各生成一张图卡页。

    为什么要有这个函数（2026-09-26）：组图里的原图数完全取决于 LLM 写 poster.spec 时
    给了几个 `kind:"figure"` 块 —— 实测 run_e24920f4d088 给了 1 个，于是 7 页组图里
    29 张源图只出现了 **1 张**（fig-2，还被封面和图卡页各用一次）。源图明明在
    `intake/images/`躺着，digest 里也登记了 5 张 fig-*，只是没人去用。

    规则：
      · 只要 `fig-*`（表格不进竖图，见 FIG_FILE_RE 的说明）；
      · 跳过 `exclude` 里已用过的（LLM 选中的 + 封面 teaser），不做重复；
      · 跳过小于 MIN_FIG_PX 的图（放大只会糊）；
      · 文件在 figures_dir 下真的存在才算数（_fig_src 解析）。

    返回 [{kicker, title, figure}]，已按「图号」排序，调用方直接拼进页面计划。
    """
    out: list[dict[str, Any]] = []
    seen = {e for e in (exclude or set())}
    for entry in (digest.get("figures") or []):
        if not isinstance(entry, dict) or len(out) >= limit:
            continue
        name = _fig_name(entry)
        if not name or name in seen or not FIG_FILE_RE.match(name):
            continue
        if _fig_src({"file": name}, Path(figures_dir)) is None:
            continue
        if _too_small(Path(figures_dir) / name):
            continue
        seen.add(name)
        caption = str(entry.get("caption") or "").strip()
        bare = _CAPTION_PREFIX_RE.sub("", caption).strip()
        out.append({
            "kicker": f"证据 · {entry.get('id') or ('图 ' + _figure_no(entry))}",
            "title": fit_caption(bare, "md", max_lines=3) or bare or f"图 {entry.get('id') or _figure_no(entry)}",
            "title_kind": "md",       # 英文图注当 h-xl 一行只装得下两三个词，降一级才读得懂
            "title_lines": 3,
            "figure": {"file": name, "number": _figure_no(entry)},
            "_id": entry.get("id") or name,
        })
    out.sort(key=lambda p: str(p["figure"].get("number") or ""))
    return out


def _too_small(path: Path, min_px: int = MIN_FIG_PX) -> bool:
    """图太小就别放大。读不到尺寸不算太小（宁可放过，别因为 PIL 缺依赖就丢图）。"""
    try:
        from PIL import Image

        with Image.open(path) as im:
            return min(im.size) < min_px
    except Exception:
        return False


#: 论点顺序。组图要能连成一条线，就必须规定块的出场次序 —— 2026-09-26 实测
#: run_e24920f4d088 的块序是「难点 → 方法 → 架构图 → 结果 → 训练消融」，
#: 训练细节排在结果之后、而证明它自己的两张图（GRPO 训练环、消融）却被丢在最后
#: 四张连着的纯图页里，整组图读下来不像论证，像「先讲完再补图」。
#: 声明了 role 的块按这个顺序**稳定排序**；没声明的沿用前一个块的 role（不乱跑）。
ROLE_ORDER = {"problem": 0, "method": 1, "evidence": 2, "result": 3, "detail": 4}
#: 兜底次序没给全时的中性位置：排在「结果」后、「细节」前
ROLE_FALLBACK = 2.5


def _ordered_blocks(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """把 spec 的 columns 摊平成一个块列表，并按 role 稳定排序。

    只有**一个块都没声明 role** 时才完全不排序（老 spec 的行为，避免无谓变动）。
    """
    out: list[dict[str, Any]] = []
    for col in spec.get("columns") or []:
        for blk in col if isinstance(col, list) else [col]:
            if isinstance(blk, dict):
                out.append(blk)
    if not any(str(b.get("role") or "").strip() for b in out):
        return out
    last = ROLE_FALLBACK
    keyed: list[tuple[float, int, dict[str, Any]]] = []
    for i, b in enumerate(out):
        role = str(b.get("role") or "").strip().lower()
        if role in ROLE_ORDER:
            last = float(ROLE_ORDER[role])
        keyed.append((last, i, b))
    keyed.sort(key=lambda t: (t[0], t[1]))          # 稳定：同 role 保持原顺序
    return [b for _r, _i, b in keyed]


def plan_pages(spec: dict[str, Any], cover: Optional[dict[str, Any]], digest: dict[str, Any],
               *, max_items: int = MAX_ITEMS_PER_PAGE,
               extra_figures: Optional[list[dict[str, Any]]] = None,
               fig_notes: Optional[dict[str, str]] = None) -> list[dict[str, Any]]:
    """spec → 组图页面计划（纯函数，不碰文件系统）。返回 [{kind, kicker, title, ...}]。

    `extra_figures` 是 build() 用 pick_figure_pages 备好的补充图卡（已过滤、已去重）。
    放在这里而不是在函数内部去读文件，是为了保住「纯函数、不碰文件系统」这条约定。
    """
    pages: list[dict[str, Any]] = []
    cv = cover or {}
    # LLM 为每张图写的中文说明（spec.figureNotes）。图卡页优先用它 —— PDF 抽出来的
    # 图注是英文，直接印在卡片上等于让读者看外语（实测印出过截断的英文标题）。
    fig_notes = {Path(str(k)).name: str(v) for k, v in (spec.get("figureNotes") or {}).items() if v}
    teaser = cv.get("teaser") or spec.get("teaser") or {}
    teaser_name = Path(str(teaser.get("file") or "")).name
    raw_title = cv.get("title") or spec.get("title") or ""
    if label_like(raw_title):
        # 封面大标题不能只是方法名（「SpeakerMem-R1：双轨记忆」只说了论文叫什么）。
        # 顶上来的候选按「有多具体」排序：贡献 > 结论式副标题 > 论文原名。
        cand = next((str(c).strip() for c in (digest.get("contributions") or [])
                     if str(c or "").strip() and not label_like(c)), "")
        cand = cand or fit_caption(str(cv.get("subtitle") or spec.get("subtitle") or ""), "display") \
            or fit_caption(raw_title, "display")
        if cand:
            raw_title = cand
    pages.append({
        "kind": "cover",
        "kicker": cv.get("kicker") or spec.get("kicker") or "",
        "title": raw_title,
        "subtitle": cv.get("subtitle") or spec.get("subtitle") or "",
        "teaser": teaser,
        "chips": (cv.get("chips") or spec.get("chips") or [])[:3],
        "venue": spec.get("venue") or "",
    })

    block_no = 0
    used_figs: set[str] = {teaser_name} if teaser_name else set()
    anchored: set[str] = set()          # 已被某个论点认领的图（与 teaser 可以重叠）
    for blk in _ordered_blocks(spec):
        block_no += 1
        if blk.get("kind") == "figure":
            used_figs.add(Path(str(blk.get("file") or "")).name)
            pages.append({
                "kind": "figure",
                "kicker": f"证据 · 图 {blk.get('number') or block_no}",
                "title": str(fig_notes.get(Path(str(blk.get('file') or '')).name) or "").strip()
                          or blk.get("caption") or "",
                "figure": {"file": blk.get("file"), "number": blk.get("number")},
            })
            continue
        items = seq_items(blk.get("items") or blk.get("items_tall") or [], limit=max_items)
        if not items:
            continue
        # 禁「本文/作者」要覆盖**要点正文**，不只是封面副标题 ——
        # 实测 run_f308d04cf07a 第 2 页要点里就写着「本文追问这种线性是否…」。
        mname = method_name(cv.get("title") or spec.get("title") or "")
        clean = [de_selfref(it, mname)[0] for it in items]
        ptitle = informative_title(blk.get("title") or "要点", clean)
        # 标题是从某条要点里切出来的 → 把那条的前缀去掉，避免同页说两遍
        for i, it in enumerate(clean):
            trimmed = _strip_head(it, ptitle)
            if trimmed != it:
                clean[i] = trimmed
                break
        pages.append({
            "kind": "panel",
            # kicker 不再用「要点 · 论文里的事实」这种每页都一样的 boilerplate：
            # 模型给了就用它的，没给就留空（页码与页脚已经足够定位）。
            "kicker": blk.get("kicker") or "",
            "title": ptitle,
            "items": clean,
        })
        # **证据紧跟论点**：这一页的要点由哪张原图证明，那张图就贴在它后面。
        # 之前所有补充图都堆在最后（实测 run_e24920f4d088 第 7-10 张是四张连着的纯图页），
        # 读起来像附录，不像论证。
        #
        # 允许和封面 teaser 用同一张：封面把它当 16:9 的窄带、这一页把它当整版大图，
        # 重复出现是正常的（小红书封面图常常就是正文里那张）。但**两个论点不能抢同一张**。
        anchor = Path(str(blk.get("figure") or "")).name
        if anchor and anchor not in anchored:
            anchored.add(anchor)
            pages.append({
                "kind": "figure",
                "kicker": f"证据 · {anchor[:-4]}",
                "title": str(fig_notes.get(anchor) or "").strip() or blk.get("figureCaption") or "",
                "title_kind": "md", "title_lines": 3,
                "figure": {"file": anchor, "number": anchor[4:-4] if anchor.startswith("fig-") else ""},
            })

    # 没被任何论点认领的原图放这里，kicker 写「更多证据」——
    # 它们是补充材料，不是论证的一环。混在正文里会被读成「结论又在重复一遍」。
    # 放在「判断 · 边界」之前 —— 收尾判断页必须在最后。
    for extra in (extra_figures or []):
        name = _fig_name({"source": extra.get("figure", {}).get("file")})
        if name in used_figs or name in anchored:
            continue
        # 有 LLM 写的中文说明就用它，别把 PDF 的英文图注截断了印上去。
        # 退化路径（老 spec 没有 figureNotes）才用英文原注，但**断在句号**而不是半截词。
        note = str(fig_notes.get(name) or "").strip()
        title = note or _caption_title(extra.get("title") or "")
        pages.append({"kind": "figure", "kicker": "更多证据",
                      "title": title,
                      "title_kind": "md", "title_lines": 3,
                      "figure": extra.get("figure") or {}})
        used_figs.add(name)

    lims = [str(x) for x in (digest.get("limitations") or []) if str(x).strip()][:3]
    if lims:
        pages.append({"kind": "closing", "kicker": "判断 · 边界", "title": "别把它当结论，把它当线索",
                      "items": lims})
    # 上限裁剪要**保住封面与收尾**（中间的图卡/要点页才是可牺牲的）
    if len(pages) > MAX_PAGES:
        head = pages[:1]
        tail = pages[-1:] if pages[-1]["kind"] == "closing" else []
        mid = pages[1:len(pages) - len(tail)]
        keep = MAX_PAGES - len(head) - len(tail)
        pages = head + mid[:max(0, keep)] + tail
    return pages


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
    /* 行高上限由页面按要点条数算好后写进 --row-max（见 _row_max_px）：3 条撑满、
       4 条不越界。之前写死 260px（3 条时下半页空 200px），试过 330px 又让 4 条
       顶穿内容区触发 R2 FAIL。 */
    .ledger-row { flex: 1 1 auto; align-items: center; min-height: 118px; max-height: var(--row-max, 260px); }
    /* 收尾页：限制条目 + 分隔线 + 出处收在**一个** flex 子节点里（见 build_html 的
       closing 分支：stack 的行距会把 .meta 顶进页脚，R2 判 FAIL）。
       min-height:0 是关键 —— 不然 flex 子项的自动最小尺寸会拒绝收缩，照样溢出。
       内部 space-between：限制条目在上、出处贴着内容区底部，页面重心才稳。 */
    .limits { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column;
              justify-content: space-between; gap: 20px; }
    .lims { display: flex; flex-direction: column; gap: 26px; }
    .limits .lim { margin: 0; line-height: 1.42; }
    .limits .rule { margin: 0; }

    /* ---------- 行内强调：**粗体** 与 ==底色== ----------
       小红书信息流里最常见的两种强调。这里刻意做得「轻」：
       · 底色用**荧光笔**而不是实心色块 —— 实心块会把 88px 的大标题切碎、显得廉价。
         上下边缘用硬停在 30%/92%（不是全高实心），字形上半截留在纸面上，
         视觉上像马克笔划过一道，跨行时每行各自成段（box-decoration-break: clone）。
       · 颜色是**暖琥珀**：主题是靛蓝/纸灰这一路冷色，暖色带是唯一的暖点，
         天然成为视线落点；透明度压到 .34，深靛墨字（#0a1f3d）压在上面对比度仍很高。
       · 粗体只提到 700：模板全篇是 500 的细衬线（技能 HANDOFF 明确说 900 是误改），
         一路加粗会和 h-xl 的重量基准冲突，所以 700 是上限。
       · 两端留一点内边距，色带不跟相邻字贴死。 */
    .content strong { font-weight: 700; }
    mark.hl {
      background: linear-gradient(180deg,
        rgba(255, 197, 61, 0)   28%,
        rgba(255, 197, 61, .34) 30%,
        rgba(255, 197, 61, .34) 93%,
        rgba(255, 197, 61, 0)   95%);
      color: inherit;
      padding: 0 .07em;
      margin: 0 -.03em;
      border-radius: 3px;
      font-variant-numeric: tabular-nums;   /* 高亮区里的数字对齐，别歪 */
      -webkit-box-decoration-break: clone;
      box-decoration-break: clone;
    }
  </style>
</head>"""
    tpl = tpl.replace("</head>", override)

    assets_dir = Path(out_dir) / "assets"
    used = 0
    de_selfref_hits = 0
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
                    f'        <figure class="frame-img r-{COVER_FIG_RATIO} fit-contain">\n'
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
                # 封面副标题是读者唯一会读完的一段话，兜底去掉「本文/作者」这类自称
                sub, hit = de_selfref(pg["subtitle"], method_name(pg.get("title") or ""))
                if hit:
                    de_selfref_hits += 1
                # 行数自己算死：技能校验器不查 .lead 的溢出，超了也不会报（实测超 18px 仍 0 warn）
                lead_size, lead_html = fit_lead(sub)
                fig_html += (f'        <p class="lead" style="font-size:{lead_size}px">'
                             f'{lead_html}</p>\n')
            size, lines = fit_title(pg["title"], "display")
            head_kicker = " · ".join(dedupe_parts(pg.get("kicker"), pg.get("venue"), "PaperCast 论文速读"))
            body = (
                f'        <p class="kicker">{_esc(head_kicker)}</p>\n'
                f'        <h1 class="h-display" style="font-size:{size}px">'
                + "<br>".join(inline(l) for l in lines) + "</h1>\n"
                + fig_html
            )
            sections.append(_page(pid=pid, kicker="", title=None, title_kind="xl", body_html=body,
                                  strip=strip))
        elif pg["kind"] == "figure":
            # LLM 自己写的图卡用 h-xl（大字，图是配角）；自动补进来的图卡用 h-md ——
            # 那些标题是**英文图注**，88px 下一行只装得下两三个词（实测 "A multi-party group
            # chat is…"），降一级才读得出是什么图。图仍是主角：画框 flex:1 撑满剩余高度。
            tkind = pg.get("title_kind") or "xl"
            _size, _lines = fit_title(pg.get("title") or "", tkind, max_lines=pg.get("title_lines"))
            src = _fig_src(pg.get("figure") or {}, figures_dir)
            if not src:
                continue
            rel = _copy_asset(src, assets_dir)
            used += 1
            cap = pg.get("figure", {}).get("number")
            # 画框用**原图自己的比例**，不拉成 `flex:1` 撑满。
            # 实测：fig-4 是 1224×562（2.18:1），塞进 flex:1 的 ~800px 高框里只剩
            # 415px 的图、上下各空 190px，看着像「一条窄带浮在大白框里」。
            # 按原图比例 + `margin:auto 0` 居中，空的地方就是干净的留白。
            ar = _img_aspect(src)
            style = (f"aspect-ratio:{ar[0]}/{ar[1]};margin:auto 0" if ar
                     else "flex:1 1 auto;aspect-ratio:auto;min-height:0")
            body = (
                f'        <figure class="frame-img fit-contain" style="{style}">\n'
                f'          <img src="{_esc(rel)}" alt="{_esc(pg.get("title"))}">\n'
                "        </figure>\n"
                + (f'        <p class="img-cap">Fig. {_esc(cap)}</p>\n' if cap else "")
            )

            sections.append(_page(pid=pid, kicker=pg["kicker"],
                                  title="<br>".join(inline(l) for l in _lines),
                                  title_kind=tkind, title_size=_size,
                                  body_html=body, strip=strip))
        elif pg["kind"] == "closing":
            # 收尾页：每条 limitation 都是**整句**，所以全页用一个字号（uniform_fit），
            # 不再「第 1 行当大标题、其余当小字」—— 那样一页里会跳出两种字号，
            # 而且 max_lines=2 会把句子静默截断。行数上限给到 3，句子才放得完整。
            #
            # 整块（限制条目 + 分隔线 + 出处）必须放进**同一个** flex 子节点里：
            # `.content.stack.gap-3` 的行距实测约 78px，四个子节点就多出 300px，
            # 把 .meta 顶到 y=16330 —— 而内容区（1440-172 页脚留白）只到 16212、
            # 页脚条从 16285 开始，于是 R2「meta 压到页脚」判 FAIL（实测复现）。
            # 收成一个子节点后，撑高的是它自己，页脚线永远在内容框内。
            lims = [str(x) for x in (pg.get("items") or []) if str(x).strip()]
            if lims:
                bsize, blines = uniform_fit(lims, "md", max_lines=3,
                                            budget_px=LIM_BUDGET_PX, min_items=LIM_MIN_ITEMS)
                if len(blines) < len(lims):
                    # 少放的那几条要**看得见地**少放：图注里说明，不静默吞掉论文的 Limitations
                    body_note = f"{short_note(note)}（本页列 {len(blines)}/{len(lims)} 条，其余见原文）"
                else:
                    body_note = short_note(note)
                # 字号必须**显式写出来**：uniform_fit 给的是全页统一的那一档，
                # 未必等于 .h-md 的默认 56px（长句会把它压到 50/44）。
                blocks = "".join(
                    f'          <p class="h-md lim" style="font-size:{bsize}px">'
                    + "<br>".join(inline(l) for l in lines) + "</p>\n"
                    for lines in blines
                )
                body = ('        <div class="limits">\n'
                        '          <div class="lims">\n' + blocks + "          </div>\n"
                        '          <hr class="rule">\n'
                        f'          <p class="meta">{_esc(body_note or "见原文")}</p>\n'
                        "        </div>\n")
            else:
                body = (f'        <p class="meta">{_esc(short_note(note) or "见原文")}</p>\n')
            msize, mlines = fit_title(pg["title"], "md")
            sections.append(_page(pid=pid, kicker=pg["kicker"],
                                  title="<br>".join(inline(l) for l in mlines), title_kind="md",
                                  title_size=msize, body_html=body, strip=strip))

        else:  # panel
            psize, plines = fit_title(pg.get("title") or "", "xl")
            body = ('        <div class="ledger" style="--row-max:'
                    f'{_row_max_px(len(pg.get("items") or []))}px">\n'
                    + _bullet_rows(pg.get("items") or []) + "\n        </div>\n")
            sections.append(_page(pid=pid, kicker=pg["kicker"],
                                  title="<br>".join(inline(l) for l in plines), title_kind="xl",
                                  title_size=psize, body_html=body, strip=strip))

    i = tpl.index('<main class="sheet">')
    j = tpl.index("</main>")
    out_html = tpl[:i] + '<main class="sheet">\n\n' + "\n\n".join(sections) + "\n  </main>" + tpl[j + len("</main>"):]

    out_dir = Path(out_dir)
    (out_dir / "index.html").write_text(out_html, encoding="utf-8")
    bg = Path(template).parent / BG_SCRIPT_REL.name
    if bg.is_file():
        _copy_asset(bg, assets_dir)
    return {"pages": len(sections), "assets": used, "deSelfrefHits": de_selfref_hits,
            "html": str(out_dir / "index.html")}


def build(spec: dict[str, Any], cover: Optional[dict[str, Any]], digest: dict[str, Any],
          figures_dir: Path | str, out_dir: Path | str, *, theme: str = DEFAULT_THEME,
          max_items: int = MAX_ITEMS_PER_PAGE, keep_pages: Optional[int] = None,
          max_figures: int = MAX_FIGURE_PAGES, note: str = "") -> dict[str, Any]:
    """完整装配：spec → 页面计划 → index.html（+ assets/ + deck.plan.json）。"""
    sd = skill_dir()
    if not sd:
        raise FileNotFoundError(
            f"技能未安装：{SKILL_NAME}（跑 ./ops/install_skills.sh，或用 GUIZANG_SKILL_DIR 指到技能目录）"
        )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 补充图卡先备好：plan_pages 自己不碰文件系统，由这里把「哪些原图还没用过」查清楚。
    figs = Path(figures_dir)
    teaser_name = Path(str((cover or spec).get("teaser", {}).get("file") or "")).name
    used = {teaser_name} if teaser_name else set()
    for blk in _ordered_blocks(spec):
        # panel 自己的 `figure`（贴在论点后面的那张）也要算「已用」——
        # 否则它会同时出现在论证里和「更多证据」里，同一张图在组图里出现两次。
        anchor = Path(str(blk.get("figure") or "")).name
        if anchor:
            used.add(anchor)
        if blk.get("kind") == "figure":
            used.add(Path(str(blk.get("file") or "")).name)
    extra = pick_figure_pages(digest, figs, exclude=used, limit=max_figures) if max_figures else []
    pages = plan_pages(spec, cover, digest, max_items=max_items, extra_figures=extra)
    if keep_pages:
        pages = pages[:keep_pages]
    info = build_html(pages, figs, out_dir, theme=theme,
                      template=sd / TEMPLATE_REL, note=note)
    (out_dir / "deck.plan.json").write_text(
        json.dumps({"theme": theme, "pages": pages, "note": note}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    distinct = {p["figure"]["file"] for p in pages if p.get("kind") == "figure" and p.get("figure", {}).get("file")}
    if teaser_name:
        distinct.add(teaser_name)
    info.update({"ok": True, "skill": str(sd), "theme": theme, "max_items": max_items,
                 "addedFigurePages": len(extra), "distinctFigures": len(distinct), "plan": pages})
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

    渲染前**清掉上一轮的 xhs-* 产物**：重排时页数只会变少（自检不过 → keep_pages 收敛、
    或某张图这次没选上），残留的旧页会让人以为这次渲了那么多张 —— 2026-09-26 实测
    3 页的 deck 导出里还躺着上轮 9 页的 p4..p9，投递就会把过期图发出去。
    """
    script = renderer_script()
    if not script.is_file():
        raise FileNotFoundError(f"组图渲染入口不存在：{script}")
    out_root = Path(out_dir) / "output"
    out_root.mkdir(parents=True, exist_ok=True)
    for old in list(out_root.glob("xhs-*")):
        if old.is_file():
            old.unlink()
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
