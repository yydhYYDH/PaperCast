"""poster 的**视觉系统**（版式 + 配色 + 字阶），与渲染引擎解耦。

为什么单独一个文件：`poster.py` 负责「机制」——二分字号、几何闸门、渠道预设、出图；
本文件负责「长相」——把 spec 排成一份自包含 HTML。换风格只动这一个文件，
引擎的契约保持不动：`[data-panel]` 溢出检测、`[data-region]` 填充率、`.panel li/p` 的字号常量。

## 视觉系统：纸面编辑风（Paper Editorial）

面向**小红书 / 知乎信息流**，不是会议墙报。三条判据：

1. **像一篇文章，不像一块展板**：暖白纸面 + 近黑字 + 1px 发丝线分区；无深色底、无渐变、无阴影。
   层次靠字号对比与留白，不靠卡片堆叠和色块。
2. **一个强调色**：朱红只出现在栏目标题序号（01 / 02）与 kicker 短杠上，其余是近黑与三档灰。
   颜色用来指路，不用来装饰 —— 与前端 `src/style.css` 的「暖调单色，颜色只表达状态」同源。
3. **外框固定、字随内容二分**：外边距用**不乘 `--s`** 的 cqw（每条渠道都留够安全边），
   内部字号/间距统一乘 `--s`（由 `poster.py` 二分求「不溢出的最大字号」）。

`BODY_CQW` 是正文（`.panel li` / `.panel p`）的字号常量，`poster.py` 用它反推画布倍率：
**改这里必须同步改 `poster.BODY_CQW`**，否则 `body_px` 与可读性闸门会失真。

## 借鉴与边界

版式规则（安全边、封面结构「大标题 + 一个强视觉 + 底部要点」、栏目序号化）参考了
`reference/upstream/guizang-social-card-skill`（AGPL-3.0，**只读参考**）。这里**没有复制它的任何 CSS 或模板**：
样式是按上面三条判据自己写的，配色取本仓库前端自己的纸面色 —— 既避开 AGPL 传染
（本仓库 MIT 且公开发布），也让海报与产品界面是同一套语言。
"""

from __future__ import annotations

import html as html_mod
from typing import Any

# 本机可用字体只有 Microsoft YaHei（CJK）与 DejaVu（拉丁），见 docs/07 §5：
# 标题走「重字重 + 紧字距」，不用衬线 —— 落到不存在的 Songti/Noto Serif 上会造成回退跳变。
FONT_STACK = '"Microsoft YaHei","Microsoft YaHei UI","DejaVu Sans",sans-serif'

# 正文（.panel li / .panel p）字号常量，单位 cqw；poster.BODY_CQW 必须与它一致。
BODY_CQW = 0.97

TOKENS: dict[str, str] = {
    "paper": "#f7f6f3",   # 画布：与前端 style.css 的 --bg 同一个暖白
    "card": "#ffffff",
    "ink": "#1a1918",
    "ink2": "#45413c",
    "ink3": "#6f6a63",
    "line": "#e4e0d8",
    "accent": "#c8362a",  # 朱红：只给栏目序号与 kicker 短杠
}

THEME_KEYS = tuple(TOKENS)

