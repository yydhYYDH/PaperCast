"""app/styles.py：平台 × 人格身份层（纯函数，无外部依赖）。"""

from __future__ import annotations

import pytest

from app import styles


# --------------------------------------------------------------------------- #
# parse_variant / variant_id / variant_label
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("xhs-author", ("xhs", "independent")),        # 退役 id：现落到第三方独立视角
        ("zhihu-analyst", ("zhihu", "analyst")),
        ("bilibili-peer", ("bilibili", "peer")),
        ("en-newsflash", ("en", "newsflash")),
        ("  XHS-Reviewer  ", ("xhs", "reviewer")),      # 大小写与空白都容错
        ("xhs", ("xhs", styles.DEFAULT_VOICE)),         # 旧 id：只写平台 → 默认人格
        ("xhs-academic", ("xhs", "independent")),       # 历史 id
        ("xhs-media", ("xhs", "newsflash")),
        ("zhihu-academic", ("zhihu", "independent")),
        ("bilibili-academic", ("bilibili", "independent")),
        ("en", ("en", styles.DEFAULT_VOICE)),           # 只写平台名也认
    ],
)
def test_parse_variant_accepts_known_ids(raw, expected):
    assert styles.parse_variant(raw) == expected


def test_retired_author_voice_falls_to_third_party():
    # 2026-09-19 用户要求：不要「作者自述」。旧写法仍能解析（老配置不静默丢变体），
    # 但一律落到第三方独立视角，不再冒充论文作者。
    assert "author" not in styles.VOICES
    assert styles.RETIRED_VOICES == {"author": "independent"}
    assert styles.parse_variant("xhs-author") == ("xhs", "independent")
    assert styles.parse_variant("en-author") == ("en", "independent")


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        None,
        "wechat",                 # 已下线的平台：如实解析不出，不悄悄生成
        "wechat-academic",
        "wechat-media",
        "xhs-unknownvoice",       # 平台认识、人格不认识
        "nosuchplatform-author",
        "xhs-author-extra",       # 三段式不是合法 id
    ],
)
def test_parse_variant_rejects_unknown(raw):
    assert styles.parse_variant(raw) is None


def test_variant_id_round_trips_with_parse_variant():
    for pid in styles.PLATFORMS:
        for vid in styles.VOICES:
            v = styles.variant_id(pid, vid)
            assert v == f"{pid}-{vid}"
            assert styles.parse_variant(v) == (pid, vid)


def test_variant_label_uses_spec_labels():
    assert styles.variant_label("xhs", "independent") == "小红书 × 第三方独立视角"
    assert styles.variant_label("en", "analyst") == "英文传播（X / LinkedIn） × 技术解读"


# --------------------------------------------------------------------------- #
# normalize_variants
# --------------------------------------------------------------------------- #

def test_normalize_empty_falls_back_to_default():
    assert styles.normalize_variants(None) == [(styles.DEFAULT_PLATFORM, styles.DEFAULT_VOICE)]
    assert styles.normalize_variants([]) == [(styles.DEFAULT_PLATFORM, styles.DEFAULT_VOICE)]
    assert styles.normalize_variants(["", "wechat", "nope"]) == [
        (styles.DEFAULT_PLATFORM, styles.DEFAULT_VOICE)
    ]


def test_normalize_dedupes_legacy_and_new_ids():
    # xhs-author / xhs / xhs-academic 都归一到 (xhs, independent)，只留一份
    assert styles.normalize_variants(["xhs-author", "xhs", "xhs-academic"]) == [("xhs", "independent")]


def test_normalize_caps_at_max_variants():
    asked = ["xhs-author", "zhihu-analyst", "bilibili-peer", "en-newsflash", "xhs-peer", "zhihu-reviewer"]
    out = styles.normalize_variants(asked)
    assert len(out) == styles.MAX_VARIANTS == 4
    # 保序：保住前 MAX_VARIANTS 个解析结果
    assert out == [("xhs", "independent"), ("zhihu", "analyst"), ("bilibili", "peer"), ("en", "newsflash")]


def test_normalize_respects_custom_limit():
    assert styles.normalize_variants(["xhs-author", "zhihu-analyst"], limit=1) == [("xhs", "independent")]


def test_max_variants_is_a_sane_budget():
    # 每个变体一次 LLM 调用，上限不能无限大（也不能为 0，否则空配置没法跑）
    assert 1 <= styles.MAX_VARIANTS <= 8


# --------------------------------------------------------------------------- #
# 长度口径：中文按 CJK 字数，英文按词数
# --------------------------------------------------------------------------- #

