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


def test_kicker_parts_dedupe():
    assert cd.dedupe_parts("Nature · Vol 651 · 2026", "Nature", "PaperCast 论文速读") == \
        ["Nature · Vol 651 · 2026", "PaperCast 论文速读"]
    assert cd.dedupe_parts("arXiv", "") == ["arXiv"]
    assert cd.dedupe_parts("", None, "  ") == []


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
    chk = cd.validate(out)
    assert chk["sections"] == 4 and chk["fails"] == 0 and chk["exit"] == 0
