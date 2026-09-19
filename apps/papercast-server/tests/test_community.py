"""app/modules/community.py：人读版 markdown 拼装 + 数据复盘口径（LLM 全 AsyncMock，渠道接口全 mock）。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules import community


def _plan(**overrides):
    plan = {
        "communities": [
            {
                "name": "r/MachineLearning", "kind": "学术社区", "language": "en",
                "audience": "研究者", "angle": "方法创新", "bestTime": "周二上午",
                "rules": "禁自推、先贡献再发", "risk": "被当成广告",
                "draftTitle": "A new method", "draftBody": "body " * 20,
            },
        ],
        "interaction": {
            "replyStrategy": ["先回技术问题"],
            "watchMetrics": ["upvotes"],
            "escalation": "低于 5 分就停",
        },
    }
    plan.update(overrides)
    return plan


# --------------------------------------------------------------------------- #
# render_markdown
# --------------------------------------------------------------------------- #

def test_render_markdown_without_stats_says_it_has_no_data():
    md = community.render_markdown(_plan(), title="论文标题", stats={"available": False, "reason": "未投递"})
    assert md.startswith("# 社区投放计划 · 论文标题")
    assert "## 1. r/MachineLearning（学术社区 · en）" in md
    assert "**标题**：A new method" in md
    assert "**正文**：" in md
    assert "## 互动与复盘" in md
    assert "- 先回技术问题" in md
    assert "- upvotes" in md
    assert "**止损条件**：低于 5 分就停" in md
    assert "没有可读回的真实投递数据：未投递" in md


def test_render_markdown_with_stats_lists_real_receipts():
    stats = {"available": True, "lines": {"视频 A": "views=10，likes=2"}, "source": "ops.metrics"}
    md = community.render_markdown(_plan(), title="T", stats=stats)
    assert "- 视频 A：views=10，likes=2" in md
    assert "- 数据来源：ops.metrics" in md
    assert "没有可读回的真实投递数据" not in md


def test_render_markdown_handles_empty_plan_and_missing_fields():
    md = community.render_markdown({}, title="T", stats={"available": False, "reason": "r"})
    assert "共 0 个社区" in md
    assert "（模型未给出）" in md
    assert md.endswith("\n")            # 合法文本（不以半截行结尾）

    md2 = community.render_markdown({"communities": [{"name": "x"}]}, title="T", stats={"available": False, "reason": "r"})
    assert "## 1. x（ · ）" in md2      # 缺字段时留空位，不崩也不编


def test_render_markdown_numbers_come_from_the_plan_not_invented():
    plan = _plan()
    plan["communities"][0]["draftBody"] = "提升了 57.18%。"
    md = community.render_markdown(plan, title="T", stats={"available": False, "reason": "r"})
    assert "提升了 57.18%。" in md


# --------------------------------------------------------------------------- #
# _stats_snapshot：只读接口 + 取不到就如实说（ops.metrics 一律 mock）
# --------------------------------------------------------------------------- #

def _snapshot(monkeypatch, fake_metrics, fake_ctx):
    monkeypatch.setattr(community.ops_mod, "metrics", fake_metrics)
    return asyncio.run(community._stats_snapshot(fake_ctx()))


def test_stats_snapshot_reports_unavailable_when_channel_raises(monkeypatch, fake_ctx):
    async def boom():
        raise RuntimeError("小红书 MCP 不在线")

    stats = _snapshot(monkeypatch, boom, fake_ctx)
    assert stats["available"] is False
    assert "RuntimeError" in stats["reason"]


def test_stats_snapshot_reports_unavailable_on_empty_payload(monkeypatch, fake_ctx):
    async def empty():
        return {}

    stats = _snapshot(monkeypatch, empty, fake_ctx)
    assert stats["available"] is False
    assert "没有返回任何已投递条目" in stats["reason"]


def test_stats_snapshot_formats_items(monkeypatch, fake_ctx):
    async def data():
        return {"items": [
            {"title": "视频 A", "views": 10, "likes": 2},
            {"name": "图文 B", "views": 0},
            {"title": "没有数字 C"},
            "不是 dict 的行",
        ]}

    stats = _snapshot(monkeypatch, data, fake_ctx)
    assert stats["available"] is True
    assert stats["lines"]["视频 A"] == "views=10，likes=2"
    assert stats["lines"]["图文 B"] == "views=0"
    assert stats["lines"]["没有数字 C"] == "接口没给数字"
    assert "ops.metrics" in stats["source"]


# --------------------------------------------------------------------------- #
# run_community：整段编排（digest 只从磁盘读、LLM mock）
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def no_channel_io(monkeypatch):
    """run_community 尾部会去读渠道真实数据；单测里一律换成空实现，杜绝任何真实网络请求。"""

    async def fake_metrics():
        return {"items": []}

    monkeypatch.setattr(community.ops_mod, "metrics", fake_metrics)


def _prepare(run_tree, make_run, digest: dict, llm_plan: dict, brief: str = ""):
    llm = AsyncMock()
    llm.chat_json = AsyncMock(return_value=llm_plan)
    ctx, run_dir = run_tree(digest=digest, content="论文原文：提升 57.18%", run=make_run(brief=brief), llm=llm)
    materials = SimpleNamespace(title="论文标题", body="正文" * 50, tags=["标签"], images=["a.png", "b.png"], video=None)
    return ctx, materials, llm


DIGEST = {"title": "论文标题", "venue": "NeurIPS", "year": 2025, "abstractCn": "摘要", "contributions": ["贡献"]}


def test_run_community_writes_artifacts_and_checks(run_tree, make_run):
    plan = _plan()
    ctx, materials, llm = _prepare(run_tree, make_run, DIGEST, plan)
    out = asyncio.run(community.run_community(ctx, materials, {"xiaohongshu": {"channelName": "小红书", "status": "ready"}}, ["xiaohongshu"]))
    assert out == plan
    assert llm.chat_json.await_count == 1
    assert (ctx.work / "community.md").is_file()
    assert (ctx.work / "community.plan.json").is_file()
    assert [a["rel"] for a in ctx.artifacts] == ["community.md", "community.plan.json"]
    # 只有 1 个社区、且只覆盖 en → 社区覆盖 fail（如实报，不粉饰）
    assert ctx.state_of("社区覆盖") == "fail"
    assert ctx.state_of("草稿可用") == "pass"
    assert ctx.state_of("社区规矩") == "pass"
    assert ctx.state_of("数字可回溯") == "pass"
    # 渠道接口返回空（autouse 的 mock）→ 如实标 run，不许假装有数据
    assert ctx.state_of("投递数据复盘") == "run"
    assert "暂无可读回数据" in ctx.detail_of("投递数据复盘")


def test_run_community_flags_untraceable_numbers(run_tree, make_run):
    plan = _plan()
    plan["communities"][0]["draftBody"] = "提升了 99.9%。" + "body " * 20
    ctx, materials, _ = _prepare(run_tree, make_run, DIGEST, plan)
    asyncio.run(community.run_community(ctx, materials, {}, []))
    assert ctx.state_of("数字可回溯") == "run"
    assert "99.9" in ctx.detail_of("数字可回溯")


def test_run_community_rejects_empty_plan(run_tree, make_run):
    ctx, materials, _ = _prepare(run_tree, make_run, DIGEST, {"communities": []})
    with pytest.raises(RuntimeError):
        asyncio.run(community.run_community(ctx, materials, {}, []))


def test_run_community_requires_digest_on_disk(run_tree, make_run):
    # digest=None → 不写 understand/digest.json
    ctx, _ = run_tree(run=make_run())
    materials = SimpleNamespace(title="t", body="b", tags=[], images=[], video=None)
    with pytest.raises(RuntimeError) as e:
        asyncio.run(community.run_community(ctx, materials, {}, []))
    assert "digest.json" in str(e.value)


def test_plan_facts_collects_every_published_field():
    facts = community._plan_facts(_plan())
    for token in ["r/MachineLearning", "研究者", "方法创新", "周二上午", "禁自推", "被当成广告", "A new method", "先回技术问题", "upvotes", "低于 5 分就停"]:
        assert token in facts
