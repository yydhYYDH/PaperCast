"""cards_deck：小红书组图 provider 的契约测试（离线、不联网、秒级）。

锁的是「接进流水线」这条链上最容易回退的几件事：

1. **AGPL 边界**：技能的模板/CSS 只在运行时从用户级安装目录读，**不进仓库**；
   技能没装时 `build()` 必须 fail-closed 抛错（由 stage 记一条 run 跳过，而不是把阶段判失败）。
2. **不截字**：标题排不下时先按标点砍从句、再整档降字号，但**绝不能截出「罕见病诊断智…」**
   —— 上一版就是这么干的，被真跑看出来了。
3. **kicker 去重**：`Nature · VOL 651 · 2026` + `Nature` 拼在一起会读成两个 Nature。
4. **行均分撑满页**：模板的 `.ledger` 会把 3 条要点挤在上半页（技能自己的 R5 量的是"元素占位"
   不是"墨迹"，抓不到），所以覆盖层里 `.ledger{flex:1}` + 行高下限 118px（M08 配方）。
5. **自检结果要能解析**：`validate-social-deck.mjs` 的输出是闸门口径，解析错了会把 fail 当 pass。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from app.modules import cards_deck as cd

SKILL = "/home/yydh/.agents/skills/guizang-social-card-skill"
has_skill = pytest.mark.skipif(not cd.available(), reason="guizang 技能未安装（./ops/install_skills.sh）")


@pytest.fixture()
def spec() -> dict:
    return {
        "title": "DeepRare：可追溯推理的罕见病诊断智能体系统",
        "kicker": "Nature · Vol 651 · 2026",
        "subtitle": "多智能体系统在2,919种罕见病上Recall@1达57.18%，领先次优23.79%",
        "venue": "Nature",
        "chips": ["罕见病诊断", "多智能体系统", "可追溯推理"],
        "teaser": {"file": "fig-1.png"},
        "columns": [
            [{"kind": "panel", "title": "问题", "items": ["罕见病影响超过3亿人", "平均诊断耗时5年以上"]}],
            [{"kind": "figure", "file": "fig-2.png", "number": "2", "caption": "七个公开注册库上的召回对比"}],
        ],
    }


@pytest.fixture()
def cover() -> dict:
    return {"title": "可追溯推理的罕见病诊断智能体", "subtitle": "Nature 651, 775–783",
            "kicker": "Nature · Vol 651 · 2026", "teaser": {"file": "fig-1.png"}}


@pytest.fixture()
def digest() -> dict:
    return {"limitations": ["决策支持而非替代医生", "证据链仍需人工核对", "队列集中在亚洲"]}


@pytest.fixture()
def figures(tmp_path: Path) -> Path:
    d = tmp_path / "images"
    d.mkdir()
    for n in ("fig-1.png", "fig-2.png"):
        (d / n).write_bytes(b"\x89PNG\r\n\x1a\n" + n.encode())   # 内容无所谓：只测装配与拷贝
    return d


# ---------------------------------------------------------------- 文本工具

def test_cover_title_is_never_cut_mid_word():
    """13 字标题：要么一行，要么整档降字号 —— 不许出现省略号。"""
    size, lines = cd.fit_title("可追溯推理的罕见病诊断智能体", "display")
    assert len(lines) <= 2
    assert "…" not in "".join(lines)
    assert "".join(lines) == "可追溯推理的罕见病诊断智能体"
    assert size in cd.SIZE_LADDER["display"]


def test_long_title_trimmed_at_punctuation_not_ellipsis():
    text = "九个数据集上的跨数据集召回对比结果，以及加入基因数据之后的多模态性能提升幅度"
    size, lines = cd.fit_title(text, "xl")
    assert len(lines) <= 2
    assert "…" not in "".join(lines)
    # 砍从句：留下的必须是原文前缀，且结束在标点处或完整
    joined = "".join(lines)
    assert text.startswith(joined.rstrip("，,、；;。：: "))
    assert size == cd.SIZE_LADDER["xl"][0]      # 先保字号，砍内容


def test_unbreakable_overlong_title_degrades_deterministically():
    """无标点可砍的超长标题：降到最小字号并**如实超行** —— 由 stage 的减内容重排兜住，
    不在这里偷偷截字（那种"看起来通过、内容已被毁"的行为正是要避免的）。"""
    text = "罕见病" * 20
    size, lines = cd.fit_title(text, "xl")
    assert size == cd.SIZE_LADDER["xl"][-1]
    assert "".join(lines) == text and "…" not in "".join(lines)


def test_latin_cover_title_breaks_at_hyphen_not_mid_word():
    """「西文模型名：中文副标题」必须断在连字符后，不能把模型名拆两半。

    2026-09-26 实测（run_e24920f4d088 封面）：逐字贪心断行 + ASCII 按 0.55em 估算，
    预测「SpeakerMem-R」/「1：双轨记忆」两行就收工，实际浏览器里「SpeakerMem-R」是
    999px > 可用 904px，于是被再折一次 → 三行、落单一个「R」（技能校验器 R6 WARN，
    而 WARN 不拦发布，坏图就这么发出去了）。

    封面顶档现在是 100px（原 124 → 112 → 100，两轮收小：先修行数，再给副标题腾行数）。
    """
    size, lines = cd.fit_title("SpeakerMem-R1：双轨记忆", "display")
    assert size == cd.SIZE_LADDER["display"][0] == 100
    assert lines == ["SpeakerMem-", "R1：双轨记忆"]
    # 每一行都必须真的装得下 —— 只看行数会漏掉「单词本身超宽」
    per_line = cd.AVAIL_PX / size
    assert all(cd.units(l) <= per_line + 1e-9 for l in lines)


def test_cover_title_never_starts_a_line_with_cjk_punctuation():
    """避头：标点不另起一行（但只在仍能装下时才留在上一行 —— 溢出更难看）。"""
    _size, lines = cd.fit_title("双轨记忆：可追溯的逐字与结构化状态", "xl")
    assert lines
    for line in lines[1:]:
        assert line[0] not in cd.NO_LINE_START


def test_ascii_em_is_calibrated_not_guessed():
    """0.55 会把西文标题系统性低估约 18%（实测 0.672em/字，含 .04em 字距），
    低估的代价是「模型说装得下、浏览器说装不下」。守住这个下限。"""
    assert cd.ASCII_EM >= 0.63


def test_letter_spacing_is_counted_in_the_width_model():
    """纯中文标题同样会溢出 —— 这次不是 ASCII 宽度，是 letter-spacing。

    2026-09-26 实测（run_f308d04cf07a 第 2 页）：88px 下 10 个汉字字形 880px「刚好装下」，
    但 .h-xl 有 .03em 字距，10 字就是 26.5px → 实际 906px > 可用 904px，浏览器再折一次
    → 三行（R6 WARN）。字距是每字累加的，字符越多越致命，不能当常数忽略。
    """
    text = "注意力修补：结构比内容更关键"
    size, lines = cd.fit_title(text, "xl")
    track = cd.TRACK_EM["xl"]
    assert len(lines) <= 2
    for line in lines:
        assert cd.line_units(line, track) * size <= cd.AVAIL_PX + 1e-9, f"这行会溢出：{line!r}"


# ---------------------------------------------------------------- 行内强调

def test_inline_renders_bold_and_highlight():
    out = cd.inline("提升 ==12.4 个== 且 **超过**基线")
    assert "<mark class=\"hl\">12.4 个</mark>" in out
    assert "<strong>超过</strong>" in out
    # 记号本身不该漏到页面上
    assert "==" not in out and "**" not in out


def test_inline_cannot_inject_html():
    """模型给的文本永远换不成可执行 HTML：先转义、再只替换两个记号。"""
    banned = ("<img", "<script", "<b>", "<svg", "<iframe", "<style")
    for evil in ('<img src=x onerror=alert(1)>', '<script>alert(1)</script>',
                 '**<b>bold</b>**', '=="><svg onload=alert(1)>=='):
        out = cd.inline(evil)
        assert not any(t in out for t in banned), f"漏出了标签：{out!r}"
        # 只允许我们自己那两种强调标签
        allowed = {"<strong>", "</strong>", '<mark class="hl">', "</mark>"}
        for tag in re.findall(r"<[^>]+>", out):
            assert tag in allowed, f"出现了未经允许的标签：{tag!r}"


def test_emphasis_markers_do_not_consume_width():
    """`**`/`==` 不占像素 —— 量宽度时必须剥掉，否则会误判成超宽而白降字号。"""
    plain = "关键数字 62.33% 在这里"
    marked = "==关键==数字 **62.33%** 在这里"
    assert cd.units(marked) == cd.units(plain)
    assert cd.line_units(marked, 0.03) == cd.line_units(plain, 0.03)


def test_emphasis_markers_survive_line_wrapping():
    """短强调区间（≤EMPH_ATOM_MAX）必须整体换行、不丢记号。"""
    marked = "**" + "甲乙丙丁戊己庚辛壬癸" * 2 + "**"
    assert cd.plain(marked) and len(cd.plain(marked)) <= cd.EMPH_ATOM_MAX
    lines = cd._wrap_no_cut(marked, cd.AVAIL_PX / 56, cd.TRACK_EM["md"])
    assert "".join(lines).count("**") == 2
    assert "<strong>" in cd.inline("".join(lines))


def test_overlong_emphasis_span_never_leaks_literal_markers():
    """整段加粗（>EMPH_ATOM_MAX）断行后开合不配对 —— 这时**丢掉强调、但绝不能印出 `**`**。"""
    marked = "**" + "甲乙丙丁戊己庚辛壬癸" * 8 + "**"
    assert len(cd.plain(marked)) > cd.EMPH_ATOM_MAX
    lines = cd._wrap_no_cut(marked, cd.AVAIL_PX / 56, cd.TRACK_EM["md"])
    assert len(lines) > 1, "超长强调区间仍应可断行，否则会溢出画布"
    for line in lines:
        out = cd.inline(line)
        assert "**" not in out, f"字面记号漏到页面上了：{out!r}"


def test_emphasis_span_is_never_split_across_lines():
    """强调区间必须整体换行 —— 踩过的坑：`==62.33%==` 被断成「==62」+「.33%==」，
    而 inline() 是逐行跑的，`==` 开合不在同一行就匹配不上，页面上直接印出字面的
    `==62 .33%==`（2026-09-26 封面实测）。"""
    text = "公开榜取 ==62.33%==。" * 4
    for size in (28, 24):
        lines = cd._wrap_no_cut(text, cd.AVAIL_PX / size, 0.0)
        for line in lines:
            assert line.count("==") % 2 == 0, f"强调标记被拆开了：{line!r}"
        # 每行单独 inline 之后，字面的记号必须一个都不剩
        for line in lines:
            out = cd.inline(line)
            assert "==" not in out, f"字面记号漏到页面上了：{out!r}"
        assert cd.inline("<br>".join(lines)).count("<mark") == 4


def test_bold_span_is_never_split_across_lines():
    text = "提升 **12.4 个百分点**，超过基线。" * 4
    for size in (28, 24):
        for line in cd._wrap_no_cut(text, cd.AVAIL_PX / size, 0.0):
            assert line.count("**") % 2 == 0, f"加粗记号被拆开了：{line!r}"


# ---------------------------------------------------------------- 标题质量

@pytest.mark.parametrize("bad", ["两个瓶颈", "三个提升", "问题", "方法", "结果", "两条结论", "5个问题", ""])
def test_label_like_titles_are_detected(bad):
    assert cd.label_like(bad)


@pytest.mark.parametrize("good", ["多人对话记忆系统普遍丢掉人物关系", "通用 LLM 记不住谁说了什么",
                                  "一次记两个想法，不串味", "同一条消息要写进两条记忆轨"])
def test_claim_titles_pass_through(good):
    assert not cd.label_like(good)


def test_label_title_is_replaced_by_first_item():
    """「两个瓶颈」这种标题等于没说话 —— 顶上一个小标签（实测切成 8-9 字，一行放得下）。"""
    items = ["消息归因与关系理解：谁说了什么、每条陈述涉及谁", "状态重建：从分散在成员与时间的线索恢复状态"]
    out = cd.informative_title("两个瓶颈", items)
    assert out == "消息归因与关系理解", out
    assert "…" not in out, "标题永远不该被截断"
    # 本来就是判断句的标题不许被改
    assert cd.informative_title("记不住谁说了什么", items) == "记不住谁说了什么"


def test_borrowed_label_is_stripped_from_the_item():
    """标题已经写了「消息归因与关系理解」，要点里就不该再说一遍 —— 要点只留解释。"""
    assert cd._strip_head("消息归因与关系理解：谁说了什么、每条陈述涉及谁",
                          "消息归因与关系理解") == "谁说了什么、每条陈述涉及谁"
    # 碰巧开头相近但并非同一标签时，不许误伤
    assert cd._strip_head("消息归因的三个层次", "消息归因与关系理解") == "消息归因的三个层次"
    assert cd._strip_head("状态重建：从线索恢复", "状态重建") == "从线索恢复"


# ---------------------------------------------------------------- 第三人称自称

def test_method_name_extracted_from_title():
    assert cd.method_name("SpeakerMem-R1：双轨记忆") == "SpeakerMem-R1"
    assert cd.method_name("Transformer 一次装两个念头") == "Transformer"
    assert cd.method_name("双轨记忆的写入与查询") == "双轨记忆"


@pytest.mark.parametrize("bad,good", [
    ("本文提出一种双轨记忆系统", "双轨记忆提出一种双轨记忆系统"),
    ("该论文用双轨存储解决归因", "双轨记忆用双轨存储解决归因"),
    ("作者认为线性是架构自带的", "双轨记忆认为线性是架构自带的"),
])
def test_self_reference_replaced_by_method_name(bad, good):
    out, hit = cd.de_selfref(bad, "双轨记忆")
    assert hit is True
    assert out == good


def test_self_reference_untouched_when_absent():
    text = "三个多人基准全部超过主流框架最好结果，公开榜 62.33%。"
    assert cd.de_selfref(text, "SpeakerMem-R1") == (text, False)


def test_self_reference_without_method_name_only_drops_word():
    """取不到方法名时只删词，不硬塞主语（残缺也比留着「本文」强，提示词会给出方法名）。"""
    out, hit = cd.de_selfref("本文提出一种双轨记忆系统", "")
    assert hit is True
    assert "本文" not in out and out == "提出一种双轨记忆系统"


def test_cover_figure_band_is_shorter_than_before():
    """主图 16:10 → 16:9：给副标题腾 57px。16:10 在 904px 宽下占 565px，
    吃掉内容区一半还多，副标题只剩 1.5 行，装不下「痛点→方法→结果」。"""
    assert cd.COVER_FIG_RATIO == "16x9"
    assert 904 * 9 / 16 < 904 * 10 / 16
    # 16:9 是刻意选的：论文原图实测 1.27–2.18 的比例，21:9 会把 1.4 的架构图压成窄带
    assert cd.COVER_FIG_RATIO != "21x9"


def test_uniform_fit_gives_every_item_the_same_size():
    """收尾页三种长度的限制条目必须同一字号（用户报「最后一页字体大小不统一」）。"""
    lims = [
        "系统假设名册、source/owner 归因与时间识别可靠；别名、成员变动、隐性受众与并行事件仍然困难（论文 Limitations）。",
        "论文明确说明：RL 结果只表明本地可部署的小 Writer 接近大 Writer 参考，不构成跨领域 RL 泛化的证据。",
        "LoCoMo 多跳仍偏弱。",
    ]
    size, blines = cd.uniform_fit(lims, "md", max_lines=3)
    assert size in cd.SIZE_LADDER["md"]
    # 最重要的一条不变量：一条字都不能少（原文丢 Limitations 是最糟的失败）
    for lim, lines in zip(lims, blines):
        assert cd.plain("".join(lines)) == cd.plain(lim), f"这句被截断了：{lim[:20]}"
    # 整页行数不超预算（3 条 × 每条 3 行），否则会顶进页脚
    assert sum(len(x) for x in blines) <= 3 * len(lims)



def test_kicker_parts_dedupe():
    assert cd.dedupe_parts("Nature · Vol 651 · 2026", "Nature", "PaperCast 论文速读") == \
        ["Nature · Vol 651 · 2026", "PaperCast 论文速读"]
    assert cd.dedupe_parts("arXiv", "") == ["arXiv"]
    assert cd.dedupe_parts("", None, "  ") == []


# ---------------------------------------------------------------- 论证顺序


def _panel_titles(spec):
    """只要 panel 页的标题（plan_pages 第 0 页永远是封面，标题可能为空）。"""
    return [p["title"] for p in cd.plan_pages(spec, None, {}) if p["kind"] == "panel"]

def test_blocks_are_sorted_by_declared_role():
    """块序按 role 稳定排序 —— 训练细节不该排在结果之后。

    2026-09-26 实测（run_e24920f4d088）：块序是「难点 → 方法 → 架构图 → 结果 → 训练消融」，
    训练细节排在结果之后，而证明它自己的两张图被丢到最后四张纯图页里 ——
    整组图读下来像「先讲完再补图」，不像一条论证。
    """
    spec = {"columns": [
        {"kind": "panel", "role": "result", "title": "三个基准全部超过最好结果", "items": ["甲"]},
        {"kind": "panel", "role": "problem", "title": "记不住谁说了什么", "items": ["乙"]},
        {"kind": "panel", "role": "detail", "title": "用 RL 训一个小 Writer", "items": ["丙"]},
        {"kind": "panel", "role": "method", "title": "把逐字与结构化分开记", "items": ["丁"]},
    ]}
    assert _panel_titles(spec) == [
        "记不住谁说了什么", "把逐字与结构化分开记", "三个基准全部超过最好结果", "用 RL 训一个小 Writer",
    ]


def test_undeclared_role_inherits_previous_block():
    spec = {"columns": [
        {"kind": "panel", "role": "problem", "title": "归因是最难的一环", "items": ["甲"]},
        {"kind": "panel", "title": "没写 role 的块", "items": ["乙"]},
        {"kind": "panel", "role": "result", "title": "三个基准都超最好结果", "items": ["丙"]},
        {"kind": "panel", "title": "同样没写 role", "items": ["丁"]},
    ]}
    titles = _panel_titles(spec)
    assert titles[:2] == ["归因是最难的一环", "没写 role 的块"]
    assert titles[2] == "三个基准都超最好结果"
    assert titles[3] == "同样没写 role"


def test_spec_without_any_role_is_not_reordered():
    """老 spec 一个 role 都没写 —— 完全不排序，别把已有版面搅乱。"""
    spec = {"columns": [
        {"kind": "panel", "title": "归因是最难的一环", "items": ["甲"]},
        {"kind": "panel", "title": "把逐字与结构化分开记", "items": ["乙"]},
    ]}
    assert _panel_titles(spec) == ["归因是最难的一环", "把逐字与结构化分开记"]


def test_panel_figure_is_attached_right_after_its_panel():
    """证据紧跟论点 —— 以前所有图都堆在最后（实测第 7-10 张是四张连着的纯图页）。"""
    spec = {"columns": [[
        {"kind": "panel", "role": "problem", "title": "多人群聊不是一条消息流",
         "items": ["甲"], "figure": "fig-1.png", "figureCaption": "群聊示意"},
        {"kind": "panel", "role": "method", "title": "双轨分开记", "items": ["乙"], "figure": "fig-2.png"},
    ]]}
    pages = cd.plan_pages(spec, None, {})
    assert [p["kind"] for p in pages] == ["cover", "panel", "figure", "panel", "figure"]
    assert pages[2]["figure"]["file"] == "fig-1.png"
    assert pages[4]["figure"]["file"] == "fig-2.png"
    assert pages[2]["kicker"] == "证据 · fig-1"
    assert pages[2]["title"] == "群聊示意"


def test_anchored_figure_is_not_picked_again_as_extra(tmp_path):
    """panel 认领过的图不能再被当成「补充图」挑一次（否则组图里同一张出现两次）。"""
    for n in ("fig-1.png", "fig-2.png"):
        (tmp_path / n).write_bytes(b"\x89PNG\r\n\x1a\n" + n.encode())
    digest = {"figures": [
        {"id": "fig-1", "source": "fig-1.png", "caption": "Figure 1: A group chat stream"},
        {"id": "fig-2", "source": "fig-2.png", "caption": "Figure 2: Overall architecture"},
    ]}
    extra = cd.pick_figure_pages(digest, tmp_path, exclude={"fig-1.png"}, limit=6)
    assert [Path(e["figure"]["file"]).name for e in extra] == ["fig-2.png"]


def test_unclaimed_figures_are_marked_as_appendix():
    """没被认领的原图 kicker 是「更多证据」—— 补充材料，不是论证的一环。"""
    spec = {"columns": [[{"kind": "panel", "role": "problem", "title": "难点", "items": ["甲"]}]]}
    extra = [{"kicker": "证据 · fig-9", "title": "某图", "title_kind": "md", "title_lines": 3,
              "figure": {"file": "fig-9.png", "number": "9"}}]
    pages = cd.plan_pages(spec, None, {}, extra_figures=extra)
    assert [p["kicker"] for p in pages if p["kind"] == "figure"] == ["更多证据"]


# ---------------------------------------------------------------- 标签前缀

@pytest.mark.parametrize("bad", ["方法：双轨写入 + 查询组合", "结果：三个基准", "问题：x",
                                 "方法：a", "关键结果", "核心结论"])
def test_label_prefix_forms_are_detected(bad):
    assert cd.label_like(bad)


@pytest.mark.parametrize("good", ["方法：双轨记忆解决归因", "问题：记不住谁说了什么",
                                  "结果：三个基准全部超过主流框架最好结果"])
def test_colon_titles_with_a_claim_pass(good):
    assert not cd.label_like(good)


# ---------------------------------------------------------------- 页面计划

def test_plan_pages_order_and_caps(spec, cover, digest):
    pages = cd.plan_pages(spec, cover, digest, max_items=1)
    assert [p["kind"] for p in pages] == ["cover", "panel", "figure", "closing"]
    assert pages[0]["title"].startswith("可追溯")
    assert pages[1]["items"] == ["罕见病影响超过3亿人"]     # max_items=1 生效
    assert pages[2]["figure"]["file"] == "fig-2.png"
    assert pages[3]["items"] == digest["limitations"]


def test_plan_pages_without_cover_falls_back_to_spec(spec, digest):
    pages = cd.plan_pages(spec, None, digest)
    assert pages[0]["kind"] == "cover"
    assert pages[0]["kicker"] == spec["kicker"]
    assert pages[0]["teaser"]["file"] == "fig-1.png"


def test_plan_pages_capped(spec, cover):
    long_spec = {**spec, "columns": [[{"kind": "panel", "title": f"P{i}", "items": ["a"]}] for i in range(30)]}
    assert len(cd.plan_pages(long_spec, cover, {})) <= cd.MAX_PAGES


def test_plan_pages_skips_empty_panel(spec, digest):
    s = {**spec, "columns": [[{"kind": "panel", "title": "空", "items": []}]]}
    assert [p["kind"] for p in cd.plan_pages(s, None, digest)] == ["cover", "closing"]


# ---------------------------------------------------------------- fail-closed

def test_build_without_skill_raises(monkeypatch, tmp_path, spec, cover, digest, figures):
    monkeypatch.setattr(cd, "skill_dir", lambda: None)
    monkeypatch.setenv("GUIZANG_SKILL_DIR", "")
    with pytest.raises(FileNotFoundError) as e:
        cd.build(spec, cover, digest, figures, tmp_path / "cards")
    assert "install_skills" in str(e.value)


def test_enabled_semantics(monkeypatch):
    monkeypatch.setattr(cd, "skill_dir", lambda: None)
    assert cd.enabled("off") is False
    assert cd.enabled("auto") is False          # auto = 没装就不跑
    assert cd.enabled("on") is True             # 强制 on：装了没有都"允许跑"，跑失败由 stage 如实报
    monkeypatch.setattr(cd, "skill_dir", lambda: Path("/tmp/x"))
    assert cd.enabled("auto") is True


# ---------------------------------------------------------------- 装配（用真模板）

def test_build_html_contract(tmp_path, figures, spec, cover, digest):
    tpl = tmp_path / "tpl.html"
    tpl.write_text('<html lang="zh-CN" data-theme="ink-classic">\n</head>\n'
                   '<body><main class="sheet">\n<!-- POSTERS_HERE -->\n</main></body></html>',
                   encoding="utf-8")
    pages = cd.plan_pages(spec, cover, digest)
    out = tmp_path / "cards"
    info = cd.build_html(pages, figures, out, theme="forest-ink", template=tpl, note="测试")
    html = (out / "index.html").read_text(encoding="utf-8")
    assert info["pages"] == len(pages) == html.count('class="poster xhs"')
    assert html.count('<main class="sheet">') == 1 and "POSTERS_HERE" not in html
    assert 'data-theme="forest-ink"' in html
    # 本地覆盖层：中文字体栈 / 图表底色透明 / M08 行高下限，一个都不能少
    assert "--serif-zh: \"Microsoft YaHei\"" in html
    assert ".frame-img.fit-contain { background: transparent; }" in html
    assert "min-height: 118px" in html and ".ledger { flex: 1 1 auto" in html
    # 用到的图才拷
    assert sorted(p.name for p in (out / "assets").glob("*.png")) == ["fig-1.png", "fig-2.png"]


def test_build_html_theme_whitelist(tmp_path, figures, spec, cover, digest):
    tpl = tmp_path / "tpl.html"
    tpl.write_text('<html data-theme="x">\n</head>\n<main class="sheet"></main>', encoding="utf-8")
    out = tmp_path / "cards"
    cd.build_html(cd.plan_pages(spec, cover, digest), figures, out,
                  theme="');</style><script>alert(1)</script>", template=tpl)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "alert(1)" not in html
    assert f'data-theme="{cd.DEFAULT_THEME}"' in html


def test_missing_figure_is_skipped_not_faked(tmp_path, figures, spec, cover, digest):
    s = {**spec, "teaser": {"file": "nope.png"},
         "columns": [[{"kind": "figure", "file": "nope.png", "number": "9", "caption": "缺失"}]]}
    tpl = tmp_path / "tpl.html"
    tpl.write_text('<html data-theme="x"></head><main class="sheet"></main>', encoding="utf-8")
    out = tmp_path / "cards"
    cd.build_html(cd.plan_pages(s, cover, digest), figures, out, template=tpl)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert html.count('class="poster xhs"') == 2      # 封面（无图）+ 判断页；缺图那页不占位
    assert "nope.png" not in html


# ---------------------------------------------------------------- 阶段接线

class _FakeCtx:
    """最小 ctx：只要 log/check/artifact/progress + settings（与 pipeline 的接口一致）。"""

    def __init__(self, mode: str = "auto") -> None:
        self.checks: list[tuple[str, str, str]] = []
        self.artifacts: list[str] = []
        self.logs: list[str] = []

        class _S:
            poster_deck = mode

        self.settings = _S()

    def log(self, level: str, msg: str) -> None:
        self.logs.append(f"{level}:{msg}")

    def check(self, name: str, state: str, detail: str) -> None:
        self.checks.append((name, state, detail))

    def artifact(self, kind: str, label: str, path: str, **kw) -> None:
        self.artifacts.append(path)

    def progress(self, p: float) -> None:
        pass


async def _run_stage_deck(monkeypatch, tmp_path, spec, cover, digest, figures, mode: str):
    from app.modules import poster_stage as ps
    ctx = _FakeCtx(mode)
    await ps._run_deck(ctx, spec, cover, digest, str(figures), tmp_path / "poster")
    return ctx


def test_stage_skips_without_failing_when_skill_missing(monkeypatch, tmp_path, spec, cover, digest, figures):
    """技能没装 → 记一条 run（不是 fail），且一个产物都不登记；渠道画布照常交付。"""
    monkeypatch.setattr(cd, "skill_dir", lambda: None)
    import anyio

    ctx = anyio.run(_run_stage_deck, monkeypatch, tmp_path, spec, cover, digest, figures, "auto")
    assert ctx.artifacts == []
    assert ctx.checks and ctx.checks[0][1] == "run" and "install_skills" in ctx.checks[0][2]


def test_stage_skip_when_disabled_by_config(monkeypatch, tmp_path, spec, cover, digest, figures):
    import anyio

    ctx = anyio.run(_run_stage_deck, monkeypatch, tmp_path, spec, cover, digest, figures, "off")
    assert ctx.artifacts == []
    assert ctx.checks[0][1] == "run" and "off" in ctx.checks[0][2]


# ---------------------------------------------------------------- 自检解析

SAMPLE = """==== validate-social-deck ====
target:   x/index.html
sections: 5  ·  4 clean  ·  1 fails  ·  2 warns
rules:    R1=1  R6=1

