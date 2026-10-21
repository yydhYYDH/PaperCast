"""从论文 PDF 第 1 页裁出「标题 + 作者 + 单位」区块（首图里当作出处截图）。

为什么单独一步：小红书首图要放一张**论文原页头部截图**（标题/作者/单位），
让人一眼能核对出处。渲染端（cards_deck 的 cover.titleBlock）已经会嵌这张图，
这里负责**生成**它 —— 确定性裁图，不依赖 LLM。

arXiv 优先（本工作区基本只投 arXiv）：arXiv PDF 模板规整，用「字号最大的行当标题、
往下收作者/单位行、遇 摘要/图注/章节标题/链接/引用说明 或大空白为止」这套几何启发式够用。
对「摘要没有 Abstract 标题、又紧跟单位」的模板，再用「已过单位行后出现的整段正文」兜底。
定不到就返回 None（不裁、不报错），下游照旧。只读 PDF、只写一张 PNG。
"""

from __future__ import annotations

import re
import statistics
from pathlib import Path
from typing import Any, Optional

import pymupdf

#: 标题块下方遇到这些（**行内任意位置**）就停：摘要/关键词、图/表标题、引用说明、DOI。
#: 注意**不能加 `^` 锚定** —— NAVA-WAM 的「†Work done at Meta, ∗Project lead and
#: corresponding author」不以关键词开头，锚定会漏（2026-10-10 实测，摘要被整段吞进来）。
_STOP_RE = re.compile(
    r"(?i)("
    r"abstract|摘\s*要|keywords|index terms|ccs concepts|"
    r"(?:figure|fig\.?|table)\s*\.?\s*\d|"
    r"equal contribution|corresponding author|"
    r"doi\b|arxiv:"
    r")"
)
#: 行内出现链接/邮箱就停（图片里永不出现链接）。GRACE 单位行下面就是
#: 「Project page: https://cvlab-kaist.github.io/GRACE/」，开头不是 http。
_LINK_INLINE_RE = re.compile(r"(?i)https?://|www\.|\b[\w.+-]+@[\w-]+\.[\w.-]+")
#: 这一行像「单位」：命中一次后，后面再出现「整段正文」就认为是摘要，收尾。
_AFFIL_RE = re.compile(
    r"(?i)universit|institut|college|school|laborator|\blabs?\b|academy|"
    r"google|meta\b|microsoft|nvidia|openai|deepmind|bytedance|tencent|alibaba|baidu|"
    r"huawei|apple\b|amazon|samsung|\binc\b|\bcorp\b|\bltd\b|\bllc\b|gmbh|"
    r"大[学學]|学院|實驗室|实验室|研究院|研究所"
)

_TITLE_SIZE_RATIO = 0.9
_TITLE_ZONE = 0.5
_GAP_FACTOR = 2.6
_MIN_TITLE_PT = 11.0
_FULL_WIDTH_RATIO = 0.55
_PARAGRAPH_GAP = 8.0     # 整段正文前的留白（比作者行间距大）
_TIGHT_GAP = 4.0         # 正文段内行距（很小）


def _page_lines(page: "pymupdf.Page") -> list[dict[str, Any]]:
    """把页面文本摊成水平行：bbox / 最大字号 / 文本，按 (y, x) 排序。"""
    out: list[dict[str, Any]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            # 只认水平行：arXiv PDF 左侧有一条**竖排**的「arXiv:xxxx [cs.CV] 日期」stamp，
            # 字号（20pt）比标题还大，会把标题检测带偏（2026-10-10 实测）。
            d = line.get("dir") or (1.0, 0.0)
            if abs(float(d[0])) < 0.5:
                continue
            spans = line.get("spans") or []
            text = "".join(str(s.get("text") or "") for s in spans).strip()
            if not text:
                continue
            size = max((float(s.get("size") or 0.0) for s in spans), default=0.0)
            x0, y0, x1, y1 = line["bbox"]
            out.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "size": size, "text": text})
    out.sort(key=lambda l: (round(l["y0"], 1), l["x0"]))
    return out


def _rows(page: "pymupdf.Page") -> list[dict[str, Any]]:
    """把同一行的多个 span/line 合并成「行」（作者常一人一段，同一 y 上并列）。"""
    rows: list[dict[str, Any]] = []
    for l in _page_lines(page):
        if rows and abs(l["y0"] - rows[-1]["y0"]) <= 2.0:
            r = rows[-1]
            r["x0"] = min(r["x0"], l["x0"])
            r["x1"] = max(r["x1"], l["x1"])
            r["y1"] = max(r["y1"], l["y1"])
            r["size"] = max(r["size"], l["size"])
            r["text"] = (r["text"] + " " + l["text"]).strip()
        else:
            rows.append(dict(l))
    return rows


def _median_height(rows: list[dict[str, Any]]) -> float:
    hs = [max(1.0, r["y1"] - r["y0"]) for r in rows]
    return statistics.median(hs) if hs else 12.0


