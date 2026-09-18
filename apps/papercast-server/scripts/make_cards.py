#!/usr/bin/env python
"""小红书 3:4 卡片图出图脚本（M2 的 article/cards 那一步，可单独跑）。

卡片渲染本身在 app/cards/render.py（PIL，确定性排版）。本脚本只做两件事：
1. 把 digest.json 的 figures[]（中文图注）与 M1 intake 的图片文件对上；
2. 调 render_cards 出 p1..pN.png，并打印机器可读的结果。

用法（在 apps/papercast-server 下）：
  .venv/bin/python scripts/make_cards.py \
      --digest <digest.json> --figures-dir <intake/images> --out-dir <article/cards> \
      [--map fig1=fig-1-teaser.png ...] [--series "..."] [--source-note "..."]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cards import render as card_render  # noqa: E402

# digest 里的 figureId 与 intake 里的图片文件名不是同一套编号（一个来自 LLM 摘要，
# 一个来自 LaTeX includegraphics），所以必须显式给映射，不允许猜。
DEFAULT_MAP: dict[str, str] = {}


def pick_map(args_map: list[str]) -> dict[str, str]:
    out = dict(DEFAULT_MAP)
    for item in args_map or []:
        k, _, v = item.partition("=")
        if k and v:
            out[k.strip()] = v.strip()
    return out


def build_picks(digest: dict, mapping: dict[str, str], figures_dir: Path) -> tuple[list[dict], list[str]]:
    picks, notes = [], []
    figs = digest.get("figures") or []
    for i, f in enumerate(figs, 1):
        fid = str(f.get("id") or "")
        file = mapping.get(fid, "")
        if not file:
            notes.append(f"{fid}: 没有给图片映射，跳过")
            continue
        if not (figures_dir / file).is_file():
            notes.append(f"{fid}: 映射到 {file}，但文件不存在，跳过")
            continue
        cap = (f.get("caption") or "").strip()
        picks.append({
            "figureId": fid,
            "file": file,
            "badge": f"{i}/{len(figs)}",
            "headline": cap.split("：")[0].split(":")[0][:22] or f"图 {i}",
            "captionCn": cap,
        })
    return picks, notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--digest", required=True)
    ap.add_argument("--figures-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--map", action="append", default=[], help="fig1=fig-1-teaser.png，可重复")
    ap.add_argument("--series", default="")
    ap.add_argument("--source-note", default="")
    ap.add_argument("--font", default="")
    a = ap.parse_args()

    digest = json.loads(Path(a.digest).read_text(encoding="utf-8"))
    figures_dir = Path(a.figures_dir)
    picks, notes = build_picks(digest, pick_map(a.map), figures_dir)
    series = a.series or (digest.get("title") or "")[:24]
    note = a.source_note or f"图源：{digest.get('title', '')}（arXiv {digest.get('arxivId', '')}）"

    made, errors = card_render.render_cards(
        picks, figures_dir, Path(a.out_dir),
        series=series, source_note=note, font_preferred=a.font,
    )
    print(json.dumps({"made": made, "errors": errors + notes, "picks": len(picks)}, ensure_ascii=False))
    return 0 if made else 4


if __name__ == "__main__":
    sys.exit(main())
