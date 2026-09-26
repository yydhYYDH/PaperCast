#!/usr/bin/env python
"""只重抽 images/ 里的图，不动 content.md / sections.json / figures.json 的其余字段。

用途：2026-09-26 修了 `_figure_region` 的一个真 bug —— 裁剪框下边界用的是**图注底**，
于是每张抽出来的 PNG 都把英文图注一起烤了进去（实测 fig-4 的 bbox y 82.3→269.0，
而图注块是 213.4→267.3）。修完想看效果，但不想为了换图重跑整条流水线
（会重新调 LLM、重新抓 arXiv，还可能让 figure id 漂移，digest 就对不上了）。

    .venv/bin/python scripts/reextract_figures.py run_xxx [run_yyy ...]

只做三件事：按修好的裁剪框重新栅格化 → 覆盖 images/<file>.png → 回写该图的
width/height/bbox。caption、id、kind 一个字都不改。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf  # noqa: E402

from app.intake import pdf_parser as pp  # noqa: E402


def reextract(run_dir: Path, *, zoom: float = 3.0, dry_run: bool = False) -> tuple[int, int]:
    intake = run_dir / "intake"
    pdf_path = intake / "paper.pdf"
    figs_path = intake / "figures.json"
    if not pdf_path.is_file() or not figs_path.is_file():
        print(f"  跳过 {run_dir.name}：缺 paper.pdf 或 figures.json")
        return 0, 0

    figures = json.loads(figs_path.read_text(encoding="utf-8"))
    if isinstance(figures, dict):
        figures = figures.get("figures") or []
    if not figures:
        return 0, 0

    doc = pymupdf.open(pdf_path)
    changed = same = 0
    try:
        by_page: dict[int, list[dict]] = {}
        for f in figures:
            by_page.setdefault(int(f.get("page") or 0), []).append(f)

        for pno, group in by_page.items():
            if not (1 <= pno <= doc.page_count):
                continue
            page = doc[pno - 1]
            vis, blocks = pp._page_items(page)
            caps = pp._find_captions(blocks)
            cap_rects = [c["rect"] for c in caps]
            for f in group:
                cap = _match_cap(caps, f)
                if cap is None:
                    print(f"  {run_dir.name} {f.get('id')}: 这一页找不到对应图注，跳过")
                    continue
                clip, hit = pp._figure_region(cap["rect"], cap, vis, blocks, page.rect, cap_rects)
                clip = clip & page.rect
                if clip.is_empty or clip.height < 20:
                    print(f"  {run_dir.name} {f.get('id')}: 裁剪框退化，跳过")
                    continue
                before = [f.get("width"), f.get("height")]
                if dry_run:
                    print(f"  {run_dir.name} {f.get('id')}: {before} -> "
                          f"{round(clip.width)}x{round(clip.height)}  (dry-run)")
                    continue
                target = intake / str(f.get("file") or "")
                if not target.name:
                    continue
                # 位图能直抽就直抽（保持原分辨率），否则按裁剪框栅格化
                raster = pp._best_raster(page, clip)
                src = "render"
                if raster and raster[0]:
                    try:
                        img = doc.extract_image(raster[0])
                        target.write_bytes(img["image"])
                        src = "raster"
                    except Exception:
                        src = "render"
                if src == "render":
                    page.get_pixmap(clip=clip, matrix=pymupdf.Matrix(zoom, zoom)).save(str(target))
                with pymupdf.open(target) as im:
                    w, h = im[0].rect.width, im[0].rect.height
                f["width"], f["height"] = int(w), int(h)
                f["bbox"] = [round(v, 1) for v in clip]
                after = (int(w), int(h))
                if (before[0], before[1]) != after:
                    changed += 1
                else:
                    same += 1
    finally:
        doc.close()

    if not dry_run:
        figs_path.write_text(json.dumps(figures, ensure_ascii=False, indent=1), encoding="utf-8")
    return changed, same


def _match_cap(caps: list[dict], fig: dict) -> dict | None:
    """按图号 + 类型找到这一页里对应的图注（图号可能为空，按顺序兜底）。"""
    num = str(fig.get("number") or "")
    kind = str(fig.get("kind") or "fig")
    for c in caps:
        if str(c.get("number") or "") == num and c.get("kind") == kind:
            return c
    if not num:                       # 没编号的（内嵌图像）：按同类型的第一个
        for c in caps:
            if c.get("kind") == kind and not c.get("number"):
                return c
    return None


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    if not args:
        print(__doc__)
        return 2
    root = Path(__file__).resolve().parents[3] / "var" / "runs"
    for rid in args:
        changed, same = reextract(root / rid, dry_run=dry)
        print(f"{rid}: {changed} 张尺寸变了，{same} 张没变")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