[FAIL]  xhs-02  · xhs
  FAIL · R1  overflow 8px (scrollH 1448 > clientH 1440)
         fix: nudge content up
  WARN · R6  .h-xl "标题" renders 3 lines (cap 2 on xhs)
"""


def test_parse_validate_summary_and_details():
    out = cd.parse_validate(SAMPLE)
    assert (out["sections"], out["clean"], out["fails"], out["warns"]) == (5, 4, 1, 2)
    assert out["rules"] == {"R1": 1, "R6": 1}
    assert out["details"][0]["level"] == "FAIL" and out["details"][0]["rule"] == "R1"
    assert out["details"][1]["level"] == "WARN"


def test_parse_validate_on_garbage_is_empty_not_pass():
    out = cd.parse_validate("boom\n")
    assert out["fails"] == 0 and out["sections"] == 0 and out["details"] == []


# ---------------------------------------------------------------- 与技能的真集成

@has_skill
def test_build_against_real_skill_template(tmp_path, figures, spec, cover, digest):
    info = cd.build(spec, cover, digest, figures, tmp_path / "cards", note="测试")
    assert info["ok"] and info["pages"] == 4
    assert (tmp_path / "cards" / "deck.plan.json").is_file()   # 页面计划落盘（可复现）
    assert json.loads((tmp_path / "cards" / "deck.plan.json").read_text(encoding="utf-8"))["theme"]
    html = Path(info["html"]).read_text(encoding="utf-8")
    assert html.count('class="poster xhs"') == 4
    assert "--serif-zh" in html            # 覆盖层在
    assert "Noto Serif SC" in html         # 模板原文还在（我们没改模板，只是运行时读它）


@has_skill
@pytest.mark.skipif(os.environ.get("PAPERCAST_TEST_DECK_RENDER") != "1",
                    reason="真渲染要起 chromium，默认跳过（PAPERCAST_TEST_DECK_RENDER=1 打开）")
def test_render_and_validate_roundtrip(tmp_path, figures, spec, cover, digest):
    out = tmp_path / "cards"
    cd.build(spec, cover, digest, figures, out, note="测试")
    rep = cd.render(out, scale=1)
    assert rep["ok"] and rep["count"] == 4
    assert rep.get("scale") == 1 and rep.get("jpegs") == 4   # 默认 1x + JPEG 侧车
    assert (out / "output" / "xhs-01.jpg").is_file()
    chk = cd.validate(out)
    assert chk["sections"] == 4 and chk["fails"] == 0 and chk["exit"] == 0


# --------------------------------------------------------------------------- #
# JPEG 侧车（不用 chromium：纯 Pillow）
# --------------------------------------------------------------------------- #

def test_to_jpeg_writes_sidecar_and_annotates_frames(tmp_path):
    """PNG 母版旁边落一份 JPEG 侧车，并把 jpeg 路径/体积写回 frame（登记与投递都靠它）。"""
    from PIL import Image

    src = tmp_path / "xhs-01.png"
    Image.new("RGB", (1080, 1440), (24, 24, 32)).save(src)
    frames: list[dict] = [{"id": "xhs-01", "path": str(src)}]
    assert cd._to_jpeg(frames) == 1
    sidecar = tmp_path / "xhs-01.jpg"
    assert sidecar.is_file() and Image.open(sidecar).format == "JPEG"
    assert frames[0]["jpeg"].endswith("xhs-01.jpg") and frames[0]["jpegBytes"] > 0
    # 原 PNG 不能被删（它是可编辑母版）
    assert src.is_file()
    # 文件不在（或不是图）就跳过，不抛异常：转 JPEG 失败不该拖垮整条 poster 阶段
    assert cd._to_jpeg([{"path": str(tmp_path / "nope.png")}]) == 0
    assert cd._to_jpeg([{"id": "x", "path": ""}]) == 0


# ---------------------------------------------------------------- 标题候选的质量门槛

def test_clause_head_does_not_split_inside_brackets():
    """括号内的逗号不是断句点 —— 否则切出「…62.33%（1」这种挂着括号的碎片。"""
    got = cd._clause_head("EverMemBench 公开排行榜取得 62.33%（1,496/2,400），为最新 SOTA 结果")
    # 在**括号外**的那个逗号处断；括号必须配对（坏情况是切出「…62.33%（1」这种半开的）
    assert got == "EverMemBench 公开排行榜取得 62.33%（1,496/2,400）"
    assert got.count("（") == got.count("）")


@pytest.mark.parametrize("bad,why", [
    ("GroupMemBench 47.9%、SocialMemBench 69.2%、EverMemBench 61.9%", "指标清单"),
    ("305 题受控评测", "以数字结尾，像数据项"),
    ("EverMemBench 公开排行榜取得 62.33%（1", "尾巴挂着没关的括号"),
    ("S1 S2", "汉字不足两个，纯西文"),
])
def test_bad_title_candidates_are_rejected(bad, why):
    assert not cd._title_candidate_ok(bad, cd.AVAIL_PX / 88), why


def test_good_title_candidate_is_accepted():
    """这条回归钉的是那个正则陷阱：`[（(]?$` 会在任何字符串末尾匹配空串，
    于是**所有**候选全被否掉、兜底彻底失效（实测全部退回原标签）。"""
    assert cd._title_candidate_ok("消息归因与关系理解", cd.AVAIL_PX / 88)
    assert cd._title_candidate_ok("提出叠加线性假设", cd.AVAIL_PX / 88)


def test_label_title_prefers_claim_over_spec_detail():
    """兜底不能拿实现细节或纯指标清单去当标题 —— 那比「关键结果」这种标签更糟。"""
    metrics = ["GroupMemBench 47.9%、SocialMemBench 69.2%、EverMemBench 61.9%，分别高出 3.3、12.4、9.4 个百分点"]
    assert cd.informative_title("关键结果", metrics) == "关键结果"

    spec_detail = ["System 1 逐字轨道不使用语言模型，追加每条消息的文本、说话人、时间与频道"]
    assert cd.informative_title("方法：双轨写入 + 查询组合", spec_detail) == "方法：双轨写入 + 查询组合"

    claim = ["Transformer 由自注意力与非线性 MLP 构成，通常被视为一次前向只处理单一语义流",
             "提出叠加线性假设：两条流被线性组合后，模型输出的是各单独下一 token 分布的叠加"]
    assert cd.informative_title("问题", claim) == "提出叠加线性假设"


# ---------------------------------------------------------------- 图注中文说明

def test_figure_note_beats_the_english_caption():
    """图卡页优先用 LLM 写的中文说明。

    背景（2026-09-26）：digest 里的 `figure.caption` 是**从 PDF 抽的英文原文，从没翻译过**。
    要点页标题是 LLM 写的中文，自动补的附录图却直接印英文 —— 实测印出过
    「Memory-path and hierarchy ablations. Labels show accuracy…」这种截断外语。
    """
    spec = {"figureNotes": {"fig-9.png": "去掉逐字轨或结构化轨，三个基准都掉分"},
            "columns": [[{"kind": "panel", "role": "problem", "title": "记不住谁说了什么",
                          "items": ["甲"], "figure": "fig-9.png", "figureCaption": "英文的也行"}]]}
    pages = cd.plan_pages(spec, None, {})
    fig = [p for p in pages if p["kind"] == "figure"][0]
    assert fig["title"] == "去掉逐字轨或结构化轨，三个基准都掉分"


def test_caption_fallback_cuts_at_a_sentence_not_mid_word():
    """没有中文说明时（老 spec），英文原注要断在句号上，不能断在半截词。"""
    got = cd._caption_title(
        "Memory-path and hierarchy ablations. Labels show accuracy and change from the best "
        "full dual-track result. Here, w/o S2 removes all four System 2 derived layers.")
    assert got == "Memory-path and hierarchy ablations."      # 完整一句，不是 "Labels show accuracy…"
    assert "…" not in got


def test_caption_fallback_keeps_more_sentences_when_they_fit():
    short = "Figure 1: a group chat is not a flat message stream."
    assert cd._caption_title(short) == "Figure 1: a group chat is not a flat message stream."
