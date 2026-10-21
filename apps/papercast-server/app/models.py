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
SourceKind = Literal["arxiv", "pdf", "latex", "zhihu", "url", "github"]
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
    # 默认只发小红书（2026-09-23 用户要求）：默认不再产出/投递知乎与 B 站的内容。
    targets: list[str] = Field(default_factory=lambda: ["xiaohongshu"])
    autoPublish: bool = False


class RunConfig(BaseModel):
    # 用户自由文本指令（「这篇论文我想出成什么格式」）。只影响风格/体裁/篇幅/侧重，
    # 不允许改变事实层；边界见 prompts.BRIEF_RULES，遵从度由 generate.py 的 brief_checks 机检。
    brief: str = Field(default="", max_length=2000)
    article: ArticleConfig = Field(default_factory=ArticleConfig)
    poster: PosterConfig = Field(default_factory=PosterConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    publish: PublishConfig = Field(default_factory=PublishConfig)


def enabled_platforms(config: RunConfig) -> set[str]:
    """发布目标对应的文案/画布平台集合（app/styles.PLATFORMS 的 id）。

    用途：**默认只产出真要发的平台**的内容 —— 文案变体、poster 画布、视频合成都按它来。
    不认识的渠道 id 原样忽略（留给发布阶段的兜底顺序处理）。
    """
    out: set[str] = set()
    for target in config.publish.targets or []:
        pid = _TARGET_PLATFORM.get(str(target).strip().lower())
        if pid:
            out.add(pid)
    return out


def skipped_stages_for(config: RunConfig) -> set[str]:
    """这次运行可以跳过的阶段（在全局 SKIPPED_STAGES 之外，按配置推导）。

    默认只产出小红书：B 站不在发布目标里时就不跑视频合成 —— TTS + ffmpeg 是整条链最贵的
    一步，而默认的小红书图文用不上它。想要成片（B 站投稿 / 小红书视频笔记）就把 bilibili
    加进 publish.targets。
    """
    skipped = set(SKIPPED_STAGES)
    if "bilibili" not in enabled_platforms(config):
        skipped.add("video")
    return skipped


def align_variants_with_targets(config: RunConfig) -> RunConfig:
    """让文案变体与发布目标一致：**目标平台外的去掉、目标平台缺的补上**（人格取默认），原地改。

    两条来历合起来才需要这个函数：
    - 「补」：targets 与 variants 曾自相矛盾（targets 3 个渠道、variants 只有 xhs-author），
      发布知乎时抓不到 zhihu 变体，只能拿小红书短稿顶上（2026-09-19 实测）；
    - 「去」（2026-09-23）：默认只发小红书后，前端可能带着**历史遗留的变体**（用户风格页
      勾过知乎/英文，存在 localStorage，会跟着每次提交一起发过来）。如果只在 targets 上收口，
      就会出现「targets=[xiaohongshu]，却还在写知乎长文」——后端必须保证不生成不发的平台。

    targets 为空（= 用全部渠道）时不做任何裁剪。只认 app/styles.PLATFORMS 里真实存在的平台；
    不认识的变体/渠道原样跳过（变体留给 article 阶段跳过，渠道留给发布阶段的兜底顺序）。
    """
    from . import styles  # 函数内导入，避免 models ↔ styles 的导入顺序问题

    enabled = enabled_platforms(config)
    if not enabled:
        return config

    # 1) 去掉目标平台外的变体（保留原写法，兼容 xhs 等别名）
    kept: list[str] = []
    have: set[str] = set()
    for raw in config.article.variants or []:
        parsed = styles.parse_variant(str(raw))
        if parsed and parsed[0] in enabled:
            kept.append(str(raw))
            have.add(parsed[0])

    # 2) 补上目标平台里还没有变体的（裸平台写法 → parse_variant 映射到该平台默认人格）
    need: list[str] = []
    for target in config.publish.targets or []:
        pid = _TARGET_PLATFORM.get(str(target).strip().lower())
        if pid and pid in styles.PLATFORMS and pid not in need:
            need.append(pid)
    add = [pid for pid in need if pid not in have]

    # 上限由 styles.MAX_VARIANTS 定（每个变体一次 LLM 调用）：放不下就补到放不下为止。
    room = max(0, styles.MAX_VARIANTS - len(kept))
    config.article.variants = [*kept, *add[:room]][: styles.MAX_VARIANTS]
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
    # 按配置推导可跳过的阶段（默认只发小红书 → 不跑视频合成），在 run.json 里如实标 skipped
    skipped = skipped_stages_for(config)
    stages: list[Stage] = []
    for sid in STAGE_ORDER:
        meta = STAGE_META[sid]
        stages.append(
            Stage(
                id=sid,  # type: ignore[arg-type]
                label=meta["label"],
                engine=meta["engine"],
                status="skipped" if sid in skipped else "pending",
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
