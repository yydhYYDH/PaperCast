"""作品级直投：从「作品库」直接把某次运行的作品投到某个渠道。

与 M3 发布阶段（app/modules/publish.py）的分工：

| 路径 | 粒度 | 闸门 | 什么时候能用 |
| --- | --- | --- | --- |
| M3 发布阶段 | 一次运行 → 扇出 run.config.publish.targets 里的全部渠道 | 流水线里的 `wait_gate` 协程 | **只在运行跑到 publish 阶段并停等时**（协程只在内存里，run 跑完或后端重启就没了） |
| 本模块（作品库直投） | 一件作品 → 一个渠道 | 前端确认后带 `confirmed=true`，后端仍然 fail-closed 白名单校验 | run 完成之后、后端重启之后，**任何时候** |

两条路径**共用**渠道层（app/channels/）与物料收集（`collect_materials_for`）—— 变体选择逻辑
（哪个渠道投哪一份文案）只存在于一处，不许在这里重写一遍（2026-09-19「三渠道共用一份文案」
那个 bug 就是这么来的）。

三条硬约束照抄渠道层：真实投递必须 confirmed；单渠道失败不丢素材（投递前先落 export/）；
状态如实上报（没接通就报 blocked，不假装成功）。

X（推特）是 material-only 渠道（见 channels/x.py）：作品库里点它只会落一份素材包 + draft 回执，
**任何路径都不会真的发出去**（下面 channel.material_only 的两个分支）。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from . import platforms as platforms_mod
from .channels import registry
from .channels.base import Channel, Delivery, Materials, Preflight, is_material_only
from .config import settings
from .models import Artifact, new_id
from .modules.publish import (
    PublishError,
    collect_materials_for,
    collect_materials_from_text,
    previous_delivery,
)

#: run 目录下不属于 M3 的那一半：M3 写 `publish/<渠道>/`，这里写 `publish/direct/<渠道>/`。
#: 必须分开 —— 否则作品库直投会把 M3 的回执覆盖掉，「这次到底是谁投的」就查不清了。
DIRECT_DIR = "direct"


def _err(status: int, code: str, message: str, details: Any = None) -> platforms_mod.PlatformError:
    """统一用平台层的错误形状 { error: { code, message } }（main.py 已有它的处理器）。"""
    return platforms_mod.PlatformError(status, code, message, details)


def _load(store: Any, run_id: str, *, allow_missing_article: bool = False) -> tuple[Any, Path]:
    """取运行与它的产物目录。

    `allow_missing_article=True` 放行**没有 `article/` 的运行**：独立脚本产出的成片就落在这种
    run 里（`run.json` 的 video 阶段一直是 skipped，成片不在流水线产物里），这种运行没有原文案，
    投递文案只能由调用方在 `overrides` 里给。默认仍然拦住 —— 没文章又没文案时发什么都没意义。
    """
    run = store.get(run_id)
    if run is None:
        raise _err(404, "RUN_NOT_FOUND", f"没有这次运行：{run_id}")
    run_dir = store.dir(run_id)
    if not allow_missing_article and not (run_dir / "article").is_dir():
        raise _err(409, "ARTICLE_MISSING", "这次运行还没有产出文章，先把写作阶段跑完再来发布")
    return run, run_dir


def _has_override_text(overrides: Optional[dict[str, Any]]) -> bool:
    """调用方是不是给了可用的文案（标题和正文都要：缺一个都组不出能投的物料）。"""
    data = overrides or {}
    title, content = data.get("title"), data.get("content")
    return bool(isinstance(title, str) and title.strip()
                and isinstance(content, str) and content.strip())


def _collect(run_dir: Path, run: Any, channel_id: str, overrides: Optional[dict[str, Any]],
             warn: Any) -> tuple[Optional[Materials], str]:
    """收物料：有 `article/` 走常规口径；没有的（只出成片的 run）用调用方给的文案。

    返回 `(物料, 人话原因)`，两者必有一个为空 —— 与 `_safe_materials` 同口径。
    """
    if (run_dir / "article").is_dir():
        return _safe_materials(run_dir, run, channel_id, warn)
    data = overrides or {}
    try:
        m = collect_materials_from_text(
            run_dir, run,
            title=str(data.get("title") or ""), body=str(data.get("content") or ""),
            tags=[str(t) for t in (data.get("tags") or [])], warn=warn)
    except PublishError as exc:
        return None, f"这次运行没有文章产物，发布要在发布面板里自己填标题和正文：{exc.message}"
    return m, ""


def _preview_without_article(run_dir: Path, run: Any, warn: Any) -> tuple[Optional[Materials], str]:
    """没有文章产物的运行：先把成片摆出来，并说清缺的是文案（人是可以在面板里填的）。

    故意用 `require_text=False`：界面要能看见「这条运行有什么可投的」，`supports()` 会照实
    报「缺标题、正文」，而不是让整个草稿列表 409 掉。
    """
    try:
        return collect_materials_from_text(run_dir, run, title="", body="", warn=warn,
                                           require_text=False), ""
    except PublishError as exc:
        return None, exc.message


def _pick(pool: list[Channel], channel_id: str) -> Optional[Channel]:
    cid = registry.canonical(channel_id)
    return next((c for c in pool if c.id == cid), None)


def _rel(run_id: str, run_dir: Path, path: Path) -> dict[str, str]:
    """产物 → 前端能直接拿来预览的相对地址（后端静态路由 /artifacts/{run_id}/{rel}）。"""
    rel = path.relative_to(run_dir).as_posix()
    return {"path": rel, "name": path.name, "url": f"/artifacts/{run_id}/{rel}"}


async def _probe(channels: list[Channel]) -> dict[str, Preflight]:
    """并发探测各渠道，探测异常只影响它自己（与 M3 的 _probe_channels 同口径）。"""
    results = await asyncio.gather(*(c.preflight() for c in channels), return_exceptions=True)
    out: dict[str, Preflight] = {}
    for channel, result in zip(channels, results):
        if isinstance(result, Exception):
            result = Preflight(
                state="offline", transport=channel.transport,
                detail=f"探测异常：{type(result).__name__}: {result}"[:200],
                hint=channel.restart_hint,
            )
        out[channel.id] = result
    return out


def _safe_materials(run_dir: Path, run: Any, channel_id: str, warn: Any) -> tuple[Optional[Materials], str]:
    """按渠道收集物料；收不到时返回人话原因，而不是让整个列表 500。

    没有文案不是错误，是「这个渠道现在还发不了」—— 列表页要照常显示其它渠道。
    """
    try:
        return collect_materials_for(run_dir, run, channel_id, warn=warn), ""
    except PublishError as exc:
        text = str(exc)
        if exc.code == "TITLE_MISSING":
            text = "这次运行没有可发布的标题（文章变体缺失或为空），先补写作阶段"
        return None, text
    except Exception as exc:
        return None, f"{type(exc).__name__}: {str(exc)[:160]}"


def _draft(run_id: str, run_dir: Path, channel: Channel, state: Preflight,
           materials: Optional[Materials], reason: str, *,
           film: Optional[Path] = None) -> dict[str, Any]:
    """一个渠道的待发草稿（给界面预览用）。物料缺失时只有原因，没有正文。

    `materials` 必须已经按**这个渠道的默认形态**整理过（见 list_drafts）：界面预览的
    `reason`/`images` 就是主按钮真会发出去的那一版。`film` 是**另立**的：这条 run 对这个
    渠道还另有成片可发（小红书默认发图文，但成片按钮要用它）—— 界面靠它决定要不要亮出
    第二个动作，别从 `images`/`video` 的位置反推。
    """
    out: dict[str, Any] = {
        "channelId": channel.id,
        "name": channel.name,
        "capabilities": sorted(channel.capabilities),
        # 不指定形态时这个渠道发什么（images/video）：界面用它给主按钮定性
        "defaultMedia": channel.default_media,
        "transport": channel.transport,
        "state": state.state,
        "account": state.account,
        "detail": state.detail,
        "hint": state.hint,
        "ready": state.ready,
    }
    if materials is None:
        out.update({"hasDraft": False, "suitable": False, "reason": reason or "这个渠道拿不到可投的文案"})
        return out

    suitable, why = channel.supports(materials)
    out.update({
        "hasDraft": True,
        "suitable": suitable,
        "reason": why,
        "title": materials.title,
        "body": materials.body,
        "tags": list(materials.tags),
        "images": [_rel(run_id, run_dir, p) for p in materials.images],
        # 这个渠道**可用**的成片（不一定被这次默认形态用到）：界面显示成片名 + 决定要不要
        # 给「发布视频」。这次真发哪个形态看上面的 defaultMedia 与 reason。
        "video": _rel(run_id, run_dir, film) if film is not None else None,
        "cover": _rel(run_id, run_dir, materials.cover) if materials.cover is not None else None,
        # 文案来源可审计：界面要能说清「这一版投的是哪份文案」（与 M3 的闸门详情同口径）
        "variant": str(materials.extra.get("variant") or ""),
        "variantPlatform": str(materials.extra.get("variantPlatform") or ""),
        "source": materials.source,
    })
    if not state.ready:
        out["blockedBy"] = state.state
        out["reason"] = "；".join(x for x in (state.detail, state.hint) if x)
    return out


async def list_drafts(store: Any, run_id: str, *, channels: Optional[Iterable[Channel]] = None) -> dict[str, Any]:
    """这次运行的**逐渠道待发草稿**（真实探测登录态 + 真实物料，不编造）。

    `channels` 只为测试注入；生产走 registry.build_all(settings)。
    """
    run, run_dir = _load(store, run_id, allow_missing_article=True)
    pool = list(channels) if channels is not None else registry.build_all(settings)
    states = await _probe(pool)

    warnings: list[str] = []
    has_article = (run_dir / "article").is_dir()
    drafts = []
    for channel in pool:
        # 没有文章产物的运行（只出成片的 run）：草稿照出，只是文案缺 —— 界面要能先看见成片，
        # 再由人把标题/正文填上（填了就由 /publish 的 overrides 带进来）。
        materials, reason = (
            _safe_materials(run_dir, run, channel.id, warnings.append) if has_article
            else _preview_without_article(run_dir, run, warnings.append)
        )
        # 形态口径要跟「点主按钮会发生什么」一致：先按渠道默认摘掉/保留成片再预览，
        # 否则小红书草稿会写着「视频笔记」，而主按钮其实发的是图文（界面自相矛盾）。
        # 成片先记下来再摘：界面要靠它显示成片名、决定要不要给「发布视频」这个动作。
        film = materials.video if materials is not None else None
        if materials is not None:
            _apply_media(materials, _default_media(channel))
        drafts.append(_draft(run_id, run_dir, channel, states[channel.id], materials, reason,
                             film=film))
    return {
        "runId": run_id,
        "previous": previous_delivery(run_dir) or None,
        "warnings": warnings,
        "channels": drafts,
    }


def _apply_overrides(materials: Materials, overrides: Optional[dict[str, Any]]) -> None:
    """界面改过的标题/正文/标签就地写回物料（只认非空值；改完调用方必须重新过 supports）。"""
    data = overrides or {}
    title = data.get("title")
    if isinstance(title, str) and title.strip():
        materials.title = title.strip()
    content = data.get("content")
    if isinstance(content, str) and content.strip():
        materials.body = content.strip()
    tags = data.get("tags")
    if isinstance(tags, list):
        materials.tags = [str(t).strip().lstrip("#") for t in tags if str(t).strip()]


#: 允许的投递形态（渠道 capabilities 用的是同一套词）。
MEDIA_KINDS = ("images", "video")


def _resolve_media(channel: Channel, media: str) -> str:
    """定下这次到底发什么形态：调用方指定优先，没指定就用渠道口径。

    同一条 run 往往**两个产物都有**（卡片组图 + 竖版成片），而小红书里图文笔记和视频笔记
    是两种不同的笔记 —— 渠道只看到 `materials.video` 非空就一定走视频分支
    （channels/xiaohongshu.py 的 supports），所以"这次发图文"必须能把已挑好的成片**明确摘掉**，
    否则那几张卡片一张都不会被用到。2026-09-19 实测踩过：默认没摘，6 张卡全被跳过。
    """
    kind = (media or "").strip() or _default_media(channel)
    if kind not in MEDIA_KINDS:
        raise _err(400, "MEDIA_UNSUPPORTED",
                   f"不认的投递形态「{kind}」：只能填 {' / '.join(MEDIA_KINDS)}。"
                   f"不填就用渠道默认（{channel.name} 默认发"
                   f"{'图文' if _default_media(channel) == 'images' else '视频'}）")
    return kind


def _default_media(channel: Channel) -> str:
    """渠道默认形态：先问手里这个实例，再退回按 id 查注册表（测试里的假渠道两个都不是）。"""
    return str(getattr(channel, "default_media", "")
               or registry.default_media_of(channel.id))


def _apply_media(materials: Materials, kind: str) -> str:
    """按定下来的形态整理物料，返回空串=可以发，否则返回「为什么这个形态发不了」。

    不是发视频就把成片摘掉，让渠道走图文分支。反过来（**要发视频但 run 里没有成片**）必须
    在这里挡住：`materials.video` 留 None 的话，channels/xiaohongshu.py 的 supports() 会
    顺着往下走回图文分支、把卡片当成"图文笔记"发出去 —— 调用方要的是视频笔记，结果收到一条
    图文，形态悄悄变了还报成功。所以宁可返回一句人话原因，让调用方按 blocked 处理。
    """
    if kind != "video":
        materials.video = None
        return ""
    if materials.video is None:
        return "缺成片：这条 run 里没有 video/，发不了视频笔记（要发图文就别指定形态）"
    return ""


def _receipt(channel: Channel, state: Preflight, materials: Materials, delivery: Delivery,
             export: dict[str, Any], option: str) -> dict[str, Any]:
    """与 M3 的回执同字段口径（字段名不同就得多写一套前端渲染，不值得）。"""
    out: dict[str, Any] = {
        "channel": channel.id,
        "channelName": channel.name,
        "status": delivery.status,
        "optionId": option,
        "title": materials.title,
        "contentChars": len(materials.body),
        "imageCount": len(materials.images),
        "video": materials.video.name if materials.video is not None else "",
        # 这次发的是什么形态（图文/成片）：回执要能自证，不然事后翻记录看不出"发的是哪一种笔记"
        "media": "video" if materials.video is not None else "images",
        "tags": list(materials.tags),
        "variant": str(materials.extra.get("variant") or ""),
        "source": materials.source,
        "exportDir": str(export.get("dir") or ""),
        "state": state.dump(),
        "at": int(time.time()),
        # 这条回执是「作品库直投」写的，不是 M3 流水线写的 —— 界面上要能分得清
        "via": "work-library",
    }
    for src, dst in (("url", "url"), ("remote_id", "remoteId"), ("account", "account")):
        value = getattr(delivery, src, "")
        if value:
            out[dst] = value
    if delivery.error:
        out["error"] = delivery.error
    # 渠道报告的降级（配图没插进去、标签没加上、正文结构被压平……）必须进回执。
    # 2026-09-19 的教训：知乎那条「发布成功」的文章其实是无图无标签的纯文字版，
    # 而回执里只有 status=published —— 看回执的人根本不知道降级了。
    degradations = list((delivery.raw or {}).get("warnings") or [])
    if degradations:
        out["degradations"] = degradations
    upstream = str((delivery.raw or {}).get("upstreamMessage") or "")
    if upstream:
        out["upstreamMessage"] = upstream
    return out


def _merge_receipts(run_dir: Path, receipt: dict[str, Any]) -> tuple[bool, str]:
    """把这次直投并进 M3 的 `publish/receipts.json`。

    为什么要并：作品库（前端 data/works.ts）按这份总表显示「这件发了没有」，不并进去的话
    直投成功的作品在作品库里还写着「待发布」，等于界面在骗人。

    文件不存在（这条 run 没跑过发布阶段）就跳过 —— 那时候建一份残缺的总表只会误导下游。
    """
    path = run_dir / "publish" / "receipts.json"
    if not path.is_file():
        return False, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"发布总表不是合法 JSON，这次回执未并入：{type(exc).__name__}"
    if not isinstance(data, dict) or not isinstance(data.get("channels"), dict):
        return False, "发布总表的结构不认识，这次回执未并入"
    channels: dict[str, Any] = data["channels"]

    cid = str(receipt["channel"])
    channels[cid] = receipt
    for bucket in ("published", "failed", "blocked"):
        ids = data.get(bucket)
        if isinstance(ids, list):
            data[bucket] = [x for x in ids if x != cid]
    bucket = {"published": "published", "failed": "failed", "blocked": "blocked"}.get(str(receipt["status"]))
    if bucket:
        if not isinstance(data.get(bucket), list):
            data[bucket] = []
        if cid not in data[bucket]:
            data[bucket].append(cid)
    if receipt["status"] == "published":
        data["status"] = "published"
    data["at"] = int(time.time())
    data["updatedBy"] = "work-library"      # 谁最后改的这份总表，要能查
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return True, ""


def _register_artifact(store: Any, run_id: str, run: Any, receipt: dict[str, Any], rel: str) -> bool:
    """把直投回执登记成发布阶段的产物。

    作品库按「产物 + 发布总表」两样东西显示状态（前端 data/works.ts）：少登记一样，刚发布
    成功的作品在货架上还是旧状态。**流水线正持有这个阶段时（running/waiting）不碰 run.json**
    —— 那会与流水线的保存互相覆盖，得不偿失。
    """
    stage = next((s for s in run.stages if s.id == "publish"), None)
    if stage is None or stage.status in ("running", "waiting"):
        return False
    if any(a.path == rel for a in stage.artifacts):
        return False
    stage.artifacts.append(Artifact(
        id=new_id("art"), stageId="publish", kind="json",
        label=f"{receipt.get('channelName') or receipt['channel']} 发布回执（作品库直投）",
        path=rel, url=f"/artifacts/{run_id}/{rel}", meta={"status": receipt["status"]},
    ))
    try:
        store.save(run)
    except Exception:
        stage.artifacts.pop()
        return False
    return True


def _result(store: Any, run_id: str, run: Any, channel: Channel, state: Preflight, materials: Materials,
            delivery: Delivery, export: dict[str, Any], option: str, warnings: list[str],
            note: str = "") -> dict[str, Any]:
    """回执落盘 + 并入发布总表 + 登记产物 + 组装返回体。

    回执写在自己的目录（`publish/direct/<渠道>/receipt.json`），**不覆盖 M3 的**
    `publish/<渠道>/receipt.json` —— 否则「这次到底是谁投的」就查不清了。

    `note` 是给人看的一句话（例如「只存了草稿，因为渠道还没就绪」），进回执也进返回体，
    界面上要和文件数一起显示 —— 不然「存成草稿了」会被误读成「发出去了」。
    """
    # 渠道报告的降级先并进 warnings：前端/调用方只看 warnings 也跑不掉
    for item in (delivery.raw or {}).get("warnings") or []:
        text = str(item)
        if text and text not in warnings:
            warnings.append(text)
    receipt = _receipt(channel, state, materials, delivery, export, option)
    if note:
        receipt["note"] = note
    rel = f"publish/{DIRECT_DIR}/{channel.id}/receipt.json"
    try:
        target = Path(export["dir"]).parent / "receipt.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(receipt, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as exc:
        rel = ""
        warnings.append(f"回执落盘失败（投递结果不受影响）：{type(exc).__name__}: {str(exc)[:160]}")

    if rel:
        # export 目录是 <run>/publish/direct/<渠道>/export → parents[3] 就是 run 目录
        _merged, why = _merge_receipts(Path(export["dir"]).parents[3], receipt)
        if why:
            warnings.append(why)
        _register_artifact(store, run_id, run, receipt, rel)

    return {
        "channelId": channel.id,
        "channelName": channel.name,
        "status": delivery.status,
        "url": delivery.url,
        "remoteId": delivery.remote_id,
        "account": delivery.account,
        "error": delivery.error,
        "files": list(export.get("files") or []),
        "exportDir": str(export.get("dir") or ""),
        "exportError": export.get("error", ""),
        "receipt": receipt,
        "receiptUrl": f"/artifacts/{run_id}/{rel}" if rel else "",
        "note": note,
        "warnings": warnings,
    }


async def publish_work(store: Any, run_id: str, channel_id: str, *,
                       confirmed: bool = False,
                       overrides: Optional[dict[str, Any]] = None,
                       confirm_account: str = "",
                       media: str = "",
                       channels: Optional[Iterable[Channel]] = None) -> dict[str, Any]:
    """把这次运行的作品投到一个渠道（或只落草稿）。

    - `confirmed=False`：**只落 export/**，一个发布接口都不调 → status="draft"；
    - `confirmed=True`：先落 export/ 兜底，再调渠道 publish() → status 由 Delivery 决定；
    - `media`：`images`（图文）或 `video`（成片）；**留空就用渠道口径**
      （小红书默认图文、B 站默认视频，见 `Channel.default_media`）。想发成片走
      `POST /api/runs/{id}/publish/video`；
    - 账号二次校验：`confirm_account` 与探测到的账号不一致时 409（防投错号）；
    - 素材不适配 / 渠道没就绪 / 没有文案：**不报 4xx**，返回 `status="blocked"` + 人话原因 ——
      界面要把「为什么投不了」原样显示出来，而不是把它当成一次失败请求；
    - **没有 `article/` 的运行**（独立脚本只出了成片）：文案由 `overrides` 里的标题/正文给，
      没给才按老规矩 409 `ARTICLE_MISSING`。
    """
    run, run_dir = _load(store, run_id, allow_missing_article=_has_override_text(overrides))
    pool = list(channels) if channels is not None else registry.build_all(settings)
    channel = _pick(pool, channel_id)
    if channel is None:
        raise _err(404, "CHANNEL_NOT_FOUND",
                   f"未知渠道：{channel_id}（可用：{', '.join(c.id for c in pool)}）")

    warnings: list[str] = []
    materials, reason = _collect(run_dir, run, channel.id, overrides, warnings.append)
    if materials is None:
        return {"channelId": channel.id, "status": "blocked", "warnings": warnings,
                "error": {"code": "MATERIAL_MISSING", "message": reason}, "receipt": None}

    _apply_overrides(materials, overrides)
    # 形态口径先定下来再落盘/判定：回执里 imageCount/video 要如实反映**这次实际会发什么**，
    # 否则界面上写着"图片 6 张"、真发出去的却是成片（2026-09-19 踩过）。
    media_kind = _resolve_media(channel, media)
    media_problem = _apply_media(materials, media_kind)

    state = (await _probe([channel]))[channel.id]
    suitable, why = channel.supports(materials)

    # ---- 1. 素材兜底：**先落盘，再做任何判定** ----
    #
    # 顺序是有意为之：「仅存草稿」的意义就是**服务全挂了也能手动发**，所以它不该被
    # 「渠道没登录 / 素材还不适配」挡住。原来把就绪判定放在落盘之前，未登录的渠道点
    # 「仅存草稿」会得到一句 blocked 而磁盘上什么都没有 —— 兜底等于没做（2026-09-19 修）。
    out = run_dir / "publish" / DIRECT_DIR / channel.id / "export"
    try:
        export = await channel.export(materials, out)
    except Exception as exc:
        export = {"dir": str(out), "files": [], "error": f"{type(exc).__name__}: {str(exc)[:200]}"}

    # 未确认、或渠道本来就不投（X）：只落 export/ → status="draft"
    if not confirmed or is_material_only(channel):
        notes: list[str] = []
        if is_material_only(channel):
            notes.append(f"{channel.name}只出素材包、不接投递：{channel.why}")
        if not suitable:
            notes.append(f"另外，这版素材这个渠道还投不了：{why}")
        if media_problem:
            notes.append("另外，" + media_problem)
        if not state.ready and not is_material_only(channel):
            notes.append("另外，这个渠道现在还没就绪：" + "；".join(x for x in (state.detail, state.hint) if x))
        return _result(store, run_id, run, channel, state, materials,
                       Delivery(channel=channel.id, status="draft", export_dir=str(out),
                                raw={"note": channel.why} if is_material_only(channel) else {}),
                       export, "draft", warnings, note="；".join(notes))

    # ---- 2. 只有「真投递」才做严格判定：素材适配 → 渠道就绪 → 账号对得上 ----
    # 形态先判：它比「素材适配」更具体 —— "要发视频但没成片"比"素材不适配"更能说明问题。
    if media_problem:
        return {"channelId": channel.id, "status": "blocked", "warnings": warnings,
                "error": {"code": "MEDIA_UNAVAILABLE", "message": media_problem}, "receipt": None}
    if not suitable:
        return {"channelId": channel.id, "status": "blocked", "warnings": warnings,
                "error": {"code": "MATERIAL_UNSUITABLE", "message": why}, "receipt": None}
    # material-only（X）：没有投递通道，永远到不了「就绪」—— 它不是没配好，是设计上就不投
    if not state.ready and not is_material_only(channel):
        return {"channelId": channel.id, "status": "blocked", "warnings": warnings,
                "error": {"code": state.state.upper(),
                          "message": "；".join(x for x in (state.detail, state.hint) if x)},
                "receipt": None}
    if confirm_account and state.account and confirm_account != state.account:
        raise _err(409, "ACCOUNT_MISMATCH",
                   f"账号对不上：当前登录的是「{state.account}」，你确认的是「{confirm_account}」")

    # ---- 3. 真实投递（confirmed 白名单在渠道层还会再校验一次） ----
    try:
        delivery = await channel.publish(materials, confirmed=True)
    except Exception as exc:
        delivery = Delivery(channel=channel.id, status="failed",
                            error={"code": "CHANNEL_CRASHED", "message": f"{type(exc).__name__}: {str(exc)[:200]}"})
    return _result(store, run_id, run, channel, state, materials, delivery, export, "continue", warnings)
