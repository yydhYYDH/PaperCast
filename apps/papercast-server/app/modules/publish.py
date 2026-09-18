"""M3：发布 —— 一份物料投递到多个平台（渠道层：小红书 / 知乎 / B 站）。

渠道抽象在 app/channels/（见该包 base.py 的分层说明）。本模块只做**编排**：

1. **先落素材包**：每个渠道在闸门之前都把自己的 export/ 备好 —— 服务全挂也能手动发；
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

from ..channels import registry
from ..channels.base import Channel, Delivery, Materials, Preflight
from ..pipeline import StageContext


class PublishError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- #
# 物料收集：与平台无关，只做一次
# --------------------------------------------------------------------------- #

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


def _pick_media(run_dir: Path) -> tuple[list[Path], Optional[Path], Optional[Path]]:
    """图片 / 视频 / 封面。视频是 B 站渠道的前提，封面优先用 poster 的成图。"""
    images = sorted((run_dir / "article" / "cards").glob("p*.png"))
    if not images:
        images = sorted((run_dir / "intake" / "images").glob("fig-*.png"))[:6]
    video: Optional[Path] = None
    # 顶层成片优先（video/*.mp4）；上游套件会把中间产物放在嵌套目录里，别抓错
    for cand in sorted((run_dir / "video").glob("*.mp4")) or sorted((run_dir / "video").rglob("*.mp4")):
        video = cand
        break
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


def collect_materials(run_dir: Path, run: Any) -> Materials:
    """把 M1/M2（以及将来 M4）的产物收成一份与平台无关的物料。"""
    article_dir = run_dir / "article"
    title, content, tags = _read_article_text(article_dir)
    if not title.strip():
        raise PublishError("TITLE_MISSING", "标题为空，拒绝发布（先把 M2 的 export/title.txt 修好）")

    images, video, cover = _pick_media(run_dir)

    source = ""
    src = getattr(run, "source", None)
    if src is not None:
        if getattr(src, "kind", "") == "arxiv":
            source = f"https://arxiv.org/abs/{src.value}"
        else:
            source = str(getattr(src, "title", "") or src.value or "")

    return Materials(
        title=title.strip(),
        body=content.strip(),
        tags=list(tags),
        images=images,
        video=video,
        cover=cover,
        run_id=getattr(run, "id", ""),
        source=source,
    )


# --------------------------------------------------------------------------- #
# 编排
# --------------------------------------------------------------------------- #

def _export_artifact_rels(materials: Materials) -> list[tuple[str, str]]:
    return [("export/title.txt", "标题（发布用）"), ("export/README.txt", "手动发布指引")]


async def _prepare_exports(ctx: StageContext, channels: list[Channel], materials: Materials) -> dict[str, dict[str, Any]]:
    """闸门之前把每个渠道的素材包落盘：这是「服务全挂也不丢素材」的保险。"""
    exports: dict[str, dict[str, Any]] = {}
    for channel in channels:
        out = ctx.work / channel.id / "export"
        try:
            exports[channel.id] = await channel.export(materials, out)
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


def _gate_detail(rows: list[dict[str, Any]], previous: Optional[dict[str, Any]] = None) -> str:
    lines = ["本次发布计划（每个渠道相互独立，一个失败不影响其它）："]
    for row in rows:
        channel, state, suitable, reason = row["channel"], row["state"], row["suitable"], row["reason"]
        if not suitable:
            lines.append(f"· {channel.name}：跳过 —— {reason}")
        elif state.ready:
            who = f"，账号 {state.account}" if state.account else ""
            lines.append(f"· {channel.name}：将投递 {reason}{who}")
        else:
            lines.append(f"· {channel.name}：投不了（{state.state}）—— {state.detail}")
    if previous:
        where = previous.get("bvid") or previous.get("url") or "未知稿件"
        lines.append(
            f"⚠ 这个 run 已经投递过一次（{previous.get('source')} → {where}）："
            "确认发布会把同一份物料再投一遍，重复投稿不可逆，请先确认是不是故意的。"
        )
    lines.append("所有渠道的素材包都已落在 publish/<渠道>/export/，即使全部投递失败也能手动发布。")
    return "\n".join(lines)


async def _deliver(ctx: StageContext, rows: list[dict[str, Any]], materials: Materials, confirmed: bool) -> dict[str, Delivery]:
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
        *(row["channel"].publish(materials, confirmed=confirmed) for row in todo),
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

    # ---- 1. 物料：与平台无关，只收一次 ----
    materials = collect_materials(run_dir, ctx.run)
    ctx.log("info", f"待发布物料：{materials.summary()}")

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

    # ---- 2. 素材包先落盘（闸门之前，纯本地、无副作用） ----
    exports = await _prepare_exports(ctx, targets, materials)

    # ---- 3. 逐渠道判定「能不能投」并探测状态 ----
    states = await _probe_channels(ctx, targets)
    rows: list[dict[str, Any]] = []
    for channel in targets:
        state = states[channel.id]
        suitable, reason = channel.supports(materials)
        rows.append({"channel": channel, "state": state, "suitable": suitable, "reason": reason})
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
    )

    # ---- 5. 投递（失败隔离） ----
    confirmed = chosen not in ("draft", "skip")
    if confirmed:
        deliveries = await _deliver(ctx, rows, materials, True)
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
        receipt = {
            "channel": channel.id,
            "channelName": channel.name,
            "status": delivery.status,
            "optionId": chosen,
            "title": materials.title,
            "contentChars": len(materials.body),
            "imageCount": len(materials.images),
            "video": materials.video.name if materials.video else "",
            "tags": materials.tags,
            "source": materials.source,
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
        "material": {
            "title": materials.title, "contentChars": len(materials.body),
            "imageCount": len(materials.images), "video": materials.video.name if materials.video else "",
            "tags": materials.tags,
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
