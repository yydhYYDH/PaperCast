"""人工闸门的缺省值必须 fail-closed：发布是不可逆动作，宁可只存草稿。

背景（2026-09-19 修）：ctx.gate() 在人工没给出选择时退到 options[0][0]，而发布闸门的
options[0] 正是「确认发布」；紧接着 publish 用黑名单 chosen not in ("draft","skip")
判定是否投递，任何意外值都算"已确认"。两处叠加 = 闸门异常时默认真投递。
"""

from __future__ import annotations

from pathlib import Path

from app.modules.publish import _is_confirmed
from app.pipeline import pick_gate_choice

PUBLISH_OPTIONS = [
    ("continue", "确认发布", None),
    ("draft", "仅存草稿", None),
    ("skip", "本轮不发布", None),
]


def test_declared_safe_default_wins():
    assert pick_gate_choice(PUBLISH_OPTIONS, "draft") == "draft"


def test_no_options_never_falls_back_to_continue():
    assert pick_gate_choice([]) == "skip"
    assert pick_gate_choice([], "draft") == "draft"


def test_is_confirmed_is_a_whitelist():
    assert _is_confirmed("continue") is True
    for weird in (None, "", "draft", "skip", "CONTINUE", "yes", "unknown-id"):
        assert _is_confirmed(weird) is False, f"{weird!r} 不该被当成确认发布"


def test_publish_gate_declares_draft_default_and_no_blacklist():
    """源码级回归：这两处写法任何一个回退，都会重新变成 fail-open。"""
    src = (Path(__file__).resolve().parents[1] / "app" / "modules" / "publish.py").read_text(encoding="utf-8")
    assert 'default="draft"' in src
    assert 'chosen not in ("draft", "skip")' not in src
    assert "_is_confirmed(chosen)" in src
