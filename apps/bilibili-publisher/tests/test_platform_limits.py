"""B 站标题/简介的平台上限收口（纯函数，不联网、不投稿）。

背景（2026-09-19 真实故障）：`run_x0demo0001` 没有 B 站变体，按兜底顺序借用了知乎稿，
3624 字的文章正文被当成稿件简介直接交给 biliup，B 站回：

    ResponseData { code: 21052, message: "稿件描述长度太长，已超过限制" }

biliup 退出码 1，整次投稿白跑（视频都传完了）。超长不是「B 站帮你截」，而是整单失败，
所以要在发起上传前收口，并且**把截断这件事如实报出去**（通道会带进回执 degradations）。

跑法：cd apps/bilibili-publisher && ../papercast-server/.venv/bin/python -m pytest tests -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from main import (  # noqa: E402
    BILI_DESC_LIMIT,
    BILI_TITLE_LIMIT,
    PublishBody,
    _apply_platform_limits,
    _clamp_text,
)


def test_short_text_is_untouched() -> None:
    text, cut = _clamp_text("短简介", BILI_DESC_LIMIT)
    assert (text, cut) == ("短简介", False)


def test_exactly_at_limit_is_untouched() -> None:
    """正好到上限不算超 —— 差一个字就截断会让文案莫名其妙少一句。"""
    raw = "字" * BILI_DESC_LIMIT
    text, cut = _clamp_text(raw, BILI_DESC_LIMIT)
    assert cut is False and len(text) == BILI_DESC_LIMIT


def test_over_limit_cuts_at_sentence_end_and_marks_ellipsis() -> None:
    raw = "第一句。" * 800          # 远超上限，句号密集
    text, cut = _clamp_text(raw, BILI_DESC_LIMIT)
    assert cut is True
    assert len(text) <= BILI_DESC_LIMIT
    assert text.endswith("…")
    assert text[:-1].endswith("。")   # 尽量切在句末，不在句子中间断


def test_over_limit_without_sentence_end_still_cuts() -> None:
    text, cut = _clamp_text("字" * 5000, BILI_DESC_LIMIT)
    assert cut is True and len(text) == BILI_DESC_LIMIT and text.endswith("…")


def test_the_real_failure_case_is_now_handled() -> None:
    """复刻真实事故：3624 字的知乎正文当 B 站简介。"""
    body = PublishBody(title="DeepRare：三层多智能体系统做罕见病诊断", desc="正文。 " * 1200)
    assert len(body.desc) > BILI_DESC_LIMIT

    fixed, warnings = _apply_platform_limits(body)

    assert len(fixed.desc) <= BILI_DESC_LIMIT
    assert len(fixed.title) <= BILI_TITLE_LIMIT
    assert any(str(BILI_DESC_LIMIT) in w and "截断" in w for w in warnings)
    assert any("B 站变体" in w for w in warnings)     # 提醒根因
    assert fixed.title == body.title                  # 不超长就别动


def test_long_title_is_clamped_too() -> None:
    """标题上限同类问题，一并收口（B 站标题超过 80 字同样会打回）。"""
    body = PublishBody(title="题" * 200, desc="短简介")
    fixed, warnings = _apply_platform_limits(body)
    assert len(fixed.title) <= BILI_TITLE_LIMIT
    assert any("标题" in w for w in warnings)


def test_no_warnings_when_everything_fits() -> None:
    """没截断就不许造 warning，否则回执里每次都有噪声降级。"""
    body = PublishBody(title="正常标题", desc="正常简介")
    fixed, warnings = _apply_platform_limits(body)
    assert warnings == []
    assert fixed is body or (fixed.title, fixed.desc) == (body.title, body.desc)
