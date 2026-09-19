"""app/modules/generate.py 的 brief_checks：用户指令的机检遵从度（纯函数，LLM 无关）。

判据来自 prompts.BRIEF_RULES：**平台硬约束 > 用户指令**。
所以「指令上限低于平台正文下限」时必须报 run（优先级裁决），不能报 fail（那不是执行失败）。
"""

from __future__ import annotations

import pytest

from app import styles
from app.modules import generate

XHS = styles.PLATFORMS["xhs"]        # body_min=0, body_max=1000
ZHIHU = styles.PLATFORMS["zhihu"]    # body_min=2000, body_max=4000


def limit_label(label: str, limit: int) -> str:
    return f"{label} · 指令遵从度 · 字数上限 {limit}"


# --------------------------------------------------------------------------- #
# 字数上限
# --------------------------------------------------------------------------- #

def test_no_brief_produces_no_checks(fake_ctx):
    ctx = fake_ctx()
    generate.brief_checks(ctx, "", "xhs", "随便一段正文", XHS)
    assert ctx.checks == []


def test_whitespace_only_brief_is_the_callers_responsibility(fake_ctx):
    """brief_checks 只判「空串」，不替调用方 strip —— 真实调用点（_brief_of / brief_block）都先 strip 过。"""
    ctx = fake_ctx()
    generate.brief_checks(ctx, "   ", "xhs", "随便一段正文", XHS)
    assert ctx.state_of("xhs · 指令遵从度") == "run"


def test_word_limit_within_platform_bounds_passes(fake_ctx):
    ctx = fake_ctx()
    generate.brief_checks(ctx, "控制在 600 字以内", "xhs", "字" * 500, XHS)
    assert ctx.state_of(limit_label("xhs", 600)) == "pass"


def test_word_limit_exceeded_fails_with_overflow_detail(fake_ctx):
    ctx = fake_ctx()
    generate.brief_checks(ctx, "控制在 600 字以内", "xhs", "字" * 700, XHS)
    assert ctx.state_of(limit_label("xhs", 600)) == "fail"
    assert "超出 100 字" in ctx.detail_of(limit_label("xhs", 600))


def test_limit_below_platform_body_min_is_run_not_fail(fake_ctx):
    """核心用例：brief 要 ≤500 字，但知乎正文下限 2000 字 → 按平台为准，报 run。"""
    ctx = fake_ctx()
    generate.brief_checks(ctx, "不超过 500 字", "zhihu", "字" * 3000, ZHIHU)
    state = ctx.state_of(limit_label("zhihu", 500))
    assert state == "run"
    assert state != "fail"
    detail = ctx.detail_of(limit_label("zhihu", 500))
    assert "平台硬约束 > 用户指令" in detail and "2000" in detail


def test_limit_wider_than_platform_body_max_is_run(fake_ctx):
    ctx = fake_ctx()
    generate.brief_checks(ctx, "不超过 3000 字", "xhs", "字" * 900, XHS)
    assert ctx.state_of(limit_label("xhs", 3000)) == "run"
    assert "1000" in ctx.detail_of(limit_label("xhs", 3000))


def test_platform_spec_optional(fake_ctx):
    # 不给 spec 时按纯字数判定（兼容老调用）
    ctx = fake_ctx()
    generate.brief_checks(ctx, "不超过 800 字", "xhs", "字" * 900)
    assert ctx.state_of(limit_label("xhs", 800)) == "fail"


@pytest.mark.parametrize("brief", ["正文不要超过 800 字", "字数不要超过 800 字"])
def test_negative_phrasing_of_word_limit_is_machine_checked(fake_ctx, brief):
    """已修（2026-09-19）。原缺口：

    BRIEF_WORD_LIMIT 只认「不超过 / 不多于 / 最多 / 控制在 / 上限 / 限制在 / 压缩到」这几种前缀，
    「不要超过 N 字」这种同样常见的写法匹配不上。后果有两个：
    1) 漏检：既没有「字数上限」check，正文超没超上限完全没人看；
    2) 假阳性：那条短语本身被 BRIEF_FORBID 当成「禁用表达」抓走（捕到「超过 800 字」），
       于是报一条 pass「未见 超过 800 字」——看着检查过了，其实什么也没查。

    期望：也应产生「字数上限 800」check，并按实际字数报 fail/pass。
    """
    ctx = fake_ctx()
    generate.brief_checks(ctx, brief, "xhs", "字" * 900, XHS)
    assert ctx.state_of(limit_label("xhs", 800)) == "fail"
    # 修好的另一半：上限表达不再被当成「禁用表达」抓走（旧行为会留下一条 "
    # 未见 超过 800 字" 的假阳性 pass）
    assert ctx.find("禁用表达") == []


