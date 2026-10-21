"""M1：论文处理 —— PDF / LaTeX / arXiv → content.md + images/ + 元数据。"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from ..intake import arxiv, latex_parser, pdf_parser
from ..pipeline import StageContext


class IntakeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _unzip(archive: Path, dest: Path) -> Optional[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                p = Path(name)
                if p.is_absolute() or ".." in p.parts:
                    continue  # 挡掉 zip slip
            zf.extractall(dest)
        return dest
    except Exception:
        return None


async def run_intake(ctx: StageContext) -> None:
    import asyncio

    src = ctx.run.source
    work = ctx.work
    ctx.log("info", f"输入类型：{src.kind} :: {src.value}")

    paper_pdf: Optional[Path] = None
    latex_root: Optional[Path] = None
    arxiv_meta: dict = {}
    preparsed: Optional[object] = None          # 知乎 / GitHub 等"非论文"源直接给解析结果
    zhihu_meta: dict = {}
    github_meta: dict = {}

    # ---------------- GitHub 仓库（REST API 抓 README / 元数据 / 图片） ----------------
    if src.kind == "github":
        from ..intake import github as _github
        preparsed, github_meta = await _github.parse_repo(src.value, work, log=ctx.log)
        ctx.log("ok", f"抓取 GitHub 仓库：{github_meta.get('fullName', '')} / "
                      f"{github_meta.get('stars', 0)}★ / {github_meta.get('textChars', 0)} 字 / "
                      f"{github_meta.get('images', 0)} 图")
        ctx.progress(0.75)

    # ---------------- 知乎文章（浏览器抓取，正文+图片已在抓取时拿到） ----------------
    elif src.kind in ("zhihu", "url"):
        preparsed, zhihu_meta = await asyncio.to_thread(_fetch_zhihu_source, src, work, ctx.log)
        ctx.log("ok", f"抓取知乎文章：{zhihu_meta.get('title', '')[:60]} / {zhihu_meta.get('textChars', 0)} 字 / {len(zhihu_meta.get('images') or [])} 图")
        ctx.progress(0.75)

    # ---------------- arXiv ----------------
    elif src.kind == "arxiv":
        try:
            arxiv_id, version = arxiv.normalize(src.value)
        except ValueError as e:
            raise IntakeError("ARXIV_BAD_ID", str(e)) from e
        ctx.log("info", f"归一化 arXiv 标识：{arxiv_id}{version}")
        ctx.progress(0.08)
        try:
            arxiv_meta = await arxiv.fetch_metadata(arxiv_id)
        except Exception as e:
            raise IntakeError("ARXIV_METADATA_FAILED", f"arXiv 元数据获取失败：{e}") from e
        ctx.log("ok", f"元数据：{arxiv_meta['title'][:70]} / {len(arxiv_meta['authors'])} 位作者 / {arxiv_meta['published'][:10]}")
        ctx.progress(0.16)
        try:
            paper_pdf = await arxiv.download_pdf(arxiv_id, work / "paper.pdf", version=version)
            ctx.log("ok", f"下载 PDF：{paper_pdf.stat().st_size // 1024} KB")
        except Exception as e:
            raise IntakeError("ARXIV_PDF_FAILED", f"arXiv PDF 下载失败：{e}") from e
        ctx.progress(0.28)

        # 源码包只是补强，失败不阻塞
        archive = await arxiv.download_source(arxiv_id, work / f"arXiv-{arxiv_id}.tar.gz")
        if archive and archive.is_file():
            ctx.log("info", f"下载 arXiv 源码包：{archive.stat().st_size // 1024} KB")
            unpacked = arxiv.unpack_source(archive, work / "latex_src")
            if unpacked:
                texes = list(unpacked.rglob("*.tex"))
                ctx.log("info", f"源码包解出 {len(texes)} 个 .tex（用于补强章节结构）")
                latex_root = unpacked if texes else None
            else:
                ctx.log("warn", "源码包解包失败，跳过（不影响 PDF 通道）")
        else:
            ctx.log("warn", "未取到源码包，跳过（不影响 PDF 通道）")

    # ---------------- 上传的 PDF / LaTeX ----------------
    else:
        upload = ctx.store.upload_path(src.value)
        if upload is None:
            # 也允许直接给本地路径（部署在同机时的快捷方式）
            p = Path(src.value).expanduser()
            upload = p if p.is_file() or p.is_dir() else None
        if upload is None:
            raise IntakeError("UPLOAD_NOT_FOUND", f"找不到上传文件：{src.value}")
        meta = ctx.store.upload_meta(src.value) if upload.is_file() else {}
        ctx.log("info", f"输入文件：{upload.name}（{upload.stat().st_size // 1024} KB）")

        if src.kind == "pdf":
            if upload.is_dir():
                raise IntakeError("INPUT_MISMATCH", "kind=pdf 但给的是目录")
            if upload.suffix.lower() != ".pdf":
                raise IntakeError("INPUT_MISMATCH", f"kind=pdf 只接受 .pdf，收到 {upload.suffix}")
            paper_pdf = work / "paper.pdf"
            shutil.copyfile(upload, paper_pdf)
            ctx.run.source.bytes = upload.stat().st_size
        else:  # latex
            if upload.is_dir():
                latex_root = upload
            elif upload.suffix.lower() == ".zip":
                unpacked = _unzip(upload, work / "latex_src")
                if unpacked is None:
                    raise IntakeError("LATEX_UNZIP_FAILED", "LaTeX zip 解包失败")
                latex_root = unpacked
            elif upload.suffix.lower() == ".tex":
                (work / "latex_src").mkdir(parents=True, exist_ok=True)
                shutil.copyfile(upload, work / "latex_src" / upload.name)
                latex_root = work / "latex_src"
            else:
                raise IntakeError("INPUT_MISMATCH", f"kind=latex 只接受 .zip/.tex/目录，收到 {upload.suffix}")
            ctx.run.source.bytes = upload.stat().st_size if upload.is_file() else None
            # 有同名 PDF 就优先走 PDF 通道（保真度更高）
            sibling = upload.with_suffix(".pdf")
            if upload.is_file() and sibling.is_file():
                paper_pdf = work / "paper.pdf"
                shutil.copyfile(sibling, paper_pdf)
                ctx.log("info", "检测到同名 PDF，改走 PDF 通道（保真度更高）")
        if meta.get("sha256"):
            ctx.log("info", f"sha256={meta['sha256'][:16]}…")

    # ---------------- 解析 ----------------
    parsed = None
    if preparsed is not None:
        if src.kind == "github":
            ctx.log("info", "解析通道：GitHub 仓库（REST API，正文与图片已就绪）")
        else:
            ctx.log("info", "解析通道：知乎文章（Playwright 抓取，正文与图片已就绪）")
        parsed = preparsed
    elif paper_pdf is not None:
        ctx.log("info", "解析通道：PDF（PyMuPDF / pymupdf4llm）")
        ctx.progress(0.35)
        import asyncio as _a

        try:
            parsed = await _a.to_thread(
                pdf_parser.parse_pdf,
                paper_pdf,
                work,
                log=ctx.log,
                engine=ctx.settings.intake_engine,
            )
        except Exception as e:
            raise IntakeError("PDF_PARSE_FAILED", f"PDF 解析失败：{e}") from e
    elif latex_root is not None:
        ctx.log("info", "解析通道：LaTeX 源码（本机无 TeX 引擎，排版信息会丢失）")
        ctx.progress(0.35)
        try:
            parsed = await asyncio.to_thread(latex_parser.parse_latex, latex_root, work, log=ctx.log)
        except Exception as e:
            raise IntakeError("LATEX_PARSE_FAILED", f"LaTeX 解析失败：{e}") from e
    else:
        raise IntakeError("NO_PARSABLE_INPUT", "没有可解析的输入（既没有 PDF 也没有 LaTeX 源码）")

    # ---------------- 补图：PDF 抽不到图时回退源码包 ----------------
    # 常见于把图做成矢量 PDF 再 \includegraphics 嵌进来的论文（如 OneStreamer 2610.01762）：
    # 正文抽得出、图注抽图 0 张，但 arXiv 源码包里图是齐的。用 latex_parser 只取图，
    # 不动 PDF 抽出来的正文。
    if paper_pdf is not None and latex_root is not None and not parsed.figures:
        ctx.log("info", "PDF 未抽到图，回退用源码包 \\includegraphics 补图…")
        try:
            n = await asyncio.to_thread(_augment_figures_from_latex, latex_root, work, parsed, ctx.log)
            if n:
                ctx.log("ok", f"源码包补图 {n} 张（PDF 通道 0 张）")
            else:
                ctx.log("warn", "源码包解析到图但文件拷贝失败，仍无图")
        except Exception as e:
            ctx.log("warn", f"源码包补图失败，继续（不影响正文）：{type(e).__name__}: {str(e)[:150]}")

    ctx.progress(0.75)

    # ---------------- 标题/作者/单位截图（给小红书首图当出处） ----------------
    # 渲染端（cards_deck.cover.titleBlock）会嵌这张图；这里确定性裁出来，不依赖 LLM。
    # arXiv 优先：模板规整，几何启发式足够；定不到就跳过（不裁、不报错）。
    title_block: dict = {}
    if paper_pdf is not None:
        try:
            from ..intake import titleblock as _titleblock

            tb_out = work / "images" / "titleblock.png"
            tb = await asyncio.to_thread(_titleblock.crop_titleblock, paper_pdf, tb_out)
            if tb:
                title_block = tb
                ctx.log("ok", f"标题/作者/单位截图：{tb['w']}×{tb['h']}（{tb['lines']} 行）")
            else:
                ctx.log("info", "未能定位标题/作者/单位区块，跳过该截图")
        except Exception as e:  # 截图失败绝不阻塞主链路
            ctx.log("warn", f"标题块截图失败，跳过：{type(e).__name__}: {str(e)[:120]}")

    # ---------------- 元数据合并 ----------------
    title = (arxiv_meta.get("title") or parsed.meta.get("pdfTitle") or "").strip()
    if not title:
        first_heading = next(
            (ln.lstrip("# ").strip() for ln in parsed.markdown.splitlines() if ln.startswith("# ")), ""
        )
        title = first_heading or ctx.run.title
    ctx.run.title = title[:160]
    ctx.run.source.title = title[:160]
    if arxiv_meta:
        ctx.run.source.authors = arxiv_meta["authors"]
        ctx.run.source.venue = arxiv_meta.get("comment") or "arXiv preprint"
    elif parsed.meta.get("pdfAuthor"):
        ctx.run.source.authors = [a.strip() for a in re_split_authors(parsed.meta["pdfAuthor"]) if a.strip()]
    if parsed.meta.get("pages"):
        ctx.run.source.pages = int(parsed.meta["pages"])

    merged_meta = {
        **parsed.meta,
        "source": {"kind": src.kind, "value": src.value},
        "arxiv": arxiv_meta or None,
        "zhihu": zhihu_meta or None,
        "github": github_meta or None,
        "title": title,
        "titleBlock": title_block or None,
    }
    (work / "meta.json").write_text(json.dumps(merged_meta, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------------- 产物与校验 ----------------
    if paper_pdf is not None:
        ctx.artifact("text", "论文 PDF", "paper.pdf", preview=True, meta={"pages": parsed.meta.get("pages", 0)})
    src_archive = next(iter(work.glob("arXiv-*.tar.gz")), None)
    if src_archive:
        ctx.artifact("text", "arXiv 源码包", src_archive.name, preview=False,
                     meta={"bytes": src_archive.stat().st_size})
    ctx.artifact("markdown", "解析正文 content.md", "content.md", preview=True)
    ctx.artifact("json", "元数据 meta.json", "meta.json", preview=True)
    ctx.artifact("json", "图表索引 figures.json", "figures.json", preview=True)

    if title_block:
        ctx.artifact("image", "标题/作者/单位截图", f"images/{title_block['file']}", preview=True,
                     meta={"w": title_block["w"], "h": title_block["h"]})

    figures = [f.as_dict() for f in parsed.figures]
    for f in figures[:8]:
        ctx.artifact("image", f"{f['id']}（p{f['page']}）", f["file"], preview=True,
                     meta={"w": f["width"], "h": f["height"]})
    if len(figures) > 8:
        ctx.log("info", f"另有 {len(figures) - 8} 张图未登记为产物（文件都在 images/ 里）")

    md = parsed.markdown
    chars = len(md)
    headings = [ln for ln in md.splitlines() if ln.startswith("#")]
    ctx.progress(0.95)

    if chars < 1500:
        hint = ""
        if paper_pdf is not None:
            hint = "；若原文件是扫描件，需要 OCR（本机未装 tesseract-ocr）"
        raise IntakeError(
            "CONTENT_TOO_SHORT",
            f"正文只抽到 {chars} 字符，低于 1500 的下限{hint}",
        )
    ctx.check("正文抽取", "pass", f"{chars // 1000}k 字符 / {len(headings)} 个标题")
    ctx.check(
        "图片抽取",
        "pass" if figures else "fail",
        f"{len(figures)} 张（fig {sum(1 for f in figures if f['kind'] == 'fig')} / "
        f"table {sum(1 for f in figures if f['kind'] == 'table')} / "
        f"未匹配 {sum(1 for f in figures if f['kind'] == 'img')}）",
    )
    ctx.check("元数据", "pass" if len(title) > 8 else "fail", title[:80] or "标题为空")
    missing = _missing_images(work, md, figures)
    ctx.check(
        "图片引用",
        "fail" if missing else "pass",
        "全部图片文件存在" if not missing else f"缺失 {len(missing)} 个：{missing[:3]}",
    )
    if parsed.warnings:
        ctx.log("warn", f"解析警告 {len(parsed.warnings)} 条，例如：{parsed.warnings[0][:100]}")

    ctx.shared["intake"] = {
        "work": str(work),
        "contentMd": str(work / "content.md"),
        "meta": merged_meta,
        "figures": figures,
        "sections": parsed.sections,
        "markdown": md,
        "titleBlock": title_block or None,
    }
    ctx.log("ok", f"M1 完成：{title[:60]}")


def re_split_authors(s: str) -> list[str]:
    import re

    return [a for a in re.split(r"\s*(?:,|;| and )\s*", s or "") if a]


def _augment_figures_from_latex(latex_root: Path, work: Path, parsed, log) -> int:
    """PDF 抽不到图时，用源码包的 \\includegraphics 补图，并把图搬进 work/images/。

    只取图，不动 parsed.markdown（PDF 抽出来的正文保真度更高）。返回补到的图数。
    """
    fb_dir = work / "latex_figs"
    lp = latex_parser.parse_latex(latex_root, fb_dir, log=log)
    merged = []
    for f in lp.figures:
        src_file = fb_dir / f.file
        if not src_file.is_file():
            continue
        dst_name = Path(f.file).name
        (work / "images").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_file, work / "images" / dst_name)
        f.file = f"images/{dst_name}"
        merged.append(f)
    if merged:
        parsed.figures = merged
        (work / "figures.json").write_text(
            json.dumps([f.as_dict() for f in merged], ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return len(merged)


def _fetch_zhihu_source(src, work: Path, log) -> tuple[object, dict]:
    """知乎文章 → 与 PDF 解析同形状的 ParseResult（content.md + images/ + figures.json）。

    抓取交给 ops/zhihu_fetch.py（它自己会用 var/toolchains/zhihu-mcp-venv 的 Playwright +
    var/secrets/zhihu/cookies.json）。这里只负责把它产出的 article.md/images 搬进 run 的
    intake 工作目录，并把远程图片引用改成本地 images/ 路径，下游无需感知来源。
    """
    import subprocess
    import sys

    url = src.value.strip()
    if src.kind == "zhihu" and not url.startswith("http"):
        url = f"https://zhuanlan.zhihu.com/p/{url}"
    if "zhihu.com" not in url:
        raise IntakeError("URL_UNSUPPORTED", f"目前 url 源只支持知乎文章，收到：{url[:80]}")

    script = Path(__file__).resolve().parents[4] / "ops" / "zhihu_fetch.py"
    if not script.is_file():
        raise IntakeError("ZHIHU_FETCH_MISSING", f"找不到抓取脚本：{script}")

    out = work / "zhihu"
    log("info", f"调用 {script.name} 抓取：{url}")
    proc = subprocess.run(
        [sys.executable, str(script), url, "-o", str(out), "--json"],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        raise IntakeError("ZHIHU_FETCH_FAILED", f"抓取失败：{(proc.stderr or proc.stdout).strip()[-300:]}")

    try:
        meta = json.loads((proc.stdout or "").strip().splitlines()[-1])
    except Exception as e:
        raise IntakeError("ZHIHU_FETCH_BAD_JSON", f"抓取脚本输出无法解析：{e}") from e

    md = (out / "article.md").read_text("utf-8") if (out / "article.md").is_file() else ""
    images = meta.get("images") or []

    (work / "images").mkdir(parents=True, exist_ok=True)
    figs = []
    for i, im in enumerate(images):
        rel = im.get("file") or ""
        if not rel:
            continue
        src_file = out / rel
        name = Path(rel).name
        if src_file.is_file():
            shutil.copyfile(src_file, work / "images" / name)
        if im.get("src"):
            md = md.replace(f"]({im['src']})", f"](images/{name})")
        figs.append(pdf_parser.Figure(
            id=f"img{i}", kind="img", number=str(i + 1), caption=im.get("alt") or "",
            file=f"images/{name}", page=0, bbox=[],
            width=int(im.get("w") or 0), height=int(im.get("h") or 0), source="raster",
        ))

    (work / "content.md").write_text(md, encoding="utf-8")
    (work / "figures.json").write_text(
        json.dumps([f.as_dict() for f in figs], ensure_ascii=False, indent=1), encoding="utf-8"
    )
    parsed = pdf_parser.ParseResult(
        meta={
            "pdfTitle": meta.get("title") or src.title or "",
            "pdfAuthor": meta.get("author") or "",
            "sourceUrl": url,
        },
        markdown=md, figures=figs, sections=[], warnings=[],
    )
    return parsed, meta


def _missing_images(work: Path, md: str, figures: list[dict]) -> list[str]:
    import re

    missing = []
    for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", md):
        rel = m.group(1).strip()
        if rel.startswith("http"):
            continue
        if not (work / rel).is_file():
            missing.append(rel)
    return sorted(set(missing))
