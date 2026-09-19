"""B3 / B4 / B5：物料按渠道分发（各渠道拿匹配变体、兜底确定性、图片按 figures.json），
外加 B6（words 按平台口径）的回归。

背景都是 2026-09-19 独立验证轨道的实测（数据在 var/runs/，本文件只用 tmp_path 复现）：
- **B3** run_d76ca9da493e（xhs-author + zhihu-analyst）：三个渠道共用唯一一份
  article/export/，回执 zhihu.contentChars=921（= 小红书正文），而磁盘上 2745 字的知乎长文
  没被用过；闸门详情也写「知乎：将投递 长文（921 字…）」—— 界面在骗人。
- **B3 之二** run_720e83bdae91（en + zhihu）：知乎拿到的是英文 thread。
- **B4** run_9105dc770228：导出兜底取「第一个 markdown 变体」→ article/export/title.txt 是
  83 字符的英文标题，B 站（上限 80）被判素材不适配而跳过；反序却正常。
- **B5** run_720e83bdae91：intake 用旧命名 img-pXX-N.png → imageCount=0（回执写「无配图」），
  而 intake/ 里躺着 4 张图。
- **B6** run_720e83bdae91 的 run.articles 里 en-analyst 的 words=0（登记用了 cjk_len）。

本文件不联网、不起服务、不写真 var/runs：渠道都是本文件里的替身（不触网）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import styles
from app.channels.base import Delivery, Materials, Preflight
from app.modules import publish as P

# --------------------------------------------------------------------------- #
# 造 run 目录：只用 tmp_path
# --------------------------------------------------------------------------- #

XHS_MD = """# 小红书图文帖：多智能体怎么做罕见病诊断

## 候选标题
1. 多智能体怎么做罕见病诊断（计重 30）

推荐标题：多智能体怎么做罕见病诊断

## TL;DR
把鉴别诊断拆成三层多智能体流程。

## 正文
这是小红书正文：短、口语、只讲三件事。

## 标签
#罕见病 #多智能体 #鉴别诊断 #可追溯推理

## 配图顺序
1. `cards/p1.png`：总览图 —— 对应 #notatag
"""

ZHIHU_MD = """# 多智能体罕见病诊断系统的技术解读

导语：结论前置。

## 问题与瓶颈
这一段是知乎长文正文，明显比小红书长。

## 话题标签
- #罕见病诊断
- #多智能体系统
- #大语言模型
"""

# 83 字符的英文标题 —— 正是 run_9105dc770228 踩到 B 站 80 上限的那一份
EN_MD = """# DeepRare: an agentic LLM system for rare disease diagnosis with traceable reasoning

1/6 DeepRare turns differential diagnosis into a three-layer agentic system.

## Tags
- #RareDisease
- #LLMAgent
"""

BILI_MD = """# B 站脚本标题

