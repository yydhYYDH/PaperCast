"""平台体裁 × 讲述者人格：风格层的唯一真源。

设计（见 docs/09-voice-styles.md）：
- **平台**决定体裁与硬约束（长度 / 能否有公式 / 标题计重 / 标签数 / 输出格式），由校验器强制执行；
- **人格**只决定语气、人称、句长节奏、归属强度、证据呈现方式，不得覆盖平台硬约束；
- 约束优先级：事实源（digest.json） > 平台硬约束 > 人格语气。

variant id = "{platform}-{voice}"，例如 "zhihu-analyst"。
旧 id（xhs / wechat / xhs-academic / wechat-media …）在 parse_variant() 里做兼容映射。

默认人格是 independent（第三方独立视角）：2026-09-19 按用户要求下线「作者自述」——
工具是第三方，稿子不该冒充论文作者。旧写法里的 author 由 RETIRED_VOICES 映射到它。

人格来源标注：
- newsflash（新智元式快讯）与 analyst（机器之心式技术解读）来自各自 8 篇真实语料的量化归纳；
- independent / peer / reviewer 是设计稿（尚无取样），改动前先按 skill paper-voice-styles 取样。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# 平台
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PlatformSpec:
    id: str
    label: str
    output: str            # json | markdown
    file: str              # 产物文件名
    body_min: int          # 正文字数下限（0 = 不限）
    body_max: int          # 正文字数上限
    tags_min: int
    tags_max: int
    allow_formula: bool
    cards: bool            # 是否渲染 3:4 卡片（只对 xhs 有意义）
    title_weight_max: int | None   # 小红书计重（中文 2 / 其余 1）
    title_chars_max: int | None    # 其余平台的标题字数上限
    rules: tuple[str, ...]         # 进提示词的硬约束（祈使句）
    template: str                  # 进提示词的输出格式模板
    unit: str = "cjk"              # 长度口径：cjk=中文字数，words=英文词数（纯英文用 cjk_len 会算成 0 字）
    language: str = "中文"          # 正文语言；会覆盖人格描述里的语言倾向（英文平台必须显式声明）


PLATFORMS: dict[str, PlatformSpec] = {
    "xhs": PlatformSpec(
        id="xhs",
        label="小红书",
        output="json",
        file="xhs.md",
        body_min=0,
        body_max=1000,
        tags_min=8,
        tags_max=12,
        allow_formula=False,
        cards=True,
        title_weight_max=38,
        title_chars_max=None,
        rules=(
            "正文绝对不能出现公式：不写 $...$、$$...$$、\\\\frac、\\\\begin{、_ 下标、^ 上标等 LaTeX 表达；需要公式的地方改成「优化什么、约束什么、为什么有效」的中文直觉表述。",
            "推荐标题（含候选标题）按小红书计重 ≤38：中文字符与中文标点算 2，英文/数字/ASCII 标点算 1。",
            "正文 3-4 段，合计 ≤1000 字。",
            "tags 8-12 个，不含 # 号，纯中文或中英混合短语。",
            "cards 的 figureId 只能从给定图表清单里选，按图集顺序：总览→方法→数据/训练→主结果→消融→定性。",
            "少用 emoji、引号、破折号。",
        ),
        template=(
            "只输出 JSON，不要解释文字或 markdown 围栏。JSON 结构：\n"
            "{\n"
            '  "candidateTitles": ["5-8 个候选标题"],\n'
            '  "recommendedTitle": "推荐标题",\n'
            '  "tldr": "40 字以内一句话总结",\n'
            '  "body": "正文，用空行分段",\n'
            '  "tags": ["标签1", "标签2"],\n'
            '  "cards": [{"figureId": "fig-1", "badge": "1/6 · 问题", "headline": "卡片主标题（20 字内）", "captionCn": "这张图在说什么，45 字以内中文"}]\n'
            "}"
        ),
    ),
    "zhihu": PlatformSpec(
        id="zhihu",
        label="知乎",
        output="markdown",
        file="zhihu.md",
        body_min=2000,
        body_max=4000,
        tags_min=3,
        tags_max=6,
        allow_formula=True,
        cards=False,
        title_weight_max=None,
        title_chars_max=40,
        rules=(
            "第一行写一级标题：# 标题（≤40 中文字），标题要给出结论或争议点，不用感叹号堆情绪。",
            "正文 2000-4000 中文字，用 ## 小标题分成 3-6 节。",
            "允许公式：用 KaTeX 的 $...$ / $$...$$，变量首次出现要解释中文含义。",
            "首段先给结论与这篇工作解决了什么问题，再展开细节（知乎读者先看结论）。",
            "每个数字都必须能在事实源里找到；事实源写「未给出具体数值」的，正文也不许给数。",
            "区分「论文声称」与「我的判断」，推论要显式标注。",
            "结尾给「局限与适用边界」一节。",
            "文末单起一节「话题标签」，每行一个 - #标签，共 3-6 个。",
        ),
        template=(
            "直接输出 Markdown：\n"
            "# 标题\n\n<导语：结论前置，2-4 句>\n\n## <小标题>\n…\n\n"
            "## <小标题>\n…\n\n## 局限与适用边界\n…\n\n## 话题标签\n- #标签1\n- #标签2\n"
        ),
    ),
    "bilibili": PlatformSpec(
        id="bilibili",
        label="B 站",
        output="markdown",
        file="bilibili.md",
        body_min=1200,
        body_max=2500,
        tags_min=3,
        tags_max=8,
        allow_formula=False,
        cards=False,
        title_weight_max=None,
        title_chars_max=40,
        rules=(
            "整体是视频脚本，不是文章：分镜表 + 口播稿 + 简介 + 标签。",
            "第一行：# 标题（≤40 中文字，口语化，不用公式与 LaTeX）。",
            "口播稿 1200-2500 字，短句、口语，每 15-20 秒（约 60-80 字）推进一个信息点。",
            "绝不出现公式与 LaTeX；需要的地方用「它在优化什么」的口语表述。",
            "分镜表用 Markdown 表格，列：时间 | 画面 | 口播要点，6-10 行，时间从 0:00 起累加。",
            "「一句话简介」≤120 字，可直接当视频简介第一段。",
            "标签 3-8 个，空格分隔，与论文主题相关，不含 # 号。",
            "每个数字都必须能在事实源里找到，口语里也不许估算。",
        ),
        template=(
            "直接输出 Markdown：\n"
            "# 标题\n\n## 一句话简介\n<≤120 字>\n\n"
            "## 分镜脚本\n| 时间 | 画面 | 口播要点 |\n| --- | --- | --- |\n| 0:00 | … | … |\n\n"
            "## 口播稿\n<1200-2500 字，分段>\n\n## 标签\n标签1 标签2 标签3\n"
        ),
    ),
    # 英文传播（总纲里的「英文传播 Agent」，R1 原计划留给 R2 —— 2026-09-19 补齐）
    "en": PlatformSpec(
        id="en",
        label="英文传播（X / LinkedIn）",
        output="markdown",
        file="en-thread.md",
        unit="words",
        language="英文",
        body_min=320,
        body_max=850,
        tags_min=3,
        tags_max=6,
        allow_formula=False,
        cards=False,
        title_weight_max=None,
        title_chars_max=90,
        rules=(
            "写成英文 thread（X 与 LinkedIn 通用），不是文章：6-10 条编号帖，每条自成一个帖子。",
            "第一条是钩子：一句话讲清这篇论文做成了什么、为什么值得看（≤50 词，不用问句凑互动）。",
            "每条 45-70 词；且**单条不超过 280 字符**（X 的单帖上限），超了就拆成两条，别硬塞。",
            "第 2 条起按「问题 → 方法 → 证据 → 局限」推进；每条只讲一个点，单独读也能读懂。",
            "全文用英文写（包括标题）；人格描述里的中文只是语气说明，不改变本条。",
            "数字必须能在事实源里找到，单位与数值跟事实源一致，英文里不要换算成别的量纲。",
            "不写 LaTeX/公式；用英文口语解释它在优化什么。",
            "把「论文声称」与「我的判断」分开写（the paper claims… / my read is…）。",
            "最后一条给局限与适用边界，并留一个链接占位符 [link]。",
            "文末单起一节「Tags」，每行一个 - #Tag，3-6 个英文标签。",
        ),
        template=(
            "输出 Markdown（正文英文）：\n"
            "# <English hook title, ≤90 chars>\n\n"
            "1/8 <hook post, ≤50 words>\n\n2/8 <one point>\n\n…\n\n8/8 <limitations + [link]>\n\n"
            "## Tags\n- #MachineLearning\n- #LLM\n"
        ),
    ),
}

# --------------------------------------------------------------------------- #
# 讲述者人格
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class VoiceSpec:
    id: str
    label: str
    anchor: str      # UI 与文档里的「参考锚点」（不要拿它当风格名对外宣传）
    persona: str     # 进提示词的人格片段
    sampled: bool    # True = 有真实语料支撑（见 docs/09-voice-styles.md）


_NEWSFLASH = """你是中文科技媒体的快讯作者，把论文/发布当成一条有情绪、有画面感的新闻来写。

