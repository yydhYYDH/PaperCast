#!/usr/bin/env python3
"""把横版讲解视频转成小红书竖版（1080x1920）：模糊背景 + 大字幕 + 卡片式幻灯片。

输入：paper-slides-to-video 产出的 run 目录（video_frames/ 里有
      slide_NNN.png(帧) / slide_NNN_final.mp4(帧+配音) / slide_NNN.mp3(配音)，
      以及 narration.json）。
输出：<out-dir>/ 下
      xhs_vertical.mp4    1080x1920 竖版成片（默认 1.25x 提速，与横版时长一致）
      cover_xhs.png       1080x1440 封面（3:4）
      xiaohongshu_meta.json  标题/正文/话题标签
      frames_portrait/    逐页竖版版式图（可复用/可改）
      subtitles/*.ass     逐页字幕（自然语速时间轴，随 setpts 一起提速）

设计要点：字幕在 setpts 提速*之前*烧进画面，因此字幕文件用自然时间轴，
最后一步 setpts/atempo 提速时字幕跟着一起走，无需二次编码。

用法：
  python ops/make_portrait_video.py --video-dir <run>/video [--out-dir ...] [--speed 1.25]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
SLIDE_W = 1000                      # 幻灯片卡片宽（16:10 -> 625 高）
CARD_X, CARD_Y = (W - SLIDE_W) // 2, 430
ACCENT = (18, 90, 168)              # 主色（深蓝）
ACCENT2 = (18, 179, 166)            # 强调色（青）
PAPER_ID = "arXiv 2510.05096"
FOOTER = "Paper2Video · 论文分享"
FONT_FAMILY = "Microsoft YaHei"


def resolve_tool(name: str) -> str:
    """先找 PATH，再回落到本工作区工具链 var/toolchains/p2b/bin（不写死绝对路径）。"""
    found = shutil.which(name)
    if found:
        return found
    alt = Path(__file__).resolve().parents[1] / "var" / "toolchains" / "p2b" / "bin" / name
    if alt.exists():
        return str(alt)
    raise SystemExit(f"找不到可执行文件 {name}（装到 PATH 或 var/toolchains/p2b/bin）")


FFMPEG = resolve_tool("ffmpeg")
FFPROBE = resolve_tool("ffprobe")


def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def ffprobe_duration(path: Path) -> float:
    out = sh([FFPROBE, "-v", "error", "-show_entries", "format=duration",
              "-of", "csv=p=0", str(path)]).stdout.strip()
    return float(out)


def resolve_font() -> Path:
    out = sh(["fc-match", "-f", "%{file}", FONT_FAMILY]).stdout.strip()
    if not out or not Path(out).exists():
        raise SystemExit(f"找不到字体 {FONT_FAMILY}；用 fc-list :lang=zh 看看系统里有哪些中文字体")
    return Path(out)


def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


# ---------- 版式 ----------

def make_portrait(slide: Path, title: str, index: int, total: int, out: Path, font_path: Path) -> None:
    base = Image.open(slide).convert("RGB")

    # 背景：幻灯片铺满 + 高斯模糊 + 压暗
    ratio = max(W / base.width, H / base.height)
    bg = base.resize((math.ceil(base.width * ratio), math.ceil(base.height * ratio)), Image.LANCZOS)
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2,
                  (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
    bg = bg.filter(ImageFilter.GaussianBlur(42))
    bg = Image.eval(bg, lambda v: int(v * 0.42))
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    canvas.paste(bg, (0, 0))

    draw = ImageDraw.Draw(canvas, "RGBA")
    f_pill = load_font(font_path, 40)
    f_title = load_font(font_path, 60)
    f_small = load_font(font_path, 32)

    # 顶部序号胶囊
    pill = f"{index:02d} / {total}"
    pw = draw.textlength(pill, font=f_pill)
    draw.rounded_rectangle([60, 96, 60 + pw + 56, 96 + 74], radius=37, fill=ACCENT2 + (235,))
    draw.text((60 + 28, 96 + 13), pill, font=f_pill, fill=(255, 255, 255))

    # 标题（最多两行，超出截断）
    lines, cur = [], ""
    for ch in title:
        if draw.textlength(cur + ch, font=f_title) <= W - 120:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
            if len(lines) == 2:
                break
    if cur and len(lines) < 2:
        lines.append(cur)
    y = 196
    for line in lines:
        draw.text((60, y), line, font=f_title, fill=(255, 255, 255))
        y += 76

    # 幻灯片卡片 + 阴影
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [CARD_X - 10, CARD_Y - 10, CARD_X + SLIDE_W + 10, CARD_Y + int(SLIDE_W * base.height / base.width) + 10],
        radius=34, fill=(0, 0, 0, 150))
    canvas = Image.alpha_composite(canvas.convert("RGBA"),
                                  shadow.filter(ImageFilter.GaussianBlur(18))).convert("RGB")
    draw = ImageDraw.Draw(canvas, "RGBA")
    card_h = int(SLIDE_W * base.height / base.width)
    draw.rounded_rectangle([CARD_X, CARD_Y, CARD_X + SLIDE_W, CARD_Y + card_h], radius=26, fill=(255, 255, 255))
    canvas.paste(base.resize((SLIDE_W, card_h), Image.LANCZOS), (CARD_X, CARD_Y))
    draw.rounded_rectangle([CARD_X, CARD_Y, CARD_X + SLIDE_W, CARD_Y + card_h], radius=26, outline=(255, 255, 255), width=2)


    # 页脚 + 进度条
    foot_y = H - 118
    draw.line([60, foot_y - 34, W - 60, foot_y - 34], fill=(255, 255, 255, 70), width=2)
    draw.text((60, foot_y), PAPER_ID, font=f_small, fill=(255, 255, 255, 210))
    right = f_small.getbbox(FOOTER) and FOOTER
    draw.text((W - 60 - draw.textlength(right, font=f_small), foot_y), right, font=f_small, fill=(255, 255, 255, 210))
    bar_y = H - 44
    draw.rounded_rectangle([60, bar_y, W - 60, bar_y + 10], radius=5, fill=(255, 255, 255, 60))
    draw.rounded_rectangle([60, bar_y, 60 + int((W - 120) * index / total), bar_y + 10], radius=5, fill=ACCENT2)

    canvas.save(out, "PNG")


# ---------- 字幕 ----------

def split_sentences(text: str, max_len: int = 30) -> list[str]:
    """按标点切句，再按长度二次切分，避免一行太长。"""
    parts = [p for p in re.split(r"(?<=[。！？；!?;])", text.strip()) if p.strip()]
    out: list[str] = []
    for part in parts:
        part = part.strip()
        while len(part) > max_len:
            cut = max(part.rfind("，", 0, max_len), part.rfind(",", 0, max_len), part.rfind("、", 0, max_len))
            cut = cut if cut > max_len * 0.5 else max_len
            out.append(part[:cut + 1].strip())
            part = part[cut + 1:].strip()
        if part:
            out.append(part)
    return out


def ass_time(t: float) -> str:
    t = max(t, 0.0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def make_ass(cues: list[tuple[float, float, str]], out: Path) -> None:
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{FONT_FAMILY},54,&H00FFFFFF,&H00FFFFFF,&H96000000,&H00000000,-1,0,0,0,100,100,0.5,0,1,3,1,2,60,60,360,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for start, end, text in cues:
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{text}")
    out.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


def build_cues(narration: str, speech_len: float) -> list[tuple[float, float, str]]:
    """把一段旁白按字符数比例铺在 [0, speech_len] 上。"""
    chunks = split_sentences(narration)
    if not chunks:
        return []
    total = sum(len(c) for c in chunks)
    cues, t = [], 0.0
    for i, chunk in enumerate(chunks):
        dur = speech_len * len(chunk) / total
        gap = 0.10 if i < len(chunks) - 1 else 0.0
        cues.append((t, max(t + dur - gap, t + 0.4), chunk))
        t += dur
    return cues


# ---------- 主流程 ----------

def slide_titles(pdf: Path | None, frames: list[Path], narr: dict) -> list[str]:
    titles = []
    if pdf and pdf.exists():
        try:
            import pymupdf
            doc = pymupdf.open(pdf)
            for page in doc:
                best, best_size = "", 0.0
                for block in page.get_text("dict")["blocks"]:
                    for line in block.get("lines", []):
                        for span in line["spans"]:
                            if span["size"] > best_size and span["bbox"][1] < page.rect.height * 0.35:
                                best_size, best = span["size"], span["text"].strip()
                titles.append(best)
            if len(titles) == len(frames):
                return titles
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 从 PDF 取标题失败：{exc}", file=sys.stderr)
    for item in narr.get("slides", []):
        titles.append(item.get("title") or "")
    return titles


CLEAN_RE = [
    (re.compile(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?"), ""),
    (re.compile(r"[{}]"), ""),
    (re.compile(r"\s+"), " "),
]


def _clean(text: str) -> str:
    for pattern, repl in CLEAN_RE:
        text = pattern.sub(repl, text)
    return text.strip()


def titles_from_tex(tex: Path) -> list[str]:
    """按 deck 源码顺序还原「节分隔页 + 内容页」的逐页标题（与 PDF 页码一致）。"""
    titles: list[str] = []
    for line in tex.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("\\section{"):
            titles.append(_clean(re.search(r"\\section\{([^{}]*)\}", stripped).group(1)))
        elif stripped.startswith("\\begin{frame}"):
            m = re.match(r"\\begin\{frame\}(?:\[[^\]]*\])?\{(.*)\}", stripped)
            titles.append(_clean(m.group(1)) if m else "")
    return titles


XHS_TITLE = "论文自动生成讲解视频，成本0.001美元"
XHS_BODY = """Paper2Video（arXiv 2510.05096，NUS Show Lab）——给一篇论文，自动产出一段带幻灯片、配音、光标和数字人讲者的学术演示视频。

