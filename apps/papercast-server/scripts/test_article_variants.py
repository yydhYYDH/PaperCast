#!/usr/bin/env python3
"""只跑 article 阶段：用已有 run 的 intake/ + understand/digest.json 验证「平台 × 人格」变体。

为什么不用整条流水线：understand 阶段要跑十几分钟并且卡在人工闸门上；这个脚本直接复用
已有的事实源，只把 article 阶段的代码路径跑一遍（本脚本不修改原 run 目录）。

用法：
    python scripts/test_article_variants.py <source_run_id> [variant,variant,...] [--out DIR]

示例：
    python scripts/test_article_variants.py run_a7b9460d3953 xhs-analyst,zhihu-newsflash
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

COMPONENT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMPONENT))

from app import styles  # noqa: E402
from app.config import settings  # noqa: E402
from app.models import (  # noqa: E402
    ArticleConfig,
    PaperDigest,
    PaperRun,
    RunConfig,
    SourceInput,
    Stage,
    now_ts,
    new_id,
)
from app.modules.generate import run_article  # noqa: E402
from app.pipeline import Pipeline, StageContext  # noqa: E402
from app.store import RunStore  # noqa: E402


def load_intake(run_dir: Path) -> tuple[dict, PaperDigest]:
    intake = {
        "figures": json.loads((run_dir / "intake" / "figures.json").read_text(encoding="utf-8")),
        "meta": json.loads((run_dir / "intake" / "meta.json").read_text(encoding="utf-8")),
        "markdown": (run_dir / "intake" / "content.md").read_text(encoding="utf-8"),
    }
    digest = PaperDigest.model_validate_json(
        (run_dir / "understand" / "digest.json").read_text(encoding="utf-8")
    )
    return intake, digest


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id", nargs="?", help="已有 intake/ 与 understand/digest.json 的 run id")
    ap.add_argument("variants", nargs="?", default="xhs-author",
                    help="逗号分隔的 variant，如 xhs-analyst,zhihu-newsflash")
    ap.add_argument("--out", default="", help="输出目录（默认 <workspace>/var/tmp/article-variants/<时间戳>）")
    ap.add_argument("--list", action="store_true", help="只打印平台与人格清单")
    args = ap.parse_args()

    if args.list:
        print("平台：", json.dumps(styles.platform_menu(), ensure_ascii=False, indent=1))
        print("人格：", json.dumps(styles.voice_menu(), ensure_ascii=False, indent=1))
        return 0

    source_dir = Path(settings.data_dir) / args.run_id
    if not (source_dir / "understand" / "digest.json").is_file():
        print(f"[err] 找不到事实源：{source_dir}/understand/digest.json", file=sys.stderr)
        return 2
    intake, digest = load_intake(source_dir)

    out = Path(args.out) if args.out else Path(settings.data_dir).parent / "tmp" / "article-variants" / time.strftime("%Y%m%d-%H%M%S")
    store = RunStore(out / "runs", out / "uploads")
    # 卡片渲染要从 run 的 intake/images/ 取原图：这里软链回源 run，保证卡片路径也被真实执行
    src_images = source_dir / "intake" / "images"
    run = PaperRun(
        id=new_id("run"),
        createdAt=now_ts(),
        title=digest.title or args.run_id,
        source=SourceInput(kind="arxiv", value=digest.arxivId or args.run_id),
        status="running",
        stages=[Stage(id="article", label="文章生成", engine="styles", status="running")],
        config=RunConfig(article=ArticleConfig(variants=[v for v in args.variants.split(",") if v])),
        digest=digest,
    )
    store.add(run)
    if src_images.is_dir():
        link = store.stage_dir(run.id, "intake") / "images"
        if not link.exists():
            link.symlink_to(src_images)

    pipeline = Pipeline(store, settings)
    stage = run.stages[0]
    ctx = StageContext(pipeline, run, stage, {"intake": intake})

    print(f"[info] 源 run={args.run_id}  变体={run.config.article.variants}  输出={out}")
    try:
        await run_article(ctx)
    except Exception as e:
        print(f"[fail] {type(e).__name__}: {e}")
        for line in stage.logs[-8:]:
            print(f"   {line.level}: {line.text[:160]}")
        return 1

    print("\n[产物]")
    for a in stage.artifacts:
        print(f"  {a.kind:9s} {a.label[:28]:30s} {a.path}")
    print("\n[校验]")
    for c in stage.checks or []:
        print(f"  {c.state:4s} {c.label}：{c.detail}")
    print("\n[变体]")
    for v in run.articles or []:
        print(f"  {v.id:22s} {v.label:20s} {v.words} 字  {v.url}")
    print(f"\n[文件] {store.stage_dir(run.id, 'article')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
