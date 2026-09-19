"""M2.5 · 视频讲解（真出 mp4）：digest → 中文分镜 → PIL 帧 + edge-tts 配音 → ffmpeg 合成。

一句话：**把一篇论文的事实源（understand/digest.json）变成一段能直接投放的 mp4 讲解视频。**

设计要点（完整版见 docs/10-module-video.md）：

1. **事实源唯一**：分镜里的每个数字都必须能在 digest 文本里回溯到，回溯不到就丢句 / 丢页并记日志
   —— 与 M2（app/modules/generate.py 的 _drop_untraceable）同一套规则，不允许出现 digest 里没有的数字。
2. **不引入 GPU 依赖**：帧用 PIL 画（复用 config.find_cjk_font 找中文字体），编码用 x264（CPU）。
3. **阻塞活全部丢线程**：画帧 / TTS / ffmpeg 都是 CPU 或阻塞 IO，统一走 asyncio.to_thread，事件循环只编排 + 报进度。
4. **TTS 失败不静默**：降级成无声视频（时长按语速估算），但如实记 check=fail 并把原始报错写进 detail。
5. **不用 FastAPI 也能跑**：python -m app.modules.video --run <runId>，见文件末尾的 CLI。

产物契约（写在 <run>/video/ 下）：
    video.mp4            1920×1080 H.264 + AAC，faststart
    video-vertical.mp4   1080×1920，模糊背景 + 居中卡片
    cover.png            1920×1080 封面
    narration.json       {title, totalSec, slides[{index,title,bullets,narration,durationSec}]}
    subtitles.srt        与配音时间轴一致（时间戳来自 edge-tts 的句级边界，不是估算）
    video.report.json    本次合成的工程指标（ffprobe 实测、字体、工具链版本、丢弃记录）—— 验收证据
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # 只为类型标注，运行时不导入（避免 CLI 之外的循环依赖）
    from ..pipeline import StageContext

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

W, H = 1920, 1080            # 横版（B站/YouTube）
VW, VH = 1080, 1920          # 竖版（小红书）
FPS = 25
N_MIN, N_MAX = 6, 12         # 分镜页数区间（契约要求 6–12）
CPS = 4.6                    # 中文语速估计（字/秒）：只用于无声降级与时长预估

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_TTS_TIMEOUT = 120

# 与 app/cards/render.py 同一套配色（视觉上是一家人）
BG = (251, 249, 246)
PANEL = (255, 255, 255)
INK = (26, 26, 26)
BODY = (46, 46, 46)
SUB = (120, 116, 110)
LINE = (226, 222, 214)
CARD_BORDER = (231, 227, 220)
ACCENT = (232, 80, 58)

MARGIN = 72
ACCENT_H = 14


class VideoError(RuntimeError):
    """带错误码的失败：pipeline 会把 code/message 记进 run.error。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- #
# 工具链定位（不写死 /home/yydh/hack，按工作区约定推导）
# --------------------------------------------------------------------------- #

def workspace_root() -> Path:
    """推导工作区根目录。两条路都要能工作：

    1. env：PAPERCAST_DATA_DIR 一般指向 <WS>/var/runs —— 从它往上找含 apps/ + var/ 的那层；
    2. __file__：.../<WS>/apps/papercast-server/app/modules/video.py 往上找同样特征。
    都失败时退回 app.config.VAR_DIR（它自己已经处理了「被拷出去单独跑」的情况）。
    """
    env = (os.environ.get("PAPERCAST_DATA_DIR") or "").strip()
    if env:
        p = Path(env).expanduser()
        try:
            p = p.resolve()
        except OSError:
            pass
        for cand in [p, *p.parents]:
            if (cand / "apps").is_dir() and (cand / "var").is_dir():
                return cand
        # PAPERCAST_DATA_DIR=<WS>/var/runs 的常见写法：上溯两级
        return p.parent.parent
    here = Path(__file__).resolve()
    for cand in here.parents:
        if (cand / "apps").is_dir() and (cand / "var").is_dir():
            return cand
    from ..config import VAR_DIR

    return VAR_DIR.parent


def _first_file(*cands: str) -> str:
    for c in cands:
        if c and Path(c).is_file():
            return str(Path(c))
    return ""


def tool_ffmpeg() -> str:
    return (os.environ.get("PAPERCAST_FFMPEG") or "").strip() or _first_file(
        str(workspace_root() / "var/toolchains/p2b/bin/ffmpeg"),
        shutil.which("ffmpeg") or "",
    )


def tool_ffprobe() -> str:
    return (os.environ.get("PAPERCAST_FFPROBE") or "").strip() or _first_file(
        str(workspace_root() / "var/toolchains/p2b/bin/ffprobe"),
        shutil.which("ffprobe") or "",
    )


def tool_tts_python() -> str:
    """edge-tts 只装在 bili-venv 里（后端 venv 没有），所以单独探一个解释器。"""
    return (os.environ.get("PAPERCAST_TTS_PYTHON") or "").strip() or _first_file(
        str(workspace_root() / "var/toolchains/bili-venv/bin/python"),
        str(workspace_root() / "var/toolchains/bili-venv/bin/python3"),
        sys.executable,
    )


def _which_runnable(path: str) -> bool:
    return bool(path) and (Path(path).is_file() or shutil.which(path) is not None)


# --------------------------------------------------------------------------- #
# 子进程 / ffprobe
# --------------------------------------------------------------------------- #