def test_text_len_cjk_vs_words():
    text = "中文四个字 hello world"
    assert styles.text_len(text, "cjk") == 5          # 只数 CJK（中文四个字 = 5 个汉字）
    assert styles.text_len(text, "words") == 2        # 只数英文词
    assert styles.text_len(text) == styles.text_len(text, "cjk")   # 缺省口径 = cjk


def _en_thread_md(words: int) -> str:
    return "# An English thread\n\n" + " ".join(f"word{i}" for i in range(words)) + "\n\n## Tags\n- #LLM\n- #AI\n- #ML\n"


def test_en_platform_counts_words_not_cjk():
    """新口径的核心：纯英文内容在 cjk 口径下会被算成 0 字，长度校验会整体误判。"""
    spec = styles.PLATFORMS["en"]
    assert spec.unit == "words"
    md = _en_thread_md(400)

    checks = dict((label, state) for label, state, _ in styles.validate_markdown(spec, md))
    assert checks["正文长度"] == "pass"
    detail = [d for l, _, d in styles.validate_markdown(spec, md) if l == "正文长度"][0]
    assert "词" in detail and "字（" not in detail

    # 同一篇内容按中文口径只有 0 字 → 落在 320-850 之外，会误报 fail
    assert styles.cjk_len(md) < spec.body_min


def test_en_platform_too_long_fails_on_word_count():
    spec = styles.PLATFORMS["en"]
    checks = dict((label, state) for label, state, _ in styles.validate_markdown(spec, _en_thread_md(900)))
    assert checks["正文长度"] == "fail"


def test_zh_cjk_platform_still_counts_cjk():
    md = "# 标题\n\n" + "中" * 2100 + "\n\n## 话题标签\n- #甲\n- #乙\n- #丙\n"
    checks = dict((label, state) for label, state, _ in styles.validate_markdown(styles.PLATFORMS["zhihu"], md))
    assert checks["正文长度"] == "pass"
    detail = [d for l, _, d in styles.validate_markdown(styles.PLATFORMS["zhihu"], md) if l == "正文长度"][0]
    assert "2109 字" in detail


def test_title_weight_counts_cjk_as_two():
    assert styles.title_weight("ab") == 2
    assert styles.title_weight("中文") == 4
    assert styles.title_weight("中a") == 3


# --------------------------------------------------------------------------- #
# _md_tags / validate_markdown
# --------------------------------------------------------------------------- #

def test_md_tags_reads_chinese_section():
    assert styles._md_tags("## 标签\n- #机器学习\n- #大模型\n") == ["机器学习", "大模型"]


def test_md_tags_reads_english_section():
    """英文平台写的是 ## Tags —— 只认中文小节会让英文变体的标签数永远判 0。"""
    assert styles._md_tags("## Tags\n- #MachineLearning\n- #LLM\n") == ["MachineLearning", "LLM"]


@pytest.mark.parametrize("heading", ["## 话题标签", "### 标签", "## tags", "## Hashtags"])
def test_md_tags_accepts_section_aliases(heading):
    assert styles._md_tags(heading + "\n- #甲\n") == ["甲"]


def test_md_tags_falls_back_to_space_separated_list():
    assert styles._md_tags("## 标签\n标签1 标签2 标签3\n") == ["标签1", "标签2", "标签3"]


def test_md_tags_empty_when_absent():
    assert styles._md_tags("没有标签小节\n\n# 标题\n") == []
    assert styles._md_tags("") == []


def test_en_tags_section_makes_tag_check_pass():
    checks = dict((label, state) for label, state, _ in styles.validate_markdown(styles.PLATFORMS["en"], _en_thread_md(340)))
    assert checks["标签数量"] == "pass"


def test_en_missing_tags_fails_tag_check():
    md = "# Hook\n\n" + " ".join(["word"] * 340) + "\n"
    checks = dict((label, state) for label, state, _ in styles.validate_markdown(styles.PLATFORMS["en"], md))
    assert checks["标签数量"] == "fail"


def test_validate_markdown_flags_formula_only_on_platforms_without_formula():
    md_with_formula = "# 标题\n\n公式 $x^2$ 出现在这里。\n\n## 话题标签\n- #甲\n- #乙\n- #丙\n"
    zhihu = dict((label, state) for label, state, _ in styles.validate_markdown(styles.PLATFORMS["zhihu"], md_with_formula))
    assert zhihu["公式策略"] == "pass"          # 知乎允许 KaTeX
    xhs = dict((label, state) for label, state, _ in styles.validate_markdown(styles.PLATFORMS["xhs"], md_with_formula))
    assert xhs["无公式"] == "fail"


def test_validate_markdown_reports_missing_title():
    en_checks = styles.validate_markdown(styles.PLATFORMS["en"], "没有标题\n")
    assert ("标题", "fail", "缺少一级标题") in en_checks