_SHARED_CSS = """
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{background:#eceae5}
  body{display:flex;justify-content:center;font-family:__FONT__;
        -webkit-font-smoothing:antialiased;text-rendering:geometricPrecision}
  .card{background:var(--card);border:1px solid var(--line);border-radius:2px}
  .kicker{font-size:calc(var(--s)*.80cqw);letter-spacing:.3em;text-transform:uppercase;
          color:var(--ink3);display:flex;align-items:center;gap:calc(var(--s)*.85cqw)}
  .kicker::before{content:"";width:calc(var(--s)*1.7cqw);height:1px;background:var(--accent);flex:none}
  .tags{display:flex;flex-wrap:wrap;gap:calc(var(--s)*.6cqw)}
  .tags span{font-size:calc(var(--s)*.85cqw);color:var(--ink2);border:1px solid var(--line);
             background:var(--card);padding:calc(var(--s)*.32cqw) calc(var(--s)*.9cqw);letter-spacing:.02em}
  .panel h2{font-size:calc(var(--s)*1.26cqw);font-weight:700;letter-spacing:-.01em;color:var(--ink);
            display:flex;align-items:baseline;gap:calc(var(--s)*.75cqw);
            padding-bottom:calc(var(--s)*.62cqw);border-bottom:1px solid var(--line);
            margin-bottom:calc(var(--s)*.85cqw)}
  .panel h2 .num{font-size:calc(var(--s)*.86cqw);font-weight:700;color:var(--accent);
                 letter-spacing:.08em;font-variant-numeric:tabular-nums}
  .panel .blk-kicker{font-size:calc(var(--s)*.72cqw);letter-spacing:.24em;text-transform:uppercase;
                     color:var(--ink3);margin-bottom:calc(var(--s)*.45cqw)}
  .panel ul{list-style:none;display:flex;flex-direction:column;gap:calc(var(--s)*.66cqw)}
  .panel li{position:relative;padding-left:calc(var(--s)*1.55cqw);line-height:1.62;color:var(--ink2)}
  .panel li::before{content:"";position:absolute;left:0;top:calc(var(--s)*.72cqw);
                    width:calc(var(--s)*.62cqw);height:1px;background:var(--ink3)}
  .panel p{line-height:1.62;color:var(--ink2)}
  .panel li,.panel p{font-size:calc(var(--s)*__BODY__cqw)}
  .figure{display:flex;flex-direction:column;gap:calc(var(--s)*.7cqw);padding:calc(var(--s)*1.0cqw)}
  .figure img{width:100%;object-fit:contain;display:block;max-height:calc(var(--s)*15.5cqw)}
  figcaption{font-size:calc(var(--s)*.80cqw);color:var(--ink3);line-height:1.5}
  figcaption .fignum{color:var(--ink2);font-weight:700;margin-right:.35em}
  .grow{flex:1 1 auto;min-height:0}
""".replace("__FONT__", FONT_STACK).replace("__BODY__", str(BODY_CQW))

_GRID_CSS = """
  .sheet{container-type:inline-size;width:100%;aspect-ratio:__RATIO__;background:var(--paper);
         color:var(--ink);display:flex;flex-direction:column;overflow:hidden}
  header{padding:calc(var(--s)*2.2cqw*var(--rhythm)) 7.2cqw calc(var(--s)*1.35cqw*var(--rhythm));border-bottom:1px solid var(--line)}
  h1{font-size:calc(var(--s)*3.35cqw);line-height:1.08;letter-spacing:-.018em;font-weight:700;
     margin-top:calc(var(--s)*.85cqw);max-width:92%}
  .hook{font-size:calc(var(--s)*1.28cqw);line-height:1.5;color:var(--ink2);margin-top:calc(var(--s)*.9cqw);
        max-width:84%}
  .byline{font-size:calc(var(--s)*.85cqw);color:var(--ink3);margin-top:calc(var(--s)*1.0cqw);line-height:1.5}
  header .tags{margin-top:calc(var(--s)*1.05cqw)}
  /* 主图通栏卡：图在左、图注在右（杂志导语的做法）。
     竖版图放进通栏卡会左边一大片空 —— 排成一行就没有空档，图注还顺带被读到了。 */
  .teaser{margin:calc(var(--s)*1.35cqw) 7.2cqw 0;padding:calc(var(--s)*1.05cqw);
          display:flex;flex-direction:row;align-items:center;gap:calc(var(--s)*1.7cqw)}
  .teaser img{max-width:46%;object-fit:contain;display:block;max-height:calc(var(--s)*15cqw);
              border:1px solid var(--line)}
  .teaser figcaption{flex:1;min-width:0;font-size:calc(var(--s)*.95cqw);line-height:1.6;color:var(--ink2)}
  .cols{flex:1;min-height:0;display:grid;grid-template-columns:repeat(__COLS__,minmax(0,1fr));
        grid-auto-rows:minmax(0,1fr);gap:calc(var(--s)*1.5cqw*var(--rhythm));padding:calc(var(--s)*1.5cqw*var(--rhythm)) 7.2cqw}
  .col{display:flex;flex-direction:column;gap:calc(var(--s)*1.5cqw*var(--rhythm));min-height:0}
  /* 关键：栏内子项 min-height:0 —— 内容装不下时「面板被压扁并报溢出」（几何闸门抓得到），
     而不是把整栏顶出画布再被 .sheet 的 overflow:hidden 悄悄裁掉。 */
  .col > *{min-height:0}
  .panel{padding:calc(var(--s)*1.35cqw*var(--rhythm)) calc(var(--s)*1.6cqw)}
  footer{display:flex;justify-content:space-between;gap:2cqw;align-items:baseline;
         border-top:1px solid var(--line);padding:calc(var(--s)*.95cqw) 7.2cqw;margin-top:calc(var(--s)*.9cqw*var(--rhythm));
         font-size:calc(var(--s)*.78cqw);color:var(--ink3)}
  footer .gen{color:var(--ink3)}
"""

