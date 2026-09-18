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

    # ---------------- arXiv ----------------
    if src.kind == "arxiv":
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
    if paper_pdf is not None:
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

    ctx.progress(0.75)

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
        "title": title,
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
    }
    ctx.log("ok", f"M1 完成：{title[:60]}")


def re_split_authors(s: str) -> list[str]:
    import re

    return [a for a in re.split(r"\s*(?:,|;| and )\s*", s or "") if a]


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
