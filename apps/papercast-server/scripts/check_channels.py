#!/usr/bin/env python
"""渠道层自检：不依赖 LLM、不碰真实 var/，跑一遍「物料 → 素材包 → 闸门 → 回执」的完整 M3。

用法（在 apps/papercast-server 下）：
  .venv/bin/python scripts/check_channels.py            # 离线：契约、适配规则、素材包、未确认必须拒绝
  .venv/bin/python scripts/check_channels.py --live     # 额外真实探测三个通道服务（小红书/知乎/B站）
  .venv/bin/python scripts/check_channels.py --run      # 真实跑一遍 M3 编排（合成 run，闸门选 draft）
  .venv/bin/python scripts/check_channels.py --run --option continue --with-video

为什么要有它：渠道层最容易出的错是「悄悄降级」——某个平台挂了却假装发成功、
或素材包没落盘就把运行判成完成。这个脚本专门盯这些点。
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.channels import registry                      # noqa: E402
from app.channels.base import Materials                # noqa: E402
from app.config import settings                        # noqa: E402
from app.models import PublishConfig, RunConfig, SourceInput, new_run  # noqa: E402
from app.modules import publish as publish_mod         # noqa: E402
from app.pipeline import Pipeline, StageContext        # noqa: E402
from app.store import RunStore                         # noqa: E402

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)

FAILED: list[str] = []
OK = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global OK
    if cond:
        OK += 1
        print(f"  ✓ {label}" + (f" —— {detail}" if detail else ""))
    else:
        FAILED.append(label)
        print(f"  ✗ {label}" + (f" —— {detail}" if detail else ""))


def sample_materials(*, with_video: bool, run_id: str, tmp: Path) -> Materials:
    images = []
    for i in (1, 2):
        p = tmp / f"p{i}.png"
        p.write_bytes(PNG_1PX)
        images.append(p)
    video = None
    if with_video:
        video = tmp / "x_narrated.mp4"
        video.write_bytes(b"\x00" * 1024)   # 只测编排，不真上传
    cover = tmp / "cover.png"
    cover.write_bytes(PNG_1PX)
    return Materials(title="论文太长记不住？三张图讲清", body="正文" * 80, tags=["论文", "科研"],
                     images=images, video=video, cover=cover, run_id=run_id,
                     source="https://arxiv.org/abs/2510.05096")


def offline_checks(tmp: Path) -> None:
    print("\n[1] 契约与注册表")
    channels = registry.build_all(settings)
    check("内置三个渠道", [c.id for c in channels] == ["xiaohongshu", "zhihu", "bilibili"],
          "、".join(c.name for c in channels))
    check("别名 xhs → xiaohongshu", registry.canonical("xhs") == "xiaohongshu")
    got, problems = registry.resolve_targets(settings, ["xhs", "zhihu", "bilibili", "not-a-platform"])
    check("目标解析含别名", [c.id for c in got] == ["xiaohongshu", "zhihu", "bilibili"])
    check("未知渠道不静默丢弃", [p["id"] for p in problems] == ["not-a-platform"], json.dumps(problems, ensure_ascii=False))
    _, disabled = registry.resolve_targets(settings, ["wechat"])
    check("未实现的渠道如实报 unknown", disabled and disabled[0]["reason"] == "unknown")

    print("\n[2] 素材适配规则（平台差异留在 adapter 里）")
    no_video = sample_materials(with_video=False, run_id="run_offline", tmp=tmp)
    with_video = sample_materials(with_video=True, run_id="run_offline", tmp=tmp)
    xhs, zhihu, bili = channels
    check("小红书要图片", xhs.supports(no_video)[0] and "图文笔记" in xhs.supports(no_video)[1])
    check("小红书有视频走视频笔记", xhs.supports(with_video)[1] == "视频笔记")
    long_title = dataclasses.replace(no_video, title="标题" * 30)
    ok, why = xhs.supports(long_title)
    check("小红书标题计重超限被本地拦下", not ok and "计重" in why, why)
    check("知乎纯文本可投", zhihu.supports(no_video)[0])
    ok, why = bili.supports(no_video)
    check("B站缺视频时如实报不可投", not ok and "缺视频" in why, why)
    check("B站有视频可投", bili.supports(with_video)[0])
    check("知乎能力声明不含视频（没接就不吹）", "video" not in zhihu.capabilities)

    print("\n[3] 兜底素材包（渠道服务全挂也要能手动发）")
    out = tmp / "exports"
    for channel in channels:
        info = asyncio.run(channel.export(with_video if channel.id == "bilibili" else no_video, out / channel.id))
        files = set(info["files"])
        needed = {"title.txt", "content.txt", "tags.txt", "publish_request.json", "README.txt"}
        check(f"{channel.name} 素材包齐全", needed <= files, "、".join(sorted(files)))
        check(f"{channel.name} 手动发布指引非空", (out / channel.id / "README.txt").stat().st_size > 50)
    check("B站素材包含视频", "video.mp4" in (out / "bilibili" / "publish_request.json").read_text(encoding="utf-8"))

    print("\n[4] 未过闸门绝不允许真投")
    for channel in channels:
        delivery = asyncio.run(channel.publish(with_video if channel.id == "bilibili" else no_video, confirmed=False))
        check(f"{channel.name} 未确认 → blocked/NOT_CONFIRMED",
              delivery.status == "blocked" and delivery.error["code"] == "NOT_CONFIRMED")


def duplicate_guard_checks(tmp: Path) -> None:
    """重复投递防护：上游投过的证据必须能被 M3 看见（否则人会手滑重复投不可逆动作）。"""
    print("\n[5] 重复投递防护")
    fake = tmp / "fake_run"
    (fake / "video").mkdir(parents=True)
    check("没投过时不误报", publish_mod.previous_delivery(fake) == {})
    (fake / "video" / "upload_result.json").write_text(
        json.dumps({"status": "success", "bv": "BV1DveU6GEPR", "url": "https://www.bilibili.com/video/BV1DveU6GEPR"}),
        encoding="utf-8")
    prev = publish_mod.previous_delivery(fake)
    check("能识别上游投递回执", prev.get("bvid") == "BV1DveU6GEPR" and prev.get("channel") == "bilibili", json.dumps(prev, ensure_ascii=False))

    real = sorted(settings.data_dir.glob("*/video/upload_result.json"))
    if real:
        got = publish_mod.previous_delivery(real[0].parents[1])
        check("真实 run 的回执可解析", bool(got.get("bvid")), f"{real[0].parents[1].name} → {got.get('bvid')}")


async def run_m3(tmp: Path, option: str, with_video: bool, already: bool) -> None:
    print(f"\n[6] 真实跑一遍 M3 编排（闸门选 {option}）")
    runs, uploads = tmp / "runs", tmp / "uploads"
    store = RunStore(runs, uploads)
    pipe = Pipeline(store, dataclasses.replace(settings, data_dir=runs, upload_dir=uploads))
    run = new_run(SourceInput(kind="arxiv", value="2510.05096", title="示例论文"),
                  RunConfig(publish=PublishConfig(targets=["xiaohongshu", "zhihu", "bilibili"])),
                  "示例论文")
    store.add(run)
    run_dir = store.dir(run.id)
    (run_dir / "article" / "export").mkdir(parents=True)
    (run_dir / "article" / "export" / "title.txt").write_text("论文太长记不住？三张图讲清", encoding="utf-8")
    (run_dir / "article" / "export" / "content.txt").write_text("正文内容。\n\n#论文 #科研", encoding="utf-8")
    (run_dir / "article" / "cards").mkdir(parents=True)
    for i in (1, 2):
        (run_dir / "article" / "cards" / f"p{i}.png").write_bytes(PNG_1PX)
    if with_video:
        (run_dir / "video").mkdir(parents=True)
        (run_dir / "video" / "x_narrated.mp4").write_bytes(b"\x00" * 4096)
        # 故意埋一个「已经投过」的回执，验证 M3 会把它顶到闸门上
        (run_dir / "video" / "run_nested").mkdir(exist_ok=True)
        (run_dir / "video" / "run_nested" / "other.mp4").write_bytes(b"\x00" * 2048)
        if already:
            (run_dir / "video" / "upload_result.json").write_text(
                json.dumps({"bv": "BV1DveU6GEPR", "url": "https://www.bilibili.com/video/BV1DveU6GEPR"}),
                encoding="utf-8")

    materials = publish_mod.collect_materials(run_dir, run)
    check("物料收集：标题/正文/图片/来源",
          materials.title.startswith("论文太长") and materials.images and "arxiv.org" in materials.source,
          materials.summary())
    check("物料收集：视频", (materials.video is not None) == with_video)
    if with_video:
        check("选片：顶层成片优先，不抓嵌套目录", materials.video.name == "x_narrated.mp4", materials.video.name)

    stage = next(s for s in run.stages if s.id == "publish")
    stage.status = "running"
    ctx = StageContext(pipe, run, stage, {})
    task = asyncio.create_task(publish_mod.run_publish(ctx))
    for _ in range(200):                       # 等闸门出现
        if stage.gate is not None or task.done():
            break
        await asyncio.sleep(0.05)
    check("闸门出现且 detail 列清各渠道", stage.gate is not None and "本次发布计划" in stage.gate.detail)
    if stage.gate is not None:
        print("    闸门 detail:\n" + "\n".join("      " + line for line in stage.gate.detail.splitlines()))
        check("闸门给出 export 兜底说明", "export" in stage.gate.detail or "素材包" in stage.gate.detail)
        if already:
            check("已投递过 → 闸门明确警告", "已经投递过一次" in stage.gate.detail)
            check("已投递过 → stage.check 记录", any(c.label == "历史投递" for c in stage.checks))
        pipe.resolve_gate(run.id, "publish", option)
    await asyncio.wait_for(task, timeout=180)

    work = store.stage_dir(run.id, "publish")
    receipts = json.loads((work / "receipts.json").read_text(encoding="utf-8"))
    print("    回执总表: " + json.dumps({k: receipts[k] for k in ("optionId", "status", "published", "failed")}, ensure_ascii=False))
    check("回执总表三渠道齐全", set(receipts["channels"]) == {"xiaohongshu", "zhihu", "bilibili"})
    check("每个渠道都有独立回执文件",
          all((work / cid / "receipt.json").is_file() for cid in receipts["channels"]))
    check("每个渠道都有素材包", all((work / cid / "export" / "title.txt").is_file() for cid in receipts["channels"]))
    check("兼容旧别名 xhs_receipt.json", (work / "xhs_receipt.json").is_file())
    if option == "draft":
        check("draft：所有渠道 status=draft（没有真投）",
              {r["status"] for r in receipts["channels"].values()} == {"draft"})
        check("draft：结论 check 为 run", any(c.label == "发布结果" and c.state == "run" for c in stage.checks))
    else:
        check("continue：回执带状态", all(r["status"] for r in receipts["channels"].values()))
        check("continue：状态如实（没账号就不会是 published）",
              all(r["status"] == "published" for r in receipts["channels"].values() if r["state"]["state"] == "ready") or
              all(r["status"] != "published" for r in receipts["channels"].values()))
    check("stage.checks 覆盖每个渠道", sum(1 for c in stage.checks if c.label.startswith("渠道状态：")) == 3)
    check("产物已登记（receipts.json）", any(a.label == "发布回执总表" for a in stage.artifacts))


async def live_checks() -> None:
    print("\n[7] 真实探测三个通道服务（--live）")
    for channel in registry.build_all(settings):
        state = await channel.preflight()
        print(f"  · {channel.name:<4} {state.state:<15} {state.detail[:70]}")
        check(f"{channel.name} 探测有明确结论", state.state in
              ("ready", "login_required", "offline", "unconfigured", "blocked"),
              f"{state.state} / hint={'有' if state.hint or state.ready else '无'}")
        check(f"{channel.name} 不可用时必须给下一步动作", state.ready or bool(state.hint))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="真实探测通道服务")
    parser.add_argument("--run", action="store_true", help="真跑一遍 M3 编排")
    parser.add_argument("--option", default="draft", choices=["continue", "draft", "skip"])
    parser.add_argument("--with-video", action="store_true", help="带上假视频（让 B 站渠道进入可投状态）")
    parser.add_argument("--already-published", action="store_true", help="额外埋一份「已投递过」回执，验证重复投递防护")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="papercast-channels-"))
    try:
        print(f"临时工作目录：{tmp}")
        offline_checks(tmp)
        duplicate_guard_checks(tmp)
        if args.live:
            asyncio.run(live_checks())
        if args.run:
            asyncio.run(run_m3(tmp, args.option, args.with_video, args.already_published))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n===== {OK} 项通过 / {len(FAILED)} 项失败 =====")
    for label in FAILED:
        print(f"  ✗ {label}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