def _run(cmd: list[str], *, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def ffprobe_json(path: Path, ffprobe: str, entries: str) -> dict:
    r = _run([ffprobe, "-v", "error", "-show_entries", entries, "-of", "json", str(path)], timeout=120)
    if r.returncode != 0:
        raise VideoError("FFPROBE_FAILED", f"ffprobe 读 {path.name} 失败：{r.stderr.strip()[:200]}")
    try:
        return json.loads(r.stdout or "{}")
    except json.JSONDecodeError as e:
        raise VideoError("FFPROBE_BAD_JSON", f"ffprobe 输出无法解析：{e}") from e


def media_duration(path: Path, ffprobe: str) -> float:
    data = ffprobe_json(path, ffprobe, "format=duration")
    try:
        return float((data.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def media_info(path: Path, ffprobe: str) -> dict:
    """一个文件的可验收摘要：时长 + 每条流的编码/分辨率。"""
    data = ffprobe_json(path, ffprobe, "format=duration,size,format_name")
    streams = ffprobe_json(path, ffprobe, "stream=codec_type,codec_name,width,height,sample_rate,channels")
    out: dict[str, Any] = {
        "name": path.name,
        "bytes": path.stat().st_size if path.is_file() else 0,
        "duration": float((data.get("format") or {}).get("duration") or 0.0),
        "format": (data.get("format") or {}).get("format_name", ""),
        "streams": [],
    }
    for s in streams.get("streams") or []:
        item = {"type": s.get("codec_type"), "codec": s.get("codec_name")}
        if s.get("width"):
            item["width"] = s.get("width")
            item["height"] = s.get("height")
        if s.get("sample_rate"):
            item["sample_rate"] = s.get("sample_rate")
            item["channels"] = s.get("channels")
        out["streams"].append(item)
    return out


def _fmt_hms(sec: float) -> str:
    sec = max(0.0, float(sec))
    return f"{int(sec // 60):02d}:{int(sec % 60):02d}"

# --------------------------------------------------------------------------- #
# 文本工具
# --------------------------------------------------------------------------- #

_MD_MARKS = re.compile(r"[*_#>|~\[\]]+")
_WS = re.compile(r"[ \t\u3000]+")


def clean_speakable(text: str) -> str:
    """把一段文本洗成「能直接念」的样子：去公式、去 markdown 符号、压空白。"""
    from .generate import strip_formulas  # 与 M2 同一套去公式规则（延迟导入，避免模块级重依赖）

    t = strip_formulas(text or "")[0]
    t = _MD_MARKS.sub("", t)
    t = re.sub(r"\\[a-zA-Z]+", "", t)
    t = t.replace("（见图）", "").replace("（如下表）", "")
    t = _WS.sub(" ", t)
    return t.strip(" ·-—:：")


def numbers_in(text: str) -> list[str]:
    from .generate import numbers_in as _numbers_in  # 同一套抽取规则，避免两处漂移

    return _numbers_in(text)


def _flat(text: str) -> str:
    return re.sub(r"[\s,，]", "", text or "")


_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}
_CN_CHARS = "".join(_CN_DIGITS) + "".join(_CN_UNITS) + "点"
# 只对「像数值」的中文数字做强校验：百分比 / 带小数 / 亿·万量级 / 倍
_CN_HARD = re.compile(
    r"(?:百分之)[" + _CN_CHARS + r"]{1,12}"
    r"|[" + _CN_CHARS + r"]{2,12}(?=倍|个百分点)"
    r"|[" + re.sub(r"点", "", _CN_CHARS) + r"]{1,6}[万亿](?![米])"
)


def _cn_value(token: str) -> Optional[float]:
    """中文数字 → 数值（「五十七点一八」→ 57.18）；解析不了返回 None。"""
    dec = ""
    if "点" in token:
        head, _, tail = token.partition("点")
        digits = [_CN_DIGITS.get(c) for c in tail]
        if any(d is None for d in digits):
            return None
        dec = "".join(str(d) for d in digits)          # type: ignore[arg-type]
        token = head
    total = section = number = 0
    for ch in token:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            u = _CN_UNITS[ch]
            if u >= 10000:
                total += (section + (number or 1)) * u
                section = number = 0
            else:
                section += (number or 1) * u
                number = 0
        else:
            return None
    value = float(total + section + number)
    if dec:
        value = float(f"{int(value)}.{dec}")
    return value


def _num_str(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}"


def _cn_candidates(expr: str) -> list[str]:
    """把中文数字表达转成「可能在 digest 里出现的写法」候选（含单位形式）。"""
    cands: list[str] = []
    had_percent = expr.startswith("百分之")
    body = expr[len("百分之"):] if had_percent else expr
    unit = ""
    m = re.search(r"[万亿]$", body)
    if m:
        unit = m.group(0)
        body = body[: -len(unit)]
    value = _cn_value(body)
    if value is None:
        return []
    cands.append(f"{_num_str(value)}{unit}" if unit else _num_str(value))
    if had_percent:
        cands.append(f"{_num_str(value)}%")
    return cands


def untraceable_numbers(text: str, flat_haystack: str) -> list[str]:
    """返回文本里「在事实源中找不到」的数字（阿拉伯数字 + 硬表达的中文数字）。

    比 generate.py 的规则多认两种等价形式：57.18 与 57.18%、三亿 与 3亿。
    方向是「宁可不杀」，不会放松到放过 digest 里没有的数字。
    """
    bad: list[str] = []
    for n in numbers_in(text):
        key = _flat(n)
        if not key:
            continue
        if key in flat_haystack or key.rstrip("%") in flat_haystack or f"{key.rstrip('%')}%" in flat_haystack:
            continue
        bad.append(n)
    for m in _CN_HARD.finditer(text or ""):
        expr = m.group(0)
        cands = _cn_candidates(expr)
        if cands and any(c in flat_haystack for c in cands):
            continue
        bad.append(expr)
    return bad


_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])")


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT.split(text or "") if s.strip()]


def drop_untraceable(text: str, flat_haystack: str, on_drop) -> str:
    """句子级丢弃：含无法回溯数字的句子整句删掉（就近改写的成本高于收益，也更容易再次出错）。"""
    kept: list[str] = []
    for sent in split_sentences(text):
        bad = untraceable_numbers(sent, flat_haystack)
        if bad:
            on_drop(sent.strip(), bad)
            continue
        kept.append(sent)
    return "".join(kept).strip()


# --------------------------------------------------------------------------- #
# 版式工具（与 app/cards/render.py 同源；这里独立一份是为了让视频版式能单独调参）
# --------------------------------------------------------------------------- #

def _font(path: str, size: int):
    from PIL import ImageFont

    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for token in re.split(r"(\s+)", text or ""):
        if not token:
            continue
        if token.isspace():
            if cur:
                cur += " "
            continue
        units = [token] if re.fullmatch(r"[A-Za-z0-9\-_/.%]+", token) else list(token)
        for u in units:
            probe = cur + u
            if draw.textlength(probe, font=font) <= max_w or not cur:
                cur = probe
            else:
                lines.append(cur.rstrip())
                cur = u
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [""]


def _fit_inside(img, box_w: int, box_h: int, *, max_up: float = 2.0):
    from PIL import Image

    iw, ih = img.size
    scale = min(box_w / max(1, iw), box_h / max(1, ih), max_up)
    if abs(scale - 1.0) > 1e-3:
        img = img.resize((max(1, int(iw * scale)), max(1, int(ih * scale))), Image.LANCZOS)
    return img


def _cover_fit(img, box_w: int, box_h: int):
    from PIL import Image

    iw, ih = img.size
    scale = max(box_w / max(1, iw), box_h / max(1, ih))
    img = img.resize((max(1, int(iw * scale) + 1), max(1, int(ih * scale) + 1)), Image.LANCZOS)
    iw, ih = img.size
    left, top = (iw - box_w) // 2, (ih - box_h) // 2
    return img.crop((left, top, left + box_w, top + box_h))


# --------------------------------------------------------------------------- #
# 输入装载
# --------------------------------------------------------------------------- #

