"""app/modules/poster_stage.py：spec 收敛（_sanitize）、减块（_trim_spec）、写 spec 的编排。

LLM 一律 AsyncMock —— 这里不产生任何真实网络调用。
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app.modules import poster_stage as ps

FIGURES = [
    {"file": "fig-1.png", "caption": "总览", "kind": "figure"},
    {"file": "fig-2.png", "caption": "主结果", "kind": "table"},
]
HAYSTACK = "论文报告在 3 个数据集上提升 57.18%，主干 12 层，参数量 3 亿。"


def _spec(**overrides):
    spec = {
        "title": "论文海报",
        "teaser": {"file": "fig-1.png", "caption": "总体框架"},
        "columns": [
            [
                {"kind": "text", "title": "方法", "items": ["在 3 个数据集上提升 57.18%"]},
                {"kind": "figure", "file": "fig-2.png", "number": "图 2", "caption": "主结果"},
            ],
            [
                {"kind": "text", "title": "局限", "items": ["主干 12 层"]},
            ],
        ],
    }
    spec.update(overrides)
    return spec


# --------------------------------------------------------------------------- #
# _sanitize
# --------------------------------------------------------------------------- #

def test_sanitize_keeps_traceable_spec_intact():
    spec, stats = ps._sanitize(_spec(), FIGURES, HAYSTACK)
    assert stats["dropped"] == []
    assert stats["bad_numbers"] == []
    assert spec["title"] == "论文海报"
    assert len(spec["columns"]) == 2
    assert spec["teaser"]["caption"] == "总体框架"


def test_sanitize_drops_teaser_referencing_missing_figure():
    data = _spec(teaser={"file": "fig-9.png", "caption": "不存在的图"})
    spec, stats = ps._sanitize(data, FIGURES, HAYSTACK)
    assert "teaser" not in spec
    assert any("不存在的图" in d for d in stats["dropped"])


def test_sanitize_drops_figure_block_with_missing_figure():
    data = _spec(columns=[[
        {"kind": "figure", "file": "fig-404.png", "caption": "主结果"},
        {"kind": "text", "title": "方法", "items": ["主干 12 层"]},
    ]])
    spec, stats = ps._sanitize(data, FIGURES, HAYSTACK)
    assert [b["kind"] for b in spec["columns"][0]] == ["text"]
    assert any("不存在的图" in d for d in stats["dropped"])


def test_sanitize_keeps_figure_but_strips_untraceable_caption():
    data = _spec(columns=[[
        {"kind": "figure", "file": "fig-2.png", "caption": "提升了 88.8%"},
        {"kind": "text", "title": "方法", "items": ["主干 12 层"]},
    ]])
    spec, stats = ps._sanitize(data, FIGURES, HAYSTACK)
    block = spec["columns"][0][0]
    assert block["kind"] == "figure" and block["file"] == "fig-2.png"
    assert "caption" not in block
    assert "88.8" in stats["bad_numbers"]


def test_sanitize_drops_only_untraceable_items():
    data = _spec(columns=[[{
        "kind": "text", "title": "数据",
        "items": ["在 3 个数据集上有效", "提升了 91.7%", "主干 12 层"],
    }]])
    spec, stats = ps._sanitize(data, FIGURES, HAYSTACK)
    assert spec["columns"][0][0]["items"] == ["在 3 个数据集上有效", "主干 12 层"]
    assert "91.7" in stats["bad_numbers"]


def test_sanitize_removes_block_emptied_by_dropping_items():
    data = _spec(columns=[[
        {"kind": "text", "title": "只有假数字", "items": ["提升了 91.7%"]},
        {"kind": "text", "title": "真数字", "items": ["参数量 3 亿"]},
    ]])
    spec, stats = ps._sanitize(data, FIGURES, HAYSTACK)
    assert [b["title"] for b in spec["columns"][0]] == ["真数字"]
    assert any("被清空" in d and "只有假数字" in d for d in stats["dropped"])


def test_sanitize_drops_paragraph_with_untraceable_number():
    data = _spec(columns=[[
        {"kind": "text", "title": "段落", "text": "提升了 91.7%", "items": ["主干 12 层"]},
    ]])
    spec, stats = ps._sanitize(data, FIGURES, HAYSTACK)
    assert "text" not in spec["columns"][0][0]      # text 被丢掉
    assert spec["columns"][0][0]["items"] == ["主干 12 层"]
    assert any("段落含无法回溯的数字" in d for d in stats["dropped"])


def test_sanitize_raises_when_every_column_is_cleared():
    data = _spec(columns=[[{"kind": "figure", "file": "fig-404.png"}], [{"kind": "text", "title": "x", "items": ["9.9"]}]])
    with pytest.raises(ValueError) as e:
        ps._sanitize(data, FIGURES, HAYSTACK)
    assert "清空" in str(e.value)


def test_sanitize_raises_without_title():
    with pytest.raises(ValueError):
        ps._sanitize({"columns": []}, FIGURES, HAYSTACK)


def test_sanitize_is_not_supposed_to_mutate_its_input():
    """已修（2026-09-19）。原缺口：_sanitize 只对顶层做 dict() 浅拷贝，栏目与块仍是调用方的对象，
    被丢掉的 items / text / caption 会就地删掉原 dict。

    当前没炸，是因为唯一调用方 _write_spec 传的是刚 json.loads 出来的对象；
    但同名的 _trim_spec 走的是 json 深拷贝、完全不改输入，两者语义不一致，容易被后续调用方踩到。
    期望：_sanitize 也一样纯（返回新对象，不改入参）。"""
    # 注意：这个 spec 里必须**留一个能回溯的块**，否则所有内容都被剔除、_sanitize 按设计抛
    # ValueError（见 test_sanitize_raises_without_title/_without_title），就测不到「就地改动」这件事了。
    data = _spec(columns=[[
        {"kind": "text", "title": "只有假数字", "items": ["提升了 91.7%"]},
        {"kind": "text", "title": "方法", "items": ["在 3 个数据集上提升 57.18%"]},
    ]])
    snapshot = json.dumps(data, ensure_ascii=False, sort_keys=True)
    _spec_out, stats = ps._sanitize(data, FIGURES, HAYSTACK)
    assert stats["dropped"], "这条用例的前提是确实剔除了内容，否则测不到『就地改动』"
    assert json.dumps(data, ensure_ascii=False, sort_keys=True) == snapshot


# --------------------------------------------------------------------------- #
# _trim_spec
# --------------------------------------------------------------------------- #

def _two_col_spec():
    return {
        "title": "t",
        "columns": [
            [{"kind": "text", "title": "a", "items": ["1"]}, {"kind": "text", "title": "b", "items": ["2"]}],
            [{"kind": "figure", "file": "fig-1.png"}, {"kind": "text", "title": "c", "items": ["3"]}],
        ],
    }


def test_trim_zero_is_noop():
    spec = _two_col_spec()
    assert ps._trim_spec(spec, 0) == spec


def test_trim_drops_from_the_last_column_first_keeping_figures_longer():
    spec = _two_col_spec()
    after1 = ps._trim_spec(spec, 1)
    assert [b.get("title") for b in after1["columns"][1]] == [None]  # 先丢最后一栏的文字块 c，图块留着
    after2 = ps._trim_spec(spec, 2)
    assert len(after2["columns"]) == 1                              # 图块最后才丢，丢完空栏被移除
    assert [b["title"] for b in after2["columns"][0]] == ["a", "b"]


def test_trim_never_empties_the_layout():
    spec = _two_col_spec()
    for drop in range(3, 12):
        out = ps._trim_spec(spec, drop)
        assert sum(len(c) for c in out["columns"]) >= 1
        assert out["columns"]


def test_trim_keeps_a_single_column_single_block():
    spec = {"title": "t", "columns": [[{"kind": "text", "title": "only", "items": ["1"]}]]}
    out = ps._trim_spec(spec, 5)
    assert out["columns"] == [[{"kind": "text", "title": "only", "items": ["1"]}]]


def test_trim_does_not_mutate_input():
    spec = _two_col_spec()
    snapshot = json.dumps(spec, ensure_ascii=False, sort_keys=True)
    for drop in (1, 2, 3):
        ps._trim_spec(spec, drop)
    assert json.dumps(spec, ensure_ascii=False, sort_keys=True) == snapshot


# --------------------------------------------------------------------------- #
# _spec_text / _numbers / _digest_of / _available_figures
# --------------------------------------------------------------------------- #

def test_spec_text_covers_every_rendered_field():
    text = ps._spec_text({
        "title": "T", "subtitle": "S", "kicker": "K", "venue": "V", "affiliation": "A", "footer": "F",
        "authors": ["作者甲"], "chips": ["chip"], "teaser": {"caption": "图注"},
        "columns": [[{"title": "块题", "caption": "块注", "text": "段落", "items": ["项1"], "items_tall": ["项2"]}]],
    })
    for token in ["T", "S", "K", "V", "A", "F", "作者甲", "chip", "图注", "块题", "块注", "段落", "项1", "项2"]:
        assert token in text


def test_numbers_extracts_decimals():
    assert ps._numbers("提升 57.18%，共 3 组") == ["57.18", "3"]


def test_digest_of_reads_understand_stage(fake_ctx, tmp_path):
    ctx = fake_ctx(work=tmp_path / "run1" / "poster")
    with pytest.raises(RuntimeError):
        ps._digest_of(ctx)
    (tmp_path / "run1" / "understand").mkdir(parents=True)
    (tmp_path / "run1" / "understand" / "digest.json").write_text(json.dumps({"title": "T"}), encoding="utf-8")
    assert ps._digest_of(ctx) == {"title": "T"}


def test_available_figures_reads_disk_and_merges_meta(tmp_path):
    intake = tmp_path / "intake"
    (intake / "images").mkdir(parents=True)
    (intake / "images" / "fig-1.png").write_bytes(b"png")
    (intake / "images" / "fig-2.png").write_bytes(b"png")
    (intake / "figures.json").write_text(json.dumps([{"file": "fig-1.png", "caption": "总览", "kind": "figure"}]))
    figs = ps._available_figures(intake)
    assert [f["file"] for f in figs] == ["fig-1.png", "fig-2.png"]
    assert figs[0]["caption"] == "总览" and figs[0]["kind"] == "figure"
    assert figs[1]["caption"] == "" and figs[1]["kind"] == ""


def test_available_figures_tolerates_legacy_dict_and_broken_json(tmp_path):
    intake = tmp_path / "intake"
    (intake / "images").mkdir(parents=True)
    (intake / "images" / "fig-1.png").write_bytes(b"png")
    (intake / "figures.json").write_text("{ not json")
    assert [f["file"] for f in ps._available_figures(intake)] == ["fig-1.png"]
    (intake / "figures.json").write_text(json.dumps({"figures": [{"file": "fig-1.png", "caption": "旧格式"}]}))
    assert ps._available_figures(intake)[0]["caption"] == "旧格式"


# --------------------------------------------------------------------------- #
# _write_spec（LLM 全是 AsyncMock）
# --------------------------------------------------------------------------- #

DIGEST = {"title": "论文标题", "venue": "NeurIPS", "year": 2025, "authors": ["甲", "乙"]}


def _llm_returning(*payloads):
    llm = AsyncMock()
    llm.chat_json = AsyncMock(side_effect=list(payloads))
    return llm


def test_write_spec_returns_sanitized_spec_and_cover(fake_ctx, make_run):
    llm = _llm_returning({
        "spec": _spec(chips=["a", "b", "c", "d", "e"]),
        "cover": {"teaser": {"file": "fig-9.png"}},
    })
    ctx = fake_ctx(run=make_run(), llm=llm)
    spec, cover, stats = asyncio.run(ps._write_spec(ctx, DIGEST, FIGURES, HAYSTACK))
    assert llm.chat_json.await_count == 1
    assert spec["title"] == "论文海报"
    assert cover["layout"] == "cover"
    assert cover["title"] == "论文海报"
    assert len(cover["chips"]) <= 4
    assert "teaser" not in cover                       # 封面引用了不存在的图 → 去掉
    assert stats["dropped"] == []


def test_write_spec_retries_once_then_succeeds(fake_ctx, make_run):
    bad = {"spec": {"columns": [[{"kind": "figure", "file": "fig-404.png"}]]}}
    llm = _llm_returning(bad, {"spec": _spec()})
    ctx = fake_ctx(run=make_run(), llm=llm)
    spec, _, _ = asyncio.run(ps._write_spec(ctx, DIGEST, FIGURES, "正文"))
    assert llm.chat_json.await_count == 2
    assert spec["title"] == "论文海报"
    assert any(level == "warn" and "校验未过" in text for level, text in ctx.logs)
    # 第二次请求带着上一次的错误原因
    second_prompt = llm.chat_json.await_args_list[1].args[1]
    assert "上一次的输出有问题" in second_prompt


def test_write_spec_gives_up_after_two_attempts(fake_ctx, make_run):
    bad = {"spec": {"columns": []}}
    llm = _llm_returning(bad, bad)
    ctx = fake_ctx(run=make_run(), llm=llm)
    with pytest.raises(RuntimeError) as e:
        asyncio.run(ps._write_spec(ctx, DIGEST, FIGURES, "正文"))
    assert llm.chat_json.await_count == 2
    assert "两次都没能生成可用的 spec" in str(e.value)


def test_write_spec_accepts_bare_spec_payload(fake_ctx, make_run):
    # 模型有时直接吐 spec（外面没有 spec 键）
    llm = _llm_returning(_spec())
    ctx = fake_ctx(run=make_run(), llm=llm)
    spec, cover, _ = asyncio.run(ps._write_spec(ctx, DIGEST, FIGURES, "正文"))
    assert spec["title"] == "论文海报"
    assert cover == {}


def test_write_spec_prompt_carries_figure_list_and_brief(fake_ctx, make_run):
    llm = _llm_returning({"spec": _spec()})
    ctx = fake_ctx(run=make_run(brief="海报要突出方法，少写字"), llm=llm)
    asyncio.run(ps._write_spec(ctx, DIGEST, FIGURES, "正文"))
    system, user = llm.chat_json.await_args.args[:2]
    assert "海报" in system
    assert "fig-1.png" in user and "fig-2.png" in user
    assert "海报要突出方法" in user