def test_validate_markdown_title_too_long_fails():
    long_title = "# " + "字" * 60 + "\n\n" + "中" * 2100 + "\n"
    checks = dict((label, state) for label, state, _ in styles.validate_markdown(styles.PLATFORMS["zhihu"], long_title))
    assert checks["标题"] == "fail"


def test_platform_menus_expose_every_platform_and_voice():
    assert set(p["id"] for p in styles.platform_menu()) == set(styles.PLATFORMS)
    assert set(v["id"] for v in styles.voice_menu()) == set(styles.VOICES)
    # 菜单不泄露提示词正文
    assert all("persona" not in v for v in styles.voice_menu())


# --------------------------------------------------------------------------- #
# 公式判定：$...$ 的护栏（英文里的金额不是公式）
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "text",
    [
        "成本是 $0.001，另一处 $0.05。",            # 两个金额凑成一对，朴素的 $[^$]+$ 会误判
        "PresentAgent 只要 $0.001. 人工要 $62K token.",  # 跨普通句子的两个 $
        "价格 $1,200 与 $42%。",
        "没有货币符号也没有公式。",
    ],
)
def test_money_is_not_a_formula(text):
    assert styles.find_formula(text) is None


# 反斜杠用 chr(92) 拼，避免测试文件里的转义序列被写坏（"\l" 不是合法转义，会被吃掉）
BS = chr(92)


@pytest.mark.parametrize(
    "text",
    [
        "$x^2 + y^2$",
        "$O(n) " + BS + "log n$",                    # 反斜杠命令 + 空格，仍应算公式
        "$" + BS + "alpha$ 与 $" + BS + "beta$",
        BS + "frac{a}{b}",
        BS + "begin{aligned}",
        "下标 $x_i$",
    ],
)
def test_real_formula_still_detected(text):
    assert styles.find_formula(text) is not None


def test_en_platform_with_money_passes_no_formula_check():
    """加英文平台时踩到的误报：成本数字 $0.001 被当成行内公式，en 的「无公式」判 fail。"""
    md = "# A hook\n\n" + " ".join(["word"] * 340) + " cost $0.001 per clip.\n\n## Tags\n- #LLM\n- #AI\n- #ML\n"
    checks = dict((label, state) for label, state, _ in styles.validate_markdown(styles.PLATFORMS["en"], md))
    assert checks["无公式"] == "pass"
    md_bad = md.replace("cost $0.001 per clip.", "公式 $x^2$ 仍在。")
    checks_bad = dict((label, state) for label, state, _ in styles.validate_markdown(styles.PLATFORMS["en"], md_bad))
    assert checks_bad["无公式"] == "fail"



# --------------------------------------------------------------------------- #
# style_menu：前端风格页直接展示的组合清单
# --------------------------------------------------------------------------- #

def test_style_menu_covers_every_platform_voice_pair():
    menu = styles.style_menu()
    assert len(menu) == len(styles.PLATFORMS) * len(styles.VOICES)
    assert [s["variant"] for s in menu] == sorted(
        {s["variant"] for s in menu}, key=[s["variant"] for s in menu].index
    )  # id 唯一（顺序按平台→人格遍历）
    for s in menu:
        assert s["variant"] == styles.variant_id(s["platform"], s["voice"])
        assert styles.parse_variant(s["variant"]) == (s["platform"], s["voice"])
        assert s["platformLabel"] == styles.PLATFORMS[s["platform"]].label


def test_style_menu_carries_the_ui_names_and_constraints():
    """风格页要显示「小红书 · 专业科普」：口语名与一句话手感必须来自这里，前端不自己编。"""
    for s in styles.style_menu():
        assert s["short"], f"{s['variant']} 缺口语名（VoiceSpec.short）"
        assert s["hint"], f"{s['variant']} 缺一句话说明（VoiceSpec.hint）"
    xhs = [s for s in styles.style_menu() if s["variant"] == "xhs-newsflash"][0]
    assert xhs["short"] == "震惊流"
    assert xhs["platformLabel"] == "小红书"
    assert xhs["bodyMax"] == 1000 and xhs["allowFormula"] is False and xhs["cards"] is True
    en = [s for s in styles.style_menu() if s["variant"] == "en-analyst"][0]
    assert en["unit"] == "words"


def test_voice_menu_exposes_short_names():
    menu = {v["id"]: v for v in styles.voice_menu()}
    assert menu["independent"]["short"] == "专业科普"
    assert menu["reviewer"]["short"] == "审稿视角"
    # 规范名（label）与锚点仍在，日志和文档要用
    assert menu["newsflash"]["label"] == "科技快讯" and menu["newsflash"]["anchor"] == "新智元式"