口播稿：口语、短句、每 15 秒推进一个信息点。
"""

README_TEXT = """手动发布指引
1. 打开平台发布页
2. 标题取 title.txt，正文取 content.txt
3. 配图按 p1/p2 顺序插入
"""

EXPORT = ("导出的标题", "导出的正文：没有变体文件时用它。")


def _write(run_dir: Path, rel: str, text: str) -> Path:
    path = run_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _run_tree(tmp_path: Path, *, variants: dict[str, str] | None = None,
              export: tuple[str, str] | None = None, figures: object = None,
              image_files: tuple[str, ...] = (), cards: int = 0,
              videos: tuple[str, ...] = ()) -> Path:
    """构造一个最小 run 目录（只有 article/ intake/ 与可选的卡片、成片）。"""
    run_dir = tmp_path / "run"
    (run_dir / "article").mkdir(parents=True)
    for name, text in (variants or {}).items():
        _write(run_dir, "article/" + name, text)
    if export:
        _write(run_dir, "article/export/title.txt", export[0])
        _write(run_dir, "article/export/content.txt", export[1])
    for rel in image_files:
        _write(run_dir, "intake/" + rel, "")
    if figures is not None:
        (run_dir / "intake").mkdir(parents=True, exist_ok=True)
        (run_dir / "intake" / "figures.json").write_text(
            figures if isinstance(figures, str) else json.dumps(figures, ensure_ascii=False),
            encoding="utf-8")
    for i in range(1, cards + 1):
        _write(run_dir, "article/cards/p%d.png" % i, "")
    for name in videos:
        _write(run_dir, "video/" + name, "")
    return run_dir


def _collect(run_dir: Path, channel_id: str, warns: list[str] | None = None) -> Materials:
    return P.collect_materials_for(run_dir, None, channel_id,
                                  warn=(warns.append if warns is not None else None))


def _variant_warns(warns: list[str]) -> list[str]:
    """只挑「变体选择」那类 warn —— 每条都以 [渠道 id] 开头，图片/媒体的 warn 不带前缀。"""
    return [w for w in warns if w.startswith("[")]


# --------------------------------------------------------------------------- #
# B3：各渠道拿到匹配变体
# --------------------------------------------------------------------------- #

def test_each_channel_gets_its_own_variant(tmp_path):
    """三渠道各自拿自己那份文案 —— 不再共用唯一一份 export/。"""
    run_dir = _run_tree(tmp_path, variants={"xhs.md": XHS_MD, "zhihu-analyst.md": ZHIHU_MD},
                        export=EXPORT,
                        figures=[{"id": "fig-1", "file": "images/fig-1.png", "kind": "fig"}],
                        image_files=("images/fig-1.png",))

    xhs = _collect(run_dir, "xiaohongshu")
    zhihu = _collect(run_dir, "zhihu")

    assert xhs.extra["variant"] == "xhs"
    assert xhs.title == "多智能体怎么做罕见病诊断"          # 推荐标题，不是 export 里的标题
    assert "这是小红书正文" in xhs.body and len(xhs.body) < len(zhihu.body)
    # xhs 图文帖：正文只取「## 正文」一节，候选标题 / TL;DR / 标签 / 配图顺序都不进正文
    for leaked in ("## 候选标题", "## 标签", "## 配图顺序", "TL;DR"):
        assert leaked not in xhs.body
    assert xhs.tags == ["罕见病", "多智能体", "鉴别诊断", "可追溯推理"]   # 只取「## 标签」一节
    assert "notatag" not in xhs.tags                                   # 后续小节里的 # 不算标签

    assert zhihu.extra["variant"] == "zhihu-analyst"
    assert zhihu.title == "多智能体罕见病诊断系统的技术解读"
    assert zhihu.body.startswith("# 多智能体罕见病诊断系统")            # 长文全文（与历史 export 同口径）
    assert zhihu.tags == ["罕见病诊断", "多智能体系统", "大语言模型"]
    assert zhihu.body != xhs.body
    assert zhihu.images and zhihu.images[0].name == "fig-1.png"        # 图片按 figures.json


def test_en_plus_zhihu_does_not_hand_zhihu_the_english_thread(tmp_path):
    """run_720e83bdae91 的形态：en + zhihu 组合下知乎必须拿到中文长文。"""
    run_dir = _run_tree(tmp_path, variants={"en-analyst.md": EN_MD, "zhihu-analyst.md": ZHIHU_MD})
    zhihu = _collect(run_dir, "zhihu")
    assert zhihu.extra["variant"] == "zhihu-analyst"
    assert zhihu.title == "多智能体罕见病诊断系统的技术解读"
    assert "DeepRare turns differential diagnosis" not in zhihu.body


# --------------------------------------------------------------------------- #
# B4：没有匹配变体时的兜底要确定、中文优先，并且记 warn
# --------------------------------------------------------------------------- #

def test_fallback_is_chinese_first_and_order_independent(tmp_path):
    """en + zhihu 两个变体：B 站拿到的是中文那份（标题 ≤ 80），与文件名顺序无关。"""
    assert len(EN_MD.splitlines()[0]) - 2 == 83          # 前提：英文标题就是 83 字符

    plain = _run_tree(tmp_path, variants={"en-analyst.md": EN_MD, "zhihu-analyst.md": ZHIHU_MD})
    warns: list[str] = []
    bili = _collect(plain, "bilibili", warns)
    assert bili.extra["variant"] == "zhihu-analyst"
    assert len(bili.title) <= 80                          # 旧的「第一个 markdown 变体」会给 83
    assert warns and "兜底顺序" in warns[0] and "xhs→zhihu→bilibili→en" in warns[0]

    # 换一组文件名（人格不同、排序不同）：兜底结果必须一样
    other = _run_tree(tmp_path / "other", variants={"zhihu-peer.md": ZHIHU_MD, "en-analyst.md": EN_MD})
    assert _collect(other, "bilibili").extra["variant"] == "zhihu-peer"
    assert _collect(other, "bilibili").title == bili.title

    # 有「专属变体」时不该有兜底 warn
    both = _run_tree(tmp_path / "both", variants={"en-analyst.md": EN_MD, "zhihu-analyst.md": ZHIHU_MD,
                                                  "bilibili-author.md": BILI_MD})
    quiet: list[str] = []
    assert _collect(both, "bilibili", quiet).extra["variant"] == "bilibili-author"
    assert _variant_warns(quiet) == []


def test_no_matching_variant_uses_priority_order_with_warn(tmp_path):
    """只有 en 一个变体时：命中优先级里的 en，并记 warn（英文对中文渠道是"能发但不对味"）。"""
    run_dir = _run_tree(tmp_path, variants={"en-analyst.md": EN_MD})
    warns: list[str] = []
    m = _collect(run_dir, "zhihu", warns)
    assert m.extra["variant"] == "en-analyst"
    assert any("没有 zhihu 变体" in w and "en" in w for w in _variant_warns(warns))


def test_unknown_platform_falls_back_to_first_variant_with_warn(tmp_path, monkeypatch):
    """防御分支：哪天加了新平台却忘了写进兜底优先级，也不能炸 —— 退第一个并记 warn。"""
    monkeypatch.setattr(P, "FALLBACK_PLATFORM_ORDER", ("xhs",))
    run_dir = _run_tree(tmp_path, variants={"en-analyst.md": EN_MD, "zhihu-analyst.md": ZHIHU_MD})
    warns: list[str] = []
    m = _collect(run_dir, "bilibili", warns)                   # 只认优先级里的 xhs，而它不存在
    assert m.extra["variant"] == "en-analyst"                  # → 退按文件名排序的第一个
    assert any("退第一个 markdown 变体" in w for w in _variant_warns(warns))


def test_export_fallback_survives_when_no_variant_at_all(tmp_path):
    """不含小红书变体的 run 曾经直接 publish 失败（TITLE_MISSING）—— 这条历史兜底别撤掉。"""
    run_dir = _run_tree(tmp_path, export=EXPORT)
    warns: list[str] = []
    m = _collect(run_dir, "zhihu", warns)
    assert (m.title, m.body) == EXPORT
    assert m.extra["variant"] == "export/"
    assert warns and "export/" in warns[0]

    empty = _run_tree(tmp_path / "empty")
    with pytest.raises(P.PublishError) as exc:
        _collect(empty, "zhihu")
    assert exc.value.code == "TITLE_MISSING"


def test_primary_material_prefers_chinese_and_ignores_export(tmp_path):
    """与渠道无关的主物料（社区运营用）也按中文优先，不再是 export/ 里那一份。"""
    run_dir = _run_tree(tmp_path, variants={"xhs.md": XHS_MD, "zhihu-analyst.md": ZHIHU_MD,
                                            "en-analyst.md": EN_MD}, export=EXPORT)
    primary = P.collect_materials(run_dir, None)
    assert primary.extra["variant"] == "xhs"
    assert primary.title == "多智能体怎么做罕见病诊断"


# --------------------------------------------------------------------------- #
# B5：图片清单来自 intake/figures.json（list），glob 只当最后一层兜底
# --------------------------------------------------------------------------- #

def test_figures_json_wins_over_glob(tmp_path):
    """旧命名 img-pXX-N.png 靠 figures.json 也能投出去；有清单时不走 glob、不记 warn。"""
    run_dir = _run_tree(
        tmp_path, variants={"zhihu-analyst.md": ZHIHU_MD},
        figures=[{"id": "img-p17-1", "kind": "img", "file": "images/img-p17-1.png", "caption": "无图注"},
                 {"id": "img-p18-1", "kind": "img", "file": "images/img-p18-1.png"}],
        image_files=("images/img-p17-1.png", "images/img-p18-1.png", "images/fig-9.png"),
    )
    warns: list[str] = []
    m = _collect(run_dir, "zhihu", warns)
    assert [p.name for p in m.images] == ["img-p17-1.png", "img-p18-1.png"]
    assert warns == []


def test_glob_fallback_warns_new_names_only(tmp_path):
    """读不到 figures.json 才退 glob，而且要记 warn（glob 只认 fig-*.png 新命名）。"""
    run_dir = _run_tree(tmp_path, variants={"zhihu-analyst.md": ZHIHU_MD},
                        image_files=("images/fig-1.png", "images/img-p17-1.png"))
    warns: list[str] = []
    m = _collect(run_dir, "zhihu", warns)
    assert [p.name for p in m.images] == ["fig-1.png"]
    assert len(warns) == 1 and "fig-*.png" in warns[0]


def test_broken_figures_json_warns_and_falls_back(tmp_path):
    """figures.json 坏 JSON / 不是 list 时如实 warn 并退 glob，不炸。"""
    for i, bad in enumerate(("{not json", json.dumps({"figures": []}))):
        run_dir = _run_tree(tmp_path / ("bad%d" % i), variants={"zhihu-analyst.md": ZHIHU_MD},
                            figures=bad, image_files=("images/fig-1.png",))
        warns: list[str] = []
        m = _collect(run_dir, "zhihu", warns)
        assert [p.name for p in m.images] == ["fig-1.png"]
        assert any("figures.json" in w for w in warns)


def test_cards_still_win_over_intake_figures(tmp_path):
    """小红书卡片（3:4，排版过）依旧是第一优先，行为不变。"""
    run_dir = _run_tree(tmp_path, variants={"zhihu-analyst.md": ZHIHU_MD}, cards=2,
                        figures=[{"file": "images/fig-1.png"}], image_files=("images/fig-1.png",))
    m = _collect(run_dir, "xiaohongshu")
    assert [p.name for p in m.images] == ["p1.png", "p2.png"]


# --------------------------------------------------------------------------- #
# B3 端到端：闸门详情如实写清每个渠道投哪份文案 + 回执按渠道
# --------------------------------------------------------------------------- #

class _FakeChannel:
    """渠道替身：不触网、不写真实数据，只记下 publish() 收到了哪份物料。"""

    login_kind = "none"
    transport = "fake"
    restart_hint = ""

    def __init__(self, cid: str, name: str) -> None:
        self.id, self.name = cid, name
        self.published: list[Materials] = []

    def supports(self, m: Materials) -> tuple[bool, str]:
        return True, "长文（%d 字）" % len(m.body)

    async def export(self, m: Materials, out: Path) -> dict[str, object]:
        out.mkdir(parents=True, exist_ok=True)
        files = ["title.txt", "content.txt", "README.txt"]
        for name, text in (("title.txt", m.title), ("content.txt", m.body),
                           ("README.txt", README_TEXT)):
            (out / name).write_text(text, encoding="utf-8")
        return {"dir": str(out), "files": files}

    async def preflight(self) -> Preflight:
        return Preflight(state="ready", account="tester", detail="替身渠道", transport=self.transport)

    async def publish(self, m: Materials, *, confirmed: bool = False) -> Delivery:
        assert confirmed is True
        self.published.append(m)
        return Delivery(channel=self.id, status="published", url="https://example.invalid/%s" % self.id)


@pytest.fixture
def publish_tree(run_tree, make_run, monkeypatch):
    """「带 article/ 的 run + 三个替身渠道 + 不跑真社区运营」的 ctx 工厂。"""
    from app.channels import registry

    def _make(chosen: str = "draft"):
        run = make_run(publish={"targets": ["xiaohongshu", "zhihu", "bilibili"]})
        ctx, run_dir = run_tree(run=run)
        ctx.settings = SimpleNamespace(channels=["xiaohongshu", "zhihu", "bilibili"])
        channels = [_FakeChannel("xiaohongshu", "小红书"), _FakeChannel("zhihu", "知乎"),
                    _FakeChannel("bilibili", "B站")]
        monkeypatch.setattr(registry, "resolve_targets", lambda settings, targets: (channels, []))
        monkeypatch.setattr("app.modules.community.run_community", AsyncMock(return_value={}))
        seen: dict[str, str] = {}

        async def _gate(gate_id, label, detail, options, default=None):
            seen["detail"], seen["default"] = detail, default
            return chosen

        ctx.gate = _gate
        return ctx, run_dir, channels, seen

    return _make


def test_gate_detail_and_receipts_are_per_channel(publish_tree):
    """闸门详情必须写清各家投哪份文案；回执的字数必须各渠道不同（B3 的「界面在骗人」）。"""
    ctx, run_dir, _channels, seen = publish_tree(chosen="draft")
    _write(run_dir, "article/xhs.md", XHS_MD)
    _write(run_dir, "article/zhihu-analyst.md", ZHIHU_MD)

    asyncio.run(P.run_publish(ctx))
    detail = seen["detail"]
    assert "多智能体怎么做罕见病诊断" in detail                 # 小红书那份
    assert "多智能体罕见病诊断系统的技术解读" in detail            # 知乎那份
    assert "[兜底变体 xhs（B站 没有专属变体）]" in detail         # B 站的兜底如实写在闸门里
    assert seen["default"] == "draft"                            # 安全默认值没被改掉

    receipts = json.loads((ctx.work / "receipts.json").read_text(encoding="utf-8"))
    by = receipts["channels"]
    assert by["zhihu"]["contentChars"] > by["xiaohongshu"]["contentChars"]
    assert by["zhihu"]["title"] != by["xiaohongshu"]["title"]
    assert by["zhihu"]["variant"] == "zhihu-analyst"
    assert by["bilibili"]["variant"] == "xhs"
    assert by["bilibili"]["contentChars"] == by["xiaohongshu"]["contentChars"]
    assert receipts["status"] == "draft"
    # 每个渠道的 export/ 里落的是它自己那份（不再是三份一模一样）
    assert (ctx.work / "zhihu/export/title.txt").read_text(encoding="utf-8") == by["zhihu"]["title"]
    assert (ctx.work / "xiaohongshu/export/title.txt").read_text(encoding="utf-8") == by["xiaohongshu"]["title"]


def test_delivery_hands_each_channel_its_own_materials(publish_tree):
    """放行时投出去的是各渠道自己那份（替身渠道，不触网）。"""
    ctx, run_dir, channels, _seen = publish_tree(chosen="continue")
    _write(run_dir, "article/xhs.md", XHS_MD)
    _write(run_dir, "article/zhihu-analyst.md", ZHIHU_MD)

    asyncio.run(P.run_publish(ctx))
    got = {c.id: (c.published[0].title, len(c.published[0].body)) for c in channels}
    assert len(set(got.values())) == 2                            # 小红书/知乎 各一份，B站复用兜底那份
    assert got["zhihu"][0] == "多智能体罕见病诊断系统的技术解读"
    assert got["xiaohongshu"][0] == "多智能体怎么做罕见病诊断"
    assert got["bilibili"] == got["xiaohongshu"]


# --------------------------------------------------------------------------- #
# B6：变体字数按平台口径登记（英文用词数，不是 cjk_len=0）
# --------------------------------------------------------------------------- #

def test_markdown_variant_words_use_platform_unit(fake_ctx):
    """run.articles[].words：英文变体必须 > 0（unit="words"），中文变体仍是中文字数。"""
    from app.modules.generate import _gen_markdown_variant

    digest = SimpleNamespace(title="Paper X")
    en_text = EN_MD + chr(10) + " ".join("word%d" % i for i in range(40)) + chr(10)
    ctx = fake_ctx(llm=AsyncMock(chat=AsyncMock(return_value=en_text)))
    ctx.shared["intake"] = {"markdown": ""}
    ctx.run.articles = []
    asyncio.run(_gen_markdown_variant(ctx, styles.PLATFORMS["en"], "analyst", digest, "{}", []))
    en = ctx.run.articles[-1]
    assert en.words == styles.text_len(en_text.strip(), "words") > 0
    assert any("完成" in line and "词" in line for _, line in ctx.logs)

    ctx2 = fake_ctx(llm=AsyncMock(chat=AsyncMock(return_value=ZHIHU_MD)))
    ctx2.shared["intake"] = {"markdown": ""}
    ctx2.run.articles = []
    asyncio.run(_gen_markdown_variant(ctx2, styles.PLATFORMS["zhihu"], "analyst", digest, "{}", []))
    zh = ctx2.run.articles[-1]
    assert zh.words == styles.cjk_len(ZHIHU_MD) > 0
# B7：成片朝向按渠道口径挑（横版/竖版不再由字典序决定）
# --------------------------------------------------------------------------- #

def test_bilibili_gets_landscape_video_without_channel_hint(tmp_path):
    """B 站拿横版 —— 这条是 2026-09-19 竖版投稿事故的直接回归。

    事故：`_pick_media` 原来是 `sorted(glob("*.mp4"))[0]`，而
    `"video-vertical.mp4" < "video.mp4"`（`-`0x2D < `.`0x2E），于是**所有渠道**都投了竖版，
    B 站那条投稿是 1080×1920。B 站自己的口径（channels/bilibili.py 的 manual steps）是横版 16:9。
    """
    run_dir = _run_tree(tmp_path, variants={"zhihu-analyst.md": ZHIHU_MD},
                        videos=("video.mp4", "video-vertical.mp4"))

    bili = _collect(run_dir, "bilibili")

    assert bili.video is not None and bili.video.name == "video.mp4"


def test_xiaohongshu_still_gets_vertical_video(tmp_path):
    """小红书是竖版平台：修 B 站不能把小红书从竖版带跑（别把原来的偶然行为改坏）。"""
    run_dir = _run_tree(tmp_path, variants={"xhs.md": XHS_MD},
                        videos=("video.mp4", "video-vertical.mp4"))

    xhs = _collect(run_dir, "xiaohongshu")

    assert xhs.video is not None and xhs.video.name == "video-vertical.mp4"
    # 别名 xhs 走同一个渠道类，口径必须一致
    assert _collect(run_dir, "xhs").video.name == "video-vertical.mp4"


def test_falls_back_to_the_only_video_that_exists(tmp_path):
    """只有竖版时，B 站拿它而不是 None —— 宁可用现有成片并如实记名，也不要静默没视频。"""
    run_dir = _run_tree(tmp_path, variants={"zhihu-analyst.md": ZHIHU_MD},
                        videos=("video-vertical.mp4",))

    bili = _collect(run_dir, "bilibili")

    assert bili.video is not None and bili.video.name == "video-vertical.mp4"


def test_unknown_channel_defaults_to_landscape(tmp_path):
    """未知渠道（注册表里没有）按横版母版处理，不抛错、不静默变成竖版。"""
    run_dir = _run_tree(tmp_path, variants={"zhihu-analyst.md": ZHIHU_MD},
                        videos=("video.mp4", "video-vertical.mp4"))

    assert _collect(run_dir, "nope").video.name == "video.mp4"


def test_orientation_is_channel_class_metadata(tmp_path):
    """朝向是渠道的类级口径，且别名解析到同一个答案。"""
    from app.channels import registry

    assert registry.orientation_of("bilibili") == "landscape"
    assert registry.orientation_of("xiaohongshu") == "portrait"
    assert registry.orientation_of("xhs") == "portrait"
    assert registry.orientation_of("nope") == "landscape"       # 未知按母版
    assert registry.class_of("bilibili").__name__ == "BilibiliChannel"
    assert registry.class_of("nope") is None
