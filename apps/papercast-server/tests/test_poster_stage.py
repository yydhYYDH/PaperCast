"""app/modules/poster_stage.py：spec 收敛（_sanitize）、减块（_trim_spec）、写 spec 的编排。

LLM 一律 AsyncMock —— 这里不产生任何真实网络调用。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
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


# --------------------------------------------------------------------------- #
# deck_artifact_rel（组图产物登记路径）
# --------------------------------------------------------------------------- #

def test_deck_artifact_rel_uses_RENDERER_reported_path(tmp_path):
    """渲染器落的是 <poster>/cards/output/*.png —— 登记的 rel 必须与它一致。

    回归（2026-09-19 真跑 run_77d2410986e6）：这里原先把 rel 硬写成 `cards/{id}.png`，
    而文件在 `cards/output/`，于是 7 张组图全部登记成「缺失」（渲染 JSON 说 ok、文件也在，
    阶段产物却点不开），而阶段闸门照样判 pass。
    """
    out_dir = tmp_path / "poster"
    png = out_dir / "cards" / "output" / "xhs-01.png"
    png.parent.mkdir(parents=True)
    png.write_bytes(b"png")
    rel = ps.deck_artifact_rel({"id": "xhs-01", "path": str(png)}, out_dir)
    assert rel == "cards/output/xhs-01.png"
    assert (out_dir / rel).is_file()          # 登记路径必须真能落到文件上


def test_deck_artifact_rel_never_leaks_paths_outside_poster_dir(tmp_path):
    out_dir = tmp_path / "poster"
    out_dir.mkdir()
    outside = tmp_path / "elsewhere" / "xhs-02.png"
    outside.parent.mkdir()
    outside.write_bytes(b"png")
    assert ps.deck_artifact_rel({"id": "xhs-02", "path": str(outside)}, out_dir) == "cards/output/xhs-02.png"


def test_deck_artifact_rel_falls_back_to_skill_convention(tmp_path):
    # 渲染器没报 path（旧版本/异常输出）时按技能约定拼，至少与索引同源
    assert ps.deck_artifact_rel({"id": "xhs-03"}, tmp_path) == "cards/output/xhs-03.png"
    assert ps.deck_artifact_rel({"id": "", "path": ""}, tmp_path) == "cards/output/.png"


def test_deck_deliverable_rel_prefers_jpeg_sidecar(tmp_path):
    """有 JPEG 侧车就登记 JPEG：PNG 是母版（~900KB/张），JPEG 才是上传那份（~300KB/张）。"""
    out_dir = tmp_path / "poster"
    (out_dir / "cards" / "output").mkdir(parents=True)
    (out_dir / "cards" / "output" / "xhs-01.png").write_bytes(b"png")
    (out_dir / "cards" / "output" / "xhs-01.jpg").write_bytes(b"jpg")
    assert ps.deck_deliverable_rel("cards/output/xhs-01.png", out_dir) == "cards/output/xhs-01.jpg"


def test_deck_deliverable_rel_keeps_png_without_sidecar(tmp_path):
    """没转成 JPEG（Pillow 缺席/旧产物）就照旧登记 PNG，不能登记出不存在的文件。"""
    out_dir = tmp_path / "poster"
    (out_dir / "cards" / "output").mkdir(parents=True)
    (out_dir / "cards" / "output" / "xhs-01.png").write_bytes(b"png")
    assert ps.deck_deliverable_rel("cards/output/xhs-01.png", out_dir) == "cards/output/xhs-01.png"
    assert ps.deck_deliverable_rel("cards/output/xhs-01.jpg", out_dir) == "cards/output/xhs-01.jpg"


# --------------------------------------------------------------------------- #
# _run_deck：1x 渲染 + 登记 JPEG 侧车（不真起 chromium，渲染器被替身接管）
# --------------------------------------------------------------------------- #

def test_run_deck_renders_1x_and_registers_jpeg(fake_ctx, tmp_path, monkeypatch):
    """组图阶段的三条口径：scale=1、登记 JPEG（有侧车时）、meta 尺寸是实际像素。

    回归（2026-09-19）：这里原来写死 scale=2 且 meta 里手写 w*2，产出 2160×2880 / 20MB
    的 PNG；而小红书原生口径就是 1080×1440、上传还会被平台再压一遍。
    """
    out_dir = tmp_path / "work"
    deck_out = out_dir / "cards" / "output"
    deck_out.mkdir(parents=True)
    frames = []
    for i in (1, 2):
        png = deck_out / ("xhs-%02d.png" % i)
        png.write_bytes(b"png")
        png.with_suffix(".jpg").write_bytes(b"jpg")      # JPEG 侧车（投递那份）
        frames.append({"id": "xhs-%02d" % i, "path": str(png), "w": 1080, "h": 1440,
                       "jpegBytes": 300_000})
    (out_dir / "cards" / "index.html").write_text("<html></html>", encoding="utf-8")

    seen: dict = {}
    monkeypatch.setattr(ps.cards_deck, "enabled", lambda mode: True)
    monkeypatch.setattr(ps.cards_deck, "build", lambda *a, **k: {
        "plan": [{"kind": "cover"}, {"kind": "figure"}], "theme": "midnight-ink"})
    monkeypatch.setattr(ps.cards_deck, "render", lambda d, **kw: seen.update(kw) or {
        "ok": True, "count": 2, "scale": 1, "jpegs": 2, "frames": frames})
    monkeypatch.setattr(ps.cards_deck, "validate",
                        lambda d, **k: {"fails": 0, "warns": 0, "sections": 2, "clean": 2, "details": []})

    ctx = fake_ctx(work=out_dir)
    ctx.settings = SimpleNamespace(poster_deck="auto")
    asyncio.run(ps._run_deck(ctx, {"title": "论文海报", "venue": "会议"}, None, {}, str(tmp_path), out_dir))

    assert seen.get("scale") == 1, "组图必须按 1x（1080×1440）渲染"
    imgs = [a for a in ctx.artifacts if a["kind"] == "image"]
    assert [a["rel"] for a in imgs] == ["cards/output/xhs-01.jpg", "cards/output/xhs-02.jpg"]
    assert imgs[0]["meta"]["width"] == 1080 and imgs[0]["meta"]["height"] == 1440
    assert imgs[0]["meta"]["bytes"] == 300_000
    assert ctx.state_of("小红书组图（guizang 技能）") == "pass"


def test_write_spec_prompt_carries_figure_list_and_brief(fake_ctx, make_run):
    llm = _llm_returning({"spec": _spec()})
    ctx = fake_ctx(run=make_run(brief="海报要突出方法，少写字"), llm=llm)
    asyncio.run(ps._write_spec(ctx, DIGEST, FIGURES, "正文"))
    system, user = llm.chat_json.await_args.args[:2]
    assert "海报" in system
    assert "fig-1.png" in user and "fig-2.png" in user
    assert "海报要突出方法" in user
