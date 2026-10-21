"""作品配图的手动增删：列候选 + 读写 `poster/selected.json`。

为什么单独一个模块：投递时**已经**认 `poster/selected.json`（人工选定优先于自动顺序，
见 `modules/publish.py` 的 `_selected_images`/`_pick_media`），但一直没有写它的入口 ——
界面上配图只能看不能改（2026-10-02 用户反馈）。这里只补上「列候选 / 存选择」这对视图背后的
纯函数，选图顺序的最终解释权仍在 `modules/publish.py` 一处。

安全：`selected.json` 会被投递直接吃，所以写进去的路径必须真实存在于 run 目录内 ——
越界（../）或不存在一律拒绝，不允许把 run 外的文件塞进投递清单。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from .modules import publish as pub

#: 与 modules/publish.py 同一处定义（poster/selected.json）
SELECTED_REL = pub.SELECTED_REL


def _rel(run_dir: Path, path: Path) -> str:
    return path.relative_to(run_dir).as_posix()


def _figures_meta(run_dir: Path) -> dict[str, dict[str, Any]]:
    """file 名 → figures.json 里那一条（kind/caption），给界面写图注用。"""
    f = run_dir / "intake" / "figures.json"
    meta: dict[str, dict[str, Any]] = {}
    if not f.is_file():
        return meta
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return meta
    items = data if isinstance(data, list) else (data.get("figures") or [])
    for it in items:
        if isinstance(it, dict) and it.get("file"):
            meta[Path(it["file"]).name] = it
    return meta


def _candidates(run_dir: Path, run_id: str) -> list[dict[str, Any]]:
    """这台 run 里所有可以当配图的图：组图 → 文章卡片 → 论文原图/表格。

    顺序就是界面上默认的展示顺序（组图是小红书实际投出去的那套，排最前）。
    """
    run_dir = Path(run_dir)
    figs = _figures_meta(run_dir)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(path: Path, kind: str, label: str = "") -> None:
        if not path.is_file():
            return
        rel = _rel(run_dir, path)
        if rel in seen:
            return
        seen.add(rel)
        out.append({
            "path": rel,
            "name": path.name,
            "kind": kind,
            "label": label,
            "url": f"/artifacts/{run_id}/{rel}",
        })

    for p in pub._deck_images(run_dir):
        add(p, "deck", "小红书组图")
    for p in sorted((run_dir / "article" / "cards").glob("p*.png")):
        add(p, "card", "文章卡片")
    for p in pub._intake_figures(run_dir, lambda *a: None):
        meta = figs.get(p.name, {})
        kind = "table" if str(meta.get("kind") or "") == "table" else "figure"
        caption = str(meta.get("caption") or "").strip()
        add(p, kind, caption[:90])
    # 兜底：figures.json 没列到、但磁盘上真有的图（AI hero 之类）
    img_dir = run_dir / "intake" / "images"
    if img_dir.is_dir():
        for p in sorted(img_dir.glob("*.png")):
            add(p, "figure", "")
    # 人工选过、指向别处（如 poster/hero）的也列出来，免得一存就把它挤掉
    selected, _cover = pub._selected_images(run_dir)
    for p in selected:
        add(p, "selected", "上次选定的")
    return out


def _effective_selection(run_dir: Path) -> list[str]:
    """当前真正会投出去的图：人工选过就用它，否则用自动顺序（与投递同一口径）。"""
    selected, _cover = pub._selected_images(run_dir)
    if selected:
        return [_rel(run_dir, p) for p in selected]
    images, _video, _cover = pub._pick_media(run_dir)
    return [_rel(run_dir, p) for p in images if p.is_file()]


def list_media(run_id: str, run_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    chosen = _effective_selection(run_dir)
    chosen_set = set(chosen)
    candidates = _candidates(run_dir, run_id)
    # 选中的图一律排在最前且勾上；其余按候选顺序跟在后面
    for c in candidates:
        c["chosen"] = c["path"] in chosen_set
    ranked = sorted(candidates, key=lambda c: (0 if c["chosen"] else 1, chosen.index(c["path"]) if c["path"] in chosen_set else 0))
    return {
        "runId": run_id,
        "selected": chosen,
        "candidates": ranked,
        "hasSelection": run_dir.joinpath(*SELECTED_REL).is_file(),
    }


def save_media(run_id: str, run_dir: Path, images: Optional[list[str]]) -> dict[str, Any]:
    """存人工选图。`images` 为空/None = 恢复自动顺序（删掉 selected.json）。

    只接受 run 目录内、真实存在的图片路径；任一非法就整体拒绝，不写半份。
    """
    run_dir = Path(run_dir)
    target = run_dir.joinpath(*SELECTED_REL)
    if not images:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return {"runId": run_id, "selected": _effective_selection(run_dir), "hasSelection": False}

    base = run_dir.resolve()
    clean: list[str] = []
    for rel in images:
        p = (run_dir / str(rel)).resolve()
        if p != base and base not in p.parents:
            raise ValueError(f"路径越出 run 目录：{rel}")
        if not p.is_file():
            raise ValueError(f"图片不存在：{rel}")
        clean.append(Path(str(rel)).as_posix())

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {"images": clean, "cover": clean[0], "updatedAt": int(time.time())},
            ensure_ascii=False, indent=1,
        ),
        encoding="utf-8",
    )
    return {"runId": run_id, "selected": clean, "hasSelection": True}
