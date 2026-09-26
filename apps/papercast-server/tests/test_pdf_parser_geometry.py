"""app/intake/pdf_parser.py 的裁剪框几何（纯几何断言，不解析真 PDF、不联网）。

这里钉的是 2026-09-26 修的那个真 bug：**图的裁剪框把英文图注一起烤进了 PNG**。
"""

from __future__ import annotations

import pymupdf
import pytest

from app.intake import pdf_parser as pp


def _cap(y0: float, y1: float, *, kind: str = "figure") -> dict:
    return {"rect": pymupdf.Rect(100, y0, 500, y0 + 10), "y0": y0, "bottom": y1,
            "kind": kind, "block": None, "number": "1", "text": "Figure 1: …", "ext": None}


def _empty_page():
    """没有可见图形也没有文字块的页面：_band 扫不到东西。"""
    return [], [], pymupdf.Rect(0, 0, 612, 792)


def test_figure_clip_stops_above_the_caption(monkeypatch):
    """图的裁剪框下边界必须是**图注顶**，不能是图注底。

    真实数据（run_e24920f4d088 的 fig-4）：图注块 y 213.4→267.3，修好的 bbox 是
    y ~78→215 —— 图注整段在框外。修之前是 y 82.3→269.0，图注被烤进图里。
    """
    # 造一个「图在 100..200，图注在 213..267」的版面
    vis = [pymupdf.Rect(100, 100, 500, 200)]
    page_rect = pymupdf.Rect(0, 0, 612, 792)
    cap = _cap(213.0, 267.0)

    monkeypatch.setattr(pp, "_band", lambda *a, **k: (100.0, 100.0))   # 扫到图形上边界
    monkeypatch.setattr(pp, "_x_extent", lambda x0, x1, *a, **k: (x0, x1))

    clip, hit = pp._figure_region(cap["rect"], cap, vis, [], page_rect, [])
    assert hit
    # 必须停在图注块**上方**：实测 fig-4 的图注首行行框是 y 213.42→223.48，
    # 切到 +2（215.4）就会切进首行 2pt，卡片上留下一条削掉上半截的字。
    assert clip.y1 < 213.42, f"裁剪框切进了图注首行：{clip}"
    assert clip.y0 < 213.0, "图注上方的图形没被框进去"


def test_table_clip_keeps_extending_below_the_caption(monkeypatch):
    """表的图注在**上**，裁剪框要往下扫过表体 —— 这一支不能被图的那次修复带歪。"""
    vis = [pymupdf.Rect(100, 100, 500, 300)]
    page_rect = pymupdf.Rect(0, 0, 612, 792)
    cap = _cap(100.0, 130.0, kind="table")

    monkeypatch.setattr(pp, "_band", lambda *a, **k: (320.0, 220.0))   # 往下扫到 320
    monkeypatch.setattr(pp, "_x_extent", lambda x0, x1, *a, **k: (x0, x1))

    clip, hit = pp._figure_region(cap["rect"], cap, vis, [], page_rect, [])
    assert hit
    assert clip.y1 >= 320.0, f"表体没被框进去：{clip}"
    assert clip.y0 < 130.0, "表图注本身应留在框内（表就是靠图注定位的）"


def test_figure_without_detected_graphic_keeps_a_usable_box(monkeypatch):
    """扫不到图形时不能给出零高/负高的框（宁可沿用旧行为）。"""
    page_rect = pymupdf.Rect(0, 0, 612, 792)
    cap = _cap(213.0, 267.0)
    monkeypatch.setattr(pp, "_band", lambda *a, **k: (213.0, 0.0))      # 什么都没找到
    monkeypatch.setattr(pp, "_x_extent", lambda x0, x1, *a, **k: (x0, x1))

    clip, hit = pp._figure_region(cap["rect"], cap, [], [], page_rect, [])
    assert clip.height > 0, f"给出了空框：{clip}"
    assert clip.y1 > clip.y0