_COVER_CSS_V = """
  .cover{container-type:inline-size;width:100%;aspect-ratio:__RATIO__;background:var(--paper);color:var(--ink);
         display:flex;flex-direction:column;overflow:hidden;padding:7.4cqw 7.4cqw 6.0cqw}
  .cover h1{font-size:calc(var(--s)*8.6cqw);text-wrap:balance;line-height:1.06;letter-spacing:-.02em;font-weight:700;
            margin-top:calc(var(--s)*1.5cqw)}
  .hook{font-size:calc(var(--s)*2.30cqw);line-height:1.5;color:var(--ink2);margin-top:calc(var(--s)*1.5cqw)}
  .art{flex:1;min-height:0;margin-top:calc(var(--s)*2.4cqw);display:flex;align-items:center;justify-content:center}
  .art img{max-width:100%;max-height:100%;object-fit:contain;display:block;
           border:1px solid var(--line);background:var(--card)}
  .cover .tags{margin-top:calc(var(--s)*1.9cqw)}
  .cover .tags span{font-size:calc(var(--s)*1.05cqw);padding:calc(var(--s)*.5cqw) calc(var(--s)*1.2cqw)}
  .src{margin-top:calc(var(--s)*1.3cqw);font-size:calc(var(--s)*.92cqw);color:var(--ink3)}
"""

_COVER_CSS_H = """
  .cover{container-type:inline-size;width:100%;aspect-ratio:__RATIO__;background:var(--paper);color:var(--ink);
         display:flex;align-items:stretch;overflow:hidden;padding:6.0cqw 5.6cqw;gap:calc(var(--s)*3.2cqw)}
  .cover-text{width:56%;display:flex;flex-direction:column;justify-content:center}
  .cover h1{font-size:calc(var(--s)*5.0cqw);text-wrap:balance;line-height:1.08;letter-spacing:-.02em;font-weight:700;
            margin-top:calc(var(--s)*1.3cqw)}
  .hook{font-size:calc(var(--s)*1.9cqw);line-height:1.5;color:var(--ink2);margin-top:calc(var(--s)*1.3cqw)}
  .art{flex:1;min-width:0;display:flex;align-items:center;justify-content:center}
  .art img{max-width:100%;max-height:100%;object-fit:contain;display:block;
           border:1px solid var(--line);background:var(--card)}
  .cover .tags{margin-top:calc(var(--s)*1.7cqw)}
  .cover .tags span{font-size:calc(var(--s)*1.0cqw);padding:calc(var(--s)*.45cqw) calc(var(--s)*1.1cqw)}
  .src{margin-top:calc(var(--s)*1.2cqw);font-size:calc(var(--s)*.9cqw);color:var(--ink3)}
"""


def _esc(s: Any) -> str:
    return html_mod.escape(str(s if s is not None else ""))


def _items_html(block: dict[str, Any]) -> str:
    items = block.get("items") or []
    if items:
        return "<ul>" + "".join(f"<li>{_esc(x)}</li>" for x in items) + "</ul>"
    if block.get("text"):
        return f"<p>{_esc(block['text'])}</p>"
    return ""


