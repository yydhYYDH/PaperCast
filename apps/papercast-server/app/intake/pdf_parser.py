"""PDF → Markdown + 图片（PyMuPDF）。

设计要点（都是在真实论文 arXiv:2510.05096 上验证过的）：
  1. 正文用 pymupdf4llm 抽（它对双栏阅读顺序的处理比手写块排序稳）；
  2. 图片不用 pymupdf4llm 那套 —— 它只抽内嵌位图，学术论文里大量矢量图会整张丢掉；
     改成「图注驱动 + 连续内容带」找图区域：caption 往上（图）/ 往下（表）扩展，
     撞到正文段落或 >16pt 空隙就停，再渲染成 PNG。命中内嵌位图时直抽原始流（无损）。
  3. 标题净化：pymupdf4llm 会把图注、附录 prompt 标题也标成二级标题，按章节编号/白名单过滤。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pymupdf

CAP_RE = re.compile(r"^\s*(Figure|Fig\.?|TABLE|Table)\s*(\d+|[IVX]+)\s*[:.]", re.I)
# 正文里引用图的句子（"Figure 3 shows ..."）不是图注
REF_RE = re.compile(
    r"^\s*(Figure|Fig\.?|Table)\s*\d+\s+(shows|reports|presents|gives|compares|lists|depicts|summarizes)",
    re.I,
)
SECTION_WORDS = re.compile(
    r"^(abstract|introduction|related works?|background|preliminar\w*|method\w*|approach|"
    r"experiment\w*|evaluation|result\w*|discussion|conclusion\w*|limitation\w*|references?|"
    r"bibliography|appendix|acknowledge?ments?|supplement\w*)\b",
    re.I,
)
NUMBERED_SECTION = re.compile(r"^\d+(\.\d+)*\s+\S")
APPENDIX_SECTION = re.compile(r"^[A-Z](\.\d+)*\s+\S")
MARKUP_RE = re.compile(r"[*_`]")  # * _ 反引号
GAP_TOL = 16.0
PARA_LINE_CHARS = 55
CAP_MAX_CHARS = 700
SAFE = re.compile(r"[^A-Za-z0-9]+")

LogFn = Callable[[str, str], None]


def _noop(level: str, text: str) -> None:  # pragma: no cover
    pass


@dataclass
class Figure:
    id: str
    kind: str  # "fig" | "table" | "img"
    number: str
    caption: str
    file: str  # images/fig-4.png
    page: int
    bbox: list
    width: int
    height: int
    source: str  # "raster" | "render"
    area: float = 0.0

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "number": self.number,
            "caption": self.caption,
            "file": self.file,
            "page": self.page,
            "bbox": self.bbox,
            "width": self.width,
            "height": self.height,
            "source": self.source,
        }


@dataclass
class ParseResult:
    meta: dict = field(default_factory=dict)
    markdown: str = ""
    figures: list = field(default_factory=list)
    sections: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


# --------------------------------------------------------------------------- #
# 页面元素
# --------------------------------------------------------------------------- #

def _page_items(page):
    """返回 (视觉元素矩形, 文本块列表)。视觉元素 = 位图 + 有面积的矢量路径。"""
    vis = []
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"])
        if r.width > 16 and r.height > 16:
            vis.append(r)
    for d in page.get_drawings():
        r = d["rect"]
        try:
            area = r.get_area()
        except Exception:
            area = r.width * r.height
        if r.width > 12 and r.height > 4 and area > 120:
            vis.append(r)

    blocks = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        lines = []
        for ln in b.get("lines", []):
            t = "".join(s.get("text", "") for s in ln.get("spans", [])).strip()
            if t:
                lines.append({"text": t, "rect": pymupdf.Rect(ln["bbox"])})
        if lines:
            blocks.append(
                {
                    "lines": lines,
                    "rect": pymupdf.Rect(b["bbox"]),
                    "maxline": max(len(x["text"]) for x in lines),
                }
            )
    return vis, blocks


def _find_captions(blocks):
    """行级 caption 识别 —— 图注常和别的文字挤在同一个 block 里，块级匹配会漏。"""
    caps = []
    for b in blocks:
        for li, ln in enumerate(b["lines"]):
            if not CAP_RE.match(ln["text"]) or REF_RE.match(ln["text"]):
                continue
            lines, total = [], 0
            for x in b["lines"][li:]:
                if lines and total + len(x["text"]) > CAP_MAX_CHARS:
                    break
                lines.append(x)
                total += len(x["text"])
            if not lines:
                continue
            text = " ".join(x["text"] for x in lines)
            head = CAP_RE.match(ln["text"])
            caps.append(
                {
                    "rect": pymupdf.Rect(ln["rect"]),
                    "bottom": max(x["rect"].y1 for x in lines),
                    "text": text,
                    "number": (head.group(2) or "").strip() if head else "",
                    "kind": "table" if text.lower().lstrip().startswith("table") else "fig",
                    "block": b,
                }
            )
            break
    return caps


def _band(x0, x1, anchor, direction, vis, blocks, cap_block):
    """从 anchor 沿 direction 扩展「连续内容带」，返回 (边界, 是否命中内容)。"""
    cands = [("visual", r) for r in vis if min(r.x1, x1) - max(r.x0, x0) >= 12]
    cands += [
        ("para" if b["maxline"] >= PARA_LINE_CHARS else "label", b["rect"])
        for b in blocks
        if b is not cap_block and min(b["rect"].x1, x1) - max(b["rect"].x0, x0) >= 12
    ]
    if direction == "up":
        cands = [(k, r) for k, r in cands if r.y1 <= anchor + 1]
        cands.sort(key=lambda kr: -kr[1].y1)
    else:
        cands = [(k, r) for k, r in cands if r.y0 >= anchor - 1]
        cands.sort(key=lambda kr: kr[1].y0)

    cur, hit = anchor, False
    for kind, r in cands:
        d = (cur - r.y1) if direction == "up" else (r.y0 - cur)
        if d > GAP_TOL:
            break
        if kind == "para" and d >= -1:  # 撞到正文段落 → 图边界就在这里
            break
        cur = min(cur, r.y0) if direction == "up" else max(cur, r.y1)
        hit = True
    return cur, hit


def _best_raster(page, clip):
    """区域里是否有可直抽的位图（占区域 65% 以上）。返回 (xref, bbox)。"""
    best = None
    area = max(clip.get_area(), 1.0)
    for info in page.get_image_info(xrefs=True):
        xref = info.get("xref") or 0
        if not xref:
            continue
        r = pymupdf.Rect(info["bbox"])
        inter = r & clip
        if inter.is_empty:
            continue
        cover = inter.get_area() / area
        if cover > 0.65 and (best is None or cover > best[2]):
            best = (xref, r, cover)
    if best is None:
        return None
    return best[0], best[1]


# --------------------------------------------------------------------------- #
# 标题净化
# --------------------------------------------------------------------------- #

def _sanitize_headings(md: str, title: str) -> str:
    out = []
    for line in md.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if not m:
            out.append(line)
            continue
        level, text = len(m.group(1)), m.group(2).strip()
        plain = MARKUP_RE.sub("", text).strip()
        if not plain:
            continue
        keep = (
            bool(NUMBERED_SECTION.match(plain))
            or bool(SECTION_WORDS.match(plain))
            or bool(APPENDIX_SECTION.match(plain))
            or (len(plain) <= 60 and plain.isupper() and re.search(r"[A-Z]{3}", plain))
            or (title and plain.lower() == title.lower())
        )
        if keep:
            out.append(f"{'#' * min(level, 4)} {plain}")
        else:
            # 图注 / 附录 prompt 标题 / 表格标题：降级成加粗行，不占标题层级
            out.append(f"**{plain}**" if len(plain) < 200 else plain)
    return "\n".join(out)


def _collect_sections(md: str, figures) -> list:
    sections = []
    current = None
    for line in md.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*?)\s*$", line)
        if m:
            current = {
                "level": len(m.group(1)),
                "title": m.group(2).strip(),
                "anchor": SAFE.sub("-", m.group(2).strip().lower()).strip("-")[:60],
                "figureIds": [],
            }
            sections.append(current)
            continue
        if current is None:
            continue
        for f in figures:
            if f.file in line and f.id not in current["figureIds"]:
                current["figureIds"].append(f.id)
    return sections


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #

def parse_pdf(
    pdf_path: Path,
    work_dir: Path,
    *,
    log: LogFn = _noop,
    engine: str = "pymupdf",
    zoom: float = 3.0,
) -> ParseResult:
    """把 PDF 解析成 content.md + images/ + meta.json + sections.json。

    work_dir 形如 <工作区>/var/runs/<id>/intake/。
    """
    import pymupdf4llm

    pdf_path = Path(pdf_path)
    work_dir = Path(work_dir)
    images_dir = work_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()

    if engine == "mineru":
        # 同接口换实现的位置；本机无 GPU，明确回退而不是静默降级
        log("warn", "intake.engine=mineru 但本机无可用 GPU，回退 PyMuPDF（见 docs/01-module-intake.md）")
        engine = "pymupdf"
    elif engine != "pymupdf":
        engine = "pymupdf"

    doc = pymupdf.open(pdf_path)
    result = ParseResult()
    result.meta = {
        "sourceFile": pdf_path.name,
        "engine": engine,
        "pages": doc.page_count,
        "bytes": pdf_path.stat().st_size,
        "pdfTitle": (doc.metadata or {}).get("title", "") or "",
        "pdfAuthor": (doc.metadata or {}).get("author", "") or "",
    }
    log("info", f"PyMuPDF 打开 PDF：{doc.page_count} 页 / {result.meta['bytes'] // 1024} KB")

    # ---- 1. 图/表区域：图注驱动 + 连续内容带 ----
    taken_xrefs = set()
    for pno in range(doc.page_count):
        page = doc[pno]
        vis, blocks = _page_items(page)
        if not vis and not blocks:
            continue
        for cap in _find_captions(blocks):
            crect = cap["rect"]
            is_table = cap["kind"] == "table"
            x0, x1 = crect.x0 - 6, crect.x1 + 6
            if is_table:
                bottom, hit = _band(x0, x1, cap["bottom"], "down", vis, blocks, cap["block"])
                clip = pymupdf.Rect(x0, crect.y0 - 3, x1, bottom + 4)
            else:
                top, hit = _band(x0, x1, crect.y0, "up", vis, blocks, cap["block"])
                clip = pymupdf.Rect(x0, top - 4, x1, cap["bottom"] + 2)
            height = clip.height
            if not hit or height < 40 or height > page.rect.height * 0.95:
                result.warnings.append(
                    f"p{pno + 1} 图注区域未能定位（{cap['text'][:40]}），已保留图注文字"
                )
                continue
            clip = clip & page.rect
            if clip.is_empty:
                continue

            fid = f"{'table' if is_table else 'fig'}-{cap['number'] or (len(result.figures) + 1)}"
            fname = f"{fid}.png"
            target = images_dir / fname
            raster = _best_raster(page, clip)
            source = "render"
            if raster and raster[0] not in taken_xrefs:
                xref = raster[0]
                try:
                    img = doc.extract_image(xref)
                    target.write_bytes(img["image"])
                    taken_xrefs.add(xref)
                    source = "raster"
                except Exception:
                    source = "render"
            if source == "render":
                pix = page.get_pixmap(clip=clip, matrix=pymupdf.Matrix(zoom, zoom))
                pix.save(str(target))
            with pymupdf.open(target) as im:
                w, h = im[0].rect.width, im[0].rect.height
            result.figures.append(
                Figure(
                    id=fid,
                    kind="table" if is_table else "fig",
                    number=cap["number"],
                    caption=re.sub(r"\s+", " ", cap["text"]).strip(),
                    file=f"images/{fname}",
                    page=pno + 1,
                    bbox=[round(v, 1) for v in clip],
                    width=int(w),
                    height=int(h),
                    source=source,
                    area=round(clip.get_area(), 1),
                )
            )
    log("info", f"图注驱动抽图：{len(result.figures)} 张")

    # ---- 2. 兜底：没被图注覆盖的大位图也要拿出来 ----
    known_pages = {f.page for f in result.figures}
    extra = 0
    for pno in range(doc.page_count):
        page = doc[pno]
        if (pno + 1) in known_pages:
            continue
        for i, info in enumerate(page.get_image_info(xrefs=True)):
            r = pymupdf.Rect(info["bbox"])
            xref = info.get("xref") or 0
            if r.width < 120 or r.height < 120 or not xref or xref in taken_xrefs:
                continue
            try:
                img = doc.extract_image(xref)
            except Exception:
                continue
            extra += 1
            fname = f"img-p{pno + 1}-{i + 1}.png"
            (images_dir / fname).write_bytes(img["image"])
            taken_xrefs.add(xref)
            result.figures.append(
                Figure(
                    id=f"img-p{pno + 1}-{i + 1}",
                    kind="img",
                    number="",
                    caption=f"（第 {pno + 1} 页内嵌图像 {i + 1}，未匹配到图注）",
                    file=f"images/{fname}",
                    page=pno + 1,
                    bbox=[round(v, 1) for v in r],
                    width=img.get("width", 0),
                    height=img.get("height", 0),
                    source="raster",
                )
            )
    if extra:
        log("info", f"兜底补抽未匹配图注的内嵌图像：{extra} 张")

    # ---- 3. 正文（pymupdf4llm 负责双栏阅读顺序）----
    log("info", "pymupdf4llm 抽取正文（保留公式 / 表格 / 阅读顺序）…")
    try:
        chunks = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True)
    except Exception as e:
        raise RuntimeError(f"PDF 正文抽取失败：{type(e).__name__}: {e}") from e

    by_page = {}
    for f in result.figures:
        by_page.setdefault(f.page, []).append(f)

    title = result.meta.get("pdfTitle") or ""
    page_mds = []
    for idx, chunk in enumerate(chunks):
        pno = idx + 1
        text = (chunk.get("text") or "").strip()
        for f in by_page.get(pno, []):
            embed = f"![{f.caption[:160]}]({f.file})\n"
            key = re.sub(r"\s+", " ", f.caption)[:32]
            flat = MARKUP_RE.sub("", text)
            pos = flat.find(key)
            if pos >= 0:
                # 插到图注那一行之前，读起来图文相邻
                line_start = text.rfind("\n", 0, pos)
                line_start = 0 if line_start < 0 else line_start + 1
                text = text[:line_start] + "\n" + embed + "\n" + text[line_start:]
            else:
                text += f"\n\n{embed}\n"
        page_mds.append(text)

    body = _sanitize_headings("\n\n".join(page_mds), title)
    result.markdown = body
    result.sections = _collect_sections(body, result.figures)

    # ---- 4. 落盘 ----
    (work_dir / "content.md").write_text(body, encoding="utf-8")
    (work_dir / "figures.json").write_text(
        json.dumps([f.as_dict() for f in result.figures], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    (work_dir / "sections.json").write_text(
        json.dumps(result.sections, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    result.meta.update(
        {
            "chars": len(body),
            "figureCount": len(result.figures),
            "sectionCount": len(result.sections),
            "elapsedSec": round(time.time() - started, 1),
            "warnings": result.warnings[:50],
        }
    )
    (work_dir / "meta.json").write_text(
        json.dumps(result.meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    doc.close()
    log(
        "ok",
        f"解析完成：{len(body) // 1000}k 字符 / {len(result.figures)} 张图 / "
        f"{len(result.sections)} 个章节 / {result.meta['elapsedSec']}s",
    )
    return result
