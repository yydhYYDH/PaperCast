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
import html as html_mod
import json
import shutil
import subprocess
import sys
import os
from pathlib import Path
from typing import Any, Iterable, Optional

SIZE_IN = (48.0, 36.0)          # 会议海报默认 48x36 英寸横版（唯一需要"英寸"的场景：打印）
DPI = 48                        # 2304x1728 px；打印可提高到 150（7200x5400）
SCALE_MIN = 0.45                # 自适应字号的下界；到界还溢出说明内容太多，需要删字数

# 渠道画布预设：数字渠道只认像素，不认英寸。每个预设带一个 tag，
# spec 里的块可以用 "sizes": ["wide"] / ["tall"] 声明自己上哪些画布 —— 窄画布装不下就减块，
# 而不是把字缩到看不清。
BODY_CQW = 0.97                  # CSS 里正文的字号常量（见 build_html 的 .panel p/li）
LEGIBILITY_FLOOR = 0.75          # 字号最多缩到目标值的 75%，再小就判"装不下"，去减内容而不是缩字

PRESETS: dict[str, dict[str, Any]] = {
    # body_px 是**在最终像素画布上的目标正文大小**：cqw 相对宽度，所以同一个 CSS 在 1080 宽的
    # 画布上字号会掉到 1/2 —— 必须按画布反推基础倍率，否则手机上看不清。
    # cols_max 是窄画布的内容策略：3:4 硬塞三栏 → 每栏 330px，正文必然不可读，所以收成 1 栏。
    "conf":     {"px": (2304, 1728), "tag": "wide", "cols_max": 3, "body_px": 24, "note": "48x36 in @48dpi 会议海报 / 打印存档"},
    "zhihu":    {"px": (1600, 1200), "tag": "wide", "cols_max": 3, "body_px": 22, "note": "知乎正文横版信息图（4:3；1440x1080 装不下三栏正文）"},
    "bili":     {"px": (1920, 1080), "tag": "wide", "cols_max": 3, "body_px": 22, "note": "B 站视频封面 / 横版头图（16:9）"},
    "xhs":      {"px": (1080, 1440), "tag": "tall", "cols_max": 1, "body_px": 30, "note": "小红书首图（3:4，单栏）"},
    "xhs-long": {"px": (1080, 2400), "tag": "tall", "cols_max": 1, "body_px": 26, "note": "小红书/知乎竖长图（1080x2400，单栏）"},
    # 封面类：内容很少，所以从一个大倍率往下二分，求「能放多大放多大」——封面要的就是大标题
    "bili-cover": {"px": (1920, 1080), "tag": "cover", "cols_max": 1, "body_px": 26, "scale_start": 2.6, "note": "B 站视频封面：大标题 + 主视觉"},
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


def _esc(s: Any) -> str:
    return html_mod.escape(str(s if s is not None else ""))


def _items_html(block: dict[str, Any]) -> str:
    items = block.get("items") or []
    if items:
        lis = "".join(f"<li>{_esc(x)}</li>" for x in items)
        return f"<ul>{lis}</ul>"
    if block.get("text"):
        return f"<p>{_esc(block['text'])}</p>"
    return ""


def _block_html(block: dict[str, Any], idx: int, col: int, last: bool) -> str:
    grow = " grow" if last else ""
    kind = block.get("kind", "panel")
    name = f"c{col + 1}-{idx}"
    if kind == "figure":
        src = _esc(block.get("src", ""))
        cap = block.get("caption") or ""
        num = block.get("number") or ""
        cap_html = (
            f'<figcaption><b>Fig. {_esc(num)}</b> {_esc(cap)}</figcaption>' if cap and num
            else (f"<figcaption>{_esc(cap)}</figcaption>" if cap else "")
        )
        return f'<figure class="figure{grow}" data-panel="{name}"><img src="{src}" alt="" />{cap_html}</figure>'
    accent = f' style="--accent:{_esc(block["accent"])}"' if block.get("accent") else ""
    kicker = f'<span class="kicker">{_esc(block["kicker"])}</span>' if block.get("kicker") else ""
    return (
        f'<section class="panel{grow}" data-panel="{name}"{accent}>'
        f'{kicker}<h2>{_esc(block.get("title", ""))}</h2>{_items_html(block)}</section>'
    )


def build_html(spec: dict[str, Any], *, size_in: tuple[float, float] = SIZE_IN, scale: float = 1.0) -> str:
    """spec → 自包含 HTML。尺寸一律 calc(var(--s) * Ncqw)：cqw 让版式与像素无关，--s 控制整体字号。"""
    w_in, h_in = size_in
    ratio = round(w_in / h_in, 4)
    theme = spec.get("theme") or {}
    css_vars = "".join(f"--{k}:{_esc(v)};" for k, v in theme.items())

    header_bits = []
    if spec.get("kicker"):
        header_bits.append(f'<div class="kicker">{_esc(spec["kicker"])}</div>')
    header_bits.append(f"<h1>{_esc(spec['title'])}</h1>")
    if spec.get("subtitle"):
        header_bits.append(f'<p class="subtitle">{_esc(spec["subtitle"])}</p>')
    meta_bits = []
    if spec.get("authors"):
        meta_bits.append(f'<div class="authors">{_esc(" · ".join(spec["authors"]))}</div>')
    if spec.get("affiliation"):
        meta_bits.append(f'<div class="aff">{_esc(spec["affiliation"])}</div>')
    if spec.get("venue"):
        meta_bits.append(f'<div class="venue">{_esc(spec["venue"])}</div>')
    if meta_bits:
        header_bits.append('<div class="meta">' + "".join(meta_bits) + "</div>")
    if spec.get("chips"):
        header_bits.append('<div class="chips">' + "".join(f"<span>{_esc(c)}</span>" for c in spec["chips"]) + "</div>")

    teaser = ""
    if spec.get("teaser"):
        t = spec["teaser"]
        cap = f'<figcaption>{_esc(t.get("caption", ""))}</figcaption>' if t.get("caption") else ""
        teaser = (
            f'<figure class="teaser" data-region="teaser" data-panel="teaser">'
            f'<img src="{_esc(t["src"])}" alt="" />{cap}</figure>'
        )

    cols_html = []
    for ci, blocks in enumerate(spec["columns"]):
        inner = "".join(_block_html(b, i, ci, last=(i == len(blocks) - 1)) for i, b in enumerate(blocks))
        cols_html.append(f'<div class="col" data-region="col">{inner}</div>')

    if spec.get("layout") == "cover":
        cv_bits = []
        if spec.get("kicker"):
            cv_bits.append(f'<div class="kicker">{_esc(spec["kicker"])}</div>')
        cv_bits.append(f"<h1>{_esc(spec['title'])}</h1>")
        if spec.get("subtitle"):
            cv_bits.append(f'<p class="subtitle">{_esc(spec["subtitle"])}</p>')
        meta = " · ".join([x for x in [
            " ".join(spec.get("authors") or []), spec.get("affiliation") or "", spec.get("venue") or "",
        ] if x])
        if meta:
            cv_bits.append(f'<div class="meta-line">{_esc(meta)}</div>')
        if spec.get("chips"):
            cv_bits.append('<div class="chips">' + "".join(f"<span>{_esc(c)}</span>" for c in spec["chips"]) + "</div>")
        hero_src = _esc((spec.get("teaser") or {}).get("src", ""))
        hero = f'<img class="hero" src="{hero_src}" alt="" />' if hero_src else ""
        return f"""<!doctype html>
<html lang="{_esc(spec.get('lang', 'zh'))}">
<head>
<meta charset="utf-8" />
<title>{_esc(spec['title'])} — cover</title>
<style>
  :root{{ --s:{scale:g}; --ink:#0b0f18; --ink2:#161d2e; --paper:#ffffff; {css_vars} }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  html,body{{background:var(--ink)}}
  body{{display:flex;justify-content:center;font-family:"Helvetica Neue",Helvetica,Arial,"PingFang SC","Microsoft YaHei",sans-serif}}
  .cover{{container-type:inline-size;width:100%;aspect-ratio:{ratio};position:relative;overflow:hidden;
          background:linear-gradient(115deg,var(--ink) 0%,var(--ink2) 62%,#22304d 100%);display:flex;align-items:center}}
  .cover::after{{content:"";position:absolute;right:-8cqw;top:-12cqw;width:52cqw;height:52cqw;border-radius:50%;
                 background:radial-gradient(circle,rgba(77,124,254,.30),transparent 68%)}}
  .text{{position:relative;z-index:2;width:57%;padding:0 0 0 5.2cqw;display:flex;flex-direction:column;
         gap:calc(var(--s)*.7cqw);color:#fff}}
  .kicker{{font-size:calc(var(--s)*1.0cqw);letter-spacing:.24em;text-transform:uppercase;color:#8fa6d8}}
  h1{{font-size:calc(var(--s)*4.25cqw);line-height:1.05;letter-spacing:-.02em;font-weight:800}}
  .subtitle{{font-size:calc(var(--s)*1.5cqw);color:#c7d3ee;line-height:1.35}}
  .meta-line{{font-size:calc(var(--s)*1.0cqw);color:#8fa6d8}}
  .chips{{display:flex;flex-wrap:wrap;gap:calc(var(--s)*.6cqw);margin-top:calc(var(--s)*.3cqw)}}
  .chips span{{font-size:calc(var(--s)*.95cqw);background:rgba(255,255,255,.10);border:.08cqw solid rgba(255,255,255,.22);
               border-radius:2cqw;padding:calc(var(--s)*.3cqw) calc(var(--s)*.95cqw);color:#e8eeff}}
  .art{{position:relative;z-index:1;flex:1;height:100%;display:flex;align-items:center;justify-content:center;padding:4.5cqw 4.5cqw 4.5cqw 2cqw}}
  .art img{{max-width:100%;max-height:100%;object-fit:contain;border-radius:1.1cqw;
            box-shadow:0 1.4cqw 3.4cqw rgba(0,0,0,.42);background:#fff}}
  .src{{position:absolute;left:5.2cqw;bottom:2.6cqw;z-index:2;font-size:calc(var(--s)*.8cqw);color:#7d8cad}}
</style>
</head>
<body>
<div class="cover">
  <div class="text" data-panel="cover-text">{''.join(cv_bits)}</div>
  <div class="art" data-panel="cover-art" data-region="art">{hero}</div>
  <div class="src">{_esc(spec.get('footer') or '')}</div>
</div>
</body>
</html>
"""

    footer = spec.get("footer") or ""
    note = spec.get("generated_note") or ""
    footer_html = (
        f'<footer data-region="footer"><span class="src">{_esc(footer)}</span><span class="gen">{_esc(note)}</span></footer>'
        if footer or note else ""
    )

    return f"""<!doctype html>
<html lang="{_esc(spec.get('lang', 'en'))}">
<head>
<meta charset="utf-8" />
<title>{_esc(spec['title'])} — poster</title>
<style>
  :root{{ --s:{scale:g}; --ink:#0e1524; --ink2:#1b2437; --line:#cfd7e8; --paper:#f5f7fc; --muted:#5b6780;
          --accent:#4d7cfe; --accent2:#ff4d6d; --accent3:#12b981; {css_vars} }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  html,body{{background:#0b0f18}}
  body{{display:flex;justify-content:center;font-family:"Helvetica Neue",Helvetica,Arial,"PingFang SC","Microsoft YaHei",sans-serif}}
  .poster{{container-type:inline-size;width:100%;aspect-ratio:{ratio};
           background:var(--paper);color:var(--ink);display:flex;flex-direction:column;overflow:hidden}}
  header{{background:linear-gradient(120deg,var(--ink),var(--ink2));color:#fff;
          padding:calc(var(--s)*1.35cqw) 2.4cqw calc(var(--s)*1.15cqw)}}
  .kicker{{font-size:calc(var(--s)*.92cqw);letter-spacing:.3em;text-transform:uppercase;color:#8fa6d8}}
  h1{{font-size:calc(var(--s)*3.0cqw);line-height:1.07;letter-spacing:-.02em;font-weight:800;margin-top:calc(var(--s)*.45cqw)}}
  .subtitle{{font-size:calc(var(--s)*1.22cqw);color:#c7d3ee;margin-top:calc(var(--s)*.6cqw);max-width:80%}}
  .meta{{display:flex;flex-wrap:wrap;gap:calc(var(--s)*.35cqw) 1.6cqw;align-items:baseline;
         margin-top:calc(var(--s)*.8cqw);font-size:calc(var(--s)*1.08cqw);color:#dbe5fb}}
  .meta .aff,.meta .venue{{color:#8fa6d8}}
  .chips{{display:flex;flex-wrap:wrap;gap:calc(var(--s)*.55cqw);margin-top:calc(var(--s)*.8cqw)}}
  .chips span{{font-size:calc(var(--s)*.86cqw);background:rgba(255,255,255,.1);border:.08cqw solid rgba(255,255,255,.22);
               border-radius:2cqw;padding:calc(var(--s)*.28cqw) calc(var(--s)*.85cqw);color:#e8eeff}}
  .teaser{{margin:calc(var(--s)*.85cqw) 2.4cqw 0;background:#fff;border:.12cqw solid var(--line);border-radius:.9cqw;
           padding:calc(var(--s)*.6cqw);display:flex;flex-direction:column;gap:calc(var(--s)*.4cqw)}}
  .teaser img{{width:100%;max-height:calc(var(--s)*11.5cqw);object-fit:contain;display:block}}
  .teaser figcaption{{font-size:calc(var(--s)*.86cqw);color:var(--muted);line-height:1.35}}
  .cols{{flex:1;min-height:0;display:grid;grid-template-columns:repeat({len(spec['columns'])},1fr);
         gap:calc(var(--s)*.92cqw);padding:calc(var(--s)*.9cqw) 2.4cqw}}
  .col{{display:flex;flex-direction:column;gap:calc(var(--s)*.92cqw);min-height:0}}
  .panel,.figure{{background:#fff;border:.12cqw solid var(--line);border-radius:.9cqw;
                  padding:calc(var(--s)*.95cqw) calc(var(--s)*1.1cqw);
                  box-shadow:0 .25cqw .8cqw rgba(16,24,40,.05);overflow:hidden}}
  .panel h2{{font-size:calc(var(--s)*1.32cqw);letter-spacing:-.01em;display:flex;align-items:center;gap:.55cqw;
             margin-bottom:calc(var(--s)*.55cqw)}}
  .panel h2::before{{content:"";width:.5cqw;height:calc(var(--s)*1.32cqw);border-radius:.3cqw;background:var(--accent)}}
  .panel .kicker{{display:block;font-size:calc(var(--s)*.74cqw);letter-spacing:.22em;color:var(--muted);text-transform:uppercase}}
  .panel p,.panel li{{font-size:calc(var(--s)*.97cqw);line-height:1.4;color:#26314a}}
  .panel ul{{padding-left:calc(var(--s)*1.3cqw);display:flex;flex-direction:column;gap:calc(var(--s)*.4cqw)}}
  .panel li::marker{{color:var(--accent)}}
  .figure{{display:flex;flex-direction:column;gap:calc(var(--s)*.45cqw);padding:calc(var(--s)*.7cqw)}}
  .figure img{{width:100%;object-fit:contain;display:block;max-height:calc(var(--s)*17cqw)}}
  .figure figcaption{{font-size:calc(var(--s)*.84cqw);color:var(--muted);line-height:1.35}}
  .figure figcaption b{{color:#324061}}
  .grow{{flex:1 1 auto;min-height:0}}
  footer{{display:flex;justify-content:space-between;gap:2cqw;background:var(--ink);color:#a9b8d8;
          padding:calc(var(--s)*.95cqw) 2.6cqw;font-size:calc(var(--s)*.9cqw)}}
</style>
</head>
<body>
<div class="poster">
  <header data-region="header">{''.join(header_bits)}</header>
  {teaser}
  <div class="cols" data-region="cols">{''.join(cols_html)}</div>
  {footer_html}
</div>
</body>
</html>
"""


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
    if body_px_target and report.get("body_px", 0) < body_px_target * LEGIBILITY_FLOOR - 0.5:
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
