#!/usr/bin/env python
"""单独跑 poster 阶段（不经 FastAPI），用来验证与排查。

渲染器与阶段编排都依赖 StageContext，但 poster 本身只用到 work / shared / llm / run / log 一族，
所以这里造一个最小的假 ctx，直接对一个已存在的 run 目录跑 poster 阶段。

用法：
  .venv/bin/python scripts/run_poster.py --run-dir <WS>/var/runs/<runId>
  .venv/bin/python scripts/run_poster.py --run-dir ... --skip-llm   # 复用已有的 poster.spec.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.llm import LLMClient  # noqa: E402
from app.models import RunConfig, SourceInput, new_run  # noqa: E402


class FakeCtx:
    """够 poster 用的最小 StageContext 替身：只实现日志/检查/产物三件事。"""

    def __init__(self, run_dir: Path, run) -> None:
        self.run = run
        self.run_id = run_dir.name
        self.work = run_dir / "poster"
        self.work.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.llm = LLMClient(settings)
        content_md = run_dir / "intake" / "content.md"
        self.shared = {
            "intake": {
                "work": run_dir / "intake",
                "markdown": content_md.read_text(encoding="utf-8") if content_md.is_file() else "",
            }
        }
        self.logs: list[dict] = []
        self.checks: list[dict] = []
        self.artifacts: list[dict] = []

    def log(self, level: str, text: str) -> None:
        self.logs.append({"level": level, "text": text})
        print(f"  [{level}] {text}", flush=True)

    def progress(self, value: float) -> None:
        print(f"  [progress] {value:.2f}", flush=True)

    def check(self, label: str, state: str, detail: str = "") -> None:
        self.checks.append({"label": label, "state": state, "detail": detail})
        print(f"  [check:{state}] {label} — {detail}", flush=True)

    def artifact(self, kind: str, label: str, rel: str, **kw) -> None:
        p = self.work / rel
        self.artifacts.append({"kind": kind, "label": label, "rel": rel, "exists": p.is_file()})
        print(f"  [artifact] {label} -> {rel} ({'有' if p.is_file() else '缺失'})", flush=True)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--skip-llm", action="store_true", help="不调模型，直接用手写的 poster.spec.json 试渲染")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not (run_dir / "understand" / "digest.json").is_file():
        print(f"缺 understand/digest.json：{run_dir}", file=sys.stderr)
        return 2

    digest = json.loads((run_dir / "understand" / "digest.json").read_text(encoding="utf-8"))
    run = new_run(SourceInput(kind="pdf", value="local"), RunConfig(), digest.get("title") or run_dir.name)
    ctx = FakeCtx(run_dir, run)

    from app.modules.poster_stage import run_poster  # noqa: E402  (放最后，避免 import 副作用早于 sys.path)

    if args.skip_llm:
        spec = ctx.work / "poster.spec.json"
        if not spec.is_file():
            print("要 --skip-llm 得先有一份 poster.spec.json", file=sys.stderr)
            return 2
        import app.modules.poster as renderer  # noqa: E402

        rep = renderer.make_poster(spec, ctx.work, preset="conf", out_name="poster",
                                   figures_dir=str(run_dir / "intake" / "images"), fit=True)
        print(json.dumps({k: rep.get(k) for k in ("ok", "scale", "body_px", "width", "height", "overflow", "broken_images")},
                         ensure_ascii=False, indent=1))
        return 0 if rep.get("ok") else 3

    try:
        await run_poster(ctx)
    except Exception as e:
        print(f"\n❌ poster 失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(f"\n✅ poster 完成：{len(ctx.artifacts)} 个产物 / {len(ctx.checks)} 条 check")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
