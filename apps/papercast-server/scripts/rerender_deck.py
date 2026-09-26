#!/usr/bin/env python
"""重新渲染已存在 run 的小红书组图（不重跑整条流水线）。

用途：改了 `cards_deck` 的排版/字号模型之后，把已经跑完、卡在发布闸门上的 run
用新代码重出一组图 —— 不用重新理解论文、不重新调 LLM、不重新抓 arXiv。

    .venv/bin/python scripts/rerender_deck.py run_e24920f4d088 [run_xxx ...]
    .venv/bin/python scripts/rerender_deck.py --latest 3      # 最近 3 条有 poster.spec 的 run

为什么需要它：组图是 publish 阶段唯一的图片来源（`publish._deck_images` 读
`poster/cards/xhs-*.jpg`），而 publish 阶段会停在人工闸门上等确认。闸门不点、
就只能靠这个脚本换图 —— 走 `POST /api/runs/{id}/stages/{sid}/gate` 之前就能看到新图。

只做三件事：build（重排 index.html）→ render（PNG + JPEG 侧车）→ 同步投递清单。
不碰 understand / article 的产物，也不碰 run.json 的状态机（闸门还等在那里）。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules import cards_deck  # noqa: E402
from app.config import Settings  # noqa: E402


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _sync_deliverables(run_dir: Path, frames: list[dict]) -> list[str]:
    """把组图同步进 publish 的投递清单，让工作台/渠道立刻看到新图。

    publish 阶段读的是 `publish/<channel>/export/`，而 run 往往正卡在发布闸门上
    （`chosen` 还没选、deliveries 还没落盘）。所以这里按 publish._collect 的同款命名
    约定铺一份：cover.jpg + p1..pN.jpg，**p1 与 cover 是同一张** —— 这是既有约定
    （首图既要当封面又要当第 1 张正文图），不是重复渲染。

    只认**渲染器报回来的 frame**（逐个按 id 取文件），不 glob 整个 output 目录 ——
    页数变少时目录里可能还留着上几轮的旧图，glob 会把它们一起投出去。
    """
    out: list[str] = []
    produced = Path(run_dir) / "poster" / "cards" / "output"
    jpegs: list[Path] = []
    for fr in frames:
        fid = str(fr.get("id") or "")
        if not fid:
            continue
        for ext in (".jpg", ".png"):
            p = produced / f"{fid}{ext}"
            if p.is_file():
                jpegs.append(p)
                break
    if not jpegs:
        return out
    for export in sorted(Path(run_dir).glob("publish/*/export")):
        if not export.is_dir():
            continue
        for old in list(export.glob("p*.jpg")) + list(export.glob("cover.jpg")):
            old.unlink(missing_ok=True)
        shutil.copy2(jpegs[0], export / "cover.jpg")
        for i, src in enumerate(jpegs, 1):
            shutil.copy2(src, export / f"p{i}.jpg")
        out.append(f"{export.relative_to(run_dir)}: cover + p1..p{len(jpegs)}")
    return out


def rerender(run_dir: Path, *, dry_run: bool = False) -> int:
    spec_path = run_dir / "poster" / "poster.spec.json"
    if not spec_path.is_file():
        print(f"  跳过 {run_dir.name}：没有 poster.spec.json（poster 阶段没跑完？）")
        return 1

    spec = _load(spec_path)
    cover_path = run_dir / "poster" / "poster.spec.cover.json"
    cover = _load(cover_path) if cover_path.is_file() else None
    digest = _load(run_dir / "understand" / "digest.json")
    if not spec:
        print(f"  跳过 {run_dir.name}：poster.spec.json 是空的")
        return 1

    figures = run_dir / "intake" / "images"
    note = f"{digest.get('venue') or spec.get('venue') or ''} · {digest.get('title') or spec.get('title') or ''}".strip(" ·")
    deck_dir = run_dir / "poster" / "cards"

    if dry_run:
        print(f"  [dry-run] 会重排 {run_dir.name} 的 {deck_dir}（{len(spec.get('columns') or [])} 个栏）")
        return 0

    # 与 poster_stage._run_deck 同款重试：自检不过就减内容重排（最多 3 次）。
    # 阶梯只降「每页条目数」，不砍页数 —— 砍页会把图全丢掉（见 poster_stage 里的说明）。
    last: dict = {}
    for attempt, (max_items, keep) in enumerate(((4, None), (3, None), (2, None))):
        built = cards_deck.build(spec, cover, digest, figures, deck_dir,
                                 max_items=max_items, keep_pages=keep, note=note)
        rep = cards_deck.render(deck_dir, scale=1)
        chk = cards_deck.validate(deck_dir)
        last = {"built": built, "rep": rep, "chk": chk, "attempt": attempt}
        frames = rep.get("frames") or []
        ok = chk.get("fails", 0) == 0 and rep.get("ok") and len(frames) == built.get("pages")
        if ok:
            break
        bad = [d for d in chk.get("details") or [] if d["level"] in ("FAIL", "WARN")][:2]
        print(f"  第 {attempt + 1} 次：fails={chk.get('fails')} warns={chk.get('warns')} "
              f"frames={len(frames)}/{built.get('pages')} → 减内容重排 {bad}")

    chk, rep = last["chk"], last["rep"]
    frames = rep.get("frames") or []
    print(f"  {run_dir.name}: {len(frames)} 张 · fails={chk.get('fails')} warns={chk.get('warns')}"
          f" · {'第 %d 次才通过' % (last['attempt'] + 1) if last['attempt'] else '一次通过'}")
    for d in chk.get("details") or []:
        print(f"      [{d['level']}] {d.get('rule')} {d.get('text', '')[:110]}")

    for line in _sync_deliverables(run_dir, frames):
        print(f"      投递清单已同步 → {line}")
    return 0 if chk.get("fails", 0) == 0 and frames else 2


def main() -> int:
    ap = argparse.ArgumentParser(description="用当前 cards_deck 代码重出既有 run 的小红书组图")
    ap.add_argument("runs", nargs="*", help="run id（run_xxxxxxxx）")
    ap.add_argument("--latest", type=int, default=0, help="改取最近 N 条有 poster.spec.json 的 run")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    settings = Settings.load()
    data = Path(settings.data_dir)
    if a.latest:
        cands = sorted((p for p in data.glob("run_*") if (p / "poster" / "poster.spec.json").is_file()),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:a.latest]
        ids = [p.name for p in cands]
    else:
        ids = list(a.runs)
    if not ids:
        ap.error("给 run id，或用 --latest N")

    rc = 0
    for rid in ids:
        run_dir = data / rid
        if not run_dir.is_dir():
            print(f"跳过 {rid}：目录不存在（data_dir={data}）")
            rc = 2
            continue
        rc |= rerender(run_dir, dry_run=a.dry_run)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
