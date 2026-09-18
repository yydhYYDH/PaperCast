r"""LaTeX 源 → Markdown + 图片（刻意保持简单的转换器，不是 TeX 引擎）。

本机没有 pdflatex/xelatex/latexmk，所以 LaTeX 输入走"源码解析"通道：
结构（section/abstract）、公式（保留 $$）、图（\includegraphics → PNG）、
表（tabular → Markdown）逐项抽取。排版信息（分栏、浮动体位置）会丢失，这是已知边界。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

import pymupdf

from .pdf_parser import Figure, ParseResult, MARKUP_RE, SAFE

INPUT_RE = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
GRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\s*\{([^}]+)\}")
CAPTION_RE = re.compile(r"\\caption\s*\{((?:[^{}]|\{[^{}]*\})*)\}", re.S)
LABEL_RE = re.compile(r"\\label\s*\{([^}]+)\}")

KEEP_MACROS = ("textbf", "emph", "textit", "texttt", "underline")


def find_entry(root: Path) -> Path:
    """入口 tex：优先 main.tex，否则第一个含 \\documentclass 的文件（跳过 .bib/.sty）。"""
    root = Path(root)
    main = root / "main.tex"
    if main.is_file():
        return main
    candidates = sorted(
        p for p in root.rglob("*.tex") if not any(part.startswith(".") for part in p.parts)
    )
    for p in candidates:
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:20000]
        except OSError:
            continue
        if "\\documentclass" in head:
            return p
    if candidates:
        return candidates[0]
    raise FileNotFoundError(f"在 {root} 下找不到 .tex 文件")


def _strip_comments(tex: str) -> str:
    out = []
    for line in tex.splitlines():
        idx = None
        i = 0
        while i < len(line):
            if line[i] == "%" and (i == 0 or line[i - 1] != "\\"):
                idx = i
                break
            i += 1
        out.append(line if idx is None else line[:idx])
    return "\n".join(out)


def _inline(text: str) -> str:
    for macro in KEEP_MACROS:
        text = re.sub(rf"\\{macro}\s*\{{([^{{}}]*)\}}", r"**\1**", text)
    text = re.sub(r"\\(?:cite|citep|citet|ref|eqref|autoref)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", r"[\1]", text)
    text = text.replace("~", " ").replace("\\%", "%").replace("\\&", "&").replace("\\_", "_")
    text = re.sub(r"\\(?:noindent|centering|small|footnotesize|normalsize|large|vspace\*?\{[^}]*\}|hspace\*?\{[^}]*\})", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"[ \t]{2,}", " ", text)


def _expand(path: Path, root: Path, seen: set, depth: int = 0) -> str:
    """递归展开 \\input / \\include。"""
    if depth > 12 or path in seen:
        return ""
    seen.add(path)
    try:
        tex = _strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""
    parts = []
    pos = 0
    for m in INPUT_RE.finditer(tex):
        parts.append(tex[pos : m.start()])
        name = m.group(1).strip()
        if not name.endswith(".tex"):
            name += ".tex"
        sub = (path.parent / name).resolve()
        if sub.is_file() and str(sub).startswith(str(root.resolve())):
            parts.append(_expand(sub, root, seen, depth + 1))
        else:
            parts.append(f"\n（未找到 \\input 文件：{m.group(1)}）\n")
        pos = m.end()
    parts.append(tex[pos:])
    return "".join(parts)


def _tabular_to_md(block: str) -> Optional[str]:
    body = re.search(r"\\begin\{tabular\}(?:\{[^}]*\})?(.*?)\\end\{tabular\}", block, re.S)
    if not body:
        return None
    rows = []
    for raw in re.split(r"\\\\", body.group(1)):
        raw = raw.strip()
        if not raw:
            continue
        cells = [re.sub(r"\s+", " ", c) for c in re.split(r"(?<!\\)&", raw)]
        cells = [re.sub(r"^\s*\\hline\s*", "", c).strip() for c in cells]
        if any(cells):
            rows.append(cells)
    if len(rows) < 2:
        return None
    width = max(len(r) for r in rows)
    norm = [r + [""] * (width - len(r)) for r in rows]
    head = "| " + " | ".join(norm[0]) + " |"
    sep = "| " + " | ".join("---" for _ in range(width)) + " |"
    body_rows = ["| " + " | ".join(r) + " |" for r in norm[1:]]
    return "\n".join([head, sep, *body_rows])


def _convert_graphics(rel: str, root: Path, images_dir: Path, counter: list) -> Optional[str]:
    """\\includegraphics 指向的图 → PNG。PDF/EPS 用 PyMuPDF 渲染，位图直接复制。"""
    import shutil

    src = (root / rel).resolve()
    if not src.is_file():
        for ext in (".pdf", ".png", ".jpg", ".jpeg", ".eps"):
            cand = (root / (rel + ext)).resolve()
            if cand.is_file():
                src = cand
                break
        else:
            return None
    counter[0] += 1
    stem = SAFE.sub("-", src.stem).strip("-") or "figure"
    out = images_dir / f"fig-{counter[0]}-{stem}.png"
    try:
        if src.suffix.lower() in (".png", ".jpg", ".jpeg"):
            shutil.copyfile(src, out)
        elif src.suffix.lower() == ".pdf":
            with pymupdf.open(src) as d:
                pix = d[0].get_pixmap(matrix=pymupdf.Matrix(3, 3))
                pix.save(str(out))
        elif src.suffix.lower() == ".eps":
            # PyMuPDF 读不了 EPS，本机也没有 gs；不静默丢图，交给调用方记 warn
            return None
        else:
            return None
    except Exception:
        return None
    if not out.is_file() or out.stat().st_size < 512:
        out.unlink(missing_ok=True)
        return None
    return f"images/{out.name}"


def parse_latex(source_root: Path, work_dir: Path, *, log=lambda l, t: None) -> ParseResult:
    source_root = Path(source_root)
    work_dir = Path(work_dir)
    images_dir = work_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()

    entry = find_entry(source_root)
    log("info", f"LaTeX 入口：{entry.relative_to(source_root) if entry.is_relative_to(source_root) else entry}")
    raw = _expand(entry, source_root, set())

    title_m = re.search(r"\\title\s*\{((?:[^{}]|\{[^{}]*\})*)\}", raw, re.S)
    author_m = re.search(r"\\author\s*\{((?:[^{}]|\{[^{}]*\})*)\}", raw, re.S)
    abs_m = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", raw, re.S)

    def plain(s: str) -> str:
        s = re.sub(r"\\[a-zA-Z]+\*?\s*", " ", s or "")
        s = re.sub(r"[{}]", "", s)
        return re.sub(r"\s{2,}", " ", s).strip()

    title = plain(title_m.group(1) if title_m else "") or entry.stem
    authors = [
        plain(a)
        for a in re.split(r"\\and|,|\\\\", author_m.group(1) if author_m else "")
        if plain(a)
    ]

    body = raw
    pre = body.find("\\begin{document}")
    if pre >= 0:
        body = body[pre + len("\\begin{document}") :]
    body = body.replace("\\end{document}", "")

    result = ParseResult()
    counter = [0]
    figure_records: list[Figure] = []
    warnings: list[str] = []

    # ---- 图：整段 figure 环境优先（能拿到 caption），否则裸 includegraphics ----
    def _fig_env(m: re.Match) -> str:
        inner = m.group(1)
        cap = CAPTION_RE.search(inner)
        gfx = GRAPHICS_RE.search(inner)
        cap_text = plain(cap.group(1)) if cap else ""
        if not gfx:
            return f"\n\n**{cap_text}**\n\n" if cap_text else ""
        rel = _convert_graphics(gfx.group(1).strip(), source_root, images_dir, counter)
        label = "[(figure)]"
        if rel:
            fid = f"fig-{counter[0]}"
            figure_records.append(
                Figure(
                    id=fid, kind="fig", number=str(counter[0]), caption=cap_text or rel,
                    file=rel, page=0, bbox=[], width=0, height=0, source="latex",
                )
            )
            label = f"![{cap_text or rel}]({rel})"
        else:
            warnings.append(f"图片未能转换：{gfx.group(1).strip()}")
            label = f"（图片未能转换：{gfx.group(1).strip()}）"
        return f"\n\n{label}\n\n" + (f"**{cap_text}**\n\n" if cap_text else "")

    body = re.sub(r"\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}", _fig_env, body, flags=re.S)
    body = re.sub(r"\\begin\{table\*?\}(.*?)\\end\{table\*?\}", lambda m: "\n\n" + (_tabular_to_md(m.group(1)) or m.group(1)) + "\n\n", body, flags=re.S)

    # ---- 结构 ----
    body = re.sub(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", lambda m: "\n\n## Abstract\n\n" + _inline(plain(m.group(1))) + "\n\n", body, flags=re.S)
    for macro, hashes in (("section", "##"), ("subsection", "###"), ("subsubsection", "####")):
        body = re.sub(
            rf"\\{macro}\*?\s*\{{((?:[^{{}}]|\{{[^{{}}]*\}})*)\}}",
            lambda m, h=hashes: f"\n\n{h} {plain(m.group(1))}\n\n",
            body,
        )
    body = re.sub(r"\\paragraph\s*\{([^}]*)\}", r"\n\n**\1**\n\n", body)
    body = re.sub(r"\\begin\{(itemize|enumerate)\}", "\n", body)
    body = re.sub(r"\\end\{(itemize|enumerate)\}", "\n", body)
    body = re.sub(r"\\item\s*", "\n- ", body)
    # 公式
    body = re.sub(r"\\begin\{(equation\*?|align\*?|eqnarray\*?|gather\*?)\}(.*?)\\end\{\1\}", lambda m: f"\n\n$$ {m.group(2).strip()} $$\n\n", body, flags=re.S)
    body = re.sub(r"\\\[(.*?)\\\]", lambda m: f"\n\n$$ {m.group(1).strip()} $$\n\n", body, flags=re.S)
    # 表格（裸 tabular）
    body = re.sub(r"\\begin\{tabular\}(.*?)\\end\{tabular\}", lambda m: "\n\n" + (_tabular_to_md("\\begin{tabular}" + m.group(1) + "\\end{tabular}") or "") + "\n\n", body, flags=re.S)
    # 参考文献
    body = re.sub(r"\\begin\{thebibliography\}(.*?)\\end\{thebibliography\}", lambda m: "\n\n## References\n\n" + re.sub(r"\\bibitem(?:\[[^\]]*\])?\{[^}]*\}", "\n- ", m.group(1)) + "\n\n", body, flags=re.S)
    body = re.sub(r"\\bibliography\{[^}]*\}|\\bibliographystyle\{[^}]*\}", "", body)

    body = _inline(body)
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    md = f"# {title}\n\n" + (f"{', '.join(authors)}\n\n" if authors else "") + body + "\n"
    result.markdown = md
    result.figures = figure_records
    result.warnings = warnings
    result.meta = {
        "sourceFile": str(entry),
        "engine": "latex-source",
        "pages": 0,
        "chars": len(md),
        "figureCount": len(figure_records),
        "latexEngine": None,
        "elapsedSec": round(time.time() - started, 1),
        "warnings": warnings[:50],
    }

    sections = []
    current = None
    for line in md.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*?)\s*$", line)
        if m:
            current = {"level": len(m.group(1)), "title": m.group(2).strip(),
                       "anchor": SAFE.sub("-", m.group(2).strip().lower()).strip("-")[:60],
                       "figureIds": []}
            sections.append(current)
        elif current is not None:
            for f in figure_records:
                if f.file in line and f.id not in current["figureIds"]:
                    current["figureIds"].append(f.id)
    result.sections = sections

    (work_dir / "content.md").write_text(md, encoding="utf-8")
    (work_dir / "figures.json").write_text(json.dumps([f.as_dict() for f in figure_records], ensure_ascii=False, indent=1), encoding="utf-8")
    (work_dir / "sections.json").write_text(json.dumps(sections, ensure_ascii=False, indent=1), encoding="utf-8")
    (work_dir / "meta.json").write_text(json.dumps(result.meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log("ok", f"LaTeX 解析完成：{len(md) // 1000}k 字符 / {len(figure_records)} 张图 / {len(sections)} 个章节")
    return result