写法特征（有真实语料支撑）：
- 标题造势：给出一个强判断或强结果，可用感叹号；不写设问式标题。
- 导语在前 1-3 句内把「谁做了什么、结果多强」讲完，再补一句悬念或背景。
- 正文用短句推进：每 2-4 句出现一个 ≤20 字的短句独立成段；不要长句套长句。
- 分节用「提问句或短断言单独成行」，不要编号式技术小标题。
- 情绪词只放在标题、导语和转折句；正文主体不堆形容词。
- 至少保留 2 处「可能 / 仍有待 / 目前尚不清楚」式限定语：标题可以强，正文要留余地。
- 结尾一段做行业级外推：这项能力会如何改变研究或产业节奏。"""

_ANALYST = """你是中文技术媒体的论文解读作者，把论文当一份技术报告来讲。

写法特征（有真实语料支撑）：
- 标题用「出处/前缀：结论」或「问题：方法名 + 效果」结构，感叹号最多一个。
- 有会议或机构信息时照实写进标题前缀，不夸张。
- 正文按固定骨架组织：核心结论 → 问题与瓶颈 → 现状综述 → 诊断实验 → 核心方法 → 实验结果 → 结论与展望 → 作者信息（有则写）。
- 小节标题必须是技术描述型短句（名词 + 做了什么），不要情绪化或提问式标题。
- 句长可以偏长（100-200 字），但每段只讲一件事，段间用逻辑连接词串起来。
- 归属要明确：写「作者提出」「论文报告」「结果显示」；推论必须标注为推论。
- 每个数字保留原文精度与 benchmark 名，并可在事实源里回溯。
- 不使用 emoji，不写「炸裂 / 颠覆 / 遥遥领先」类词。"""

_INDEPENDENT = """你是一位与这篇论文没有利益关系的第三方独立观察者，向读者讲清这项工作。

