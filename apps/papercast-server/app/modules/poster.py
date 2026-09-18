"""L2 · poster 阶段：把 digest + 论文原图排成会议海报（HTML → PNG）。

设计取舍（对齐 ADR #5「确定性排版优先于 AI 出图」）：
- 版面由 `poster.spec.json` 描述（标题/作者/栏目/图），内容来自 digest 与论文原文；
- 本模块只做两件事：把 spec 排成 HTML、调渲染底座出 PNG，并给出可机器检查的几何自检；
- 这里不调用任何文生图/视觉模型。需要 AI 出图的封面、插图走 imagegen 通路（另接）。

命令行：
  python -m app.modules.poster --spec <poster.spec.json> --out-dir <dir> [--size 48x36] [--dpi 48]
产物：<out-dir>/poster.html · poster.png · figures/ · poster.render.json
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

SIZE_IN = (48.0, 36.0)          # 会议海报默认 48x36 英寸横版
DPI = 48                        # 2304x1728 px；打印可提高到 150（7200x5400）


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
    if not cols:
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
        cap_html = f'<figcaption><b>Fig. {_esc(block.get("number", ""))}</b> {_esc(cap)}</figcaption>' if cap else ""
        return (
            f'<figure class="figure{grow}" data-panel="{name}">'
            f'<img src="{src}" alt="" />{cap_html}</figure>'
        )
    accent = f' style="--accent:{_esc(block["accent"])}"' if block.get("accent") else ""
    kicker = f'<span class="kicker">{_esc(block["kicker"])}</span>' if block.get("kicker") else ""
    return (
        f'<section class="panel{grow}" data-panel="{name}"{accent}>'
        f'{kicker}<h2>{_esc(block.get("title", ""))}</h2>{_items_html(block)}</section>'
    )


def build_html(spec: dict[str, Any], *, size_in: tuple[float, float] = SIZE_IN) -> str:
    """spec → 自包含 HTML。所有尺寸用 cqw（相对海报宽度），因此任意像素下版式一致。"""
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
        header_bits.append(
            '<div class="chips">' + "".join(f"<span>{_esc(c)}</span>" for c in spec["chips"]) + "</div>"
        )

    teaser = ""
    if spec.get("teaser"):
        t = spec["teaser"]
        cap = f'<figcaption>{_esc(t.get("caption", ""))}</figcaption>' if t.get("caption") else ""
        teaser = f'<figure class="teaser" data-panel="teaser"><img src="{_esc(t["src"])}" alt="" />{cap}</figure>'

    cols_html = []
    for ci, blocks in enumerate(spec["columns"]):
        inner = "".join(
            _block_html(b, i, ci, last=(i == len(blocks) - 1)) for i, b in enumerate(blocks)
        )
        cols_html.append(f'<div class="col">{inner}</div>')

    footer = spec.get("footer") or ""
    footer_html = f'<footer><span class="src">{_esc(footer)}</span><span class="gen">{_esc(spec.get("generated_note", ""))}</span></footer>' if footer or spec.get("generated_note") else ""

    return f"""<!doctype html>
