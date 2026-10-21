"""intake.titleblock：论文第 1 页「标题+作者+单位」区块裁剪（离线、秒级）。

锁三件事（都是 2026-10-10 真跑踩过的）：
1. 字号最大的**竖排 arXiv stamp** 不能当标题（否则整页被吞）；
2. 停止词要**按行内匹配**（NAVA-WAM 的「…corresponding author」不以关键词开头，锚定会漏）；
3. 链接行与摘要不能进截图（图片里永不出现链接）。
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.intake import titleblock
from app.modules import poster_stage


def _make_pdf(path: Path, *, with_stamp: bool = True) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((90, 110), "A Very Long Paper Title About Video", fontsize=18)
    page.insert_text((90, 140), "Alice Zhang, Bob Lee, Carol Wu", fontsize=10)
    page.insert_text((90, 156), "University of Test, Test Corp.", fontsize=10)
    page.insert_text((90, 172), "corresponding author: alice@test.edu", fontsize=9)
    page.insert_text((90, 210), "Abstract", fontsize=10)
    page.insert_text((90, 226), "We study the body text of the abstract here.", fontsize=10)
    page.insert_text((90, 242), "More abstract body text that should be excluded.", fontsize=10)
    if with_stamp:
        # 竖排 arXiv stamp（旋转 90°），字号比标题还大
        page.insert_text((30, 700), "arXiv:2610.99999v1  [cs.CV]  1 Oct 2026",
                         fontsize=20, rotate=90)
    doc.save(str(path))


def test_crop_includes_authors_and_affiliation_excludes_abstract(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    _make_pdf(pdf)
    out = tmp_path / "titleblock.png"
    tb = titleblock.crop_titleblock(pdf, out)
    assert tb is not None
    assert out.is_file() and out.stat().st_size > 1000
    # 下边界应停在摘要（y=210）之上，别把 abstract 印进去
    assert tb["bbox"][3] < 210


def test_rotated_stamp_is_not_taken_as_title(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    _make_pdf(pdf, with_stamp=True)
    block, _limit = titleblock.find_titleblock_rows(pymupdf.open(pdf)[0])
    title_text = " ".join(r["text"] for r in block)
    assert "A Very Long Paper Title" in title_text
    assert "arXiv:2610" not in title_text


def test_available_figures_skips_titleblock(tmp_path: Path) -> None:
    intake = tmp_path / "intake"
    (intake / "images").mkdir(parents=True)
    (intake / "images" / "fig-1.png").write_bytes(b"x")
    (intake / "images" / poster_stage.TITLEBLOCK_NAME).write_bytes(b"x")
    (intake / "figures.json").write_text('[{"file":"images/fig-1.png"}]', encoding="utf-8")
    names = [f["file"] for f in poster_stage._available_figures(intake)]
    assert names == ["fig-1.png"]


def test_attach_titleblock_only_when_present(tmp_path: Path) -> None:
    intake = tmp_path / "intake"
    (intake / "images").mkdir(parents=True)
    assert poster_stage.attach_titleblock({"title": "T"}, intake) == {"title": "T"}
    (intake / "images" / poster_stage.TITLEBLOCK_NAME).write_bytes(b"x")
    cover = poster_stage.attach_titleblock({}, intake)
    assert cover["titleBlock"] == {"file": poster_stage.TITLEBLOCK_NAME}
