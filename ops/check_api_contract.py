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
    python3 ops/check_api_contract.py --shapes   # 字段/枚举层面的漂移检查（看真实 payload）
退码：0 = 对齐；1 = 前端调了后端没有的接口（或 --shapes 发现字段/枚举漂移）；2 = 导不出后端路由表
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
    import time
    import urllib.error
    import urllib.request

    base = os.environ.get("PAPERCAST_BASE", "http://127.0.0.1:8000")
    print()
    print(f"[live] 探活 {base} （无路径参数的 GET）")
    for p in paths:
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(base + p, timeout=20) as r:
                body = r.read(4000).decode("utf-8", "replace")
            try:
                data = json.loads(body)
                shape = ("dict:" + ",".join(sorted(data)[:8])) if isinstance(data, dict) else (
                    f"list[{len(data)}]" if isinstance(data, list) else type(data).__name__)
            except Exception:
                shape = body[:60].replace("\n", " ")
            dt = time.monotonic() - t0
            # 耗时也报出来：本机常有长 run 在跑，慢是负载信号，不是接口的对错
            slow = " [慢]" if dt > 3 else ""
            print(f"     200 {p:26} {shape} {dt:.2f}s{slow}")
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
            dt = time.monotonic() - t0
            if isinstance(e, TimeoutError):
                # 超时 != 接口有问题：实测 /api/platforms 在负载下要 5.5s。
                # 探针超时只说明「这一次没在 20s 内答」，下结论前先单独 curl 复核。
                print(f"     --- {p:26} 本次超时 {dt:.1f}s（20s 上限，可能是负载）→ 单独 curl 复核再判定")
            else:
                print(f"     --- {p:26} 打不通: {type(e).__name__}")


def frontend_enums() -> dict[str, set[str]]:
    """从 apps/papercast/src/types.ts 抠出联合类型（ArtifactKind / RunStatus / StageStatus …）。

    为什么要抠而不是写死：写死就变成「我以为前端要什么」，而这里要回答的是
    「前端真的声明了什么」—— 前端类型文件是唯一来源。
    """
    src = (WS / "apps" / "papercast" / "src" / "types.ts").read_text(encoding="utf-8")
    out: dict[str, set[str]] = {}
    # 不能用「必须分号结尾」的写法：types.ts 里 ArtifactKind 是多行联合、结尾没有分号，
    # 于是正则会一路吞到后面几个声明里去（我第一版就踩了这个，只抠到 1 个类型）。
    # 正确终止条件是「分号 | 空行 | 下一个 export」，取最早出现的那个。
    pat = re.compile(r"^export type (\w+)\s*=\s*(.*?)(?:;|\n\s*\n|^export )", re.MULTILINE | re.DOTALL)
    for m in pat.finditer(src):
        name, body = m.group(1), m.group(2)
        vals = {x.strip().strip("'\"") for x in body.split("|")}
        vals = {v for v in vals if re.fullmatch(r"[A-Za-z0-9_-]+", v)}
        if 1 <= len(vals) <= 24:
            out[name] = vals
    return out


# 前端 types.ts 里 PaperRun / Stage / Artifact 的必备字段（少一个，页面上就是空/报错）
REQUIRED = {
    "run": ("id", "title", "status", "createdAt", "stages", "config"),
    "stage": ("id", "status", "artifacts"),
    "artifact": ("id", "stageId", "kind", "label", "path"),
}


def shape_check(as_json: bool = False) -> int:
    """字段与枚举层面的漂移检查：路由对得上，不等于字段与状态值对得上。

    只看**跑着的服务真实返回的 payload**，不看后端代码 —— 要看的是「现在发出去的是什么」。
    """
    import urllib.request

    base = os.environ.get("PAPERCAST_BASE", "http://127.0.0.1:8000")
    with urllib.request.urlopen(base + "/api/runs", timeout=20) as r:
        runs = json.loads(r.read().decode())
    if not runs:
        print("[i] /api/runs 为空，没有样本可比对，跳过形状检查")
        return 0
    rid = runs[0].get("id")
    with urllib.request.urlopen(base + "/api/runs/" + rid, timeout=20) as r:
        run = json.loads(r.read().decode())

    problems: list[str] = []
    miss = [k for k in REQUIRED["run"] if k not in run]
    if miss:
        problems.append(f"run 缺字段 {miss}")
    stages = run.get("stages") or []
    for s in stages:
        m = [k for k in REQUIRED["stage"] if k not in s]
        if m:
            problems.append(f"stage {s.get('id')} 缺字段 {m}")
    arts = [a for s in stages for a in (s.get("artifacts") or [])]
    for a in arts:
        m = [k for k in REQUIRED["artifact"] if k not in a]
        if m:
            problems.append(f"artifact {a.get('id')} 缺字段 {m}")

    enums = frontend_enums()
    kinds = sorted({a.get("kind") for a in arts if a.get("kind")})
    st_status = sorted({s.get("status") for s in stages if s.get("status")})
    rn_status = sorted({run.get("status")} - {None})
    for name, values, what in (
        ("ArtifactKind", kinds, "artifact.kind"),
        ("StageStatus", st_status, "stage.status"),
        ("RunStatus", rn_status, "run.status"),
    ):
        allowed = enums.get(name)
        if allowed is None:
            problems.append(f"前端 types.ts 里抠不到 {name} 联合类型（检查提取规则是否失效）")
            continue
        unknown = [v for v in values if v not in allowed]
        if unknown:
            problems.append(f"{what} 出现前端没声明的值 {unknown}（{name}={sorted(allowed)}）")

    if as_json:
        print(json.dumps({"runId": rid, "problems": problems}, ensure_ascii=False, indent=1))
        return 1 if problems else 0
    print(f"[shapes] 样本 {rid}：核对必备字段与枚举（声明来源 apps/papercast/src/types.ts）")
    print(f"  抠到的联合类型 {len(enums)} 个：{', '.join(sorted(enums))}")
    print(f"  实测值 kind={kinds} stage.status={st_status} run.status={rn_status}")
    if problems:
        for p in problems:
            print("  [!!]", p)
    else:
        print("  ok: run/stage/artifact 必备字段齐全，且实测枚举值都在前端声明的联合类型里")
    return 1 if problems else 0


def main() -> int:
    if "--shapes" in sys.argv:
        return shape_check("--json" in sys.argv)
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
