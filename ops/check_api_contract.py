#!/usr/bin/env python3
"""前后端接口对接检查：把「后端真实路由」与「前端真实调用」对起来做差集。

为什么需要它：后端路由散在 app/main.py（@app.get 装饰器）、app/channels/routes.py、
app/config_api.py、app/chat_api.py（APIRouter）；前端调用集中在 apps/papercast/src/api/http.ts。
两侧由不同的人并行修改，最容易出的错就是「前端调了后端没有的路径」（必然 404）与
「后端加了路由前端没接」。

踩过的坑（重要）：**不要**用 app.routes + getattr(r, "path") 枚举路由 ——
新版 FastAPI 的 include_router 会保留 _IncludedRouter 包装对象（没有 .path 属性），
那样会整组静默漏掉（我因此误报过 /api/config 与 /api/channels 缺失）。
只有 app.openapi()["paths"] 是准的。

用法：
    python3 ops/check_api_contract.py            # 人读报告
    python3 ops/check_api_contract.py --json     # 机器可用
退码：0 = 对齐；1 = 前端调了后端没有的接口；2 = 导不出后端路由表
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
SERVER = WS / "apps" / "papercast-server"
FRONT_SRC = WS / "apps" / "papercast" / "src"

# 前端唯一的 HTTP 出口写法：this.json<...>('/api/x', { method: 'POST' })
CALL = re.compile(
    r"""this\.json(?:<[^>()]*>)?\(\s*(['\x60])(.*?)\1"""
    r"""(?:\s*,\s*\{(?:(?!\}).)*?method:\s*(['\x60])(\w+)\3)?""",
    re.S,
)
# 裸 fetch('...') / EventSource('...')：只有 /api 开头的算接口，其余是静态资源
FETCH = re.compile(r"""(?:fetch|EventSource)\(\s*(['\x60])(.*?)\1""")


def norm(path: str) -> str:
    """路径参数统一成 {}，这样 /api/runs/{run_id} 与 /api/runs/${id} 能对上。"""
    path = path.strip()
    # 顺序要紧：先剥模板参数，否则 /api/platforms${force ? '?x=1' : ''} 会被 ? 提前切断。
    # $ 在正则里是行尾锚点，必须转义；带 ? 的模板是查询串，整段丢弃；其余当路径参数。
    path = re.sub(r"\$\{([^}]*)}", lambda m: "" if "?" in m.group(1) else "{}", path)
    path = re.sub(r"\{[^}]*\}", "{}", path)     # 手拼参数
    path = path.split("?")[0]
    return path.rstrip("/") or "/"


def backend_routes() -> dict[str, set[str]]:
    """用后端自己的 venv 跑一次 app.openapi()，拿权威路由表。"""
    code = (
        "import json;"
        "from app.main import app;"
        "p=app.openapi()['paths'];"
        "print(json.dumps({k: sorted(v) for k, v in p.items()}))"
    )
    out = subprocess.run(
        [str(SERVER / ".venv" / "bin" / "python"), "-c", code],
        cwd=SERVER, capture_output=True, text=True, timeout=180,
    )
    if out.returncode != 0:
        print("!! 导不出后端路由表：", file=sys.stderr)
        print(out.stderr[-1500:], file=sys.stderr)
        sys.exit(2)
    raw = json.loads(out.stdout.strip().splitlines()[-1])
    return {norm(p): {m.upper() for m in ms} for p, ms in raw.items()}


def frontend_calls() -> dict[tuple[str, str], list[str]]:
    """扫前端源码里的接口调用，返回 {(归一化路径, 方法): [出处...]}。"""
    found: dict[tuple[str, str], list[str]] = {}
    for f in sorted(FRONT_SRC.rglob("*")):
        if f.suffix not in {".ts", ".vue"}:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        rel = str(f.relative_to(WS))
        for _q, path, _q2, method in CALL.findall(text):
            if not path.startswith("/"):
                continue
            found.setdefault((norm(path), (method or "GET").upper()), []).append(rel)
        for _q, path in FETCH.findall(text):
            if not path.startswith("/api"):
                continue
            found.setdefault((norm(path), "GET"), []).append(rel + " [裸 fetch]")
    return found


def live_probe(paths: list[str]) -> None:
    """对无路径参数的 GET 打一次真实服务：证明「代码里有」和「跑着的有」是一回事。"""
    import urllib.error
    import urllib.request

    base = os.environ.get("PAPERCAST_BASE", "http://127.0.0.1:8000")
    print()
    print(f"[live] 探活 {base} （无路径参数的 GET）")
    for p in paths:
        try:
            with urllib.request.urlopen(base + p, timeout=8) as r:
                body = r.read(4000).decode("utf-8", "replace")
            try:
                data = json.loads(body)
                shape = ("dict:" + ",".join(sorted(data)[:8])) if isinstance(data, dict) else (
                    f"list[{len(data)}]" if isinstance(data, list) else type(data).__name__)
            except Exception:
                shape = body[:60].replace("\n", " ")
            print(f"     200 {p:26} {shape}")
        except urllib.error.HTTPError as e:
            raw = e.read(600).decode("utf-8", "replace")
            # 紧凑 JSON 没有空格：只认 "loc":["query","name"] 这种
            try:
                missing = re.findall(r'"loc":\s*\[\s*"query"\s*,\s*"([^"]+)"\s*\]', raw)
            except Exception:
                missing = []
            if e.code == 422 and missing:
                # 必填查询参数：不是坏了，是探活没带参。前端有没有传对要另外核。
                print(f"     {e.code} {p:26} [需参数] {', '.join(missing)}（前端是否传对需单独核）")
            else:
                print(f"     {e.code} {p:26} {raw[:80].replace(chr(10), ' ')}")
        except Exception as e:
            print(f"     --- {p:26} 打不通: {type(e).__name__}")


def main() -> int:
    be_paths = backend_routes()
    fe = frontend_calls()
    # 必须比 (路径, 方法) 二元组：只比路径会永远求不出交集（踩过）
    be = {(p, m) for p, ms in be_paths.items() for m in ms}
    both = sorted(be & set(fe))
    only_fe = sorted(set(fe) - be)
    only_be = sorted(be - set(fe))

    if "--json" in sys.argv:
        print(json.dumps({
            "matched": [{"path": p, "method": m} for p, m in both],
            "frontend_only": [{"path": p, "method": m, "at": sorted(set(fe[(p, m)]))} for p, m in only_fe],
            "backend_only": [{"path": p, "method": m} for p, m in only_be],
        }, ensure_ascii=False, indent=1))
        return 1 if only_fe else 0

    print(f"后端路由 {len(be)} 个(路径,方法) | 前端调用 {len(fe)} 处 | 双向对上 {len(both)} 处")
    print()
    if only_fe:
        print("[!!] 前端调了但后端没有（一定 404）：")
        for p, m in only_fe:
            print(f"     {m:6} {p}    <- {', '.join(sorted(set(fe[(p, m)])))}")
    else:
        print("[OK] 前端调的每个接口后端都有")
    print()
    if only_be:
        print("[i] 后端有、前端没接（给 CLI/其它消费方也可能，逐条判断）：")
        for p, m in only_be:
            print(f"     {m:6} {p}")
    else:
        print("[OK] 后端没有多余路由")
    print()
    print("[已对上]")
    for p, m in both:
        print(f"     {m:6} {p}")
    if "--live" in sys.argv:
        live_probe(sorted(p for p, m in be if m == "GET" and "{" not in p))
    return 1 if only_fe else 0


if __name__ == "__main__":
    sys.exit(main())