@dataclass
class Inputs:
    run_dir: Path
    digest: dict
    digest_text: str          # 事实源全文（数字回溯只用这一份，不用论文原文）
    flat: str                 # 去空白/逗号的事实源，用于回溯比对
    title: str
    figures: list[dict]       # [{id, file(Path), caption, where}]


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def load_inputs(ctx, run_dir: Path) -> Inputs:
    digest: Optional[dict] = None
    if getattr(ctx.run, "digest", None) is not None:
        try:
            digest = ctx.run.digest.model_dump()
        except AttributeError:
            digest = None
    if not digest:
        digest = _read_json(run_dir / "understand" / "digest.json", None)
    if not isinstance(digest, dict):
        raise VideoError("DIGEST_MISSING", "缺少 understand/digest.json（事实源），无法生成视频")

    digest_text = json.dumps(digest, ensure_ascii=False, indent=1)
    flat = _flat(digest_text)

    # 图片候选：digest.figures 的顺序优先（M2 已按传播价值排过序），再补 intake 其它原图与卡片图。
    intake_dir = run_dir / "intake"
    card_dir = run_dir / "article" / "cards"
    figures: list[dict] = []
    seen: dict[str, int] = {}

    def _add(fid: str, path: Path, caption: str, where: str) -> None:
        key = str(path)
        if key in seen:
            if caption and not figures[seen[key]]["caption"]:
                figures[seen[key]]["caption"] = caption
            return
        seen[key] = len(figures)
        figures.append({"id": fid, "file": path, "caption": caption, "where": where})

    for f in digest.get("figures") or []:
        if not isinstance(f, dict):
            continue
        rel = str(f.get("source") or f.get("file") or "")
        if not rel:
            continue
        p = intake_dir / rel
        if not p.is_file():                      # source 常见写法是 images/x.png，压平再兜一层
            p = intake_dir / "images" / Path(rel).name
        if p.is_file():
            _add(str(f.get("id") or p.stem), p, str(f.get("caption") or "").strip(), "intake/images")

    images_dir = intake_dir / "images"
    if images_dir.is_dir():
        for p in sorted(images_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                _add(p.stem, p, "", "intake/images")
    if card_dir.is_dir():
        for p in sorted(card_dir.iterdir()):
            if p.is_file() and p.suffix.lower() == ".png":
                _add(f"cards/{p.name}", p, f"小红书卡片 {p.stem}（图上已含标题文字）", "article/cards")

    return Inputs(
        run_dir=run_dir,
        digest=digest,
        digest_text=digest_text,
        flat=flat,
        title=str(digest.get("title") or getattr(ctx.run, "title", "") or run_dir.name),
        figures=figures,
    )

# --------------------------------------------------------------------------- #
# 分镜（LLM 主路 + 确定性兜底）
# --------------------------------------------------------------------------- #

STORY_SYSTEM = """你是学术短视频的分镜编剧：把一篇论文的事实源（digest）改写成一段中文讲解视频的分镜脚本。

铁律（违反即视为失败）：
1. 只能使用 digest 里出现过的事实、数字与结论。不引入任何外部知识，不推理新结论，不做估算或四舍五入。
2. 旁白与要点里出现的任何数字，必须与 digest 里的写法一致（digest 的数字已做过原文回溯校验）。
   数字请写成阿拉伯数字（例如 57.18%），不要写成中文数字。
3. 不出现公式、不出现 LaTeX、不出现 markdown 符号（井号、星号、反引号、竖线、下划线、波浪号等）、
   不出现「如图 3」「见附录 B」这类指向原文的指引。
4. 旁白是要直接念出来的口语，每页 40–120 字，用「研究团队」「这篇论文」这样自然的说法；不要书面语、不要口号式罗列。
5. 每页 2–4 条要点，每条不超过 22 个字，是可以一眼看懂的短句（不是旁白的复制）。
6. 配图：figure 只能填给定图片清单里的 id，每页最多一张。优先用 intake/images 里的论文原图；
   清单里标了「图上已含标题文字」的是已经排过版的小红书卡片，除非没有原图可选，否则不要用；
   标了「未匹配到图注」的原图来自论文正文内嵌图，讲数据 / 结果的页面可以用。
   整段视频建议 2–4 页配图，其余页纯文字 —— 没有合适的图就填 null，不要为了配图而配图。
7. 第 1 页开场（这篇论文解决什么问题），最后一页收束（3 条以内要点 + 一句结论）。

只输出 JSON，不要任何解释文字、不要 markdown 围栏。JSON 结构：
{
  "title": "整段视频的标题（不超过 20 字，用于封面）",
  "slides": [
    {"title": "该页小标题（不超过 14 字）",
     "bullets": ["要点 1", "要点 2"],
     "narration": "40–120 字口语化旁白",
     "figure": "图片 id 或 null"}
  ]
}"""


def _story_user(inp: Inputs, n_min: int, n_max: int, target_sec: int, hint: str, note: str,
                brief: str = "") -> str:
    from .. import prompts  # 复用项目统一的用户指令包装（含「不许改事实层」的 BRIEF_RULES）

    brief_text = prompts.brief_block(brief, stage="视频分镜：侧重与口吻")
    figs = "\n".join(
        f"- {f['id']}（{f['where']}）：{f['caption'][:80] or '无图注'}" for f in inp.figures
    ) or "（这篇论文没有可用的图片，所有页都填 figure=null）"
    fig_head = ("可选图片清单（figure 只能填这些 id 或 null）；"
                "intake/images 是论文原图，优先用；article/cards 是已排好版的卡片图，图上自带文字：")
    d = inp.digest
    payload = {
        "title": d.get("title", ""),
        "venue": d.get("venue", ""),
        "abstractCn": d.get("abstractCn", ""),
        "keywords": d.get("keywords", []),
        "contributions": d.get("contributions", []),
        "method": (d.get("method") or "")[:2500],
        "results": d.get("results", []),
        "limitations": d.get("limitations", []),
    }
    extra = f"\n作者对本段视频的额外要求（必须满足）：{hint}\n" if hint else ""
    return (
        f"论文标题：{payload['title']}\n"
        f"面向读者：对 AI / 科研有兴趣的中文读者，没读过原文。\n\n"
        f"事实源 digest（唯一可用的事实，JSON）：\n{json.dumps(payload, ensure_ascii=False, indent=1)}\n\n"
        f"{fig_head}\n{figs}\n\n"
        f"分镜要求：一共 {n_min}–{n_max} 页；总时长目标约 {target_sec} 秒"
        f"（中文配音约 {CPS:.1f} 字/秒，即旁白总长约 {int(target_sec * CPS)} 字）。\n"
        f"要点里不要写「如图所示」，图片只作为版式配图。{extra}{brief_text}{note}"
    )


def fallback_storyboard(inp: Inputs, n_max: int) -> dict:
    """不用 LLM 的确定性分镜：句子逐条取自 digest，数字天然可回溯（离线自检与降级都用它）。"""
    d = inp.digest
    slides: list[dict] = []

    def add(title: str, bullets: list[str], narration: str) -> None:
        slides.append({
            "title": title[:14],
            "bullets": [b.strip()[:26] for b in bullets if b and b.strip()][:4],
            "narration": narration.strip()[:150],
            "figure": None,
        })

    abstract = [s.strip() for s in split_sentences(str(d.get("abstractCn") or "")) if s.strip()]
    if abstract:
        add("这篇论文在做什么", [abstract[0][:22]], "".join(abstract[:2])[:118])
    for c in (d.get("contributions") or [])[:4]:
        c = str(c).strip()
        if c:
            add("核心贡献", [c[:22]], c[:118])
    for chunk in split_sentences(str(d.get("method") or ""))[:2]:
        add("方法主线", [chunk[:22]], chunk[:118])
    res = [r for r in (d.get("results") or []) if isinstance(r, dict)]
    for i in range(0, min(len(res), 6), 3):
        group = res[i:i + 3]
        add(
            "关键结果",
            [f"{str(r.get('label', ''))[:12]}：{str(r.get('value', ''))[:12]}" for r in group],
            "；".join(f"{r.get('label', '')}是{str(r.get('value', ''))}" for r in group)[:118],
        )
    lim = [str(x).strip() for x in (d.get("limitations") or []) if str(x).strip()][:2]
    if lim:
        add("局限与边界", [x[:22] for x in lim], "".join(lim)[:118])
    kws = [str(x).strip() for x in (d.get("keywords") or [])][:4]
    contrib = [str(x).strip() for x in (d.get("contributions") or [])]
    add("一句话总结", kws, (contrib[0] if contrib else "以上就是这篇论文的主要工作。")[:118])
    return {"title": str(d.get("title") or "论文速读")[:40], "slides": slides[:n_max]}


async def build_storyboard(ctx, inp: Inputs, *, target_sec: int, hint: str, allow_llm: bool,
                           brief: str = "") -> tuple[dict, str]:
    """返回 (storyboard, 来源)。LLM 失败时降级到确定性分镜，并记 warn（不静默）。"""
    note = ""
    if allow_llm and getattr(ctx.llm, "available", False):
        for attempt in (1, 2):
            try:
                ctx.log("info", f"调用 LLM 生成中文分镜（第 {attempt} 次，{N_MIN}–{N_MAX} 页）…")
                raw = await ctx.llm.chat_json(
                    STORY_SYSTEM,
                    _story_user(inp, N_MIN, N_MAX, target_sec, hint, note, brief),
                    max_tokens=12000,
                )
                if isinstance(raw, dict) and isinstance(raw.get("slides"), list) and raw["slides"]:
                    return raw, "llm"
                note = "\n\n【上一次输出结构不合法，请严格按给定 JSON 结构返回 slides 数组】"
                ctx.log("warn", "分镜 JSON 结构不合法，重试一次")
            except Exception as e:  # 网络/配额/截断：降级但不假装成功
                ctx.log("warn", f"LLM 分镜失败：{type(e).__name__}: {str(e)[:160]}")
                break
    else:
        ctx.log("warn", "没有可用的 LLM 凭据，直接用 digest 拼确定性分镜（无 LLM 降级）")
    return fallback_storyboard(inp, N_MAX), "fallback"


# --------------------------------------------------------------------------- #
# 分镜清洗（反幻觉 + 版式友好）
# --------------------------------------------------------------------------- #

@dataclass
class Slide:
    index: int
    title: str
    bullets: list[str]
    narration: str
    figure: Optional[Path] = None
    figure_label: str = ""
    duration: float = 0.0
    clip: Optional[Path] = None
    audio: Optional[Path] = None
    frame: Optional[Path] = None
    cues: list = field(default_factory=list)     # [(start, end, text)]，相对本页起点
    tts: str = ""


def _resolve_figure(inp: Inputs, spec: Any):
    if not isinstance(spec, str) or not spec.strip():
        return None, ""
    key = spec.strip()
    for f in inp.figures:
        if key in (f["id"], Path(f["file"]).name, str(f["file"])):
            return f["file"], f["id"]
    low = key.lower()
    for f in inp.figures:
        if low in (f["id"].lower(), Path(f["file"]).name.lower(), Path(f["file"]).stem.lower()):
            return f["file"], f["id"]
    return None, ""


def sanitize_storyboard(ctx, inp: Inputs, raw: dict) -> tuple[str, list[Slide], list[str]]:
    """把模型输出变成可用的分镜：去公式 / 数字回溯 / 长度与页数收敛 / 图源校验。

    返回 (视频标题, slides, 丢弃记录)。
    """
    dropped: list[str] = []
    flat = inp.flat

    def on_drop(text: str, bad: list[str]) -> None:
        dropped.append(f"「{'、'.join(bad)}」← {text[:44]}")
        ctx.log("warn", f"丢弃含无法回溯数字的内容（{'、'.join(bad)}）：{text[:60]}")

    raw_slides = [s for s in (raw.get("slides") or []) if isinstance(s, dict)]
    if len(raw_slides) > N_MAX:
        ctx.log("warn", f"模型给了 {len(raw_slides)} 页，超过上限 {N_MAX}，只保留前 {N_MAX} 页")
        raw_slides = raw_slides[:N_MAX]

    slides: list[Slide] = []
    for s in raw_slides:
        title = clean_speakable(str(s.get("title") or ""))[:14]
        narration = drop_untraceable(clean_speakable(str(s.get("narration") or "")), flat, on_drop)
        bullets: list[str] = []
        for b in (s.get("bullets") or [])[:4]:
            b = clean_speakable(str(b))
            if not b:
                continue
            bad = untraceable_numbers(b, flat)
            if bad:
                dropped.append(f"「{'、'.join(bad)}」← {b[:44]}")
                ctx.log("warn", f"丢弃含无法回溯数字的要点（{'、'.join(bad)}）：{b[:60]}")
                continue
            bullets.append(b[:26])
        # 旁白清洗后太短（大半被数字回溯杀掉）就丢整页：宁可少一页，也不要一页哑火
        if len(narration) < 20:
            dropped.append(f"整页丢弃（旁白不足 20 字）：{title or narration[:16]}")
            ctx.log("warn", f"整页丢弃：{title or '（无标题）'} —— 旁白清洗后只剩 {len(narration)} 字")
            continue
        if len(narration) > 160:
            narration = narration[:150].rstrip("，、；：") + "。"
        fig_path, fig_label = _resolve_figure(inp, s.get("figure"))
        slides.append(Slide(index=len(slides) + 1, title=title or f"第 {len(slides) + 1} 页",
                            bullets=bullets, narration=narration,
                            figure=fig_path, figure_label=fig_label))

    # 一页都没配上图 → 按 digest.figures 的顺序给最早的几页配图（没有合适图就保持纯文字版式）
    if inp.figures and not any(s.figure for s in slides):
        ctx.log("info", f"模型未指定配图，按 digest.figures 顺序给前 {min(len(inp.figures), len(slides))} 页配图")
        for i, s in enumerate(slides[: len(inp.figures)]):
            s.figure, s.figure_label = inp.figures[i]["file"], inp.figures[i]["id"]

    title = clean_speakable(str(raw.get("title") or ""))[:24] or inp.title[:24]
    return title, slides, dropped


def residual_violations(slides: list[Slide], flat: str) -> list[str]:
    """成片文本的最终复核：正常应当是空的（丢句/丢页之后就干净了）。"""
    bad: list[str] = []
    for s in slides:
        for chunk in [s.narration, *s.bullets]:
            hits = untraceable_numbers(chunk, flat)
            if hits:
                bad.append(f"第 {s.index} 页「{'、'.join(hits)}」← {chunk[:40]}")
    return bad


# --------------------------------------------------------------------------- #
# 画帧
# --------------------------------------------------------------------------- #

def _series_note(inp: Inputs) -> str:
    d = inp.digest
    tag = str(d.get("arxivId") or "").strip() or str(d.get("venue") or "").strip() or "arXiv"
    return f"论文速读 · {tag}"


def _draw_wrapped(d, text, font, x, y, max_w, line_h, fill, max_lines, *, stroke=0):
    lines = _wrap(d, text, font, max_w)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1] + "…"
    for ln in lines:
        d.text((x, y), ln, font=font, fill=fill, stroke_width=stroke, stroke_fill=fill)
        y += line_h
    return y


