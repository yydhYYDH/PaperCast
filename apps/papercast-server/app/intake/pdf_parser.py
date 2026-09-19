"""PDF → Markdown + 图片（PyMuPDF）。

设计要点（在 arXiv:2510.05096 与 Nature 排版论文上验证过）：
  1. 正文用 pymupdf4llm 抽（它对双栏阅读顺序的处理比手写块排序稳）；
  2. 图片不用 pymupdf4llm 那套 —— 它只抽内嵌位图，学术论文里大量矢量图会整张丢掉；
     改成「图注驱动 + 连续内容带」找图区域：caption 往上（图）/ 往下（表）扩展，
     撞到正文段落就停，再渲染成 PNG。命中内嵌位图时直抽原始流（无损）。
  3. 图注格式与排版差异见 docs/01-module-intake.md「Nature/Springer 排版」一节：
     * 分隔符除 `:` / `.` 外还有出版社用的 `|`（`Fig. 2 | ...`）；
     * `Extended Data Fig. 1` / `Extended Data Table 1` 是与正文图/表并行的另一套编号；
     * 跨栏整幅图（图注只占一栏、图占满两栏）需要把带内视觉元素的横向并集并入裁剪框；
     * 纯矢量图（柱状图的窄柱）要算作视觉内容，否则带扩展没有锚点。
  4. 标题净化：pymupdf4llm 会把图注、附录 prompt 标题也标成二级标题，按章节编号/白名单过滤。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pymupdf

# 图注首行：可选的出版社前缀（Nature 的 Extended Data / Supplementary）+ 关键字 + 编号 + 分隔符。
#   "Figure 1:" / "Fig. 2." / "TABLE 3:"  → 常规
#   "Fig. 2 | HPO-wise cross-dataset ..." / "Extended Data Fig. 1 | Overview ..."
#                                        → Nature/Springer 排版，分隔符是竖线且可能带前缀
CAP_RE = re.compile(
    r"^\s*(?P<ext>Extended\s+Data|Supplementary|Supplemental)?\s*"
    r"(?P<kw>Figure|Fig\.?|TABLE|Table|Tab\.?)\s*(?P<num>\d+|[IVX]+)\s*[:.|]",
    re.I,
)
# 正文里引用图的句子（"Figure 3 shows ..." / "Extended Data Fig. 1 presents ..."）不是图注
REF_RE = re.compile(
    r"^\s*(?:Extended\s+Data\s+|Supplementary\s+|Supplemental\s+)?"
    r"(Figure|Fig\.?|Table|Tab\.?)\s*\d+\s+"
    r"(shows|reports|presents|gives|compares|lists|depicts|summarizes)",
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
GAP_TOL = 16.0  # 文本块之间：图内标签与图形、图注与续行，正常就是一个行距
# 视觉内容之间：图与图注、图内多面板之间的留白常远大于一个行距（Nature 整页图实测 20~60pt），
# 这里给一个宽松但仍有的上限，避免"顺着大片空白跳到页眉装饰"这类意外
GAP_TOL_VIS = 96.0
MIN_VIS_W = 3.0
MIN_VIS_H = 3.0
MIN_VIS_AREA = 60.0
MIN_X_OVERLAP = 12.0  # 文本块与图注列要有实质交叠才算"同栏"
MIN_X_OVERLAP_VIS = 1.0  # 视觉元素只要求碰到图注列：柱状图窄柱只有 ~10pt 宽，按 12pt 判会整类漏掉
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
        # 只看"有实体面积的图形"。原先还要求宽 >12pt，会把柱状图的窄柱（实测 10.7pt 宽）
        # 整类滤掉 —— 那类图 vis 为空，图注带扩展就失去锚点，只剩一条图注细条。
        if r.width > MIN_VIS_W and r.height > MIN_VIS_H and area > MIN_VIS_AREA:
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
            head = CAP_RE.match(ln["text"])
            if not head or REF_RE.match(ln["text"]):
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
            # kind 取自匹配到的关键字，而不是整行开头：Nature 的
            # "Extended Data Table 1 | ..." 行首是 "Extended"，按开头判会误判成 fig。
            kw = (head.group("kw") or "").lower()
            caps.append(
                {
                    "rect": pymupdf.Rect(ln["rect"]),
                    "bottom": max(x["rect"].y1 for x in lines),
                    "text": text,
                    "number": (head.group("num") or "").strip(),
                    "kind": "table" if kw.startswith("tab") else "fig",
                    "ext": bool(head.group("ext")),
                    "block": b,
                }
            )
            break
    return caps


def _band(x0, x1, anchor, direction, vis, blocks, cap_block, cap_rects=()):
    """从 anchor 沿 direction 扩展「连续内容带」，返回 (边界, 是否命中内容)。

    候选分三类，边界规则不同（都是实测出来的）：
      * visual（位图 / 矢量图形）：图与图注之间、图内多面板之间的留白可以很大
        （Nature 整页图实测相邻面板间 20~60pt，远超一个行距），所以视觉内容之间
        不设固定间距上限 —— 边界交给下面两类硬边界去定；
      * para（正文段落，行长 >= PARA_LINE_CHARS）：图与外界的硬边界，撞上就停。
        正文段落之外不可能再是同一张图的内容，这条保证了"放宽视觉间距"不会吃进正文；
      * cap（另一条图注）：同页叠放多张图时的硬边界；
      * label（图内标签，短文本）：只在 GAP_TOL（行距量级）内吸收；够不着就跳过而不是
        中断 —— 否则一个离得稍远的刻度标签就会把带切在图中间。
    """
    others = [r for r in cap_rects if not r.intersects(pymupdf.Rect(x0, anchor - 2, x1, anchor + 2))]
    cands = [
        ("visual", r) for r in vis if min(r.x1, x1) - max(r.x0, x0) >= MIN_X_OVERLAP_VIS
    ]
    cands += [
        ("para" if b["maxline"] >= PARA_LINE_CHARS else "label", b["rect"])
        for b in blocks
        if b is not cap_block and min(b["rect"].x1, x1) - max(b["rect"].x0, x0) >= MIN_X_OVERLAP
    ]
    # 别的图注按"它自己那一行"当障碍，而不是整个文本块 ——
    # 图注常常和表格行挤在同一个 block 里，按块判会在图注前方 1pt 就误停
    cands += [
        ("cap", r) for r in others if min(r.x1, x1) - max(r.x0, x0) >= MIN_X_OVERLAP_VIS
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
        if kind in ("para", "cap") and d >= -1:  # 正文段落 / 另一条图注 → 图边界就在这里
            break
        if kind == "visual" and d > GAP_TOL_VIS:
            break
        if kind == "label" and d > GAP_TOL:
            continue
        cur = min(cur, r.y0) if direction == "up" else max(cur, r.y1)
        hit = True
    return cur, hit


def _x_extent(x0, x1, top, bottom, vis, page_rect):
    """裁剪框的水平范围 = 图注所在栏 ∪ 纵向落在带内的视觉元素的横向并集。

    跨栏整幅图（图注只写在一栏、图占满两栏，Nature 的 Extended Data 大图就是这样）
    用图注自身的宽度去裁只会得到左半张图；而纯文本块不参与并集，
    免得把邻栏正文的宽度也并进来。判定用「元素纵向中心落在带内」而不是「有交集」，
    避免把只擦到带边缘的邻图元也并进来。
    """
    lo, hi = (top, bottom) if top <= bottom else (bottom, top)
    for r in vis:
        cy = (r.y0 + r.y1) / 2
        if not (lo - 1 <= cy <= hi + 1):
            continue
        x0 = min(x0, r.x0)
        x1 = max(x1, r.x1)
    return max(x0, page_rect.x0), min(x1, page_rect.x1)


def _figure_region(crect, cap, vis, blocks, page_rect, cap_rects=(), *, max_rounds: int = 3):
    """图注 + 邻接内容 → (裁剪框, 是否命中内容)。

    纵向带按图注自身宽度扫；扫出的带再决定横向范围（_x_extent），横向变宽后重扫，
    这样"另一栏的图更高/更宽"也能并进来。每轮只做并集（不会把上一轮的带缩回去），
    最多迭代 max_rounds 轮后收敛。
    """
    is_table = cap["kind"] == "table"
    x0, x1 = crect.x0 - 6, crect.x1 + 6
    top, bottom, hit = crect.y0, cap["bottom"], False
    for _ in range(max_rounds):
        if is_table:
            edge, h = _band(x0, x1, cap["bottom"], "down", vis, blocks, cap["block"], cap_rects)
            bottom = max(bottom, edge)
        else:
            edge, h = _band(x0, x1, crect.y0, "up", vis, blocks, cap["block"], cap_rects)
            top = min(top, edge)
        hit = hit or h
        nx0, nx1 = _x_extent(x0, x1, top, bottom, vis, page_rect)
        if abs(nx0 - x0) < 0.5 and abs(nx1 - x1) < 0.5:
            break
        x0, x1 = nx0, nx1
    # 留白保持原样（图：上边 -4 / 图注底 +2；表：图注顶 -3 / 下边 +4），
    # 免得"修一类排版"顺手改掉所有已能用的样本的裁剪框
    if is_table:
        clip = pymupdf.Rect(x0, crect.y0 - 3, x1, max(cap["bottom"], bottom) + 4)
    else:
        clip = pymupdf.Rect(x0, min(crect.y0, top) - 4, x1, max(cap["bottom"], bottom) + 2)
    return clip, hit


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
        caps = _find_captions(blocks)
        cap_rects = [c["rect"] for c in caps]
        for cap in caps:
            crect = cap["rect"]
            is_table = cap["kind"] == "table"
            clip, hit = _figure_region(crect, cap, vis, blocks, page.rect, cap_rects)
            height = clip.height
            if not hit or height < 40 or height > page.rect.height * 0.95:
                result.warnings.append(
                    f"p{pno + 1} 图注区域未能定位（{cap['text'][:40]}），已保留图注文字"
                )
                continue
            clip = clip & page.rect
            if clip.is_empty:
                continue

            number = cap["number"]
            if cap.get("ext"):
                # "Extended Data Fig. 1" 与正文 "Fig. 1" 是两套编号，不能共用 fig-1 这个 id
                number = f"ed{number}" if number else ""
            fid = f"{'table' if is_table else 'fig'}-{number or (len(result.figures) + 1)}"
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
                    caption=f"（第 {pno + 1} 页内嵌图像 {i + 1}：无文字图注，按位置归类）",
                    file=f"images/{fname}",
                    page=pno + 1,
                    bbox=[round(v, 1) for v in r],
                    width=img.get("width", 0),
                    height=img.get("height", 0),
                    source="raster",
                )
            )
    if extra:
        log(
            "warn",
            f"兜底按位置补抽 {extra} 张内嵌图像：这些页没有可识别的文字图注"
            f"（图注本身是图片、或整页是扫描图），kind=img、无 caption，仅按页面位置归类",
        )

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
