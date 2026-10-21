"""PDF 抽不到图时，用 arXiv 源码包 \\includegraphics 补图的回退逻辑。"""

from __future__ import annotations

from app.intake import pdf_parser
from app.modules import intake as intake_mod


def _make_latex_src(root):
    (root / "figs").mkdir(parents=True, exist_ok=True)
    (root / "figs" / "a.png").write_bytes(b"\x89PNG" + b"x" * 600)  # >512B 才不会被 _convert_graphics 丢
    (root / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\begin{figure}\n"
        "\\includegraphics[width=\\textwidth]{figs/a.png}\n"
        "\\caption{系统架构图}\n"
        "\\end{figure}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )


def test_augment_figures_from_latex_copies_and_indexes(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _make_latex_src(src)
    work = tmp_path / "work"
    work.mkdir()
    parsed = pdf_parser.ParseResult(markdown="# 已有的 PDF 正文\n")

    n = intake_mod._augment_figures_from_latex(src, work, parsed, lambda *a, **k: None)

    assert n == 1
    assert len(parsed.figures) == 1
    f = parsed.figures[0]
    assert f.caption == "系统架构图"
    assert f.file.startswith("images/")
    assert (work / f.file).is_file()                     # 图搬进了 intake/images/
    assert (work / "figures.json").is_file()             # poster 读的是磁盘上的 figures.json
    # 不动 PDF 抽出来的正文
    assert parsed.markdown == "# 已有的 PDF 正文\n"


def test_parse_latex_resolves_root_relative_inputs_for_figures(tmp_path):
    """\\input{Figure/xxx} 在子文件里是相对主文件目录的，必须能展开到图（2026-10-05 的 OneStreamer bug）。"""
    from app.intake import latex_parser as lp

    root = tmp_path / "src"
    (root / "Paragraph").mkdir(parents=True)
    (root / "Figure").mkdir()
    (root / "img.png").write_bytes(b"\x89PNG" + b"x" * 600)
    (root / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\input{Paragraph/p}\n\\end{document}\n", encoding="utf-8"
    )
    (root / "Paragraph" / "p.tex").write_text("正文。\n\\input{Figure/f}\n", encoding="utf-8")
    (root / "Figure" / "f.tex").write_text(
        "\\begin{figure}\n\\includegraphics{img.png}\n\\caption{嵌套相对路径的图}\n\\end{figure}\n",
        encoding="utf-8",
    )

    res = lp.parse_latex(root, tmp_path / "work", log=lambda *a, **k: None)
    assert len(res.figures) == 1
    assert res.figures[0].caption == "嵌套相对路径的图"
    assert (tmp_path / "work" / res.figures[0].file).is_file()


def test_augment_figures_returns_zero_when_nothing_usable(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n无图。\n\\end{document}\n", encoding="utf-8"
    )
    work = tmp_path / "work"
    work.mkdir()
    parsed = pdf_parser.ParseResult(markdown="x")
    assert intake_mod._augment_figures_from_latex(src, work, parsed, lambda *a, **k: None) == 0
    assert parsed.figures == []