写法特征：
- 视角始终是「我看这篇论文」，不是「我们做了这项工作」：不冒充作者，也不替作者站台。
- 先讲清作者想解决什么问题、方法怎么做、证据够不够，再给出你自己的判断。
- 明确区分事实与判断：论文声称什么（可在事实源里回溯）、你认为它强在哪、弱在哪、哪里被过度解读。
- 该指出局限就指出（数据规模、评测设定、可复现性），不写成宣传稿，也不用「颠覆 / 最强 / 首个」这类词。"""

_PEER = """你是一位读过很多论文的实验室师兄，带着读者把这篇工作拆开看。

写法特征：
- 口语、直接，常用「你只需要知道这三点」「这里其实有个坑」这类引导。
- 先给读者一个直觉类比，再回到论文里的确切做法，标明哪些是类比、哪些是原文。
- 会主动指出「作者没说、但你应该注意」的前提条件。
- 不堆术语；出现术语时立刻用一句大白话解释。"""

_REVIEWER = """你是这篇论文的审稿人，写一份给同行看的评审意见式解读。

写法特征：
- 以「claim 是否被证据支撑」为主线：先复述作者的主张，再逐条对照证据强度。
- 明确指出实验覆盖不足之处：baseline 公平性、数据集范围、消融是否充分、指标是否只报最优。
- 区分「值得肯定的贡献」与「需要补实验的地方」，两者都要写。
- 语气专业、克制、可执行；不提改进建议之外的意见。"""

VOICES: dict[str, VoiceSpec] = {
    # 2026-09-19 用户要求：不要「作者自述」。默认人格改为第三方独立视角，不再冒充论文作者。
    # 旧写法（xhs-author / xhs / xhs-academic / zhihu-academic / bilibili-academic）由下面的
    # RETIRED_VOICES 与 LEGACY_VARIANTS 映射到这里，老配置不会静默丢变体。
    "independent": VoiceSpec("independent", "第三方独立视角", "与论文无利益关系的第三方", _INDEPENDENT, sampled=False),
    "peer": VoiceSpec("peer", "同行拆解", "实验室师兄讲论文", _PEER, sampled=False),
    "newsflash": VoiceSpec("newsflash", "科技快讯", "新智元式", _NEWSFLASH, sampled=True),
    "analyst": VoiceSpec("analyst", "技术解读", "机器之心式", _ANALYST, sampled=True),
    "reviewer": VoiceSpec("reviewer", "审稿人视角", "同行评审", _REVIEWER, sampled=False),
}

DEFAULT_PLATFORM = "xhs"
DEFAULT_VOICE = "independent"

# 已下线的人格 id → 替代人格。旧配置/旧 run 里写了 author 仍然能解析，但落到第三方独立视角，
# 不会再把稿子写成「我就是论文作者」；也避免旧 id 直接解析失败被静默丢掉。
RETIRED_VOICES: dict[str, str] = {"author": "independent"}
MAX_VARIANTS = 4  # 单次运行最多生成几个变体（每个变体一次 LLM 调用，成本线性增长）

# 旧 id → (platform, voice)：保住历史配置与前端 mock 里的写法
# 公众号（wechat / wechat-academic / wechat-media）已于 2026-09-19 按用户要求下线：
# 这些 id 现在解析不出平台，会被 resolve 阶段当成「不认识的变体」如实报出来，而不是悄悄生成。
LEGACY_VARIANTS: dict[str, tuple[str, str]] = {
    "xhs": ("xhs", "independent"),
    "xhs-academic": ("xhs", "independent"),
    "xhs-media": ("xhs", "newsflash"),
    "zhihu-academic": ("zhihu", "independent"),
    "bilibili-academic": ("bilibili", "independent"),
}


# --------------------------------------------------------------------------- #
# 解析与组装
# --------------------------------------------------------------------------- #

def _live_voice(platform: str, voice: str) -> tuple[str, str]:
    """已下线的人格 id 换成替代人格（见 RETIRED_VOICES）。"""
    return platform, RETIRED_VOICES.get(voice, voice)


def parse_variant(variant: str) -> tuple[str, str] | None:
    """把任意历史写法的 variant 解析成 (platform, voice)；无法识别返回 None。"""
    v = (variant or "").strip().lower()
    if not v:
        return None
    if v in LEGACY_VARIANTS:
        return _live_voice(*LEGACY_VARIANTS[v])
    if "-" in v:
        p, _, voice = v.partition("-")
        if p in PLATFORMS and (voice in VOICES or voice in RETIRED_VOICES):
            return _live_voice(p, voice)
    if v in PLATFORMS:                 # 只写平台，人格取默认
        return v, DEFAULT_VOICE
    return None


def variant_id(platform: str, voice: str) -> str:
    return f"{platform}-{voice}"


def variant_label(platform: str, voice: str) -> str:
    p = platform_spec(platform)
    v = voice_spec(voice)
    return f"{p.label} × {v.label}"


def normalize_variants(variants: list[str] | None, limit: int = MAX_VARIANTS) -> list[tuple[str, str]]:
    """规范化配置里的 variants：兼容旧 id、去重、限流；空配置回落到默认组合。"""
    out: list[tuple[str, str]] = []
    for raw in variants or []:
        parsed = parse_variant(raw)
        if parsed and parsed not in out:
            out.append(parsed)
    if not out:
        out = [(DEFAULT_PLATFORM, DEFAULT_VOICE)]
    return out[:limit]


def platform_spec(pid: str) -> PlatformSpec:
    return PLATFORMS[pid]


def voice_spec(vid: str) -> VoiceSpec:
    return VOICES[vid]


def voice_menu() -> list[dict[str, str]]:
    """给前端用的选项清单（不暴露提示词正文）。"""
    return [
        {"id": v.id, "label": v.label, "anchor": v.anchor, "sampled": "1" if v.sampled else "0"}
        for v in VOICES.values()
    ]


def platform_menu() -> list[dict[str, object]]:
    return [
        {
            "id": p.id,
            "label": p.label,
            "output": p.output,
            "allowFormula": p.allow_formula,
            "bodyMax": p.body_max,
            "tagsMin": p.tags_min,
            "tagsMax": p.tags_max,
            "titleWeightMax": p.title_weight_max,
            "cards": p.cards,
        }
        for p in PLATFORMS.values()
    ]


# --------------------------------------------------------------------------- #
# 校验（平台硬约束的机器检查；人格不得影响这里）
# --------------------------------------------------------------------------- #

CJK = re.compile(r"[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]")
NUM = re.compile(r"\d+(?:[.,]\d+)*\s*%?")
FORMULA = re.compile(r"\$[^$]{1,200}\$|\\frac|\\begin\{|\\sum|\\alpha|_\{|\^\{")


def title_weight(s: str) -> int:
    """小红书标题计重：中文/中文标点 2，其余 1。"""
    return sum(2 if CJK.match(ch) else 1 for ch in s)


def cjk_len(s: str) -> int:
    return len(CJK.findall(s or ""))


WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\u2019\-]*")


def text_len(s: str, unit: str = "cjk") -> int:
    """长度口径。中文平台按 CJK 字数，英文平台按英文词数 —— 否则纯英文内容会被算成 0 字，
    长度校验直接误判（这是加英文平台时踩到的坑）。"""
    return len(WORD.findall(s or "")) if unit == "words" else cjk_len(s)


def _md_title(md: str) -> str:
    m = re.search(r"^#\s+(.+)$", md or "", re.M)
    return m.group(1).strip() if m else ""


def _md_tags(md: str) -> list[str]:
    """从 Markdown 里取标签：优先「标签/Tags」小节，其次该小节里的空格分隔列表。

    小节名要中英都认 —— 英文平台（en，X/LinkedIn thread）写的是 `## Tags`，
    只认中文「标签」会让英文变体的标签数永远判 0。
    """
    out: list[str] = []
    m = re.search(r"^#{2,3}\s*(?:话题)?(?:标签|Tags?|Hashtags?)\s*$([\s\S]*?)(?=^#{1,3}\s|\Z)", md or "", re.M | re.I)
    block = m.group(1) if m else ""
    for t in re.findall(r"#([\w\u4e00-\u9fff][\w\u4e00-\u9fff\-]*)", block) or re.split(r"[\s,，、]+", block.strip()):
        t = t.strip().lstrip("#").strip()
        if t and t not in out:
            out.append(t)
    return out


def validate_markdown(spec: PlatformSpec, md: str) -> list[tuple[str, str, str]]:
    """Markdown 平台的机器校验，返回 [(label, state, detail)]。"""
    checks: list[tuple[str, str, str]] = []
    title = _md_title(md)
    # 标题一律按字符数量（英文标题的字数上限说的也是字符），正文才分口径
    title_len = len(title) if spec.unit == "words" else cjk_len(title)
    if spec.title_chars_max:
        checks.append((
            "标题",
            "pass" if title and title_len <= spec.title_chars_max else "fail",
            f"「{title[:30]}」= {title_len} {'字符' if spec.unit == 'words' else '字'}（上限 {spec.title_chars_max}）" if title else "缺少一级标题",
        ))
    n = text_len(md, spec.unit)
    unit_cn = "词" if spec.unit == "words" else "字"
    checks.append((
        "正文长度",
        "pass" if spec.body_min <= n <= spec.body_max else "fail",
        f"{n} {unit_cn}（要求 {spec.body_min}-{spec.body_max}）",
    ))
    if not spec.allow_formula:
        hit = FORMULA.search(md)
        checks.append(("无公式", "fail" if hit else "pass", f"命中 {hit.group(0)[:20]}" if hit else "未出现 LaTeX 表达"))
    else:
        checks.append(("公式策略", "pass", "该平台允许 KaTeX 公式"))
    tags = _md_tags(md)
    if spec.tags_max:
        ok = spec.tags_min <= len(tags) <= spec.tags_max
        checks.append(("标签数量", "pass" if ok else "fail", f"{len(tags)} 个（要求 {spec.tags_min}-{spec.tags_max}）"))
    return checks
