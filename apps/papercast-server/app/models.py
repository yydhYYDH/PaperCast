"""领域模型：1:1 对齐前端 papercast/src/types.ts，字段名不改。"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ViewId = Literal["workbench", "runs", "library", "settings"]
StageId = Literal["intake", "understand", "article", "poster", "video", "publish"]
StageStatus = Literal["pending", "running", "waiting", "done", "failed", "skipped"]
RunStatus = Literal["queued", "running", "waiting", "done", "failed"]
SourceKind = Literal["arxiv", "pdf", "latex"]
ArtifactKind = Literal["markdown", "html", "image", "video", "json", "pptx", "text"]

STAGE_ORDER: list[StageId] = ["intake", "understand", "article", "poster", "video", "publish"]

# 后端已接线的阶段：6 个阶段全部有真实实现（2026-09-19 收口，poster/video 不再 skipped）
IMPLEMENTED_STAGES: set[str] = {"intake", "understand", "article", "poster", "video", "publish"}
SKIPPED_STAGES: set[str] = set()

STAGE_META: dict[str, dict[str, str]] = {
    "intake": {
        "label": "输入归一化",
        "engine": "PyMuPDF · arXiv source",
        "hint": "PDF / arXiv / LaTeX → 统一 paper 模型",
    },
    "understand": {
        "label": "论文理解层",
        "engine": "paper2note",
        "hint": "唯一事实源：贡献 / 方法 / 证据 / 图表",
    },
    "article": {
        "label": "文章生成",
        "engine": "paper2xhs · paper2x",
        "hint": "小红书图文 + 知乎长文，无公式、数字可追溯",
    },
    "poster": {
        "label": "Poster 生成",
        "engine": "确定性排版 · poster.py ＋ 组图 · guizang 技能（可选）",
        "hint": "digest → 版面 spec → 按渠道渲染海报/竖长图/封面；同一份 spec 可选重排成小红书 3:4 组图（技能自检 R1–R9），几何溢出即判失败",
    },
    "video": {
        "label": "视频合成",
        "engine": "分镜 LLM + edge-tts 配音 + ffmpeg（CPU）",
        "hint": "digest → 分镜/旁白 → 逐页配音合成横版与竖版成片；TTS 失败如实标 fail",
    },
    "publish": {
        "label": "发布与运营",
        "engine": "channels · 小红书 / 知乎 / B站",
        "hint": "多平台投递，人工确认后逐个发出，失败不影响其它渠道",
    },
}


def now_ts() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class SourceInput(BaseModel):
    kind: SourceKind
    value: str
    title: Optional[str] = None
    authors: Optional[list[str]] = None
    venue: Optional[str] = None
    pages: Optional[int] = None
    bytes: Optional[int] = None


class Artifact(BaseModel):
    id: str
    stageId: StageId
    kind: ArtifactKind
    label: str
    path: str
    url: Optional[str] = None
    bytes: Optional[int] = None
    meta: Optional[dict[str, Any]] = None


class LogLine(BaseModel):
    ts: int
    level: Literal["info", "ok", "warn", "err"]
    text: str


class GateOption(BaseModel):
    id: str
    label: str
    hint: Optional[str] = None


class StageGate(BaseModel):
    id: str
    label: str
    detail: str
    options: list[GateOption]
    resolved: Optional[str] = None
    askedAt: Optional[int] = None
    note: Optional[str] = None


class StageCheck(BaseModel):
    label: str
    state: Literal["pass", "fail", "run"]
    detail: str


class Stage(BaseModel):
    id: StageId
    label: str
    engine: str
    status: StageStatus = "pending"
    progress: float = 0.0
    startedAt: Optional[int] = None
    endedAt: Optional[int] = None
    logs: list[LogLine] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    gate: Optional[StageGate] = None
    checks: Optional[list[StageCheck]] = None


class PaperDigest(BaseModel):
    arxivId: str = ""
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    venue: str = ""
    year: int = 0
    abstractCn: str = ""
    keywords: list[str] = Field(default_factory=list)
    contributions: list[str] = Field(default_factory=list)
    method: str = ""
    results: list[dict[str, str]] = Field(default_factory=list)
    figures: list[dict[str, str]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    stagesNote: str = ""


class ArticleVariant(BaseModel):
    """一个平台 × 人格的产出版本。id = "{platform}-{voice}"（见 app/styles.py）。"""

    id: str
    # 与 app/styles.py 的 PLATFORMS 保持一致；加平台时要一起加（漏了会导致该变体记不进去，
    # 2026-09-19 加英文平台时踩到）。前端 types.ts 的同名联合类型也要一起补，否则前端渲染不出这个变体。
    platform: Literal["xhs", "zhihu", "bilibili", "en"]
    voice: str
    label: str
    url: str
    words: Optional[int] = None


# 渠道 id（app/channels 的规范 id）→ 文案平台 id（app/styles.PLATFORMS 的 id）。
# 别名（xhs / x）也认；跟 publish.py 的 CHANNEL_PLATFORMS 是同一套对应关系。
_TARGET_PLATFORM: dict[str, str] = {
    "xiaohongshu": "xhs",
    "xhs": "xhs",
    "zhihu": "zhihu",
    "bilibili": "bilibili",
    "x": "en",
    "en": "en",
}


class ArticleConfig(BaseModel):
    # "{platform}-{voice}"，例如 xhs-author / zhihu-analyst；兼容旧的 xhs 等写法
    variants: list[str] = Field(default_factory=lambda: ["xhs-author"])


class PosterConfig(BaseModel):
    size: str = "36x48"
    venue: str = "arXiv"
    theme: str = "default"
    lang: str = "zh"


class VideoConfig(BaseModel):
    durationSec: int = 180
    voice: str = "zh-CN-XiaoxiaoNeural"
    aspect: Literal["16:9", "9:16"] = "9:16"
    narration: str = ""


class PublishConfig(BaseModel):
    # 投递渠道（app/channels/ 的规范 id；别名 xhs 也认）；留空 = 用 PAPERCAST_CHANNELS 的全部
    targets: list[str] = Field(default_factory=lambda: ["xiaohongshu", "zhihu", "bilibili"])
    autoPublish: bool = False


class RunConfig(BaseModel):
    # 用户自由文本指令（「这篇论文我想出成什么格式」）。只影响风格/体裁/篇幅/侧重，
    # 不允许改变事实层；边界见 prompts.BRIEF_RULES，遵从度由 generate.py 的 brief_checks 机检。
    brief: str = Field(default="", max_length=2000)
    article: ArticleConfig = Field(default_factory=ArticleConfig)
    poster: PosterConfig = Field(default_factory=PosterConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    publish: PublishConfig = Field(default_factory=PublishConfig)


def align_variants_with_targets(config: RunConfig) -> RunConfig:
    """让文案变体覆盖发布目标：缺哪个平台就补哪个（人格取该平台默认），原地改。

    原来两者是自相矛盾的：targets 默认 3 个渠道，variants 默认只有 xhs-author，于是发布
    知乎时找不到 zhihu 变体，只能按兜底顺序抓别的平台的稿子顶上（2026-09-19 实测：知乎
    拿到 994 字的小红书短稿，而它自己有变体时是 3924 字长文；24 条 run 里 20 条是这个错配，
    包括只传 source 建出来的那条默认 run）。

    只补 app/styles.PLATFORMS 里真实存在的平台；不认识的渠道 id 原样跳过，留给发布阶段的
    兜底顺序处理（那里仍会记 warn）。补的是裸平台写法，由 styles.parse_variant 映射到该平台
    默认人格（zhihu / bilibili → author），prompts.article_system 对这些组合都有真 prompt。

    刻意不做成 RunConfig 的自动 validator：那样会改掉默认对象本身（前端契约测试钉的就是默认
    值），用户显式点名变体时也会被动扩容。这里只在「配置变成一次运行」的入口调用，存进
    run.json 的就是覆盖后的真实清单。
    """
    from . import styles  # 函数内导入，避免 models ↔ styles 的导入顺序问题

    need: list[str] = []
    for target in config.publish.targets or []:
        pid = _TARGET_PLATFORM.get(str(target).strip().lower())
        if pid and pid in styles.PLATFORMS and pid not in need:
            need.append(pid)
    have: set[str] = set()
    for raw in config.article.variants or []:
        parsed = styles.parse_variant(str(raw))
        if parsed:
            have.add(parsed[0])
    add = [pid for pid in need if pid not in have]
    if not add:
        return config
    # 上限由 styles.MAX_VARIANTS 定（每个变体一次 LLM 调用）：放不下就补到放不下为止，
    # 剩下的仍走发布阶段的兜底并记 warn —— 不静默超支，也不假装覆盖了。
    room = max(0, styles.MAX_VARIANTS - len(config.article.variants))
    if room:
        config.article.variants = [*config.article.variants, *add[:room]]
    return config


class PaperRun(BaseModel):
    id: str
    createdAt: int
    title: str
    source: SourceInput
    status: RunStatus = "queued"
    stages: list[Stage] = Field(default_factory=list)
    config: RunConfig = Field(default_factory=RunConfig)
    digest: Optional[PaperDigest] = None
    articles: Optional[list[ArticleVariant]] = None
    error: Optional[dict[str, str]] = None


def new_run(source: SourceInput, config: RunConfig, title: str) -> PaperRun:
    # 文案变体必须覆盖发布目标：入口处对齐一次，run.json 里存的就是真实清单（见函数注释）
    config = align_variants_with_targets(config)
    stages: list[Stage] = []
    for sid in STAGE_ORDER:
        meta = STAGE_META[sid]
        stages.append(
            Stage(
                id=sid,  # type: ignore[arg-type]
                label=meta["label"],
                engine=meta["engine"],
                status="skipped" if sid in SKIPPED_STAGES else "pending",
            )
        )
    return PaperRun(
        id=new_id("run"),
        createdAt=now_ts(),
        title=title,
        source=source,
        status="queued",
        stages=stages,
        config=config,
    )


class CreateRunRequest(BaseModel):
    source: SourceInput
    config: Optional[RunConfig] = None


class GateRequest(BaseModel):
    optionId: str
    note: Optional[str] = None
