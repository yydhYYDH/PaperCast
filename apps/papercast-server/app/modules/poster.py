"""L2 · poster 阶段：把 digest + 论文原图排成会议海报（HTML → PNG）。

设计取舍（对齐 ADR #5「确定性排版优先于 AI 出图」）：
- 版面由 `poster.spec.json` 描述（标题/作者/栏目/图），内容来自 digest 与论文原文；
- 本模块只做三件事：把 spec 排成 HTML、二分字号直到「刚好装下」、调渲染底座出 PNG；
- 这里不调用任何文生图/视觉模型。需要 AI 出图的封面、插图走 imagegen 通路（另接）。

字号自适应（对应 Paper2Poster 的 Painter-Commentor 循环，但去掉视觉模型，改成可复现的机械循环）：
  整张海报所有字号/间距都乘一个统一变量 --s，从 1.0 往下二分，取「不溢出」的最大值。
  因此同一份 spec 在任何画布尺寸下都能收敛到「字最大且不溢出」的版面。

命令行：
  python -m app.modules.poster --spec <poster.spec.json> --out-dir <dir> [--size 48x36] [--dpi 48] [--no-fit]
产物：<out-dir>/poster.html · poster.png · poster.render.json · figures/
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import os
from pathlib import Path
from typing import Any, Iterable, Optional

# 视觉系统（版式 + 配色 + 字阶）在 poster_theme.py：本文件只管机制（二分字号、几何闸门、
# 渠道预设、出图）。换风格改那一个文件即可。
from . import poster_theme
from .poster_theme import build_html  # noqa: F401  （对外保留 poster.build_html 这个入口）

SIZE_IN = (48.0, 36.0)          # 会议海报默认 48x36 英寸横版（唯一需要"英寸"的场景：打印）
DPI = 48                        # 2304x1728 px；打印可提高到 150（7200x5400）
SCALE_MIN = 0.45                # 自适应字号的下界；到界还溢出说明内容太多，需要删字数

# 渠道画布预设：数字渠道只认像素，不认英寸。每个预设带一个 tag，
# spec 里的块可以用 "sizes": ["wide"] / ["tall"] 声明自己上哪些画布 —— 窄画布装不下就减块，
# 而不是把字缩到看不清。
BODY_CQW = poster_theme.BODY_CQW  # 唯一事实源在 poster_theme：正文 .panel li/p 的 cqw 常量
LEGIBILITY_FLOOR = 0.75          # 字号最多缩到目标值的 75%，再小就判"装不下"，去减内容而不是缩字
# 封面（cover 版式）没有正文可比，可读性改成「标题必须占到画布宽度的这个百分比」。
# 4.0% 的含义：1080 宽的小红书首图 → 标题 ≥43px（手机上三米外认得出），1920 宽的 B 站封面 → ≥77px。
COVER_H1_FLOOR_PCT = 4.0

PRESETS: dict[str, dict[str, Any]] = {
    # body_px 是**在最终像素画布上的目标正文大小**：cqw 相对宽度，所以同一个 CSS 在 1080 宽的
    # 画布上字号会掉到 1/2 —— 必须按画布反推基础倍率，否则手机上看不清。
    # cols_max 是窄画布的内容策略：3:4 硬塞三栏 → 每栏 330px，正文必然不可读，所以收成 1 栏。
    "conf":     {"px": (2304, 1728), "tag": "wide", "cols_max": 3, "body_px": 24, "note": "48x36 in @48dpi 会议海报 / 打印存档"},
    "zhihu":    {"px": (1600, 1200), "tag": "wide", "cols_max": 3, "body_px": 22, "note": "知乎正文横版信息图（4:3；1440x1080 装不下三栏正文）"},
    "bili":     {"px": (1920, 1080), "tag": "wide", "cols_max": 3, "body_px": 22, "note": "B 站视频封面 / 横版头图（16:9）"},
    "xhs":      {"px": (1080, 1440), "tag": "tall", "cols_max": 1, "body_px": 30, "note": "小红书首图（3:4，单栏）"},
    "xhs-long": {"px": (1080, 2400), "tag": "tall", "cols_max": 1, "body_px": 26, "note": "小红书/知乎竖长图（1080x2400，单栏）"},
    # 封面类：内容很少（标题 + 一句钩子 + 3 个标签 + 一张主视觉），从一个大倍率往下二分求「能放多大放多大」。
    # 纸面编辑风的封面标题本来就是「两三行的大字」，所以起点比旧版（2.6）低：再大就会一个字一行。
    "xhs-cover":  {"px": (1080, 1440), "tag": "cover", "cols_max": 1, "body_px": 30, "scale_start": 1.0, "note": "小红书首图封面（3:4 竖版：大标题 + 主视觉 + 底部标签）"},
    "bili-cover": {"px": (1920, 1080), "tag": "cover", "cols_max": 1, "body_px": 26, "scale_start": 1.15, "note": "B 站视频封面：左侧大标题 + 右侧主视觉"},
}


def _weight(block: dict[str, Any]) -> int:
    """粗估块的内容量，只为分栏均衡用。"""
    if block.get("kind") == "figure":
        return 60
    return 20 + sum(len(str(x)) for x in (block.get("items") or [])) // 2 + len(str(block.get("text") or "")) // 2


def merge_columns(spec: dict[str, Any], cols_max: int) -> dict[str, Any]:
    """把栏目数压到 cols_max：窄画布上「三栏 → 一栏」，块按内容量均衡分配。"""
    cols = spec.get("columns") or []
    if not cols or len(cols) <= cols_max:
        return spec
    blocks = [b for c in cols for b in c]
    buckets: list[list[dict[str, Any]]] = [[] for _ in range(cols_max)]
    loads = [0] * cols_max
    for b in sorted(blocks, key=_weight, reverse=True):   # 大的先放，贪心均衡
        i = loads.index(min(loads))
        buckets[i].append(b)
        loads[i] += _weight(b)
    out = json.loads(json.dumps(spec))
    # 保持每栏内部原有的阅读顺序
    order = {id(b): i for i, b in enumerate(blocks)}
    out["columns"] = [[b for b in sorted(bucket, key=lambda x: order.get(id(x), 0))] for bucket in buckets if bucket]
    return out


def target_scale(body_px: float, width_px: int) -> float:
    """反推基础倍率：让正文在最终画布上约等于 body_px。"""
    return round(body_px / max(BODY_CQW * width_px / 100.0, 0.001), 4)


def filter_for_preset(spec: dict[str, Any], tag: str) -> dict[str, Any]:
    """按 preset tag 过滤块；整栏被滤空就丢掉该栏。块没写 sizes 视为所有画布都上。"""
    out = json.loads(json.dumps(spec))
    cols = []
    for blocks in out.get("columns", []):
        keep = []
        for b in blocks:
            if b.get("sizes") and tag not in b["sizes"]:
                continue
            # 竖版装不下横版的字数：块可以用 items_tall 写一份更短的条目，而不是把字缩到看不清
            if tag == "tall" and b.get("items_tall"):
                b["items"] = b["items_tall"]
            keep.append(b)
        if keep:
            cols.append(keep)
    if not cols and out.get("layout") != "cover":
        raise ValueError(f"preset tag={tag} 把所有栏目都滤空了，检查 spec 的 sizes 字段")
    out["columns"] = cols
    if out.get("teaser") and out["teaser"].get("sizes") and tag not in out["teaser"]["sizes"]:
        out.pop("teaser")
    return out


def workspace_root() -> Path:
    """从本文件位置反推工作区根：apps/papercast-server/app/modules/poster.py"""
    return Path(__file__).resolve().parents[4]


def default_renderer() -> Path:
    return workspace_root() / "ops" / "shot" / "render.mjs"


def load_spec(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not data.get("title"):
        raise ValueError("spec 缺少 title")
    cols = data.get("columns") or []
    # cover 版式（封面）不需要栏位：它的结构是「大标题 + 主视觉」，不是网格
    if not cols and data.get("layout") != "cover":
        raise ValueError("spec 缺少 columns")
    return data

def stage_figures(spec: dict[str, Any], figures_dir: Path | str, out_dir: Path) -> dict[str, Any]:
    """把 spec 引用到的图拷进 <out>/figures/，并把 src 改成相对路径（HTML 自包含、可搬运）。

    figures_dir 支持 os.pathsep 分隔的多个目录（先找到的胜），这样「论文原图在 intake/、
    AI 生成的 hero 图在 poster/」可以同时被引用。
    """
    fig_out = out_dir / "figures"
    fig_out.mkdir(parents=True, exist_ok=True)
    search = [Path(d) for d in str(figures_dir).split(os.pathsep) if d.strip()]

    def stage(block: dict[str, Any]) -> None:
        if not block.get("file"):
            return
        src = Path(block["file"])
        if not src.is_absolute():
            for base in search:
                if (base / src).is_file():
                    src = base / src
                    break
            else:
                raise FileNotFoundError(
                    f"图不存在：{src}（已在这些目录里找过：{', '.join(str(s) for s in search)}）"
                )
        if not src.is_file():
            raise FileNotFoundError(f"图不存在：{src}")
        dst = fig_out / src.name
        if src.resolve() != dst.resolve():
            shutil.copyfile(src, dst)
        block["src"] = f"figures/{dst.name}"

    staged = json.loads(json.dumps(spec))  # 深拷贝，不改调用方
    if staged.get("teaser"):
        stage(staged["teaser"])
    for blocks in staged["columns"]:
        for b in blocks:
            stage(b)
    return staged


def render_png(
    html_path: Path,
    png_path: Path,
    *,
    width: int,
    height: int,
    renderer: Optional[Path] = None,
    node: str = "node",
    timeout: int = 120,
) -> dict[str, Any]:
    """调 ops/shot/render.mjs（横切 B 渲染底座）出 PNG，并带回几何自检 JSON。"""
    renderer = Path(renderer) if renderer else default_renderer()
    if not renderer.is_file():
        raise FileNotFoundError(f"渲染底座不存在：{renderer}")
    proc = subprocess.run(
        [node, str(renderer), "--html", str(html_path), "--out", str(png_path),
         "--width", str(width), "--height", str(height), "--check"],
        capture_output=True, text=True, timeout=timeout,
    )
    info: dict[str, Any] = {}
    for raw in reversed((proc.stdout or "").strip().splitlines()):
        raw = raw.strip()
        if raw.startswith("{"):
            try:
                info = json.loads(raw)
                break
            except json.JSONDecodeError:
                continue
    if not info:
        raise RuntimeError(f"渲染器无 JSON 输出（exit={proc.returncode}）：{(proc.stderr or '')[-400:]}")
    info["exit"] = proc.returncode
    return info


def geometry_report(info: dict[str, Any], width: int, height: int, *, scale: float) -> dict[str, Any]:
    """几何自检：溢出项、缺图、填充率。panel_fill 只看 .cols 区域（海报正文区该占总面积的多少）。"""
    panels = info.get("panels") or []
    regions_list = info.get("regions") or []
    by_name: dict[str, list[dict[str, Any]]] = {}
    for r in regions_list:
        by_name.setdefault(r.get("name") or "", []).append(r)
    # 正文面板：排除 teaser（它是通栏横带，算进去会让 panel_fill 虚高 >1）
    body_panels = [p for p in panels if p.get("name") != "teaser"]
    panel_area = sum((p.get("w", 0) * p.get("h", 0)) for p in body_panels)
    total = float(width * height) or 1.0
    # panel_fill：正文面板面积 / 三个栏位面积之和。接近 1 表示栏内没有大片空白（不留空门）。
    col_areas = [float((c.get("w") or 0) * (c.get("h") or 0)) for c in by_name.get("col", [])]
    cols_area = sum(col_areas)
    overflow = [p for p in panels if (p.get("overflowY", 0) > 2 or p.get("overflowX", 0) > 2)]
    broken = [i.get("src") for i in (info.get("brokenImages") or [])]
    report = {
        "width": width,
        "height": height,
        "scale": round(scale, 4),
        "panels": len(panels),
        "overflow": [{"panel": p.get("name"), "overflowY": p.get("overflowY"), "overflowX": p.get("overflowX")} for p in overflow],
        "broken_images": broken,
        "box_fill": round(panel_area / total, 4),
        "panel_fill": round(panel_area / cols_area, 4) if cols_area else None,
        "body_px": round(BODY_CQW * width / 100.0 * scale, 1),
        "fonts_px": info.get("fonts") or {},
        # 封面没有正文：可读性判据改用标题字号（占画布宽度的百分比），见 COVER_H1_FLOOR_PCT
        "h1_pct": round(100.0 * float((info.get("fonts") or {}).get("h1") or 0) / max(width, 1), 2),
        "regions": {
            k: ({"w": v[0].get("w"), "h": v[0].get("h")} if len(v) == 1 else
                {"w": max(x.get("w") or 0 for x in v), "h": max(x.get("h") or 0 for x in v), "count": len(v)})
            for k, v in by_name.items()
        },
    }
    report["ok"] = not overflow and not broken
    return report


def make_poster(
    spec_path: str | Path,
    out_dir: str | Path,
    *,
    size_in: tuple[float, float] = SIZE_IN,
    dpi: int = DPI,
    figures_dir: Optional[str | Path] = None,
    renderer: Optional[Path] = None,
    fit: bool = True,
    scale: float = 1.0,
    scale_min: float = SCALE_MIN,
    max_iter: int = 8,
    preset: str = "",
    out_name: str = "poster",
) -> dict[str, Any]:
    """二分 --s，取「不溢出的最大字号」；再按该字号出最终 PNG。

    preset 给了就直接用渠道像素（数字渠道只认像素）；不给则用 size_in x dpi（打印场景）。
    """
    spec_raw = load_spec(spec_path)
    body_px_target = 0.0
    floor = scale_min
    if preset:
        if preset not in PRESETS:
            raise KeyError(f"未知 preset：{preset}（可选：{', '.join(PRESETS)}）")
        pr = PRESETS[preset]
        size_in = (pr["px"][0], pr["px"][1])
        dpi = 1
        spec_raw = filter_for_preset(spec_raw, pr["tag"])
        spec_raw = merge_columns(spec_raw, int(pr.get("cols_max", 3)))
        body_px_target = float(pr.get("body_px", 0) or 0)
        if body_px_target:
            floor = round(target_scale(body_px_target, pr["px"][0]) * LEGIBILITY_FLOOR, 4)
            # 封面类内容很少：从一个大倍率往下二分，找「不溢出的最大字号」而不是「刚好可读」
            scale = float(pr.get("scale_start", 0) or 0) or target_scale(body_px_target, pr["px"][0])
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    figs: Any = str(figures_dir) if figures_dir else str(Path(spec_path).resolve().parent)
    spec = stage_figures(spec_raw, figs, out)

    width = int(round(size_in[0] * dpi))
    height = int(round(size_in[1] * dpi))
    html_path = out / f"{out_name}.html"
    png_path = out / f"{out_name}.png"

    def attempt(s: float) -> tuple[dict[str, Any], dict[str, Any]]:
        html_path.write_text(build_html(spec, size_in=size_in, scale=s), encoding="utf-8")
        info = render_png(html_path, png_path, width=width, height=height, renderer=renderer)
        return info, geometry_report(info, width, height, scale=s)

    tries: list[dict[str, Any]] = []
    info, report = attempt(scale)
    tries.append(report)
    if fit and not report["ok"]:
        lo, hi = floor, scale               # 假设「字号越小越不溢出」；下界是可读性下限，不是 0.45
        # 先确认下界能装下；装不下就直接返回下界结果（说明内容需要删字）
        info_lo, rep_lo = attempt(lo)
        tries.append(rep_lo)
        if rep_lo["ok"]:
            best_info, best = info_lo, rep_lo
            for _ in range(max_iter):
                mid = round((lo + hi) / 2, 4)
                if abs(hi - lo) < 0.02:
                    break
                info_m, rep_m = attempt(mid)
                tries.append(rep_m)
                if rep_m["ok"]:
                    lo, best_info, best = mid, info_m, rep_m
                else:
                    hi = mid
            info, report = best_info, best
        else:
            info, report = info_lo, rep_lo

    report["html"] = str(html_path)
    report["png"] = str(png_path)
    report["preset"] = preset or None
    report["columns"] = len(spec.get("columns") or [])
    report["body_px_target"] = body_px_target or None
    if spec.get("layout") == "cover":
        # 封面：标题就是全部。标题太小 = 这条渠道白出（信息流里点不进去）。
        if report["h1_pct"] < COVER_H1_FLOOR_PCT:
            report["ok"] = False
            report["reason"] = (
                "封面标题只有画布宽度的 %.1f%%（下限 %g%%）—— 要么把标题压到 15 字内，要么换更大的画布"
                % (report["h1_pct"], COVER_H1_FLOOR_PCT)
            )
    elif body_px_target and report.get("body_px", 0) < body_px_target * LEGIBILITY_FLOOR - 0.5:
        report["ok"] = False
        report["reason"] = (
            "画布装不下：正文只有 %.1fpx（目标 %gpx）—— 该渠道要减内容，或换更大画布（xhs → xhs-long）"
            % (report.get("body_px", 0), body_px_target)
        )
    report["fit"] = fit
    report["tries"] = [{"scale": t["scale"], "ok": t["ok"], "max_overflow": max([o["overflowY"] for o in t["overflow"]] or [0])} for t in tries]
    (out / f"{out_name}.render.json").write_text(
        json.dumps({**info, "report": report}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return report


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="spec/digest → 会议海报 PNG")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--figures-dir", default="")
    ap.add_argument("--size", default=f"{SIZE_IN[0]:g}x{SIZE_IN[1]:g}", help="英寸，如 48x36")
    ap.add_argument("--dpi", type=int, default=DPI)
    ap.add_argument("--scale", type=float, default=1.0, help="起始字号倍率（--preset 时会按 body_px 反推）")
    ap.add_argument("--preset", default="", help="渠道画布预设；给了就忽略 --size/--dpi")
    ap.add_argument("--list-presets", action="store_true")
    ap.add_argument("--out-name", default="poster", help="产物文件名前缀（多画布时用不同前缀）")
    ap.add_argument("--no-fit", action="store_true", help="不做二分自适应")
    ap.add_argument("--renderer", default="")
    a = ap.parse_args(list(argv) if argv is not None else None)

    if a.list_presets:
        print(json.dumps(PRESETS, ensure_ascii=False, indent=1))
        return 0

    w, h = (float(x) for x in a.size.lower().split("x"))
    report = make_poster(
        a.spec, a.out_dir, size_in=(w, h), dpi=a.dpi,
        figures_dir=a.figures_dir or None,
        renderer=Path(a.renderer) if a.renderer else None,
        fit=not a.no_fit, scale=a.scale,
        preset=a.preset, out_name=a.out_name or "poster",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
