"""app/models.py 的契约：阶段清单、实现状态、平台枚举。

这些用例盯的是「前后端契约 + 加平台时容易漏改的地方」：
docs/04-api-contract.md 说前端 6 个 stage 是契约，前端 types.ts 与这里的 Literal 必须同步。
"""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from app import models, styles

EXPECTED_STAGES = ["intake", "understand", "article", "poster", "video", "publish"]


def test_stage_order_is_exactly_six_stages_in_contract_order():
    assert models.STAGE_ORDER == EXPECTED_STAGES
    assert len(models.STAGE_ORDER) == 6
    assert len(set(models.STAGE_ORDER)) == 6          # 不许重复


def test_every_stage_is_implemented_and_none_is_skipped():
    """收口约定：6 个阶段全都有真实实现，SKIPPED_STAGES 必须为空。"""
    assert models.SKIPPED_STAGES == set()
    assert models.IMPLEMENTED_STAGES == set(models.STAGE_ORDER)
    assert len(models.IMPLEMENTED_STAGES) == 6


def test_stage_meta_covers_every_stage():
    # new_run() 会 STAGE_META[sid] 取元信息，缺一个就 KeyError
    assert set(models.STAGE_META) == set(models.STAGE_ORDER)
    for sid in models.STAGE_ORDER:
        meta = models.STAGE_META[sid]
        assert meta["label"] and meta["engine"] and meta["hint"]


def test_stage_id_literal_covers_stage_order():
    assert set(get_args(models.StageId)) == set(models.STAGE_ORDER)


def test_new_run_defaults_skip_video_when_bilibili_not_targeted(make_run):
    """默认只发小红书 → 不跑视频合成，video 阶段如实标 skipped（其余 5 个 pending）。"""
    run = make_run()
    assert [s.id for s in run.stages] == models.STAGE_ORDER
    assert [s.status for s in run.stages] == ["pending", "pending", "pending", "pending", "skipped", "pending"]
    assert run.status == "queued"
    assert run.id.startswith("run_")
    assert run.createdAt > 0


def test_new_run_runs_video_when_bilibili_is_targeted(make_run):
    """把 B 站加进发布目标，视频阶段就照常跑（默认关闭不是永久关闭）。"""
    run = make_run(publish={"targets": ["bilibili"]})
    assert [s.status for s in run.stages][models.STAGE_ORDER.index("video")] == "pending"


def test_align_variants_drops_platforms_outside_targets(make_run):
    """默认只发小红书时，历史遗留的知乎/英文变体必须被去掉（2026-09-23）。

    前端风格页勾选的变体存在 localStorage，会跟着每次提交一起发过来；只收口 targets
    会出现「targets=[xiaohongshu] 却还在写知乎长文」，所以这里也要裁。
    """
    run = make_run(article={"variants": ["xhs-peer", "zhihu-newsflash", "en"]})
    assert run.config.article.variants == ["xhs-peer"]


def test_align_variants_keeps_platforms_that_are_targeted(make_run):
    run = make_run(article={"variants": ["xhs-peer", "zhihu-newsflash"]},
                   publish={"targets": ["xiaohongshu", "zhihu"]})
    assert run.config.article.variants == ["xhs-peer", "zhihu-newsflash"]


def test_align_variants_fills_missing_target_variant(make_run):
    """目标平台一个变体都没有时，补一个该平台默认人格的（老的「只补」行为保留）。"""
    run = make_run(article={"variants": []}, publish={"targets": ["zhihu"]})
    assert run.config.article.variants == ["zhihu"]


def test_align_variants_no_targets_means_no_pruning(make_run):
    """targets 留空 = 用全部渠道，此时不做任何裁剪。"""
    run = make_run(article={"variants": ["xhs-peer", "zhihu-newsflash"]},
                   publish={"targets": []})
    assert run.config.article.variants == ["xhs-peer", "zhihu-newsflash"]


def test_article_variant_platform_literal_matches_styles_platforms():
    """加平台时要一起改枚举 —— 漏了会导致该变体记不进去（2026-09-19 加英文平台时踩到）。

    这条用例的写法是「跟着 styles.PLATFORMS 走」：以后再加平台，这里自动要求枚举同步补上。
    """
    for pid in styles.PLATFORMS:
        v = models.ArticleVariant(id=f"{pid}-author", platform=pid, voice="author", label=pid, url="/x")
        assert v.platform == pid
    assert set(get_args(models.ArticleVariant.model_fields["platform"].annotation)) == set(styles.PLATFORMS)


def test_article_variant_rejects_retired_platform():
    # 公众号已下线：枚举里不许再有 wechat（历史 id 由 styles.parse_variant 挡在前面）
    with pytest.raises(ValidationError):
        models.ArticleVariant(id="wechat-author", platform="wechat", voice="author", label="x", url="/x")


def test_article_config_default_variant_is_parseable():
    cfg = models.ArticleConfig()
    assert cfg.variants == ["xhs-author"]
    assert all(styles.parse_variant(v) for v in cfg.variants)


def test_brief_has_a_hard_length_budget():
    models.RunConfig(brief="短指令")
    with pytest.raises(ValidationError):
        models.RunConfig(brief="字" * 2001)


def test_run_config_defaults_match_frontend_contract():
    cfg = models.RunConfig()
    assert cfg.article.variants == ["xhs-author"]
    assert cfg.poster.size == "36x48" and cfg.poster.lang == "zh"
    assert cfg.video.aspect == "9:16" and cfg.video.durationSec == 180
    assert cfg.publish.autoPublish is False
    # 默认只发小红书（2026-09-23）：不再默认产出/投递知乎与 B 站
    assert cfg.publish.targets == ["xiaohongshu"]


def test_stage_status_and_run_status_vocabulary():
    assert set(get_args(models.StageStatus)) == {"pending", "running", "waiting", "done", "failed", "skipped"}
    assert set(get_args(models.RunStatus)) == {"queued", "running", "waiting", "done", "failed"}
    assert set(get_args(models.SourceKind)) == {"arxiv", "pdf", "latex", "zhihu", "url", "github"}
