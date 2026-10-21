"""非论文源（知乎/长文）传播链路的契约测试。"""

from __future__ import annotations

from types import SimpleNamespace

from app import prompts
from app.modules import generate as gen


def test_is_article_run_only_for_zhihu_and_url():
    def ctx(kind):
        return SimpleNamespace(run=SimpleNamespace(source=SimpleNamespace(kind=kind)))
    assert gen._is_article_run(ctx("zhihu")) is True
    assert gen._is_article_run(ctx("url")) is True
    assert gen._is_article_run(ctx("arxiv")) is False
    assert gen._is_article_run(ctx("pdf")) is False


def test_build_article_digest_maps_fields():
    figures = [
        {"id": "img0", "file": "images/img0.jpg", "caption": "架构图"},
        {"id": "img1", "file": "images/img1.jpg", "caption": "数据图"},
    ]
    raw = {
        "guide": "讲 DeepSeek 的沙盒基础设施。",
        "hookPoints": ["超卖 50 倍", "Agent 造环境"],
        "keyFacts": [{"label": "并发", "value": "38 万个沙盒", "note": "正文"}],
        "quotes": ["用 Agent 给 Agent 造环境"],
        "keywords": ["DeepSeek", "沙盒"],
        "figurePicks": ["img1"],
        "stagesNote": "取自原文",
    }
    d = gen._build_article_digest(raw, figures, {"title": "标题"}, "标题")
    assert d.abstractCn.startswith("讲 DeepSeek")
    assert d.contributions == ["超卖 50 倍", "Agent 造环境"]
    assert d.results[0]["value"] == "38 万个沙盒"
    assert "用 Agent 给 Agent 造环境" in d.method
    assert [f["id"] for f in d.figures] == ["img1"]


def test_article_mode_system_prompt_uses_propagation_rules():
    sys_article = prompts.article_system("xhs", "independent", article_mode=True)
    assert "小红书爆款图文" in sys_article
    assert "改写铁律" in sys_article
    assert "事实源铁律" not in sys_article          # 不再用论文的"事实源铁律"
    assert "你是一位与这篇论文" not in sys_article     # 不再套论文人格


def test_paper_mode_system_prompt_unchanged():
    sys_paper = prompts.article_system("xhs", "independent")
    assert "事实源铁律" in sys_paper
    assert "小红书爆款图文" not in sys_paper


def test_strip_article_attribution_removes_paper_signature_line():
    body = "正文一段。\n\n—— 论文：原文章标题\n\n我的看法是：值得看。"
    out = gen._strip_article_attribution(body)
    assert "论文" not in out
    assert "我的看法是" in out


def test_compose_body_omits_paper_attribution_for_article():
    from app.channels.base import Channel, Materials

    # compose_body 不依赖实例状态，直接调未绑定方法即可。
    paper = Channel.compose_body(None, Materials(title="t", body="正文", source="arXiv 2510.05096", tags=["a"]))
    assert "—— 论文：arXiv 2510.05096" in paper

    article = Channel.compose_body(None, Materials(
        title="t", body="正文", source="DeepSeek扩招",
        tags=["a"], extra={"isArticle": True},
    ))
    assert "论文" not in article and "DeepSeek扩招" not in article


def test_article_user_includes_original_text_and_source():
    u = prompts.article_user("标题", "{}", [], article_mode=True,
                             content_md="原文正文内容", source="知乎 · 量子位")
    assert "知乎 · 量子位" in u and "原文正文内容" in u
