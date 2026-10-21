#!/usr/bin/env python
"""一次性维护脚本：给**已存在**的 run 补/修媒体，不重跑整条流水线。

背景：流水线是「一次性写入」的 —— intake 抽完图就不再回头。于是当抽图逻辑修好之后，
老 run 不会自动受益。这个脚本对指定 run 做三件确定的事：

1. **修复抽成纯黑的内嵌图**（带 SMask/蒙版时 `extract_image` 的裸流全黑）：
   按 `intake/figures.json` 里的 page+bbox 用 `get_pixmap` 重渲染覆盖，仍全黑则删除该图；
2. **补裁「标题 + 作者 + 单位」截图** → `intake/images/titleblock.png`，写进 `meta.json`；
3. 把 `titleBlock` 并进 `poster.spec.cover.json` 后，复用 `rerender_deck` 重出小红书组图。

用法（在 apps/papercast-server 下）：
    .venv/bin/python scripts/refresh_run_media.py run_530f17bcec77 run_f2426b810651
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pymupdf  # noqa: E402

import rerender_deck  # noqa: E402
from app.config import Settings  # noqa: E402
from app.intake import pdf_parser, titleblock  # noqa: E402
from app.modules import poster_stage  # noqa: E402

ZOOM = 3.0


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _fix_black_figures(run_dir: Path, pdf: Path, log=print) -> int:
    """把抽成纯黑的图按页面区域重渲染；仍全黑就删掉。返回修复数。"""
    figs_path = run_dir / "intake" / "figures.json"
    figs = _load(figs_path)
    if not isinstance(figs, list) or not figs:
        return 0
    fixed = 0
    intake = run_dir / "intake"
    with pymupdf.open(pdf) as doc:
        for f in figs:
            rel = str(f.get("file") or "")
            page_no = int(f.get("page") or 0)
            bbox = f.get("bbox") or []
            if not rel or page_no < 1 or len(bbox) != 4:
                continue
            target = intake / rel
            if not target.is_file() or not pdf_parser._looks_near_black(target):
                continue
            page = doc[page_no - 1]
            page.get_pixmap(clip=pymupdf.Rect(bbox), matrix=pymupdf.Matrix(ZOOM, ZOOM)).save(str(target))
            if pdf_parser._looks_near_black(target):
                target.unlink(missing_ok=True)
                log(f"    - {rel} 重渲染仍纯黑，已删除")
            else:
                log(f"    - {rel} 纯黑已修复（重渲染）")
            fixed += 1
    return fixed


def refresh(run_dir: Path) -> int:
    pdf = run_dir / "intake" / "paper.pdf"
    if not pdf.is_file():
        print(f"  跳过 {run_dir.name}：没有 intake/paper.pdf")
        return 1

    print(f"  {run_dir.name}:")
    fixed = _fix_black_figures(run_dir, pdf)
    if not fixed:
        print("    · 没有需要修复的纯黑图")

    tb = titleblock.crop_titleblock(pdf, run_dir / "intake" / "images" / "titleblock.png")
    print(f"    · 标题/作者/单位截图：{('有，%dx%d' % (tb['w'], tb['h'])) if tb else '未定位到'}")

    meta_path = run_dir / "intake" / "meta.json"
    meta = _load(meta_path)
    if meta:
        meta["titleBlock"] = tb or None
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    cover_path = run_dir / "poster" / "poster.spec.cover.json"
    if cover_path.is_file():
        cover = poster_stage.attach_titleblock(_load(cover_path), run_dir / "intake")
        cover_path.write_text(json.dumps(cover, ensure_ascii=False, indent=2), encoding="utf-8")

    print("    · 重出小红书组图…")
    return rerender_deck.rerender(run_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description="给已有 run 补/修媒体（黑图 + 标题块）并重出组图")
    ap.add_argument("runs", nargs="+", help="run id（run_xxxxxxxx）")
    a = ap.parse_args()
    data = Path(Settings.load().data_dir)
    rc = 0
    for rid in a.runs:
        run_dir = data / rid
        if not run_dir.is_dir():
            print(f"跳过 {rid}：目录不存在（data_dir={data}）")
            rc = 2
            continue
        rc |= refresh(run_dir)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