📌 三件事
1️⃣ 多智能体流水线：Writer 写脚本、Designer 排版幻灯片
2️⃣ 一个专门的"光标智能体"决定讲到哪、指到哪
3️⃣ PaperTalker 基准：101 篇论文、四个维度自动评测

⚠️ 局限：页数上限 40 页、依赖字幕质量、数字人是 PPT 级效果

全程中文讲解 👇
#论文分享 #科研 #人工智能 #多智能体 #arXiv #读论文 #效率工具 #AI工具"""


def make_cover(slide: Path, out: Path, font_path: Path, title: str = XHS_TITLE) -> None:
    """1080x1440（3:4）小红书封面。"""
    cw, ch = 1080, 1440
    base = Image.open(slide).convert("RGB")
    ratio = max(cw / base.width, ch / base.height)
    bg = base.resize((math.ceil(base.width * ratio), math.ceil(base.height * ratio)), Image.LANCZOS)
    bg = bg.crop(((bg.width - cw) // 2, (bg.height - ch) // 2,
                  (bg.width - cw) // 2 + cw, (bg.height - ch) // 2 + ch))
    canvas = Image.alpha_composite(
        bg.filter(ImageFilter.GaussianBlur(38)).convert("RGBA"),
        Image.new("RGBA", (cw, ch), (6, 18, 34, 190)),
    ).convert("RGB")
    draw = ImageDraw.Draw(canvas, "RGBA")
    f_badge, f_title, f_small = load_font(font_path, 40), load_font(font_path, 86), load_font(font_path, 38)

    badge = "论文速览 · 3 分钟看懂"
    bw = draw.textlength(badge, font=f_badge)
    draw.rounded_rectangle([70, 150, 70 + bw + 60, 150 + 84], radius=42, fill=ACCENT2 + (235,))
    draw.text((100, 172), badge, font=f_badge, fill=(255, 255, 255))
    draw.text((70, 150 + 84 + 40), "Paper2Video", font=f_title, fill=(255, 255, 255))
    draw.text((70, 150 + 84 + 40 + 104), title, font=load_font(font_path, 62), fill=(255, 255, 255))
    draw.rectangle([70, 150 + 84 + 40 + 104 + 100, 70 + 140, 150 + 84 + 40 + 104 + 112], fill=ACCENT2)
    draw.text((70, ch - 220), "arXiv 2510.05096 · NUS Show Lab", font=f_small, fill=(255, 255, 255, 225))
    draw.text((70, ch - 160), "PaperTalker · 多智能体 · 光标与数字人讲者", font=f_small, fill=(255, 255, 255, 190))
    canvas.save(out, "PNG")


def write_meta(out_dir: Path, video: Path, cover: Path, total_sec: float) -> Path:
    meta = {
        "platform": "xiaohongshu",
        "title": XHS_TITLE,
        "content": XHS_BODY,
        "video": str(video),
        "cover": str(cover),
        "durationSec": round(total_sec, 2),
        "resolution": f"{W}x{H}",
        "tags": ["论文分享", "科研", "人工智能", "多智能体", "arXiv", "读论文", "效率工具", "AI工具"],
        "note": "视频/xiaohongshu/ 下：xhs_vertical.mp4（竖版成片，需人工确认后发布）",
    }
    path = out_dir / "xiaohongshu_meta.json"
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video-dir", required=True, help="run 的 video 目录（含 video_frames/ 与 narration.json）")
    ap.add_argument("--slides-pdf", default=None, help="课件 PDF，用来取每页标题（可选）")
    ap.add_argument("--slides-tex", default=None, help="deck 源码（首选标题来源，按节/页顺序还原）")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--speed", type=float, default=1.25, help="整体语速倍率，1.0 = 自然语速")
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true", help="只生成竖版版式图与字幕，不起视频")
    args = ap.parse_args()

    video_dir = Path(args.video_dir).resolve()
    frames_dir = video_dir / "video_frames"
    out_dir = Path(args.out_dir).resolve() if args.out_dir else video_dir / "xiaohongshu"
    out_dir.mkdir(parents=True, exist_ok=True)
    portrait_dir = out_dir / "frames_portrait"
    subs_dir = out_dir / "subtitles"
    for d in (portrait_dir, subs_dir):
        d.mkdir(exist_ok=True)

    slides = sorted(frames_dir.glob("slide_*.png"))
    slides = [p for p in slides if not p.name.endswith("_final.png")]
    if not slides:
        raise SystemExit(f"在 {frames_dir} 找不到 slide_*.png")
    total = len(slides)

    narr = {}
    narr_path = video_dir / "narration.json"
    if narr_path.exists():
        narr = json.loads(narr_path.read_text(encoding="utf-8"))
    pdf_titles = slide_titles(Path(args.slides_pdf) if args.slides_pdf else None, slides, narr)
    titles = []
    if args.slides_tex:
        tex = Path(args.slides_tex)
        if tex.exists():
            titles = titles_from_tex(tex)
        if len(titles) != total:
            print(f"[warn] deck 源码解析出 {len(titles)} 页、实际 {total} 页，改用 PDF 启发式标题",
                  file=sys.stderr)
            titles = []
    if titles:
        titles = [t or p for t, p in zip(titles, pdf_titles)]
    else:
        titles = pdf_titles

    font_path = resolve_font()
    print(f"字体：{FONT_FAMILY} -> {font_path}")
    print(f"页数：{total}，输出目录：{out_dir}")

    segments: list[Path] = []
    for i, png in enumerate(slides, start=1):
        idx = int(png.stem.split("_")[1])
        seg_src = frames_dir / f"slide_{idx:03d}_final.mp4"
        mp3 = frames_dir / f"slide_{idx:03d}.mp3"
        title = (titles[i - 1] if i - 1 < len(titles) else "") or f"第 {i} 页"
        pf = portrait_dir / f"p{idx:03d}.png"
        make_portrait(png, title, i, total, pf, font_path)

        narration = ""
        if i - 1 < len(narr.get("slides", [])):
            narration = narr["slides"][i - 1].get("narration", "")
        if not narration:
            txt = frames_dir / f"slide_{idx:03d}.txt"
            narration = txt.read_text(encoding="utf-8").strip() if txt.exists() else ""
        speech = ffprobe_duration(mp3) if mp3.exists() else 5.0
        if args.speed != 1.0:
            # 字幕在提速前烧入，时间轴用自然语速
            pass
        cues = build_cues(narration, speech)
        ass = subs_dir / f"p{idx:03d}.ass"
        make_ass(cues, ass)
        if not args.dry_run:
            if not seg_src.exists():
                raise SystemExit(f"缺少配音分片：{seg_src}")
            seg_dir = out_dir / "segments"
            seg_dir.mkdir(exist_ok=True)
            dst = seg_dir / f"seg_{idx:03d}.mp4"
            vf = f"subtitles={ass}:fontsdir={font_path.parent}"
            chain = (f"[0:v]{vf}[v0];[v0]setpts=PTS/{args.speed}[v1];"
                     f"[1:a]atempo={args.speed}[a1]") if args.speed != 1.0 else f"[0:v]{vf}[v1];[1:a]anull[a1]"
            run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                 "-loop", "1", "-framerate", "25", "-i", str(pf),
                 "-i", str(seg_src),
                 "-filter_complex", chain,
                 "-map", "[v1]", "-map", "[a1]",
                 "-c:v", "libx264", "-crf", str(args.crf), "-preset", "medium", "-tune", "stillimage",
                 "-pix_fmt", "yuv420p", "-r", "25", "-c:a", "aac", "-b:a", "192k",
                 "-shortest", "-movflags", "+faststart", str(dst)])
            segments.append(dst)
            print(f"  [{i}/{total}] {pf.name} -> {dst.name}  ({title[:24]})")

    if args.dry_run:
        print("dry-run：只出了版式图与字幕，未编码视频")
        return 0

    listfile = out_dir / "segments" / "concat.txt"
    listfile.write_text("".join(f"file '{s}'\n" for s in segments), encoding="utf-8")
    final = out_dir / "xhs_vertical.mp4"
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", str(listfile), "-c", "copy", "-movflags", "+faststart", str(final)])
    duration = ffprobe_duration(final)
    print(f"竖版成片：{final}  时长 {duration:.1f}s")

    cover = out_dir / "cover_xhs.png"
    make_cover(slides[0], cover, font_path)
    meta = write_meta(out_dir, final, cover, duration)
    print(f"封面：{cover}\n元数据：{meta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
