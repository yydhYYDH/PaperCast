"""app/modules/video.py 的纯文本工具（无 ffmpeg / 无 TTS / 无网络）。"""

from __future__ import annotations

import pytest

from app.modules import generate, video


# --------------------------------------------------------------------------- #
# clean_speakable
# --------------------------------------------------------------------------- #

def test_clean_speakable_strips_markdown_and_formulas():
    out = video.clean_speakable("## 标题 **粗体** $x^2$ \\frac{1}{2} （见图）  多余   空格 _斜体_")
    for token in ["#", "*", "_", "$", "\\", "（见图）"]:
        assert token not in out
    assert "标题" in out and "粗体" in out and "斜体" in out
    assert "  " not in out


def test_clean_speakable_keeps_numbers_and_cjk():
    assert video.clean_speakable("结果提升了 12.5%，共 3 组实验") == "结果提升了 12.5%，共 3 组实验"


def test_clean_speakable_handles_empty_and_whitespace():
    assert video.clean_speakable("") == ""
    assert video.clean_speakable(None) == ""
    assert video.clean_speakable("   ·-—:：  ") == ""


def test_clean_speakable_strips_leading_and_trailing_separators_only():
    assert video.clean_speakable("— 正文内容 —") == "正文内容"


# --------------------------------------------------------------------------- #
# split_sentences
# --------------------------------------------------------------------------- #

def test_split_sentences_keeps_delimiters_and_drops_blanks():
    assert video.split_sentences("第一句。第二句！第三句？第四句；第五句") == [
        "第一句。", "第二句！", "第三句？", "第四句；", "第五句",
    ]


def test_split_sentences_handles_ascii_and_empty():
    # 分隔符集是「。！？!?；;」：ASCII 的 ! ? 认，句点 . 刻意不认（中文稿为主，英文缩写不该被切断）
    assert video.split_sentences("A. B? C!") == ["A. B?", " C!"]
    assert video.split_sentences("One sentence. Two sentences.") == ["One sentence. Two sentences."]
    assert video.split_sentences("") == []
    assert video.split_sentences(None) == []
    assert video.split_sentences("   ") == []


# --------------------------------------------------------------------------- #
# untraceable_numbers：数字回溯口径
# --------------------------------------------------------------------------- #

def test_untraceable_flags_numbers_absent_from_haystack():
    assert video.untraceable_numbers("提升了 57.18%", "") == ["57.18%"]


def test_untraceable_accepts_percent_and_space_variants():
    flat = video._flat("提升 57.18%")
    assert video.untraceable_numbers("提升了 57.18 %", flat) == []
    assert video.untraceable_numbers("提升了 57.18%", flat) == []
    assert video.untraceable_numbers("提升了 57.18", flat) == []      # 百分比符号可省


def test_untraceable_accepts_chinese_percent_expression():
    flat = video._flat("57.18%")
    assert video.untraceable_numbers("提升了百分之五十七点一八", flat) == []
    assert video.untraceable_numbers("提升了百分之五十七点一八", video._flat("")) == ["百分之五十七点一八"]


def test_untraceable_accepts_chinese_magnitude_expression():
    assert video.untraceable_numbers("参数量 三亿", video._flat("3亿")) == []
    assert video.untraceable_numbers("参数量 三亿", video._flat("300000000")) == ["三亿"]


def test_untraceable_ignores_loose_chinese_ordinals():
    """"宁可不杀"：没有单位的中文数字不做强校验，避免误杀「三点结论」这类表达。"""
    assert video.untraceable_numbers("一共五十七个数据集", video._flat("")) == []


def test_untraceable_flags_arabic_when_absent():
    bad = video.untraceable_numbers("涨了 12.5% 和 3 倍", video._flat("12.5%"))
    assert "3" in bad and "12.5%" not in bad


def test_numbers_in_matches_generate_module():
    # video 复用 generate 的抽取规则，两处不许漂移
    text = "57.18% 与 3 组"
    assert video.numbers_in(text) == generate.numbers_in(text)


# --------------------------------------------------------------------------- #
# drop_untraceable：句子级丢弃
# --------------------------------------------------------------------------- #

def test_drop_untraceable_removes_only_offending_sentences():
    drops: list[tuple[str, list[str]]] = []
    out = video.drop_untraceable("第一句没问题。第二句涨了 99.9%。第三句也稳。", video._flat(""), lambda s, b: drops.append((s, b)))
    assert out == "第一句没问题。第三句也稳。"
    assert drops == [("第二句涨了 99.9%。", ["99.9%"])] or drops[0][1] == ["99.9%"]


def test_drop_untraceable_keeps_everything_when_haystack_covers_it():
    hay = video._flat("57.18% 3 亿")
    out = video.drop_untraceable("提升了 57.18%。参数量 3 亿。", hay, lambda s, b: pytest.fail("不该丢句"))
    assert out == "提升了 57.18%。参数量 3 亿。"


# --------------------------------------------------------------------------- #
# 其余小工具
# --------------------------------------------------------------------------- #

def test_flat_removes_spaces_and_commas():
    assert video._flat(" 1, 2 ，3 ") == "123"


@pytest.mark.parametrize("sec,expected", [(0, "00:00"), (59.9, "00:59"), (75.4, "01:15"), (-3, "00:00")])
def test_fmt_hms(sec, expected):
    assert video._fmt_hms(sec) == expected


def test_cn_value_parses_chinese_numbers():
    assert video._cn_value("五十七点一八") == pytest.approx(57.18)
    assert video._cn_value("三") == 3
    assert video._cn_value("三亿") == 300000000
    assert video._cn_value("不是数字") is None


def test_num_str_trims_trailing_zeros():
    assert video._num_str(57.0) == "57"
    assert video._num_str(57.18) == "57.18"