def render_frame(slide: Slide, *, out_path: Path, font_path: str, series: str, footer: str,
                 page: int, pages: int, img_cache: dict) -> Path:
    """一页 1920×1080：标题 + 要点（左）+ 配图（右）。没有合适的图就整页纯文字。"""
    from PIL import Image, ImageDraw

    frame = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(frame)
    f_series = _font(font_path, 34)
    f_title = _font(font_path, 68)
    f_foot = _font(font_path, 28)

    d.rectangle([0, 0, W, ACCENT_H], fill=ACCENT)
    d.text((MARGIN, 46), series, font=f_series, fill=SUB)
    badge = f"{page} / {pages}"
    d.text((W - MARGIN - d.textlength(badge, font=f_series), 46), badge, font=f_series, fill=ACCENT)

    y = _draw_wrapped(d, slide.title, f_title, MARGIN, 112, W - 2 * MARGIN, 88, INK, 2, stroke=1)
    rule_y = max(y, 236) + 6
    d.line([MARGIN, rule_y, W - MARGIN, rule_y], fill=LINE, width=3)

    top = rule_y + 40
    bottom = H - 132
    fig_w = 872 if slide.figure else 0
    text_w = (W - 2 * MARGIN - fig_w - 48) if fig_w else (W - 2 * MARGIN)

    # 要点：先按目标字号试排，装不下就缩字号（最多缩到 30），保证不压到页脚
    size = 46 if fig_w else 54
    while True:
        f_body = _font(font_path, size)
        line_h, gap = int(size * 1.55), int(size * 0.55)
        blocks = [(_wrap(d, b, f_body, text_w - 44), gap) for b in slide.bullets]
        total = sum(len(w) * line_h + g for w, g in blocks)
        if total <= bottom - top or size <= 30:
            break
        size -= 4
    cy = top
    for wrapped, gap in blocks:
        d.rectangle([MARGIN, cy + int(size * 0.42), MARGIN + 12, cy + int(size * 0.42) + 12], fill=ACCENT)
        for ln in wrapped:
            if cy + line_h > bottom:
                break
            d.text((MARGIN + 40, cy), ln, font=f_body, fill=BODY)
            cy += line_h
        cy += gap

    if slide.figure:
        box = [W - MARGIN - fig_w, top, W - MARGIN, bottom]
        d.rectangle(box, fill=PANEL, outline=CARD_BORDER, width=3)
        img = None
        try:
            img = img_cache.get(str(slide.figure))
            if img is None:
                img = Image.open(slide.figure).convert("RGB")
                if max(img.size) > 2600:      # 论文原图常 4000px 宽，先降采样再缓存
                    img = _fit_inside(img, 2600, 2600, max_up=1.0)
                img_cache[str(slide.figure)] = img
        except Exception:
            img = None
            d.text((box[0] + 24, box[1] + 24), f"图片读取失败：{Path(str(slide.figure)).name}",
                   font=_font(font_path, 30), fill=SUB)
        if img is not None:
            fitted = _fit_inside(img, box[2] - box[0] - 36, box[3] - box[1] - 36, max_up=1.6)
            frame.paste(fitted, (box[0] + (box[2] - box[0] - fitted.size[0]) // 2,
                                 box[1] + (box[3] - box[1] - fitted.size[1]) // 2))

    d.line([MARGIN, H - 96, W - MARGIN, H - 96], fill=LINE, width=2)
    d.text((MARGIN, H - 74), _wrap(d, footer, f_foot, W - 2 * MARGIN)[0], font=f_foot, fill=SUB)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame.save(out_path, "PNG", optimize=True)
    return out_path


def render_cover(*, out_path: Path, title: str, paper_title: str, figure: Optional[Path],
                 series: str, footer: str, font_path: str, img_cache: dict) -> Path:
    """1920×1080 封面：模糊主图打底 + 左侧大标题 + 右侧主图卡片。"""
    from PIL import Image, ImageDraw, ImageFilter

    canvas = Image.new("RGB", (W, H), (14, 15, 18))
    img = None
    if figure is not None:
        img = img_cache.get(str(figure))
        if img is None and Path(figure).is_file():
            try:
                img = Image.open(figure).convert("RGB")
                img_cache[str(figure)] = img
            except Exception:
                img = None
        if img is not None:
            bg = _cover_fit(img, W, H)
            small = bg.resize((max(1, W // 8), max(1, H // 8)), Image.BILINEAR)
            small = small.filter(ImageFilter.GaussianBlur(6)).resize((W, H), Image.BICUBIC)
            canvas = Image.blend(small, Image.new("RGB", (W, H), (10, 11, 14)), 0.58)

    veil = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(veil).rectangle([0, 0, 1180, H], fill=(9, 10, 13, 155))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), veil).convert("RGB")

    d = ImageDraw.Draw(canvas)
    d.rectangle([MARGIN, 150, MARGIN + 96, 160], fill=ACCENT)
    d.text((MARGIN, 184), series, font=_font(font_path, 36), fill=(240, 175, 160))
    y = _draw_wrapped(d, title, _font(font_path, 104), MARGIN, 252, 1040, 126, (255, 255, 255), 2, stroke=2)
    y = max(y, 252 + 126) + 40
    _draw_wrapped(d, paper_title, _font(font_path, 38), MARGIN, y, 1040, 54, (206, 202, 196), 3)
    d.text((MARGIN, H - 118), footer, font=_font(font_path, 28), fill=(172, 168, 162))
    d.text((MARGIN, H - 74), "内容与数字取自论文事实源 digest，可回溯校验",
           font=_font(font_path, 28), fill=(150, 146, 140))

    if img is not None:
        bw, bh = 648, 560
        box = [W - MARGIN - bw, (H - bh) // 2, W - MARGIN, (H - bh) // 2 + bh]
        d.rectangle([box[0] - 6, box[1] - 6, box[2] + 6, box[3] + 6], fill=(255, 255, 255))
        fitted = _fit_inside(img, bw - 24, bh - 24, max_up=1.6)
        canvas.paste(fitted, (box[0] + (bw - fitted.size[0]) // 2, box[1] + (bh - fitted.size[1]) // 2))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "PNG", optimize=True)
    return out_path


# --------------------------------------------------------------------------- #
# 配音 + 单页 clip
# --------------------------------------------------------------------------- #

def tts_page(*, text: str, voice: str, mp3: Path, subs: Path, tts_python: str,
             timeout: int = DEFAULT_TTS_TIMEOUT) -> None:
    """edge-tts 合成一页配音，并把句级时间戳一起落盘（字幕用真时间轴，不靠估算）。"""
    mp3.parent.mkdir(parents=True, exist_ok=True)
    r = _run(
        [tts_python, "-m", "edge_tts", "--text", text, "--voice", voice,
         "--write-media", str(mp3), "--write-subtitles", str(subs)],
        timeout=timeout,
    )
    if r.returncode != 0 or not mp3.is_file() or mp3.stat().st_size == 0:
        raise VideoError("TTS_FAILED", f"edge_tts 退出码 {r.returncode}：{(r.stderr or '').strip()[:200]}")


_CUE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*\n(.+)"
)


def parse_cues(path: Path) -> list[tuple[float, float, str]]:
    """解析 edge-tts 写出的字幕（SRT 风格）；解析不了返回空，调用方退化成按字数切。"""
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    cues: list[tuple[float, float, str]] = []
    for m in _CUE.finditer(text):
        start = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4).ljust(3, "0")) / 1000
        end = int(m.group(5)) * 3600 + int(m.group(6)) * 60 + int(m.group(7)) + int(m.group(8).ljust(3, "0")) / 1000
        body = re.sub(r"\s+", "", m.group(9))
        if body:
            cues.append((start, end, body))
    return cues


def estimate_cues(narration: str, duration: float) -> list[tuple[float, float, str]]:
    """没有 TTS 字幕时的兜底：按句子字数比例切开（只用于无声降级路径）。"""
    sents = split_sentences(narration) or [narration]
    total = sum(len(s) for s in sents) or 1
    cues, t = [], 0.0
    for s in sents:
        span = duration * len(s) / total
        cues.append((t, t + span, re.sub(r"\s+", "", s)))
        t += span
    return cues


def build_clip(*, idx: int, frame: Path, narration: str, clips_dir: Path, audio_dir: Path,
               ffmpeg: str, ffprobe: str, voice: str, tts_python: str, skip_tts: bool,
               on_log) -> dict:
    """一页：配音 → 取时长 → 帧 + 音轨合成 clip。全同步，由调用方丢线程。"""
    mp3 = audio_dir / f"p{idx:03d}.mp3"
    subs = audio_dir / f"p{idx:03d}.srt"
    clip = clips_dir / f"p{idx:03d}.mp4"
    clips_dir.mkdir(parents=True, exist_ok=True)
    tts_mode, err = "edge-tts", ""

    if skip_tts:
        tts_mode, err = "silent-degraded", "调用方要求跳过 TTS（--skip-tts）"
    else:
        last = ""
        for attempt in (1, 2):
            try:
                tts_page(text=narration, voice=voice, mp3=mp3, subs=subs, tts_python=tts_python)
                last = ""
                break
            except Exception as e:
                last = f"{type(e).__name__}: {str(e)[:200]}"
                on_log("warn", f"第 {idx} 页 TTS 第 {attempt} 次失败：{last}")
        if last:
            tts_mode, err = "silent-degraded", last

    duration, cues = 0.0, []
    if tts_mode == "edge-tts":
        try:
            duration = media_duration(mp3, ffprobe)
            cues = parse_cues(subs)
        except VideoError as e:
            duration = 0.0
            err = e.message
        if duration <= 0:
            tts_mode, err = "silent-degraded", err or "配音文件时长为 0（ffprobe 读不出来）"
            cues = []

    if tts_mode != "edge-tts":
        duration = max(2.5, len(narration) / CPS)   # 无声降级：按语速估算，绝不产出 0 时长片段
        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-loop", "1", "-framerate", str(FPS), "-i", str(frame),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-tune", "stillimage",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart", str(clip),
        ]
    else:
        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-loop", "1", "-framerate", str(FPS), "-i", str(frame), "-i", str(mp3),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-tune", "stillimage",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
            "-shortest", "-movflags", "+faststart", str(clip),
        ]
    r = _run(cmd, timeout=900)
    if r.returncode != 0 or not clip.is_file() or clip.stat().st_size == 0:
        raise VideoError("CLIP_ENCODE_FAILED", f"第 {idx} 页 clip 合成失败：{(r.stderr or '').strip()[:220]}")

    real = media_duration(clip, ffprobe)
    if real > 0:
        duration = real
    if not cues:
        cues = estimate_cues(narration, duration)
    fixed: list[tuple[float, float, str]] = []   # 时间戳收敛：不重叠、不越界
    prev_end = 0.0
    for start, end, body in cues:
        start = max(start, prev_end)
        if start >= duration:
            break
        end = min(max(end, start + 0.4), duration)
        fixed.append((start, end, body))
        prev_end = end
    return {"duration": duration, "cues": fixed, "clip": clip,
            "audio": mp3 if mp3.is_file() else None, "tts": tts_mode, "error": err}

# --------------------------------------------------------------------------- #
# 拼接 / 竖版 / 字幕
# --------------------------------------------------------------------------- #

def concat_clips(clips: list[Path], *, out: Path, work: Path, ffmpeg: str, ffprobe: str,
                 expected: float, on_log) -> tuple[str, float]:
    """先试 stream copy 拼接（快）；时长对不上就退回滤镜重编码（准）。返回 (方式, 实测时长)。"""
    listfile = work / "clips" / "concat.txt"
    listfile.parent.mkdir(parents=True, exist_ok=True)
    listfile.write_text("".join(f"file '{c.resolve()}'\n" for c in clips), encoding="utf-8")

    def _try(mode: str) -> float:
        base = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                "-i", str(listfile)]
        tail = (["-c", "copy"] if mode == "copy" else
                ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2"])
        r = _run([*base, *tail, "-movflags", "+faststart", str(out)], timeout=1800)
        if r.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
            on_log("warn", f"concat({mode}) 失败：{(r.stderr or '').strip()[:220]}")
            return 0.0
        return media_duration(out, ffprobe)

    got = _try("copy")
    if got > 0 and abs(got - expected) <= 0.5:
        return "copy", got
    if got > 0:
        on_log("warn", f"copy 拼接时长 {got:.2f}s 与分段合计 {expected:.2f}s 不符，改用滤镜重编码拼接")
    got2 = _try("reencode")
    if got2 <= 0:
        raise VideoError("CONCAT_FAILED", "两种拼接方式都失败，未能产出 video.mp4")
    return "reencode", got2


def make_vertical(*, src: Path, out: Path, ffmpeg: str, on_log) -> None:
    """竖版：模糊放大的原帧打底 + 居中卡片。一次滤镜过完整段，不重复编码每一页。"""
    vf = (
        "[0:v]split=2[bg][fg];"
        f"[bg]scale={VW}:{VH}:force_original_aspect_ratio=increase,crop={VW}:{VH},"
        "gblur=sigma=42,eq=brightness=-0.10:saturation=1.05[bgb];"
        "[fg]scale=980:-2,pad=iw+14:ih+14:7:7:color=white[fgs];"
        "[bgb][fgs]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]"
    )
    r = _run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
        "-filter_complex", vf, "-map", "[v]", "-map", "0:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-c:a", "copy", "-movflags", "+faststart", str(out),
    ], timeout=1800)
    if r.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        raise VideoError("VERTICAL_FAILED", f"竖版合成失败：{(r.stderr or '').strip()[:260]}")
    on_log("info", "竖版（1080×1920）：模糊背景 + 居中卡片")