def _block_html(block: dict[str, Any], idx: int, col: int, last: bool, num: int) -> str:
    """一个内容块：面板（带 01/02 序号）或图卡。最后一块撑满剩余高度，避免栏底留空门。"""
    grow = " grow" if last else ""
    name = f"c{col + 1}-{idx}"
    if block.get("kind") == "figure":
        src = _esc(block.get("src", ""))
        caption = block.get("caption") or ""
        fignum = block.get("number") or ""
        if caption and fignum:
            cap = f'<figcaption><span class="fignum">图 {_esc(fignum)}</span>{_esc(caption)}</figcaption>'
        else:
            cap = f"<figcaption>{_esc(caption)}</figcaption>" if caption else ""
        return f'<figure class="card figure{grow}" data-panel="{name}"><img src="{src}" alt="" />{cap}</figure>'
    kicker = f'<div class="blk-kicker">{_esc(block["kicker"])}</div>' if block.get("kicker") else ""
    head = f'<h2><span class="num">{num:02d}</span>{_esc(block.get("title", ""))}</h2>'
    return f'<section class="card panel{grow}" data-panel="{name}">{kicker}{head}{_items_html(block)}</section>'


# 画布密度：宽画布（≥1.2）内容多、要一屏讲完，纵向节奏收紧；竖长图（3:4）还有得滚动，保持舒展。
# 注意这是「收间距」而不是「缩字号」—— 字号的下限由 poster.LEGIBILITY_FLOOR 守着。
RHYTHM_WIDE = 0.72
RHYTHM_TALL = 1.0


def _root_style(theme: dict[str, Any] | None, scale: float, ratio: float) -> str:
    """主题变量 + 字号倍率 + 密度旋钮。spec.theme 只认白名单键，避免把任意字符串注进 CSS。"""
    merged = dict(TOKENS)
    for k, v in (theme or {}).items():
        key = str(k).lstrip("-")
        if key in THEME_KEYS and v:
            merged[key] = str(v)
    rhythm = RHYTHM_WIDE if ratio >= 1.2 else RHYTHM_TALL
    body = "".join(f"--{k}:{_esc(v)};" for k, v in merged.items())
    return f"--s:{scale:g};--rhythm:{rhythm:g};{body}"


def _cover(spec: dict[str, Any], size_in: tuple[float, float]) -> str:
    """封面版式：大标题 + 一个强视觉 + 底部要点。横画布（16:9）左右分栏，竖画布（3:4）上下堆叠。"""
    ratio = round(size_in[0] / size_in[1], 4)
    landscape = ratio >= 1.2
    css = (_COVER_CSS_H if landscape else _COVER_CSS_V).replace("__RATIO__", str(ratio))

    bits: list[str] = []
    if spec.get("kicker"):
        bits.append(f'<div class="kicker">{_esc(spec["kicker"])}</div>')
    bits.append(f"<h1>{_esc(spec['title'])}</h1>")
    if spec.get("subtitle"):
        bits.append(f'<p class="hook">{_esc(spec["subtitle"])}</p>')
    if spec.get("chips"):
        bits.append('<div class="tags">' + "".join(f"<span>{_esc(c)}</span>" for c in spec["chips"]) + "</div>")
    if spec.get("footer"):
        bits.append(f'<div class="src">{_esc(spec["footer"])}</div>')

    hero_src = _esc((spec.get("teaser") or {}).get("src", ""))
    hero = f'<img src="{hero_src}" alt="" />' if hero_src else ""
    if landscape:
        body = (
            '<div class="cover">'
            f'<div class="cover-text" data-panel="cover-text" data-region="text">{"".join(bits)}</div>'
            f'<div class="art" data-panel="cover-art" data-region="art">{hero}</div>'
            "</div>"
        )
    else:
        # 竖画布：文字在上、图在中、底部一条要点 + 来源（图撑满中间，读者一眼看到方法图）
        tags = next((b for b in bits if b.startswith('<div class="tags"')), "")
        src = next((b for b in bits if b.startswith('<div class="src"')), "")
        text = "".join(b for b in bits if b is not tags and b is not src)
        body = (
            '<div class="cover">'
            f'<div class="cover-text" data-panel="cover-text" data-region="text">{text}</div>'
            f'<div class="art" data-panel="cover-art" data-region="art">{hero}</div>'
            f'<div class="cover-foot" data-region="foot">{tags}{src}</div>'
            "</div>"
        )
    return body


