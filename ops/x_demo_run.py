"""造一份「X 素材包」的演示 run（给作品库看的界面样本）：复制一份真跑过的 run，
在**只启用 X** 的隔离设置下跑一遍 M3 的发布阶段 —— 用来在作品库里看
「X（推特）」这一格长什么样、回执是什么状态。

隔离点：settings.channels = ["x"]，targets = ["x"]。X 不触网（material-only），所以这一跑
不可能碰到任何真账号；生成的 run 目录用完可整个删掉。
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import shutil
import sys
import time
from pathlib import Path

WS = Path(__file__).resolve().parents[1]          # ops/x_demo_run.py → 工作区根
sys.path.insert(0, str(WS / "apps" / "papercast-server"))

from app.config import settings                   # noqa: E402
from app.modules import publish as publish_mod     # noqa: E402
from app.pipeline import Pipeline, StageContext    # noqa: E402
from app.store import RunStore                     # noqa: E402

SRC = os.environ.get("X_DEMO_SRC", "run_720e83bdae91")   # 有 en-analyst.md 的真 run（英文 thread 在）
DST = os.environ.get("X_DEMO_DST", "run_x0demo0001")


async def main() -> None:
    runs, uploads = WS / "var" / "runs", WS / "var" / "uploads"
    src, dst = runs / SRC, runs / DST
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)
    shutil.rmtree(dst / "publish", ignore_errors=True)   # 回执重写，别把原 run 的回执带过来

    data = json.loads((dst / "run.json").read_text(encoding="utf-8"))
    data["id"] = DST
    data["createdAt"] = int(time.time() * 1000)
    data["status"] = "done"
    data["config"]["publish"]["targets"] = ["x"]
    for st in data.get("stages", []):
        if st["id"] == "publish":
            st.update({"status": "running", "artifacts": [], "checks": [], "logs": []})
            st.pop("gate", None)
    (dst / "run.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    # 跳过社区运营：这一步要 LLM，演示脚本里不需要（也避免在没配 key 的 shell 里干等）
    from app.modules import community as community_mod

    async def _skip_community(ctx, *a, **k):
        ctx.log("info", "演示脚本：跳过社区运营（不需要 LLM）")
        return {}

    community_mod.run_community = _skip_community

    store = RunStore(runs, uploads)
    store.load_all()
    run = store.get(DST)
    assert run is not None, "克隆的 run 没被 store 读到"
    isolated = dataclasses.replace(settings, data_dir=runs, upload_dir=uploads, channels=["x"])
    pipe = Pipeline(store, isolated)
    stage = next(s for s in run.stages if s.id == "publish")
    ctx = StageContext(pipe, run, stage, {})
    task = asyncio.create_task(publish_mod.run_publish(ctx))
    for _ in range(600):
        if stage.gate is not None or task.done():
            break
        await asyncio.sleep(0.1)
    if stage.gate is not None:
        print("闸门 detail:\n" + stage.gate.detail)
        pipe.resolve_gate(run.id, "publish", "continue")   # 放行也只落素材包
    await asyncio.wait_for(task, timeout=180)
    # 独立调用 run_publish 时没有 pipeline 收尾，状态要自己落：不然盘上永远停在 running，
    # 后端一重启就被当成「重启中断」标成 failed。
    stage.status = "done"
    stage.gate = None
    run.status = "done"
    run.error = None
    store.save(run)

    work = store.stage_dir(DST, "publish")
    print("\n回执总表:", json.dumps(json.loads((work / "receipts.json").read_text(encoding="utf-8")),
                                   ensure_ascii=False)[:600])
    print("\n素材包:", sorted(p.name for p in (work / "x" / "export").iterdir()))


asyncio.run(main())

# 用法：apps/papercast-server/.venv/bin/python ops/x_demo_run.py
#       （跑完重启后端才能在界面上看到；清掉：rm -rf var/runs/run_x0demo0001）