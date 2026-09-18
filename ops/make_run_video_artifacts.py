#!/usr/bin/env python3
"""把 paper-share-skills 的 video 产物转成 PaperCast 的 run video 契约（D1）。

输入：
  --paper-dir  <PAPER_DIR>   paper-to-bilibili 约定目录（slides-beamer/ + video/）
  --run-dir    <run dir>     var/runs/<runId>，产物写到其 video/ 子目录

输出：
  <run-dir>/video/narration.json   {title,totalSec,slides:[{index,title,bullets,narration,durationSec}]}
  <run-dir>/video/<name>_narrated.mp4
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

WS = Path(__file__).resolve().parents[1]

CLEAN = [
    (re.compile(r"\\shl\{([^{}]*)\}"), r"\1"),
    (re.compile(r"\\keyword\{([^{}]*)\}"), r"\1"),
    (re.compile(r"\\brandemph\{([^{}]*)\}"), r"\1"),
    (re.compile(r"\\hlbox\{([^{}]*)\}"), r"\1"),
    (re.compile(r"\\textbf\{([^{}]*)\}"), r"\1"),
    (re.compile(r"\\textit\{([^{}]*)\}"), r"\1"),
    (re.compile(r"\\textsubscript\{([^{}]*)\}"), r"\1"),
    (re.compile(r"\\textsuperscript\{([^{}]*)\}"), r"\1"),
    (re.compile(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?"), ""),
    (re.compile(r"[{}]"), ""),
    (re.compile(r"\s+"), " "),
]


def clean(text: str) -> str:
    for pattern, repl in CLEAN:
        text = pattern.sub(repl, text)
    return text.replace("$", "").replace("\\", "").strip()


def parse_pages(tex: str) -> list[dict]:
    """按物理页顺序返回 [{kind,title,bullets}]，章节分隔页用 \\secblurb。"""
    pages: list[dict] = []
    lines = tex.split("\n")
    in_frame = False
    frame_title = ""
    bullets: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("% NARRATION:"):
            continue
        if stripped.startswith("\\renewcommand{\\secblurb}"):
            blurb = re.sub(r"^\\renewcommand\{\\secblurb\}\{", "", stripped).rstrip("}")
            pages.append({"kind": "section", "title": "", "bullets": [clean(blurb)], "blurb": clean(blurb)})
            continue
        if stripped.startswith("\\section{"):
            name = re.sub(r"^\\section\{", "", stripped).rstrip("}")
            for page in pages:  # 该分隔页的标题即 section 名
                if page["kind"] == "section" and not page["title"]:
                    page["title"] = clean(name)
                    break
            continue
        if stripped.startswith("\\begin{frame}"):
            in_frame = True
            bullets = []
            m = re.search(r"\{([^{}]*)\}\s*$", stripped)
            frame_title = clean(m.group(1)) if m and stripped != "\\begin{frame}" else ""
            continue
        if stripped.startswith("\\end{frame}"):
            in_frame = False
            pages.append({"kind": "frame", "title": frame_title, "bullets": bullets})
            continue
        if in_frame and stripped.startswith("\\item"):
            bullets.append(clean(stripped[len("\\item"):]))
    return pages


def probe(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-dir", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--speed", type=float, default=1.25, help="assemble_video 的语速倍率")
    args = parser.parse_args()

    paper_dir = Path(args.paper_dir).resolve()
    run_video = Path(args.run_dir).resolve() / "video"
    run_video.mkdir(parents=True, exist_ok=True)

    tex = (paper_dir / "slides-beamer" / "main.tex").read_text(encoding="utf-8")
    source_pages = parse_pages(tex)
    narrations = json.loads(
        (paper_dir / "video" / "narrations.json").read_text(encoding="utf-8")
    )
    if len(source_pages) != len(narrations):
        raise SystemExit(
            f"page mismatch: tex={len(source_pages)} narrations={len(narrations)}"
        )

    frames_dir = paper_dir / "video" / "video_frames"
    slides = []
    total = 0.0
    for index, (page, key) in enumerate(zip(source_pages, sorted(narrations, key=int)), start=1):
        segments = sorted(frames_dir.glob(f"slide_{index:03d}_final.mp4"))
        duration = (probe(segments[0]) / args.speed) if segments else 0.0
        total += duration
        title = page["title"] or (page["bullets"][0] if page["bullets"] else f"Slide {index}")
        slides.append({
            "index": index,
            "title": title,
            "kind": page["kind"],
            "bullets": page["bullets"] if page["kind"] == "frame" else [],
            "narration": narrations[key],
            "durationSec": round(duration, 2),
        })

    mp4 = next((paper_dir / "video").glob("*_narrated.mp4"), None)
    if mp4 is None:
        raise SystemExit("no narrated mp4 found")
    target_mp4 = run_video / mp4.name
    shutil.copy2(mp4, target_mp4)
    shutil.copy2(paper_dir / "video" / "cover.png", run_video / "cover.png")

    payload = {
        "title": "Paper2Video: Automatic Video Generation from Scientific Papers（arXiv 2510.05096）",
        "source": str(mp4.relative_to(WS)) if str(mp4).startswith(str(WS)) else str(mp4),
        "totalSec": round(total, 2),
        "slides": slides,
    }
    (run_video / "narration.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "narration_json": str(run_video / "narration.json"),
        "video": str(target_mp4),
        "slides": len(slides),
        "totalSec": round(total, 2),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