def build_html(spec: dict[str, Any], *, size_in: tuple[float, float], scale: float = 1.0) -> str:
    """spec → 自包含 HTML（唯一入口）。尺寸一律 calc(var(--s) * Ncqw)：
    cqw 让版式与画布像素无关，--s 让字号可被 poster.py 二分。"""
    theme = spec.get("theme") or {}
    ratio = round(size_in[0] / size_in[1], 4)
    root = _root_style(theme, scale, ratio)
    shared = _SHARED_CSS

    if spec.get("layout") == "cover":
        ratio = round(size_in[0] / size_in[1], 4)
        css = shared + (_COVER_CSS_H if ratio >= 1.2 else _COVER_CSS_V).replace("__RATIO__", str(ratio))
        shell = _cover(spec, size_in)
    else:
        cols = max(1, len(spec.get("columns") or []))
        css = shared + _GRID_CSS.replace("__COLS__", str(cols)).replace("__RATIO__", str(round(size_in[0] / size_in[1], 4)))
        head: list[str] = []
        if spec.get("kicker"):
            head.append(f'<div class="kicker">{_esc(spec["kicker"])}</div>')
        head.append(f"<h1>{_esc(spec['title'])}</h1>")
        if spec.get("subtitle"):
            head.append(f'<p class="hook">{_esc(spec["subtitle"])}</p>')
        byline = " · ".join(x for x in [
            " · ".join(spec.get("authors") or []),
            spec.get("affiliation") or "",
            spec.get("venue") or "",
        ] if x)
        if byline:
            head.append(f'<div class="byline">{_esc(byline)}</div>')
        if spec.get("chips"):
            head.append('<div class="tags">' + "".join(f"<span>{_esc(c)}</span>" for c in spec["chips"]) + "</div>")

        ratio = round(size_in[0] / size_in[1], 4)
        landscape = ratio >= 1.2
        teaser = ""
        lead_block = ""
        if spec.get("teaser"):
            t = spec["teaser"]
            cap = f'<figcaption>{_esc(t.get("caption", ""))}</figcaption>' if t.get("caption") else ""
            if landscape:
                # 横画布：主图当「导语图」放进第一栏 —— 通栏横带在宽画布上会在图注右边留一大片空档
                lead_block = (
                    f'<figure class="card figure" data-region="teaser" data-panel="teaser">'
                    f'<img src="{_esc(t["src"])}" alt="" />{cap}</figure>'
                )
            else:
                teaser = (
                    f'<figure class="card teaser" data-region="teaser" data-panel="teaser">'
                    f'<img src="{_esc(t["src"])}" alt="" />{cap}</figure>'
                )

        col_html: list[str] = []
        num = 0
        for ci, blocks in enumerate(spec["columns"]):
            inner: list[str] = []
            if ci == 0 and lead_block:
                inner.append(lead_block)
            for i, b in enumerate(blocks):
                if b.get("kind") != "figure":
                    num += 1
                inner.append(_block_html(b, i, ci, last=(i == len(blocks) - 1), num=num))
            col_html.append(f'<div class="col" data-region="col">{"".join(inner)}</div>')

        footer = spec.get("footer") or ""
        note = spec.get("generated_note") or ""
        foot = (
            f'<footer data-region="footer"><span>{_esc(footer)}</span><span class="gen">{_esc(note)}</span></footer>'
            if footer or note else ""
        )
        shell = (
            '<div class="sheet">'
            f'<header data-region="header">{"".join(head)}</header>'
            f"{teaser}"
            f'<div class="cols" data-region="cols">{"".join(col_html)}</div>'
            f"{foot}"
            "</div>"
        )

    return f"""<!doctype html>
<html lang="{_esc(spec.get('lang', 'zh'))}">
<head>
<meta charset="utf-8" />
<title>{_esc(spec['title'])} — poster</title>
<style>
  :root{{ {root} }}
{css}
</style>
</head>
<body>
{shell}
</body>
</html>
"""