def test_word_limit_phrasing_passes_when_within_limit(fake_ctx):
    ctx = fake_ctx()
    generate.brief_checks(ctx, "正文不要超过 800 字", "xhs", "字" * 700, XHS)
    assert ctx.state_of(limit_label("xhs", 800)) == "pass"


# --------------------------------------------------------------------------- #
# 禁用表达
# --------------------------------------------------------------------------- #

def test_forbidden_phrase_hit_fails(fake_ctx):
    ctx = fake_ctx()
    generate.brief_checks(ctx, "不要用炸裂", "xhs", "这篇文章很炸裂", XHS)
    assert ctx.state_of("xhs · 指令遵从度 · 禁用表达") == "fail"
    assert "炸裂" in ctx.detail_of("xhs · 指令遵从度 · 禁用表达")


def test_forbidden_phrase_absent_passes(fake_ctx):
    ctx = fake_ctx()
    generate.brief_checks(ctx, "不要用炸裂", "xhs", "这篇文章很稳", XHS)
    assert ctx.state_of("xhs · 指令遵从度 · 禁用表达") == "pass"


def test_single_char_forbid_word_is_ignored(fake_ctx):
    """只截到一个字时信号太弱，不假装检查过（如实标 run 需人工复核）。"""
    ctx = fake_ctx()
    generate.brief_checks(ctx, "不要用钱", "xhs", "这篇很稳", XHS)
    assert "xhs · 指令遵从度 · 禁用表达" not in ctx.labels
    assert ctx.state_of("xhs · 指令遵从度") == "run"


# --------------------------------------------------------------------------- #
# 必须体现的侧重
# --------------------------------------------------------------------------- #

def test_must_focus_missing_is_run_not_fail(fake_ctx):
    ctx = fake_ctx()
    generate.brief_checks(ctx, "重点讲实验部分", "xhs", "我们讲讲方法", XHS)
    assert ctx.state_of("xhs · 指令遵从度 · 侧重") == "run"


def test_must_focus_present_passes(fake_ctx):
    ctx = fake_ctx()
    generate.brief_checks(ctx, "重点讲实验部分", "xhs", "先说实验部分的结果", XHS)
    assert ctx.state_of("xhs · 指令遵从度 · 侧重") == "pass"


def test_unmachine_checkable_brief_is_run(fake_ctx):
    ctx = fake_ctx()
    generate.brief_checks(ctx, "写得活泼一点", "xhs", "正文", XHS)
    assert ctx.state_of("xhs · 指令遵从度") == "run"
    assert "人工复核" in ctx.detail_of("xhs · 指令遵从度")


def test_brief_checks_never_crashes_on_odd_input(fake_ctx):
    ctx = fake_ctx()
    for brief in ["不超过 字", "不要", "重点", "0 字", "不超过 9999 字", "不要用 " + "长" * 50]:
        generate.brief_checks(ctx, brief, "xhs", "", XHS)


# --------------------------------------------------------------------------- #
# 同一套去公式 / 数字抽取的纯函数（video.py 复用它们）
# --------------------------------------------------------------------------- #

def test_numbers_in_strips_spaces():
    assert generate.numbers_in("涨了 57.18 % 和 3 个百分点") == ["57.18%", "3"]


def test_strip_formulas_removes_inline_and_records_hits():
    out, hits = generate.strip_formulas("速度 $x^{2}$ 与 \\frac{1}{2}")
    assert "$" not in out and "\\frac" not in out
    assert hits


def test_truncate_body_prefers_sentence_boundary():
    body = "甲" * 600 + "。" + "乙" * 500
    out = generate._truncate_body(body, limit=700)
    assert len(out) <= 710 and out.endswith("。")


def test_drop_untraceable_removes_only_offending_sentences():
    kept, dropped = generate._drop_untraceable("稳住了。涨了 99.9%。也很稳。", "稳住了 也很稳")
    assert "99.9" not in kept
    assert dropped == ["99.9%"]        # 抽取口径与 brief/海报一致：百分比连符号一起抓
    assert "稳住了" in kept and "也很稳" in kept


def test_condense_keeps_head_and_tail_with_marker():
    md = "开头\n\n## 一节\n" + "字" * 200000 + "\n\n## 尾节\n结尾"
    out = generate._condense(md, limit=10000)
    assert len(out) < len(md)
    assert out.startswith("开头") and out.rstrip().endswith("结尾")
    assert "中间章节因原文过长已省略" in out