def find_titleblock_rows(page: "pymupdf.Page") -> tuple[list[dict[str, Any]], Optional[float]]:
    """返回 (属于「标题+作者+单位」的行, 结束边界的上沿)。

    第二个值是**触发停止的那一行的 y0**（大空白/摘要/图注/链接），裁图时用来把下边界
    卡在它上面，免得把下一行切半个字。定不到时返回 ([], None)。
    """
    rows = _rows(page)
    if not rows:
        return [], None
    h = page.rect.height
    zone = [r for r in rows if r["y0"] < _TITLE_ZONE * h] or rows
    max_size = max(r["size"] for r in zone)
    if max_size < _MIN_TITLE_PT:
        return [], None

    title_rows = [r for r in zone if r["size"] >= max_size * _TITLE_SIZE_RATIO]
    if not title_rows:
        return [], None
    title_bottom = max(r["y1"] for r in title_rows)
    med_h = _median_height(title_rows)
    x_lo = min(r["x0"] for r in rows)
    x_hi = max(r["x1"] for r in rows)
    text_w = max(1.0, x_hi - x_lo)

    # 页面上的内嵌图区域。标题块一旦压到图（图里的坐标轴/图例文字）就结束 ——
    # VGGT-Diff 的 Figure 1 就在单位行下面，图里那些小字（PSNR / 刻度）不触发任何关键词或
    # 大空白，会把半个图裁进「标题+单位」截图（2026-10-10 实测）。
    img_rects = []
    for info in page.get_image_info():
        ir = pymupdf.Rect(info["bbox"])
        if ir.get_area() > 1200:  # 忽略极小图标
            img_rects.append(ir + (-2, -2, 2, 2))

    def full(r: dict[str, Any]) -> bool:
        return (r["x1"] - r["x0"]) > _FULL_WIDTH_RATIO * text_w

    block = list(title_rows)
    prev_bottom = title_bottom
    seen_affil = any(_AFFIL_RE.search(r["text"]) for r in title_rows)
    limit_top: Optional[float] = None
    for i, r in enumerate(rows):
        if r["y0"] < title_bottom - 1.0:
            continue
        if any(r is t for t in block):
            prev_bottom = max(prev_bottom, r["y1"])
            if _AFFIL_RE.search(r["text"]):
                seen_affil = True
            continue
        gap = r["y0"] - prev_bottom
        if gap > _GAP_FACTOR * med_h:
            limit_top = r["y0"]
            break
        if _STOP_RE.search(r["text"]) or _LINK_INLINE_RE.search(r["text"]):
            limit_top = r["y0"]
            break
        lb = pymupdf.Rect(r["x0"], r["y0"], r["x1"], r["y1"])
        if any((lb & ir).get_area() > 0.4 * max(lb.get_area(), 1.0) for ir in img_rects):
            limit_top = r["y0"]
            break
        # 兜底：已经过了单位行，又来了一段「前有留白、连续整宽」的正文 → 那是摘要。
        if seen_affil and gap >= _PARAGRAPH_GAP and full(r):
            nxt = rows[i + 1] if i + 1 < len(rows) else None
            if nxt is not None and full(nxt) and (nxt["y0"] - r["y1"]) < _TIGHT_GAP:
                limit_top = r["y0"]
                break
        block.append(r)
        if _AFFIL_RE.search(r["text"]):
            seen_affil = True
        prev_bottom = max(prev_bottom, r["y1"])
        if len(block) > 16:  # 兜底：别把整页正文都吞进来
            break
    return block, limit_top


def crop_titleblock(pdf_path: Path, out_png: Path, *, dpi: int = 340,
                    pad: float = 6.0) -> Optional[dict[str, Any]]:
    """裁出第 1 页标题块并写成 PNG。返回元信息；定不到返回 None。"""
    pdf_path = Path(pdf_path)
    out_png = Path(out_png)
    with pymupdf.open(pdf_path) as doc:
        if doc.page_count < 1:
            return None
        page = doc[0]
        block, limit_top = find_titleblock_rows(page)
        if not block:
            return None
        x0 = min(r["x0"] for r in block) - pad
        x1 = max(r["x1"] for r in block) + pad
        y0 = min(r["y0"] for r in block) - pad
        y1 = max(r["y1"] for r in block) + pad
        if limit_top is not None:
            y1 = min(y1, limit_top - 1.0)  # 下边界卡在停止行上沿，别切下一行
        clip = pymupdf.Rect(x0, y0, x1, y1) & page.rect
        if clip.is_empty or clip.width < 40 or clip.height < 10:
            return None
        out_png.parent.mkdir(parents=True, exist_ok=True)
        pix = page.get_pixmap(clip=clip, dpi=dpi)
        pix.save(str(out_png))
    return {
        "file": out_png.name,
        "bbox": [round(clip.x0, 1), round(clip.y0, 1), round(clip.x1, 1), round(clip.y1, 1)],
        "lines": len(block),
        "w": int(pix.width),
        "h": int(pix.height),
        "dpi": dpi,
    }
