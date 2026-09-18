#!/usr/bin/env python3
"""小红书短版（60-90 秒竖版钩子视频）：按 short_script.json 逐镜出片。

与 make_portrait_video.py 的差别：这里镜数少（7 个左右）、每镜自带口播词与钩子标题，
配音直接现录（edge-tts），不沿用整篇旁白，也不做提速——短版的节奏靠镜头切换而不是语速。

用法：
  python ops/make_short_video.py --script <run>/video/xiaohongshu_short/short_script.json \
      --frames-dir <run>/video/video_frames [--out-dir ...]
产物：xhs_short.mp4（1080x1920，烧字幕）、cover_xhs.png（1080x1440）、xiaohongshu_meta.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_portrait_video import (  # noqa: E402
    FFMPEG, FFPROBE, W, H, build_cues, ffprobe_duration, load_font, make_ass,
    make_cover, make_portrait, resolve_font, resolve_tool, sh, run,
)

SHORT_TITLE = "论文自动生成讲解视频，成本0.001美元"
SHORT_BODY = """一篇论文进去，一段带幻灯片、配音、光标、数字人讲者的讲解视频出来——成本 0.001 美元。

📍 NUS Show Lab 的 Paper2Video（arXiv 2510.05096），一个多智能体框架 + 一个 101 篇论文的评测基准。

三个关键点：
1️⃣ 幻灯片直接生成 Beamer 源码，编译报错由智能体自己修
2️⃣ 光标"句内静止、句间移动"，像真人抬手示意
3️⃣ 人类评估排第二，只输给人类作品，时长还比人类短四成

完整 4 分钟中文讲解在主页 👉 关注不迷路
#论文分享 #科研 #人工智能 #多智能体 #arXiv #读论文 #效率工具"""


def tts(text: str, voice: str, rate: str, out: Path, tool: str) -> None:
    run([tool, "-v", voice, "--rate", rate, "-t", text, "--write-media", str(out)])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True, help="short_script.json")
    ap.add_argument("--frames-dir", required=True, help="video_frames 目录（取 slide_NNN.png）")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--crf", type=int, default=20)
    args = ap.parse_args()

    spec_path = Path(args.script).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    frames_dir = Path(args.frames_dir).resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir else spec_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tts").mkdir(exist_ok=True)
    (out_dir / "frames_portrait").mkdir(exist_ok=True)
    (out_dir / "subtitles").mkdir(exist_ok=True)
    (out_dir / "segments").mkdir(exist_ok=True)

    font_path = resolve_font()
    tts_tool = resolve_tool("edge-tts")
    voice = spec.get("voice", "zh-CN-XiaoyiNeural")
    rate = spec.get("rate", "+0%")
    pad = float(spec.get("padSec", 0.25))
    shots = spec["shots"]
    total = len(shots)
    print(f"字体：{font_path}\n镜数：{total}，音色：{voice} {rate}，输出：{out_dir}")

    segments: list[Path] = []
    for i, shot in enumerate(shots, start=1):
        idx = int(shot["page"])
        slide = frames_dir / f"slide_{idx:03d}.png"
        if not slide.exists():
            raise SystemExit(f"缺帧：{slide}")
        title = shot.get("title") or f"第 {i} 镜"
        mp3 = out_dir / "tts" / f"shot_{i:02d}.mp3"
        tts(shot["text"], voice, rate, mp3, tts_tool)
        speech = ffprobe_duration(mp3)

        pf = out_dir / "frames_portrait" / f"s{i:02d}.png"
        make_portrait(slide, title, i, total, pf, font_path)

        cues = build_cues(shot["text"], speech)
        ass = out_dir / "subtitles" / f"s{i:02d}.ass"
        make_ass(cues, ass)

        dst = out_dir / "segments" / f"seg_{i:02d}.mp4"
        chain = (f"[0:v]subtitles={ass}:fontsdir={font_path.parent}[v];"
                 f"[1:a]apad=pad_dur={pad}[a]")
        run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
             "-loop", "1", "-framerate", "25", "-i", str(pf), "-i", str(mp3),
             "-filter_complex", chain, "-map", "[v]", "-map", "[a]",
             "-t", f"{speech + pad:.3f}",
             "-c:v", "libx264", "-crf", str(args.crf), "-preset", "medium", "-tune", "stillimage",
             "-pix_fmt", "yuv420p", "-r", "25", "-c:a", "aac", "-b:a", "192k",
             "-ar", "44100", "-ac", "2", "-movflags", "+faststart", str(dst)])
        segments.append(dst)
        print(f"  [{i}/{total}] {title}  ({speech:.1f}s)")

    listfile = out_dir / "segments" / "concat.txt"
    listfile.write_text("".join(f"file '{s}'\n" for s in segments), encoding="utf-8")
    final = out_dir / "xhs_short.mp4"
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", str(listfile), "-c", "copy", "-movflags", "+faststart", str(final)])
    duration = ffprobe_duration(final)

    cover = out_dir / "cover_xhs.png"
    make_cover(frames_dir / f"slide_{int(shots[0]['page']):03d}.png", cover, font_path, SHORT_TITLE)
    meta = {
        "platform": "xiaohongshu",
        "kind": "short",
        "title": SHORT_TITLE,
        "content": SHORT_BODY,
        "video": str(final),
        "cover": str(cover),
        "durationSec": round(duration, 2),
        "resolution": f"{W}x{H}",
        "voice": voice,
        "tags": ["论文分享", "科研", "人工智能", "多智能体", "arXiv", "读论文", "效率工具"],
        "shots": [{"page": s["page"], "title": s.get("title", ""), "text": s["text"]} for s in shots],
    }
    (out_dir / "xiaohongshu_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"短版成片：{final}  时长 {duration:.1f}s\n封面：{cover}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
