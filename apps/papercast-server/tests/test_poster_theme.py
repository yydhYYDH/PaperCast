"""poster_theme：视觉系统的契约测试（离线、不渲染、秒级）。

锁的是 2026-09-19 换风格时踩到的三件事，避免以后"顺手改 CSS"把它们改回去：

1. **不许回到暗底墙报**：纸面编辑风的判据是「无渐变、无深色底」——旧版的
   `linear-gradient(115deg, #0b0f18, …)` 抬头正是"一眼论文墙报"的来源；
2. **栏内子项必须 `min-height:0`**：否则内容装不下时会把栏顶出画布、再被 `.sheet` 的
   overflow:hidden 悄悄裁掉，几何闸门（只看 `[data-panel]` 溢出）完全看不见；
3. **正文字号常量只有一个事实源**：`poster_theme.BODY_CQW` 与 `poster.BODY_CQW` 必须相等，
   否则 `body_px` 与可读性闸门会算错，窄画布的"装不下"判不出来。
"""

from __future__ import annotations

import re

import pytest

from app.modules import poster, poster_theme


@pytest.fixture()
def spec() -> dict:
    return {
        "title": "DeepRare：可追溯推理的罕见病诊断智能体系统",
        "kicker": "Nature · Vol 651 · 2026",
        "subtitle": "多智能体系统在2,919种罕见病上Recall@1达57.18%",
        "authors": ["Weike Zhao", "Chaoyi Wu"],
        "affiliation": "上海交通大学",
        "venue": "Nature",
        "chips": ["罕见病诊断", "多智能体系统"],
        "footer": "素材：Nature 651, 775–783",
        "teaser": {"src": "figures/fig-1.png", "caption": "三层智能体架构"},
        "columns": [
            [{"kind": "panel", "title": "问题", "items": ["罕见病影响超过3亿人"]}],
            [{"kind": "figure", "src": "figures/fig-2.png", "number": "2", "caption": "召回对比"}],
        ],
    }


def test_body_cqw_single_source_of_truth():
    assert poster.BODY_CQW == poster_theme.BODY_CQW
    assert poster_theme.BODY_CQW == 0.97, "改了正文常量要同步 update docs/07 与 poster.BODY_CQW 的注释"


@pytest.mark.parametrize("size_in", [(1080, 1440), (1080, 2400), (1600, 1200), (2304, 1728)])
def test_grid_html_is_paper_not_dark_wallposter(spec, size_in):
    html = poster_theme.build_html(spec, size_in=size_in, scale=1.0)
    assert "--paper:#f7f6f3" in html and "--ink:#1a1918" in html
    assert "linear-gradient" not in html, "纸面编辑风不许出现渐变（旧版暗底抬头的来源）"
    assert "--accent:#c8362a" in html
    assert html.count('data-panel="') == 3  # 主图 + 1 个面板 + 1 张图卡：几何闸门的探针还在


def test_columns_stay_shrinkable_so_overflow_is_detectable():
    css = poster_theme._SHARED_CSS + poster_theme._GRID_CSS
    assert ".col > *{min-height:0}" in css, "去掉它 → 内容溢出会被 overflow:hidden 静默裁掉，闸门看不见"
    assert "grid-auto-rows:minmax(0,1fr)" in css


def test_density_knob_is_set_by_canvas_shape(spec):
    wide = poster_theme.build_html(spec, size_in=(1600, 1200), scale=1.0)
    tall = poster_theme.build_html(spec, size_in=(1080, 2400), scale=1.0)
    assert "--rhythm:0.72" in wide and "--rhythm:1" in tall


def test_lead_figure_moves_into_first_column_on_wide_canvas(spec):
    wide = poster_theme.build_html(spec, size_in=(2304, 1728), scale=1.0)
    # 横版：主图作为第一栏的导语图（通栏横带会在图注右侧留一大片空档）
    assert 'class="card teaser"' not in wide
    first_col = wide.split('<div class="col"', 1)[1]
    assert 'data-panel="teaser"' in first_col


def test_cover_layout_is_landscape_split_and_portrait_stacked(spec):
    cover = dict(spec, layout="cover", columns=[])
    wide = poster_theme.build_html(cover, size_in=(1920, 1080), scale=1.15)
    tall = poster_theme.build_html(cover, size_in=(1080, 1440), scale=1.0)
    assert "cover-text" in wide and "cover-text" in tall
    assert "aspect-ratio:1.7778" in wide and "aspect-ratio:0.75" in tall
    assert "--s:1.15" in wide


def test_theme_override_is_whitelisted(spec):
    html = poster_theme.build_html(dict(spec, theme={"accent": "#123456", "evil": "url(x)"}), size_in=(1600, 1200))
    assert "--accent:#123456" in html
    assert "evil" not in html and "url(x)" not in html


def test_numbering_is_sequential_across_columns(spec):
    html = poster_theme.build_html(spec, size_in=(2304, 1728), scale=1.0)
    assert re.search(r'<span class="num">01</span>问题', html)
