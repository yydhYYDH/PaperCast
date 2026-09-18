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

# 三模块覆盖的阶段；poster / video 暂未实现（返回 skipped），契约里保留位置
IMPLEMENTED_STAGES: set[str] = {"intake", "understand", "article", "publish"}
SKIPPED_STAGES: set[str] = {"poster", "video"}

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
        "engine": "paper2poster · Paper2Poster",
        "hint": "尚未接入本后端",
    },
    "video": {
        "label": "视频合成",
        "engine": "paper-share-skills · Paper2Video",
        "hint": "尚未接入本后端",
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
    platform: Literal["xhs", "zhihu", "bilibili"]
    voice: str
    label: str
    url: str
    words: Optional[int] = None


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
    article: ArticleConfig = Field(default_factory=ArticleConfig)
    poster: PosterConfig = Field(default_factory=PosterConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    publish: PublishConfig = Field(default_factory=PublishConfig)


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