def write_srt(cues: list[tuple[float, float, str]], path: Path) -> None:
    def ts(t: float) -> str:
        ms = int(round(max(0.0, t) * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    lines: list[str] = []
    for i, (start, end, body) in enumerate(cues, 1):
        lines += [str(i), f"{ts(start)} --> {ts(end)}", body, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

async def run_video(ctx) -> None:
    """video 阶段入口：digest + intake 图片 + 卡片 → 讲解视频（横版 / 竖版 / 封面 / 字幕 / 分镜）。"""
    started = time.time()
    try:
        await _run_video_inner(ctx, started)
    except VideoError as e:
        ctx.log("err", f"视频合成失败：{e.message}")
        ctx.check("视频合成", "fail", f"[{e.code}] {e.message}"[:300])
        raise
    except Exception as e:
        ctx.log("err", f"视频合成异常：{type(e).__name__}: {str(e)[:200]}")
        ctx.check("视频合成", "fail", f"[{type(e).__name__}] {str(e)[:260]}")
        raise


async def _run_video_inner(ctx, started: float) -> None:
    run_dir = Path(ctx.work).parent
    work = Path(ctx.work)
    work.mkdir(parents=True, exist_ok=True)
    frames_dir, audio_dir, clips_dir = work / "frames", work / "audio", work / "clips"
    for d in (frames_dir, audio_dir, clips_dir):
        d.mkdir(parents=True, exist_ok=True)

    cfg = getattr(getattr(ctx.run, "config", None), "video", None)
    env_voice = (os.environ.get("PAPERCAST_TTS_VOICE") or "").strip()
    voice = env_voice or str(getattr(cfg, "voice", "") or "").strip() or DEFAULT_VOICE
    target_sec = int(getattr(cfg, "durationSec", 0) or 180)
    hint = str(getattr(cfg, "narration", "") or "").strip()
    aspect = str(getattr(cfg, "aspect", "") or "9:16").strip() or "9:16"
    brief = str(getattr(getattr(ctx.run, "config", None), "brief", "") or "").strip()
    skip_tts = bool(getattr(ctx, "_force_skip_tts", False))

    ffmpeg, ffprobe = tool_ffmpeg(), tool_ffprobe()
    if not _which_runnable(ffmpeg) or not _which_runnable(ffprobe):
        raise VideoError("FFMPEG_MISSING",
                         f"找不到可执行的 ffmpeg/ffprobe（{ffmpeg} / {ffprobe}）；"
                         f"可用 PAPERCAST_FFMPEG / PAPERCAST_FFPROBE 指定")
    tts_python = tool_tts_python()

    ctx.progress(0.03)
    inp = load_inputs(ctx, run_dir)
    ctx.log("info", f"事实源：{inp.title[:60]}｜可用图片 {len(inp.figures)} 张｜"
                    f"目标时长 {target_sec}s｜音色 {voice}")

    font_path = str(getattr(ctx.settings, "cjk_font", "") or "")
    if not font_path:
        from ..config import find_cjk_font

        font_path = find_cjk_font()
    from ..config import has_cjk_glyphs

    if not font_path or not Path(font_path).is_file():
        raise VideoError("FONT_MISSING", "找不到中文字体（设 PAPERCAST_CJK_FONT，或装 fonts-noto-cjk）")
    if not has_cjk_glyphs(font_path):
        raise VideoError("FONT_NO_GLYPH", f"字体 {font_path} 不含中文字形，画出来会是方块，已中止")
    ctx.log("info", f"中文字体：{font_path}")

    ctx.log("info", "config.video 用法："
                    f"voice={voice}" + ("（PAPERCAST_TTS_VOICE 环境变量已覆盖 config）" if env_voice else "")
                    + f"、durationSec={target_sec}（用作目标时长与旁白字数预算）、"
                    f"narration={'已拼进分镜要求' if hint else '空'}、"
                    f"aspect={aspect}（横竖两版都会产出，这里只用它决定哪一版先登记为主版本）")
    ctx.log("info", f"config.brief：{brief[:80] + '…' if len(brief) > 80 else brief}"
                    if brief else "config.brief 为空，分镜只按 digest 生成")

    # ---- 分镜 ----
    raw, source = await build_storyboard(ctx, inp, target_sec=target_sec, hint=hint, brief=brief,
                                        allow_llm=not getattr(ctx, "_force_no_llm", False))
    ctx.progress(0.12)
    video_title, slides, dropped = sanitize_storyboard(ctx, inp, raw)
    if not slides:
        raise VideoError("NO_SLIDES", "分镜清洗后一页都不剩（旁白里的数字全部无法回溯），未产出视频")
    if source == "fallback":
        ctx.log("warn", "分镜来自确定性兜底（无 LLM）：句子逐条取自 digest，数字天然可回溯")
        if brief:
            ctx.log("warn", "config.brief 本次未生效：确定性兜底不经过 LLM，无法体现口吻/侧重")
    ctx.log("info", f"分镜就绪：{len(slides)} 页，来源 {source}，"
                    f"{sum(1 for s in slides if s.figure)} 页配图，"
                    f"{sum(1 for s in slides if not s.figure)} 页纯文字版式")

    # ---- 逐页：画帧 → 配音 → clip ----
    img_cache: dict = {}
    series = _series_note(inp)
    d = inp.digest
    tag = str(d.get("arxivId") or d.get("venue") or "arXiv")
    footer = f"{inp.title[:72]} · {tag}"

    for i, s in enumerate(slides, 1):
        s.frame = await asyncio.to_thread(
            render_frame, s, out_path=frames_dir / f"p{i:03d}.png", font_path=font_path,
            series=series, footer=footer, page=i, pages=len(slides), img_cache=img_cache,
        )
        res = await asyncio.to_thread(
            build_clip, idx=i, frame=s.frame, narration=s.narration, clips_dir=clips_dir,
            audio_dir=audio_dir, ffmpeg=ffmpeg, ffprobe=ffprobe, voice=voice,
            tts_python=tts_python, skip_tts=skip_tts, on_log=ctx.log,
        )
        s.duration = float(res["duration"])
        s.cues = list(res["cues"])
        s.clip, s.audio, s.tts = res["clip"], res["audio"], str(res["tts"])
        if res["error"]:
            ctx.log("err", f"第 {i} 页 TTS 降级为无声：{res['error']}")
        ctx.log("ok", f"第 {i}/{len(slides)} 页：{s.title}｜{s.duration:.2f}s｜"
                      f"{'配音' if s.tts == 'edge-tts' else '无声降级'}"
                      f"{'｜配图 ' + s.figure_label if s.figure else '｜纯文字版式'}")
        ctx.progress(0.12 + 0.68 * i / len(slides))

    expected = sum(s.duration for s in slides)
    n_silent = sum(1 for s in slides if s.tts != "edge-tts")

    # ---- 横版 ----
    video = work / "video.mp4"
    mode, total = await asyncio.to_thread(
        concat_clips, [s.clip for s in slides if s.clip], out=video, work=work,
        ffmpeg=ffmpeg, ffprobe=ffprobe, expected=expected, on_log=ctx.log,
    )
    ctx.log("ok", f"横版合成完成：{mode} 拼接，实测 {total:.2f}s（分段合计 {expected:.2f}s）")
    ctx.progress(0.86)

    # ---- 竖版 ----
    vertical = work / "video-vertical.mp4"
    await asyncio.to_thread(make_vertical, src=video, out=vertical, ffmpeg=ffmpeg, on_log=ctx.log)
    ctx.progress(0.92)

    # ---- 封面 / 分镜 JSON / 字幕 ----
    cover = work / "cover.png"
    main_fig = next((s.figure for s in slides if s.figure), None) or (inp.figures[0]["file"] if inp.figures else None)
    cover_footer = f"{tag} · 时长 {_fmt_hms(total)} · 共 {len(slides)} 页"
    await asyncio.to_thread(
        render_cover, out_path=cover, title=video_title, paper_title=inp.title, figure=main_fig,
        series=series, footer=cover_footer, font_path=font_path, img_cache=img_cache,
    )

    story = {
        "title": f"{inp.title}（{tag}）",
        "totalSec": round(total, 2),
        "slides": [
            {"index": s.index, "title": s.title, "bullets": s.bullets,
             "narration": s.narration, "durationSec": round(s.duration, 2)}
            for s in slides
        ],
    }
    (work / "narration.json").write_text(json.dumps(story, ensure_ascii=False, indent=1), encoding="utf-8")

    global_cues: list[tuple[float, float, str]] = []
    offset = 0.0
    for s in slides:                      # 每页 cues 平移到整段视频的时间轴
        for start, end, body in s.cues:
            global_cues.append((offset + start, offset + end, body))
        offset += s.duration
    srt = work / "subtitles.srt"
    write_srt(global_cues, srt)

    # ---- ffprobe 实测（验收数据）----
    h_info = await asyncio.to_thread(media_info, video, ffprobe)
    v_info = await asyncio.to_thread(media_info, vertical, ffprobe)
    residual = residual_violations(slides, inp.flat)
    planned = _collect_planned_numbers(slides)
    last_cue = global_cues[-1][1] if global_cues else 0.0
    drift = abs(total - last_cue)
    ctx.log("info", f"横版 ffprobe：{_fmt_streams(h_info)}｜{_mb(video)}")
    ctx.log("info", f"竖版 ffprobe：{_fmt_streams(v_info)}｜{_mb(vertical)}")

    # ---- 产物登记（rel 一律相对 ctx.work＝<run>/video；横竖两版都登记）----
    landscape = ("video", "讲解视频（横版 1920×1080）", "video.mp4",
                 {"durationSec": round(h_info["duration"], 2), "w": W, "h": H, "codec": "h264/aac"})
    portrait = ("video", "讲解视频（竖版 1080×1920）", "video-vertical.mp4",
                {"durationSec": round(v_info["duration"], 2), "w": VW, "h": VH})
    # config.video.aspect 只决定哪一版排前面（主版本），两版都产出
    for kind, label, rel, meta in ((portrait, landscape) if aspect == "9:16" else (landscape, portrait)):
        ctx.artifact(kind, label, rel, preview=True, meta=meta)
    ctx.artifact("image", "视频封面 cover.png", "cover.png", preview=True, meta={"w": W, "h": H})
    ctx.artifact("json", "分镜与旁白 narration.json", "narration.json", preview=True,
                 meta={"slides": len(slides), "totalSec": story["totalSec"]})
    ctx.artifact("text", "字幕 subtitles.srt", "subtitles.srt", preview=True,
                 meta={"cues": len(global_cues)})

    report = {
        "engine": {
            "ffmpeg": ffmpeg, "ffprobe": ffprobe,
            "ffmpegVersion": (_run([ffmpeg, "-version"], timeout=60).stdout or "").splitlines()[0][:120],
            "tts": f"edge-tts via {tts_python}", "voice": voice,
            "font": font_path, "storyboard": source,
        },
        "slides": len(slides), "pagesWithFigure": sum(1 for s in slides if s.figure),
        "plannedSec": round(expected, 2), "totalSec": story["totalSec"],
        "ttsMode": "edge-tts" if n_silent == 0 else f"degraded({n_silent}/{len(slides)} silent)",
        "video": h_info, "videoVertical": v_info,
        "coverBytes": cover.stat().st_size,
        "cues": len(global_cues), "lastCueEnd": round(last_cue, 2), "cueDriftSec": round(drift, 2),
        "plannedNumbers": planned, "residualViolations": residual, "droppedTraceability": dropped,
        "elapsedSec": round(time.time() - started, 1),
    }
    (work / "video.report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    ctx.artifact("json", "合成报告 video.report.json", "video.report.json", preview=False)

    # ---- check（失败一律如实标 fail，原因写进 detail）----
    ctx.check(
        "视频可解码（横版）",
        "pass" if h_info["duration"] > 0 and _has(h_info, "video", "h264") and _has(h_info, "audio", "aac") else "fail",
        f"{_fmt_streams(h_info)}；ffprobe 时长 {h_info['duration']:.2f}s（>0）",
    )
    ctx.check(
        "视频可解码（竖版）",
        "pass" if v_info["duration"] > 0 and _has(v_info, "video", "h264") else "fail",
        f"{_fmt_streams(v_info)}；时长 {v_info['duration']:.2f}s",
    )
    ctx.check(
        "分镜数",
        "pass" if N_MIN <= len(slides) <= N_MAX else "fail",
        f"{len(slides)} 页（要求 {N_MIN}–{N_MAX}）；分镜来源 {source}；{report['pagesWithFigure']} 页配图",
    )
    ctx.check(
        "数字可回溯",
        "fail" if residual else "pass",
        (f"成片文本里的 {planned} 个数字全部可在 digest.json 中回溯"
         + (f"；过程中丢弃 {len(dropped)} 处含无法回溯数字的内容：{dropped[0][:60]}" if dropped else ""))
        if not residual else
        f"成片仍有 {len(residual)} 处无法回溯：{'；'.join(residual[:3])}",
    )
    ctx.check(
        "字幕与音轨对齐",
        "pass" if global_cues and drift <= 2.5 and all(a < b for a, b, _ in global_cues) else "fail",
        (f"{len(global_cues)} 条字幕，末条结束 {last_cue:.2f}s / 视频 {total:.2f}s，偏差 {drift:.2f}s"
         if global_cues else "没有生成任何字幕"),
    )
    ctx.check(
        "配音（TTS）",
        "pass" if n_silent == 0 else "fail",
        (f"{len(slides)} 页全部用 {voice} 配音（edge-tts）" if n_silent == 0 else
         f"{n_silent}/{len(slides)} 页 TTS 失败已降级为无声："
         f"{[s.index for s in slides if s.tts != 'edge-tts']}；首条报错见 video.report.json"),
    )
    ctx.check(
        "时长",
        "pass" if abs(total - target_sec) <= max(45, 0.35 * target_sec) else "run",
        f"成片 {total:.1f}s / 目标 {target_sec}s（旁白合计 {sum(len(s.narration) for s in slides)} 字）",
    )
    ctx.check("封面", "pass" if cover.is_file() and cover.stat().st_size > 0 else "fail",
              f"cover.png {W}×{H}，{cover.stat().st_size // 1024} KB")

    ctx.progress(1.0)
    ctx.log("ok", f"视频模块完成：{len(slides)} 页 / {total:.1f}s（横版 + 竖版 + 封面 + 字幕），"
                  f"耗时 {time.time() - started:.0f}s")
    if dropped:
        ctx.log("warn", f"反幻觉校验共丢弃 {len(dropped)} 处，明细见 video.report.json")


def _collect_planned_numbers(slides: list[Slide]) -> int:
    n = 0
    for s in slides:
        n += len(numbers_in(s.narration))
        for b in s.bullets:
            n += len(numbers_in(b))
    return n


def _has(info: dict, kind: str, codec: str) -> bool:
    return any(s.get("type") == kind and s.get("codec") == codec for s in info.get("streams") or [])


def _fmt_streams(info: dict) -> str:
    parts = []
    for s in info.get("streams") or []:
        if s.get("type") == "video":
            parts.append(f"{s.get('width')}×{s.get('height')} {s.get('codec')}")
        else:
            parts.append(f"{s.get('codec')} {s.get('sample_rate')}Hz/{s.get('channels')}ch")
    return " + ".join(parts) or "（无流）"


def _mb(path: Path) -> str:
    return f"{path.stat().st_size / 1048576:.2f} MB" if path.is_file() else "缺失"


# --------------------------------------------------------------------------- #
# CLI：不经 FastAPI / 流水线也能跑（验收与调试用）
# --------------------------------------------------------------------------- #

class _CliStage:
    id = "video"
    label = "视频合成"
    engine = "app.modules.video"


class _CliCtx:
    """最小 StageContext 替身：只实现 run_video 用到的接口，脱离 FastAPI 直接跑。

    artifact() 照 StageContext 的语义实现（rel 相对阶段目录、文件不存在就不登记），
    这样 CLI 跑出来的登记结果与真实流水线一致。
    """

    def __init__(self, run_dir: Path, settings, run, *, force_no_llm: bool, force_skip_tts: bool) -> None:
        from ..llm import LLMClient

        self.work = Path(run_dir) / "video"
        self.work.mkdir(parents=True, exist_ok=True)
        self.run = run
        self.settings = settings
        self.llm = LLMClient(settings)
        self.shared: dict = {}
        self.stage = _CliStage()
        self.artifacts: list[dict] = []
        self.checks: list[dict] = []
        self._force_no_llm = force_no_llm
        self._force_skip_tts = force_skip_tts
        self._last_pct = -10

    def log(self, level: str, text: str) -> None:
        print(f"[{level:4}] {text}", flush=True)

    def progress(self, value: float) -> None:
        pct = int(value * 100)
        if pct // 10 > self._last_pct // 10 or pct == 100:
            print(f"[prog] {pct}%", flush=True)
        self._last_pct = pct

    def artifact(self, kind: str, label: str, rel: str, *, preview: bool = True, meta=None):
        f = self.work / rel
        if not f.is_file():
            self.log("warn", f"产物缺失，未登记：{rel}")
            return None
        rec = {"kind": kind, "label": label,
               "path": f".papercast/runs/{self.run.id}/{self.stage.id}/{rel}",
               "url": f"/artifacts/{self.run.id}/{self.stage.id}/{rel}" if preview else None,
               "bytes": f.stat().st_size, "meta": meta}
        self.artifacts.append(rec)
        print(f"[artf] {kind:6} {rec['bytes']:>9} B  {rec['path']}", flush=True)
        return rec

    def check(self, label: str, state: str, detail: str) -> None:
        self.checks.append({"label": label, "state": state, "detail": detail})
        print(f"[chk ] {state:4} {label}：{detail}", flush=True)


def _cli_run(run_dir: Path):
    from ..models import PaperRun, RunConfig, SourceInput, new_run

    f = run_dir / "run.json"
    if f.is_file():
        try:
            return PaperRun.model_validate_json(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return new_run(SourceInput(kind="pdf", value=str(run_dir / "intake" / "paper.pdf")),
                   RunConfig(), run_dir.name)


def main(argv: Optional[list[str]] = None) -> int:
    from ..config import Settings

    ap = argparse.ArgumentParser(
        prog="python -m app.modules.video",
        description="视频讲解模块独立入口：拿一个已产出的 run 目录直接出 mp4（不需要 FastAPI）。",
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", help="run id（在 PAPERCAST_DATA_DIR 下找，例如 run_d5cd057bab48）")
    g.add_argument("--run-dir", help="run 目录路径（含 understand/digest.json 与 intake/）")
    ap.add_argument("--voice", default="", help=f"edge-tts 音色（默认 {DEFAULT_VOICE}）")
    ap.add_argument("--target-sec", type=int, default=0, help="覆盖目标时长（秒）")
    ap.add_argument("--no-llm", action="store_true", help="不用 LLM，按 digest 出确定性分镜")
    ap.add_argument("--skip-tts", action="store_true", help="强制无声（验证降级路径）")
    ap.add_argument("--json", action="store_true", help="结尾多打一行机器可读的汇总 JSON")
    a = ap.parse_args(argv)

    settings = Settings.load()
    run_dir = (Path(a.run_dir).expanduser().resolve() if a.run_dir
               else Path(settings.data_dir) / a.run)
    if not (run_dir / "understand" / "digest.json").is_file() and not (run_dir / "run.json").is_file():
        print(f"错误：{run_dir} 里既没有 understand/digest.json 也没有 run.json", file=sys.stderr)
        return 2

    run = _cli_run(run_dir)
    if a.voice:
        run.config.video.voice = a.voice
    if a.target_sec:
        run.config.video.durationSec = a.target_sec

    ctx = _CliCtx(run_dir, settings, run, force_no_llm=a.no_llm, force_skip_tts=a.skip_tts)
    print(f"== video 模块独立运行：run_dir={run_dir}  work={ctx.work}", flush=True)
    try:
        asyncio.run(run_video(ctx))
    except Exception as e:
        print(f"\n!! 失败：{type(e).__name__}: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        if a.json:
            print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}",
                              "checks": ctx.checks}, ensure_ascii=False))
        return 3
    if a.json:
        print(json.dumps({"ok": True, "runDir": str(run_dir), "artifacts": ctx.artifacts,
                          "checks": ctx.checks}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