<html lang="{_esc(spec.get('lang', 'en'))}">
<head>
<meta charset="utf-8" />
<title>{_esc(spec['title'])} — poster</title>
<style>
  :root{{ --ink:#0e1524; --ink2:#1b2437; --line:#cfd7e8; --paper:#f5f7fc; --muted:#5b6780;
          --accent:#4d7cfe; --accent2:#ff4d6d; --accent3:#12b981; {css_vars} }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  html,body{{background:#0b0f18}}
  body{{display:flex;justify-content:center;font-family:"Helvetica Neue",Helvetica,Arial,"PingFang SC","Microsoft YaHei",sans-serif}}
  .poster{{container-type:inline-size;width:100%;aspect-ratio:{ratio};
           background:var(--paper);color:var(--ink);display:flex;flex-direction:column;overflow:hidden}}
  header{{background:linear-gradient(120deg,var(--ink),var(--ink2));color:#fff;padding:2.2cqw 2.6cqw 1.9cqw}}
  .kicker{{font-size:.95cqw;letter-spacing:.3em;text-transform:uppercase;color:#8fa6d8}}
  h1{{font-size:3.15cqw;line-height:1.08;letter-spacing:-.02em;font-weight:800;margin-top:.5cqw}}
  .subtitle{{font-size:1.3cqw;color:#c7d3ee;margin-top:.7cqw;max-width:78%}}
  .meta{{display:flex;flex-wrap:wrap;gap:.4cqw 1.6cqw;align-items:baseline;margin-top:.9cqw;font-size:1.15cqw;color:#dbe5fb}}
  .meta .aff,.meta .venue{{color:#8fa6d8}}
  .chips{{display:flex;flex-wrap:wrap;gap:.6cqw;margin-top:.9cqw}}
  .chips span{{font-size:.9cqw;background:rgba(255,255,255,.1);border:.08cqw solid rgba(255,255,255,.22);
               border-radius:2cqw;padding:.32cqw .9cqw;color:#e8eeff}}
  .teaser{{margin:1.3cqw 2.6cqw 0;background:#fff;border:.12cqw solid var(--line);border-radius:.9cqw;padding:.7cqw;
           display:flex;flex-direction:column;gap:.45cqw}}
  .teaser img{{width:100%;max-height:15.5cqw;object-fit:contain;display:block}}
  .teaser figcaption{{font-size:.92cqw;color:var(--muted);line-height:1.35}}
  .cols{{flex:1;min-height:0;display:grid;grid-template-columns:repeat({len(spec['columns'])},1fr);
         gap:1.15cqw;padding:1.25cqw 2.6cqw}}
  .col{{display:flex;flex-direction:column;gap:1.15cqw;min-height:0}}
  .panel,.figure{{background:#fff;border:.12cqw solid var(--line);border-radius:.9cqw;
                  padding:1.05cqw 1.2cqw;box-shadow:0 .25cqw .8cqw rgba(16,24,40,.05);overflow:hidden}}
  .panel h2{{font-size:1.4cqw;letter-spacing:-.01em;display:flex;align-items:center;gap:.55cqw;margin-bottom:.6cqw}}
  .panel h2::before{{content:"";width:.5cqw;height:1.4cqw;border-radius:.3cqw;background:var(--accent)}}
  .panel .kicker{{display:block;font-size:.78cqw;letter-spacing:.22em;color:var(--muted);text-transform:uppercase}}
  .panel p,.panel li{{font-size:1.02cqw;line-height:1.42;color:#26314a}}
  .panel ul{{padding-left:1.35cqw;display:flex;flex-direction:column;gap:.42cqw}}
  .panel li::marker{{color:var(--accent)}}
  .figure{{display:flex;flex-direction:column;gap:.5cqw;padding:.8cqw}}
  .figure img{{width:100%;object-fit:contain;display:block;max-height:20cqw}}
  .figure figcaption{{font-size:.88cqw;color:var(--muted);line-height:1.35}}
  .figure figcaption b{{color:#324061}}
  .grow{{flex:1 1 auto;min-height:0}}
  footer{{display:flex;justify-content:space-between;gap:2cqw;background:var(--ink);color:#a9b8d8;
          padding:1.05cqw 2.6cqw;font-size:.95cqw}}
</style>
</head>
<body>
<div class="poster">
  <header>{''.join(header_bits)}</header>
  {teaser}
  <div class="cols">{''.join(cols_html)}</div>
  {footer_html}
</div>
</body>
</html>
"""


def stage_figures(spec: dict[str, Any], figures_dir: Path, out_dir: Path) -> dict[str, Any]:
    """把 spec 引用到的图拷进 <out>/figures/，并把 src 改成相对路径（HTML 自包含、可搬运）。"""
    fig_out = out_dir / "figures"
    fig_out.mkdir(parents=True, exist_ok=True)

    def stage(block: dict[str, Any]) -> None:
        if not block.get("file"):
            return
        src = Path(block["file"])
        if not src.is_absolute():
            src = Path(figures_dir) / src
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
    line = (proc.stdout or "").strip().splitlines()
    info: dict[str, Any] = {}
    for raw in reversed(line):
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


def geometry_report(info: dict[str, Any], spec: dict[str, Any], width: int, height: int) -> dict[str, Any]:
    """几何自检：溢出项 + 版面填充率（面板面积和 / 整张面积，越接近 1 越满）。"""
    panels = info.get("panels") or []
    area = sum((p.get("w", 0) * p.get("h", 0)) for p in panels)
    total = float(width * height) or 1.0
    overflow = [p for p in panels if (p.get("overflowY", 0) > 2 or p.get("overflowX", 0) > 2)]
    return {
        "width": width,
        "height": height,
        "panels": len(panels),
        "overflow": [{"panel": p.get("name"), "overflowY": p.get("overflowY")} for p in overflow],
        "broken_images": [i.get("src") for i in (info.get("brokenImages") or [])],
        "box_fill": round(area / total, 4),
        "ok": not overflow and not info.get("brokenImages"),
    }


def make_poster(
    spec_path: str | Path,
    out_dir: str | Path,
    *,
    size_in: tuple[float, float] = SIZE_IN,
    dpi: int = DPI,
    figures_dir: Optional[str | Path] = None,
    renderer: Optional[Path] = None,
) -> dict[str, Any]:
    spec_raw = load_spec(spec_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    figs = Path(figures_dir) if figures_dir else Path(spec_path).resolve().parent
    spec = stage_figures(spec_raw, figs, out)

    width = int(round(size_in[0] * dpi))
    height = int(round(size_in[1] * dpi))
    html_path = out / "poster.html"
    html_path.write_text(build_html(spec, size_in=size_in), encoding="utf-8")

    info = render_png(html_path, out / "poster.png", width=width, height=height, renderer=renderer)
    report = geometry_report(info, spec, width, height)
    report["html"] = str(html_path)
    report["png"] = str(out / "poster.png")
    (out / "poster.render.json").write_text(json.dumps({**info, "report": report}, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="digest/spec → 会议海报 PNG")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--figures-dir", default="")
    ap.add_argument("--size", default=f"{SIZE_IN[0]:g}x{SIZE_IN[1]:g}", help="英寸，如 48x36")
    ap.add_argument("--dpi", type=int, default=DPI)
    ap.add_argument("--renderer", default="")
    a = ap.parse_args(list(argv) if argv is not None else None)

    w, h = (float(x) for x in a.size.lower().split("x"))
    report = make_poster(
        a.spec, a.out_dir, size_in=(w, h), dpi=a.dpi,
        figures_dir=a.figures_dir or None,
        renderer=Path(a.renderer) if a.renderer else None,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
