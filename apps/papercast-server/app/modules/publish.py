"""M3：发布 —— **每个渠道投自己那份文案**（渠道层：小红书 / 知乎 / B 站）。

渠道抽象在 app/channels/（见该包 base.py 的分层说明）。本模块只做**编排**：

0. **物料按渠道分发**：xiaohongshu→xhs 变体、zhihu→zhihu 变体、bilibili→bilibili 变体（en→en），
   变体文件在 <run>/article/*.md；没有匹配时按中文优先的确定性顺序兜底并记 warn，闸门详情
   逐渠道写清「实际会投哪一份文案」（三渠道共用一份 export/ 的旧行为 = 界面在骗人，2026-09-19 修）；
1. **先落素材包**：每个渠道在闸门之前都把自己的 export/ 备好（各渠道那份）—— 服务全挂也能手动发；
2. **再探测状态**：各渠道并发探测，互不影响（小红书 MCP / 知乎 playwright / B 站 biliup）；
3. **一个闸门**：detail 写清「这次会投哪些、哪些投不了、为什么」，人只看一处；
4. **并发投递 + 失败隔离**：单渠道失败不影响其它渠道，每个渠道都留一份回执；
5. 不静默重试、不绕过风控、不假装成功：失败就是失败，素材一定还在。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any, Optional

from .. import styles
from ..channels import registry
from ..channels.base import Channel, Delivery, Materials, Preflight


def _is_confirmed(chosen: str | None) -> bool:
    """闸门选择是否代表"真的投递" —— **白名单**，只有显式 continue 才算。

    原来是黑名单（判断"不等于 draft/skip 即视为已确认"）：任何意外值（None、空串、未知 id）
    都会被当成"确认发布"，属 fail-open。发布是不可逆动作，这里必须 fail-closed。
    """
    return chosen == "continue"
from ..pipeline import StageContext


class PublishError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- #
# 物料收集：**每个渠道各取自己那份文案**
# --------------------------------------------------------------------------- #

# 渠道 id → 这个渠道该投的变体平台（变体命名与解析见 app/styles.py 的 PLATFORMS / parse_variant）。
# **三渠道不能共用同一份文案**：2026-09-19 实测 run_d76ca9da493e（xhs-author + zhihu-analyst）
# 时三个渠道拿到的都是 article/export/content.txt（小红书 921 字），磁盘上 2745 字的知乎长文
# 没被用过，回执却写 zhihu.contentChars=921、闸门详情也写「知乎：将投递 长文（921 字…）」。
CHANNEL_PLATFORMS: dict[str, tuple[str, ...]] = {
    "xiaohongshu": ("xhs",),
    "zhihu": ("zhihu",),
    "bilibili": ("bilibili",),
    # 英文传播（X / LinkedIn）还没有独立渠道服务，映射先留着：将来接上时不会又共用中文文案。
    "en": ("en",),
}

# 渠道**没有**自己匹配的变体时的兜底顺序：确定性 + 偏向中文渠道。
# 旧行为是「退第一个 markdown 变体」，于是 variants=["en-analyst","zhihu-analyst"] 时 B 站拿到
# 83 字符的英文标题（> B 站 80 上限）被判素材不适配而跳过，反序却正常（run_9105dc770228 实测）
# —— 同一个 run 的结论取决于配置顺序，属不确定性来源。
FALLBACK_PLATFORM_ORDER: tuple[str, ...] = ("xhs", "zhihu", "bilibili", "en")

MAX_INTAKE_IMAGES = 6      # 没有小红书卡片时，最多从 intake 取几张图进素材

def _read_article_text(article_dir: Path) -> tuple[str, str, list[str]]:
    """从 M2 的 export/ 读标题 / 正文 / 标签；缺失时从 xhs.md 兜底解析。"""
    title = content = ""
    tags: list[str] = []
    title_file = article_dir / "export" / "title.txt"
    content_file = article_dir / "export" / "content.txt"
    if title_file.is_file():
        title = title_file.read_text(encoding="utf-8").strip()
    if content_file.is_file():
        raw = content_file.read_text(encoding="utf-8").strip()
        m = re.search(r"((?:^|\s)#[^\s#]+(?:\s+#[^\s#]+)*)\s*$", raw)
        if m:
            tags = [t.lstrip("#") for t in m.group(1).split() if t.startswith("#")]
            raw = raw[: m.start()].strip()
        content = raw
    if not title or not content:
        md = article_dir / "xhs.md"
        if md.is_file():
            text = md.read_text(encoding="utf-8")
            if not title:
                m = re.search(r"^推荐标题：(.+)$", text, re.M)
                title = (m.group(1).strip() if m else "") or ""
            if not content:
                m = re.search(r"## 正文\n(.*?)\n## 标签", text, re.S)
                content = m.group(1).strip() if m else ""
            if not tags:
                m = re.search(r"## 标签\n(.+)$", text, re.M)
                tags = [t.lstrip("#") for t in (m.group(1).split() if m else []) if t.startswith("#")]
    return title, content, tags


def _warn(warn: Any, message: str) -> None:
    """记一条 warn。物料收集不持有 ctx，日志回调由调用方（run_publish）注入。"""
    if callable(warn):
        warn(message)


def _channel_platforms(channel_id: str) -> tuple[str, ...]:
    """渠道要的变体平台（按优先级）。认不出的渠道 id 若本身就是平台 id 也认，便于将来接新渠道。"""
    cid = (channel_id or "").strip().lower()
    if cid in CHANNEL_PLATFORMS:
        return CHANNEL_PLATFORMS[cid]
    if cid in styles.PLATFORMS:
        return (cid,)
    return ()


def _variant_index(article_dir: Path) -> dict[str, Path]:
    """扫 <run>/article/*.md，反解出「变体平台 → 文件」。

    文件名规则见 app/styles.py（xhs.md / zhihu-analyst.md / en-analyst.md …），这里用
    styles.parse_variant 反解；解析不出平台的 markdown（如 brief.md）直接忽略。同一平台有多个
    变体时，默认人格的 <platform>.md 优先，其余按文件名排序 —— 同一个 run 每次选到同一份，
    不看目录返回顺序。
    """
    index: dict[str, Path] = {}
    for path in sorted(article_dir.glob("*.md")):
        parsed = styles.parse_variant(path.stem)
        if not parsed:
            continue
        platform, _voice = parsed
        best = index.get(platform)
        if best is None or (path.stem != platform, path.name) < (best.stem != platform, best.name):
            index[platform] = path
    return index


_HEADING = re.compile(r"^#\s+(.+)$", re.M)
_XHS_TITLE = re.compile(r"^推荐标题：(.+)$", re.M)
_XHS_BODY = re.compile(r"## 正文\n(.*?)\n## 标签", re.S)
# 与 styles._md_tags 同口径：中英小节名都认，块内取 #话题，遇到下一个标题就停（这样
# 「## 配图顺序」这类后续小节里的 # 不会被算成标签）
_TAG_SECTION = re.compile(r"^#{2,3}\s*(?:话题)?(?:标签|Tags?|Hashtags?)\s*$([\s\S]*?)(?=^#{1,3}\s|\Z)", re.M | re.I)
_TAG_TOKEN = re.compile(r"#([\w\u4e00-\u9fff][\w\u4e00-\u9fff\-]*)")
_TRAILING_TAGS = re.compile(r"((?:^|\s)#[^\s#]+(?:\s+#[^\s#]+)*)\s*$")


def _tags_in_section(text: str) -> list[str]:
    """取「标签 / Tags / 话题标签」小节里的标签。"""
    m = _TAG_SECTION.search(text or "")
    if not m:
        return []
    out: list[str] = []
    for tag in _TAG_TOKEN.findall(m.group(1)):
        tag = tag.strip()
        if tag and tag not in out:
            out.append(tag)
    return out


def _trailing_tags(text: str) -> list[str]:
    """没有标签小节时，退文末的 #话题 行（与 _read_article_text 的老口径一致）。"""
    m = _TRAILING_TAGS.search(text or "")
    return [t.lstrip("#") for t in m.group(1).split() if t.startswith("#")] if m else []


def _read_variant(path: Path, platform: str) -> tuple[str, str, list[str]]:
    """读一份变体文件 → (标题, 正文, 标签)。

    - xhs 是「图文帖」结构（推荐标题 / ## 正文 / ## 标签）：正文本体只取 ## 正文 那一节；
    - zhihu / bilibili / en 是 Markdown 长文：一级标题当标题，**全文**当正文（与历史
      export/content.txt 同一口径，只是换成该渠道对应的那份变体文件）。
    """
    text = path.read_text(encoding="utf-8").strip()
    tags = _tags_in_section(text) or _trailing_tags(text)
    heading = _HEADING.search(text)
    if platform == "xhs":
        m = _XHS_TITLE.search(text)
        title = (m.group(1).strip() if m else "") or (heading.group(1).strip() if heading else "")
        body = _XHS_BODY.search(text)
        return title, (body.group(1).strip() if body else text), tags
    return (heading.group(1).strip() if heading else ""), text, tags


def _variant_candidates(article_dir: Path, channel_id: str, label: str, warn: Any) -> list[tuple[Path, str]]:
    """这个渠道按优先级该试哪些变体文件：(文件, 平台)。

    顺序 = 渠道专属平台变体 → FALLBACK_PLATFORM_ORDER（中文优先、确定性）→ 第一个 markdown
    变体。除第一条外都是兜底（能发但未必对味），一律记 warn —— 人必须能在日志与闸门详情里
    看见「这个渠道投的其实是别人的文案」。
    """
    index = _variant_index(article_dir)
    if not index:
        return []
    wanted = _channel_platforms(channel_id)
    own = [(index[p], p) for p in wanted if p in index]
    if own:
        return own
    for platform in FALLBACK_PLATFORM_ORDER:
        if platform in index:
            _warn(warn, f"[{label}] 没有 {'/'.join(wanted) or channel_id} 变体，按兜底顺序（{'→'.join(FALLBACK_PLATFORM_ORDER)}）改用「{platform}」变体 {index[platform].name}")
            return [(index[platform], platform)]
    first = sorted(index.items(), key=lambda kv: kv[1].name)[0]
    _warn(warn, f"[{label}] 没有匹配的变体，退第一个 markdown 变体 {first[1].name}")
    return [(first[1], first[0])]


def _intake_figures(run_dir: Path, warn: Any) -> list[Path]:
    """从 <run>/intake/figures.json 取图片清单（**list**，每项有 file，形如 images/img-p17-1.png，
    可能带 kind/caption）。图片投不投得出去不该取决于 intake 的文件命名，所以以这份清单为准。
    """
    f = run_dir / "intake" / "figures.json"
    if not f.is_file():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception as exc:
        _warn(warn, f"intake/figures.json 解析失败（{type(exc).__name__}），改用 intake/images/ 兜底")
        return []
    if not isinstance(data, list):
        _warn(warn, "intake/figures.json 不是 list（预期每项含 file），改用 intake/images/ 兜底")
        return []
    base = (run_dir / "intake").resolve()
    out: list[Path] = []
    for item in data:
        rel = str((item or {}).get("file") or "").strip() if isinstance(item, dict) else ""
        if not rel:
            continue
        try:
            path = (base / rel).resolve()
        except Exception:
            continue
        if base != path and base not in path.parents:   # figures.json 是外部输入，不许跳出 intake/
            _warn(warn, f"intake/figures.json 里的路径越界，已忽略：{rel}")
            continue
        if path.is_file() and path not in out:
            out.append(path)
    return out


# 一版 run 里两种朝向的成片都可能存在：video/video.mp4（1920×1080 母版）与
# video/video-vertical.mp4（1080×1920 竖切）。选哪个是平台口径，由渠道层声明
# （Channel.video_orientation），这里只负责按声明挑，**不做猜测**。
VERTICAL_HINTS = ("vertical", "portrait", "9x16")


def _pick_video(run_dir: Path, orientation: str = "landscape") -> Optional[Path]:
    """按朝向挑成片。

    2026-09-19 的真实事故：这里原来是 `sorted(glob("*.mp4"))[0]`，而
    `"video-vertical.mp4" < "video.mp4"`（`-`(0x2D) < `.`(0x2E)），于是**所有渠道**都拿到
    竖版 —— B 站那条投稿因此是 1080×1920 的竖版，而 B 站自己的口径是横版 16:9。
    字典序不该决定投什么，所以现在按名字里的朝向挑，再按「非竖版优先」兜底。
    """
    top = sorted((run_dir / "video").glob("*.mp4")) if (run_dir / "video").is_dir() else []
    cands = top or sorted((run_dir / "video").rglob("*.mp4"))
    if not cands:
        return None
    vertical = [c for c in cands if any(h in c.name.lower() for h in VERTICAL_HINTS)]
    landscape = [c for c in cands if c not in vertical]
    if orientation == "portrait":
        # 竖版平台：名字带 vertical 的优先，其次母版，最后才轮到别的
        for name in ("video-vertical.mp4", "video.mp4"):
            for c in cands:
                if c.name == name:
                    return c
        return (vertical or landscape or cands)[0]
    for name in ("video.mp4", "video-horizontal.mp4", "video-landscape.mp4"):
        for c in cands:
            if c.name == name:
                return c
    return (landscape or vertical or cands)[0]


def _pick_media(run_dir: Path, *, warn: Any = None,
                video_orientation: str = "landscape") -> tuple[list[Path], Optional[Path], Optional[Path]]:
    """图片 / 视频 / 封面。视频是 B 站渠道的前提，封面优先用 poster 的成图。

    图片顺序：小红书卡片（3:4，排版过）→ intake/figures.json（机器可读清单）→
    intake/images/fig-*.png glob。glob 只认新命名，旧命名 img-pXX-N.png 会一张都取不到
    （run_720e83bdae91 实测 imageCount=0、回执写「无配图」，而 intake 里躺着 4 张图），
    所以它只当最后一层兜底并记 warn。
    """
    images = sorted((run_dir / "article" / "cards").glob("p*.png"))
    if not images:
        images = _intake_figures(run_dir, warn)
        if not images:
            images = sorted((run_dir / "intake" / "images").glob("fig-*.png"))
            _warn(warn, "intake/figures.json 里没有可用图片，退回 intake/images/fig-*.png glob 兜底"
                        "（只认新命名，img-pXX-N.png 这类旧命名会被漏掉）")
        images = images[:MAX_INTAKE_IMAGES]
    # 顶层成片优先（video/*.mp4）；上游套件会把中间产物放在嵌套目录里，别抓错
    video = _pick_video(run_dir, video_orientation)
    cover: Optional[Path] = None
    for cand in [run_dir / "poster" / "cover.png", *(sorted((run_dir / "poster").glob("*.png")) if (run_dir / "poster").is_dir() else [])]:
        if cand.is_file():
            cover = cand
            break
    if cover is None and images:
        cover = images[0]
    return [p for p in images if p.is_file()], video, cover


def previous_delivery(run_dir: Path) -> dict[str, Any]:
    """检出「这个 run 已经投递过」的证据，防止把不可逆动作做第二次。

    上游 paper-share-skills 投完会写 `video/upload_result.json`（含 BV 号）；
    这条记录不属于 M3，但 M3 必须看见它 —— 否则人再点一次「确认发布」就会重复投稿。
    """
    for rel in ("video/upload_result.json", "video/bilibili_receipt.json"):
        f = run_dir / rel
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            bv = str(data.get("bv") or data.get("bvid") or "")
            return {
                "source": rel,
                "channel": "bilibili",
                "bvid": bv,
                "url": str(data.get("url") or (f"https://www.bilibili.com/video/{bv}" if bv else "")),
                "at": str(data.get("uploaded_at") or data.get("publishedAt") or ""),
            }
    return {}


def _build_materials(run_dir: Path, run: Any, *, title: str, body: str, tags: list[str],
                     variant: str, variant_platform: str, warn: Any,
                     video_orientation: str = "landscape") -> Materials:
    """组一份物料。标题为空直接拒发（宁可不发，也不发一份没标题的东西）。"""
    if not title.strip():
        raise PublishError("TITLE_MISSING", "标题为空，拒绝发布（先修 M2 的文章变体或 article/export/title.txt）")
    images, video, cover = _pick_media(run_dir, warn=warn, video_orientation=video_orientation)
    source = ""
    src = getattr(run, "source", None)
    if src is not None:
        if getattr(src, "kind", "") == "arxiv":
            source = f"https://arxiv.org/abs/{src.value}"
        else:
            source = str(getattr(src, "title", "") or src.value or "")
    return Materials(
        title=title.strip(),
        body=body.strip(),
        tags=list(tags),
        images=images,
        video=video,
        cover=cover,
        run_id=getattr(run, "id", ""),
        source=source,
        # 物料来源可审计：闸门详情、日志与回执都靠它说清「这一版投的是哪份文案」
        extra={"variant": variant, "variantPlatform": variant_platform},
    )


def _video_orientation_for(channel_id: str) -> str:
    """这个渠道要横版还是竖版 —— 规则在渠道层（Channel.video_orientation），这里只取用。

    渠道解析不出来（未知 id / 注册表里没有）就按横版处理：横版是母版，猜错的代价最小。
    """
    from ..channels import registry

    return registry.orientation_of(channel_id)


def collect_materials_for(run_dir: Path, run: Any, channel_id: str, *, warn: Any = None) -> Materials:
    """**按渠道**收集物料 —— 这个渠道实际会投的那一份文案。

    先取渠道专属变体（xiaohongshu→xhs、zhihu→zhihu、bilibili→bilibili、en→en）；没有匹配再按
    FALLBACK_PLATFORM_ORDER 中文优先兜底（记 warn）；一个 markdown 变体都没有时，才退回历史的
    article/export/（不含小红书变体的 run 全靠它，别撤掉）。
    """
    article_dir = run_dir / "article"
    label = channel_id
    orientation = _video_orientation_for(channel_id)     # 平台口径：横版/竖版
    for path, platform in _variant_candidates(article_dir, channel_id, label, warn):
        title, body, tags = _read_variant(path, platform)
        if not title.strip():
            _warn(warn, f"[{label}] 变体 {path.name} 里没有可用标题，换下一份")
            continue
        return _build_materials(run_dir, run, title=title, body=body, tags=tags,
                                variant=path.stem, variant_platform=platform, warn=warn,
                                video_orientation=orientation)
    title, content, tags = _read_article_text(article_dir)
    if title.strip():
        _warn(warn, f"[{label}] 没有可用的变体文案，退回 article/export/（历史兜底）")
    return _build_materials(run_dir, run, title=title, body=content, tags=tags,
                            variant="export/", variant_platform="", warn=warn,
                            video_orientation=orientation)


def collect_materials(run_dir: Path, run: Any, *, warn: Any = None) -> Materials:
    """与渠道无关的「主物料」：社区运营与回执总表用它（单渠道投哪份见 collect_materials_for）。

    口径＝ FALLBACK_PLATFORM_ORDER 里第一份可用变体（中文优先、确定性），都没有才退回
    article/export/。语义与旧的 collect_materials 一致（仍然是"一份物料"），只是不再让
    三个渠道共用它当投递文案。
    """
    article_dir = run_dir / "article"
    index = _variant_index(article_dir)
    ordered = [p for p in FALLBACK_PLATFORM_ORDER if p in index]
    ordered += [p for p in sorted(index) if p not in ordered]
    for platform in ordered:
        title, body, tags = _read_variant(index[platform], platform)
        if title.strip():
            return _build_materials(run_dir, run, title=title, body=body, tags=tags,
                                    variant=index[platform].stem, variant_platform=platform, warn=warn)
    title, content, tags = _read_article_text(article_dir)
    return _build_materials(run_dir, run, title=title, body=content, tags=tags,
                            variant="export/", variant_platform="", warn=warn)


# --------------------------------------------------------------------------- #
# 编排
# --------------------------------------------------------------------------- #

def _export_artifact_rels(materials: Materials) -> list[tuple[str, str]]:
    return [("export/title.txt", "标题（发布用）"), ("export/README.txt", "手动发布指引")]


async def _prepare_exports(ctx: StageContext, channels: list[Channel],
                           materials_by: dict[str, Materials]) -> dict[str, dict[str, Any]]:
    """闸门之前把每个渠道的素材包落盘：这是「服务全挂也不丢素材」的保险。

    落的是**该渠道自己那份**物料（不是三渠道共用的那一份）。
    """
    exports: dict[str, dict[str, Any]] = {}
    for channel in channels:
        out = ctx.work / channel.id / "export"
        try:
            exports[channel.id] = await channel.export(materials_by[channel.id], out)
            ctx.log("ok", f"[{channel.name}] 素材包已就绪：{len(exports[channel.id]['files'])} 个文件 -> publish/{channel.id}/export/")
        except Exception as exc:
            exports[channel.id] = {"dir": str(out), "files": [], "error": f"{type(exc).__name__}: {exc}"[:200]}
            ctx.log("warn", f"[{channel.name}] 素材包生成失败：{type(exc).__name__}: {exc}")
    return exports


async def _probe_channels(ctx: StageContext, channels: list[Channel]) -> dict[str, Preflight]:
    """并发探测各渠道；探测本身炸了也只影响它自己。"""
    results = await asyncio.gather(*(c.preflight() for c in channels), return_exceptions=True)
    states: dict[str, Preflight] = {}
    for channel, result in zip(channels, results):
        if isinstance(result, Exception):
            result = Preflight(
                state="offline", transport=channel.transport,
                detail=f"探测异常：{type(result).__name__}: {result}"[:200],
                hint=channel.restart_hint,
            )
        states[channel.id] = result
        level = "ok" if result.ready else ("warn" if result.state == "login_required" else "err")
        ctx.log(level, f"[{channel.name}] {result.state}：{result.detail}" + (f"（{result.hint}）" if result.hint and not result.ready else ""))
    return states


def _material_note(row: dict[str, Any]) -> str:
    """「这个渠道将投哪一份文案」——标题 + 变体来源；兜底必须显式说出来。"""
    materials = row.get("materials")
    if materials is None:
        return ""
    variant = str(materials.extra.get("variant") or "")
    platform = str(materials.extra.get("variantPlatform") or "")
    if not variant:
        return ""
    if platform and platform in _channel_platforms(row["channel"].id):
        src = f"变体 {variant}"
    elif variant == "export/":
        src = "历史 export/ 兜底"
    else:
        src = f"兜底变体 {variant}（{row['channel'].name} 没有专属变体）"
    return f"；文案「{materials.title}」[{src}]"


def _gate_detail(rows: list[dict[str, Any]], previous: Optional[dict[str, Any]] = None) -> str:
    """闸门详情：**逐个渠道写清它会投哪一份文案**（标题 + 变体来源），不能只写渠道名。

    旧版只写渠道名与一句素材描述，而三渠道共用 article/export/ 时那句描述里的字数是小红书
    正文的 921 字、知乎实际拿到的也正是那一份 —— 详情在骗人。现在每个渠道都带上它自己那份
    物料的标题与变体（兜底会写明"没有专属变体"）。
    """
    lines = ["本次发布计划（每个渠道相互独立，一个失败不影响其它）："]
    for row in rows:
        channel, state, suitable, reason = row["channel"], row["state"], row["suitable"], row["reason"]
        where = _material_note(row)
        if not suitable:
            lines.append(f"· {channel.name}：跳过 —— {reason}{where}")
        elif state.ready:
            who = f"，账号 {state.account}" if state.account else ""
            lines.append(f"· {channel.name}：将投递 {reason}{who}{where}")
        else:
            lines.append(f"· {channel.name}：投不了（{state.state}）—— {state.detail}{where}")
    if previous:
        where = previous.get("bvid") or previous.get("url") or "未知稿件"
        lines.append(
            f"⚠ 这个 run 已经投递过一次（{previous.get('source')} → {where}）："
            "确认发布会把同一份物料再投一遍，重复投稿不可逆，请先确认是不是故意的。"
        )
    lines.append("所有渠道的素材包都已落在 publish/<渠道>/export/，即使全部投递失败也能手动发布。")
    return "\n".join(lines)


async def _deliver(ctx: StageContext, rows: list[dict[str, Any]], confirmed: bool) -> dict[str, Delivery]:
    """并发投递 + 失败隔离。只有 ready 且素材适配的渠道真的投。"""
    todo = [row for row in rows if row["state"].ready and row["suitable"]]
    deliveries: dict[str, Delivery] = {}

    for row in rows:
        if row["state"].ready and row["suitable"]:
            continue
        channel, state = row["channel"], row["state"]
        if not row["suitable"]:
            deliveries[channel.id] = Delivery(channel=channel.id, status="skipped",
                                              error={"code": "MATERIAL_UNSUITABLE", "message": row["reason"]})
        else:
            deliveries[channel.id] = Delivery(channel=channel.id, status="blocked",
                                              error={"code": state.state.upper(), "message": state.detail})

    if not todo:
        return deliveries

    ctx.log("info", "开始投递：" + "、".join(row["channel"].name for row in todo))
    results = await asyncio.gather(
        *(row["channel"].publish(row["materials"], confirmed=confirmed) for row in todo),
        return_exceptions=True,
    )
    for row, result in zip(todo, results):
        channel = row["channel"]
        if isinstance(result, Exception):
            result = Delivery(channel=channel.id, status="failed",
                              error={"code": "CHANNEL_CRASHED", "message": f"{type(result).__name__}: {result}"[:300]})
        deliveries[channel.id] = result
        if result.ok:
            ctx.log("ok", f"[{channel.name}] 已发布：{result.url or result.remote_id or '已提交'}")
        else:
            err = result.error or {}
            ctx.log("err", f"[{channel.name}] 投递失败：{err.get('code', '')} {str(err.get('message', ''))[:160]}")
    return deliveries


async def run_publish(ctx: StageContext) -> None:
    run_dir = ctx.store.dir(ctx.run.id)
    if not (run_dir / "article").is_dir():
        raise PublishError("ARTICLE_MISSING", "缺少 M2 的文章产物，无法发布")

    previous = previous_delivery(run_dir)
    if previous:
        where = previous["bvid"] or previous["url"] or "未知稿件"
        ctx.check("历史投递", "run", f"{previous['channel']} 已投过：{where}（{previous['source']}）—— 再点确认会重复投稿")
        ctx.log("warn", f"这个 run 已经投递过一次（{previous['source']}：{where}）：闸门会让二次确认，别手滑重复投")

    targets, problems = registry.resolve_targets(ctx.settings, ctx.run.config.publish.targets)
    for problem in problems:
        ctx.log("warn", f"渠道配置有问题：{problem['message']}")
        ctx.check(f"渠道：{problem['id']}", "fail", problem["message"])
    if not targets:
        raise PublishError("NO_CHANNEL", "没有任何可用渠道（检查 run.config.publish.targets 与 PAPERCAST_CHANNELS）")
    ctx.log("info", f"目标渠道 {len(targets)} 个：" + "、".join(c.name for c in targets))

    # ---- 1. 物料：**每个渠道各取自己那份文案**（不再三渠道共用一份 export/） ----
    def _log_warn(message: str) -> None:
        ctx.log("warn", message)

    materials_by: dict[str, Materials] = {}
    for channel in targets:
        materials_by[channel.id] = collect_materials_for(run_dir, ctx.run, channel.id, warn=_log_warn)
        mine = materials_by[channel.id]
        ctx.log("info", f"[{channel.name}] 待发布物料：{mine.summary()} / 文案 {mine.extra.get('variant') or '?'}")
    # 与渠道无关的主物料：社区运营与回执总表用（各渠道投哪份以 materials_by 为准）
    materials = collect_materials(run_dir, ctx.run, warn=_log_warn)

    # ---- 2. 素材包先落盘（闸门之前，纯本地、无副作用） ----
    exports = await _prepare_exports(ctx, targets, materials_by)

    # ---- 3. 逐渠道判定「能不能投」并探测状态 ----（判定用的是**该渠道自己那份**物料）
    states = await _probe_channels(ctx, targets)
    rows: list[dict[str, Any]] = []
    for channel in targets:
        state = states[channel.id]
        mine = materials_by[channel.id]
        suitable, reason = channel.supports(mine)
        rows.append({"channel": channel, "state": state, "suitable": suitable, "reason": reason,
                     "materials": mine})
        ctx.check(f"素材适配：{channel.name}", "pass" if suitable else "fail", reason)
        ctx.check(
            f"渠道状态：{channel.name}",
            "pass" if state.ready else "fail",
            f"账号 {state.account}（{state.detail}）" if state.ready else state.detail,
        )

    deliverable = [row for row in rows if row["state"].ready and row["suitable"]]
    ctx.check("可投递渠道", "pass" if deliverable else "run",
              "、".join(row["channel"].name for row in deliverable) if deliverable else "本轮没有可投递渠道（素材包已就绪，可手动发布）")

    # ---- 4. 一个人工闸门 ----
    chosen = await ctx.gate(
        "publish-gate",
        "发布前人工闸门",
        _gate_detail(rows, previous),
        [
            ("continue", "确认发布", "只向就绪的渠道投递，逐个写回执"),
            ("draft", "仅存草稿", "只准备 export/，不调用任何发布接口"),
            ("skip", "本轮不发布", None),
        ],
        # 闸门异常/没等到选择时的默认值：只存草稿。绝不能默认真投递（发布不可逆）。
        default="draft",
    )

    # ---- 5. 投递（失败隔离） ----
    confirmed = _is_confirmed(chosen)
    if confirmed:
        deliveries = await _deliver(ctx, rows, True)
    else:
        reason = "仅存草稿" if chosen == "draft" else "本轮不发布"
        deliveries = {
            channel.id: Delivery(channel=channel.id, status="draft", export_dir=str(ctx.work / channel.id / "export"))
            for channel in targets
        }
        ctx.log("warn", f"{reason}：素材已备好，未调用任何发布接口")

    # ---- 6. 回执：每渠道一份 + 一份总表 ----
    published = [cid for cid, d in deliveries.items() if d.ok]
    failed = [cid for cid, d in deliveries.items() if d.status == "failed"]
    blocked = [cid for cid, d in deliveries.items() if d.status == "blocked"]
    if published:
        status = "published"          # 部分成功也是 published，失败渠道在 failed 里单列
    elif failed:
        status = "failed"
    elif chosen == "draft":
        status = "draft"
    elif confirmed:
        status = "blocked"            # 确认要发，但没有任何渠道可投（离线/未登录/素材不适用）
    else:
        status = "skipped"

    receipts: dict[str, Any] = {}
    for channel in targets:
        delivery = deliveries[channel.id]
        state = states[channel.id]
        mine = materials_by[channel.id]        # 回执写的是**这个渠道实际拿到的**那一份
        receipt = {
            "channel": channel.id,
            "channelName": channel.name,
            "status": delivery.status,
            "optionId": chosen,
            "title": mine.title,
            "contentChars": len(mine.body),
            "imageCount": len(mine.images),
            "video": mine.video.name if mine.video else "",
            "tags": mine.tags,
            "variant": str(mine.extra.get("variant") or ""),
            "source": mine.source,
            "exportDir": str(ctx.work / channel.id / "export"),
            "state": state.dump(),
            "at": int(time.time()),
        }
        if delivery.url:
            receipt["url"] = delivery.url
        if delivery.remote_id:
            receipt["remoteId"] = delivery.remote_id
        if delivery.account:
            receipt["account"] = delivery.account
        if delivery.error:
            receipt["error"] = delivery.error
        if delivery.raw:
            receipt["raw"] = delivery.raw
        receipts[channel.id] = receipt

        rel = f"{channel.id}/receipt.json"
        (ctx.work / channel.id).mkdir(parents=True, exist_ok=True)
        (ctx.work / rel).write_text(json.dumps(receipt, ensure_ascii=False, indent=1), encoding="utf-8")
        ctx.artifact("json", f"{channel.name} 发布回执", rel, preview=True, meta={"status": delivery.status})

        for rel_file, label in _export_artifact_rels(materials):
            ctx.artifact("text", f"{channel.name} · {label}", f"{channel.id}/{rel_file}",
                         preview=(rel_file == "export/title.txt"))

    if exports:
        (ctx.work / "exports.json").write_text(
            json.dumps({cid: {"dir": data.get("dir", ""), "files": data.get("files", []),
                              "remote": data.get("remote"), "error": data.get("error", "")}
                        for cid, data in exports.items()}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

    summary = {
        "optionId": chosen,
        "status": status,
        # 主物料（社区运营与总表用）；各渠道实际投的标题/字数见上面的 channels.<id>
        "material": {
            "title": materials.title, "contentChars": len(materials.body),
            "imageCount": len(materials.images), "video": materials.video.name if materials.video else "",
            "tags": materials.tags, "variant": str(materials.extra.get("variant") or ""),
        },
        "channels": receipts,
        "published": published,
        "failed": failed,
        "blocked": blocked,
        "at": int(time.time()),
    }
    (ctx.work / "receipts.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    ctx.artifact("json", "发布回执总表", "receipts.json", preview=True,
                 meta={"status": status, "published": published, "failed": failed})

    # 兼容旧别名：小红书单渠道时代写的是 xhs_receipt.json，下游文档/脚本还在引用
    if "xiaohongshu" in receipts:
        (ctx.work / "xhs_receipt.json").write_text(
            json.dumps(receipts["xiaohongshu"], ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- 6.5 社区运营：选社区 + 每个社区一版成稿文案 + 真实投递数据复盘 ----
    # 挂在发布阶段尾部（该阶段的名字就是「发布与运营」），不新增 stage —— 前端 6 段的契约不动。
    # 失败只标 check，不影响发布结果本身。
    try:
        from .community import run_community

        await run_community(ctx, materials, receipts, published)
    except Exception as e:
        ctx.log("warn", f"社区运营计划生成失败（发布结果不受影响）：{type(e).__name__}: {str(e)[:160]}")
        ctx.check("社区投放计划", "fail", f"{type(e).__name__}: {str(e)[:140]}")

    # ---- 7. 结论 ----
    if status == "published" and not failed:
        detail = "、".join(f"{receipts[c]['channelName']}={receipts[c].get('url') or receipts[c].get('remoteId') or '已提交'}" for c in published)
        ctx.check("发布结果", "pass", detail)
        ctx.log("ok", f"M3 完成：{detail}" + ("（部分渠道无可投素材或未就绪，见 checks）" if len(published) < len(targets) else ""))
    elif status == "published":
        ctx.check("发布结果", "fail", f"部分渠道失败：{'、'.join(receipts[c]['channelName'] for c in failed)}（成功：{'、'.join(receipts[c]['channelName'] for c in published)}）")
        ctx.log("warn", "部分渠道投递失败：成功的已发出，失败的素材包仍在 publish/<渠道>/export/，请人工处理")
    elif chosen == "skip":
        ctx.check("发布结果", "run", "本轮不发布")
        ctx.log("ok", "M3 完成：skipped")
    elif chosen == "draft":
        ctx.check("发布结果", "run", "仅存草稿（素材包已就绪）")
        ctx.log("ok", "M3 完成：draft")
    elif confirmed and not failed:
        why = "；".join(f"{receipts[c]['channelName']}：{receipts[c].get('error', {}).get('message', '不可投')[:60]}" for c in blocked)
        ctx.check("发布结果", "fail", f"闸门已放行，但没有渠道可投：{why}"[:160])
        ctx.log("warn", "闸门已放行但没有渠道可投（离线/未登录/素材不适用）：素材包在 publish/<渠道>/export/，先修渠道再重试")
    else:
        first_error = next((d.error for d in deliveries.values() if d.error), None) or {}
        ctx.check("发布结果", "fail", str(first_error.get("message", ""))[:120])
        ctx.log("warn", "M3 未发出：按设计失败不静默重试，素材包在 publish/<渠道>/export/，请人工处理")
