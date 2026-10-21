#!/usr/bin/env python3
"""每日 HF Daily Papers → 小红书定时发布。

流程（由 systemd timer 每天 12:00 触发，关机错过则开机补跑，见 ops/systemd/）：
    1. 从 papercast-server 拿 HF daily papers，按 upvotes 取前 N（默认 5）；
    2. 用 var/state/hf-daily-job/seen.json 去重，已处理过的 arXiv id 不再碰；
    3. 对每篇新论文 POST /api/runs 生成小红书图文，自动放行 publish 闸门（draft，
       只生成、不投递）；
    4. 读 run 的 publish/xiaohongshu/export/publish_request.json，调小红书 MCP 的
       /api/v1/publish（带 schedule_at）排期发布；
    5. 当天成功跑完打 <YYYY-MM-DD>.done 卡，同日重跑直接跳过。

为什么走 schedule_at 而不是草稿：实测小红书网页版草稿只存在浏览器本地
（不落服务端、换浏览器就没了），MCP 的临时 profile 一关草稿即丢，所以改为
排期发布——这是唯一能在服务端留下痕迹的"先攒着、到点发"方式。

用法：
    python3 ops/hf_daily_job.py                 # 正常跑当天
    python3 ops/hf_daily_job.py --force         # 忽略当天 .done 卡
    python3 ops/hf_daily_job.py --dry-run       # 只生成、不调 MCP 排期
    python3 ops/hf_daily_job.py --date 2026-10-01 --limit 2
    python3 ops/hf_daily_job.py --check         # 只体检依赖与状态，不跑
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

WS = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("HF_JOB_STATE_DIR", WS / "var" / "state" / "hf-daily-job"))
PAPERCAST_BASE = os.environ.get("PAPERCAST_BASE", "http://127.0.0.1:8000").rstrip("/")
XHS_MCP_BASE = os.environ.get("XHS_MCP_BASE", "http://127.0.0.1:18060").rstrip("/")
RUNS_DIR = Path(os.environ.get("PAPERCAST_DATA_DIR", WS / "var" / "runs"))

TOP_N = int(os.environ.get("HF_DAILY_TOP", "5"))
RUN_AFTER = os.environ.get("HF_RUN_AFTER", "12:00")            # 每天几点后才允许跑（早于此时刻的触发直接跳过）
PUBLISH_AT = os.environ.get("HF_PUBLISH_AT", "18:00")          # 当天排期起点 HH:MM
PUBLISH_GAP_MIN = int(os.environ.get("HF_PUBLISH_GAP_MIN", "15"))
RUN_TIMEOUT_SEC = int(os.environ.get("HF_RUN_TIMEOUT_SEC", str(30 * 60)))
POLL_INTERVAL_SEC = int(os.environ.get("HF_POLL_INTERVAL_SEC", "5"))
# 并发生成几篇。后端每个 run 是独立 asyncio 任务，但 arXiv 下载有限速、
# LLM 也有配额，默认 2 保守；机器/配额宽裕可调 3-5。
CONCURRENCY = max(1, int(os.environ.get("HF_CONCURRENCY", "2")))
XHS_TITLE_LIMIT = 20
# 小红书正文上限。注意：MCP 会把话题标签内联追加进正文，所以正文本身要留出标签的额度，
# 否则会出现后端 500「当前输入长度为1029，最大长度为1000」（2026-10-11 踩过）。
XHS_CONTENT_LIMIT = 1000

# 首页小红书图文的默认配置：单一 xhs-author 变体、只发小红书。
RUN_CONFIG = {
    "article": {"variants": ["xhs-author"]},
    "publish": {"targets": ["xiaohongshu"], "autoPublish": False},
}


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%F %T')}] {msg}", flush=True)


# ---------- HTTP ----------

def _request(method: str, url: str, body: dict | None = None, timeout: float = 30.0) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        raw = resp.read()
    return json.loads(raw) if raw else None


def health_ok(base: str) -> bool:
    try:
        _request("GET", f"{base}/api/health", timeout=5)
        return True
    except Exception:
        return False


def mcp_health_ok() -> bool:
    try:
        _request("GET", f"{XHS_MCP_BASE}/health", timeout=5)
        return True
    except Exception:
        return False


def fetch_papers(date: str | None, limit: int) -> list[dict[str, Any]]:
    url = f"{PAPERCAST_BASE}/api/hf-daily"
    if date:
        url += f"?date={date}"
    payload = _request("GET", url, timeout=30)
    papers = (payload or {}).get("papers") or []
    papers.sort(key=lambda p: -(p.get("upvotes") or 0))
    return papers[:limit]


# ---------- 去重台账 ----------

def load_seen() -> dict[str, Any]:
    path = STATE_DIR / "seen.json"
    if not path.exists():
        return {"version": 1, "papers": {}}
    try:
        data = json.loads(path.read_text("utf-8"))
        if not isinstance(data, dict) or "papers" not in data:
            return {"version": 1, "papers": {}}
        return data
    except Exception:
        log(f"seen.json 解析失败，按空台账处理：{path}")
        return {"version": 1, "papers": {}}


def save_seen(seen: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_DIR / "seen.json.tmp"
    tmp.write_text(json.dumps(seen, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, STATE_DIR / "seen.json")


# ---------- 生成 ----------

def create_run(paper: dict[str, Any]) -> str:
    body = {
        "source": {"kind": "arxiv", "value": paper["arxivId"], "title": paper.get("title") or ""},
        "config": RUN_CONFIG,
    }
    run = _request("POST", f"{PAPERCAST_BASE}/api/runs", body, timeout=30)
    return run["id"]


def wait_run(run_id: str, timeout_sec: int) -> dict[str, Any]:
    """轮询到 done/failed；遇到闸门自动放行（publish→draft，其余→continue）。"""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        run = _request("GET", f"{PAPERCAST_BASE}/api/runs/{run_id}", timeout=20)
        status = run.get("status")
        if status == "waiting":
            gate_stage = next((s for s in run.get("stages", []) if s.get("status") == "waiting"), None)
            if gate_stage:
                sid = gate_stage["id"]
                option = "draft" if sid == "publish" else "continue"
                try:
                    _request(
                        "POST",
                        f"{PAPERCAST_BASE}/api/runs/{run_id}/stages/{sid}/gate",
                        {"optionId": option},
                        timeout=20,
                    )
                    log(f"  run {run_id} 放行闸门 {sid} → {option}")
                except urllib.error.HTTPError as exc:
                    log(f"  run {run_id} 放行闸门 {sid} 失败（可能已被处理）：{exc.code}")
        if status in ("done", "failed"):
            return run
        time.sleep(POLL_INTERVAL_SEC)
    raise TimeoutError(f"run {run_id} 超过 {timeout_sec}s 未完成")


def read_export(run_id: str) -> dict[str, Any]:
    export_dir = RUNS_DIR / run_id / "publish" / "xiaohongshu" / "export"
    req_path = export_dir / "publish_request.json"
    if req_path.exists():
        data = json.loads(req_path.read_text("utf-8"))
    else:
        data = {
            "title": (export_dir / "title.txt").read_text("utf-8").strip(),
            "content": (export_dir / "content.txt").read_text("utf-8").strip(),
            "tags": (export_dir / "tags.txt").read_text("utf-8").split(),
            "images": sorted(p.name for p in export_dir.glob("p*.jpg")),
        }
    images = [str((export_dir / name).resolve()) for name in (data.get("images") or [])]
    missing = [p for p in images if not Path(p).exists()]
    if missing:
        raise FileNotFoundError(f"导出图片缺失：{missing}")
    data["images"] = images
    data["_exportDir"] = str(export_dir)
    return data


# ---------- 排期与投递 ----------

def calc_title_len(s: str) -> int:
    """与 MCP pkg/xhsutil/title.go 的 CalcTitleLength 保持一致：非 ASCII 计 2，向上取整除以 2。"""
    byte_len = sum(2 if ord(ch) > 127 else 1 for ch in s)
    return (byte_len + 1) // 2


def fit_title(s: str, limit: int = XHS_TITLE_LIMIT) -> str:
    s = s.strip()
    if calc_title_len(s) <= limit:
        return s
    out = ""
    for ch in s:
        if calc_title_len(out + ch) > limit:
            break
        out += ch
    return out.strip() or "论文速览"


def _tag_inline_len(tags: list[str]) -> int:
    """MCP 把话题标签内联进正文（#标签 + 分隔符），这部分同样计入正文长度。"""
    return sum(len(t) + 2 for t in tags)


def fit_content(content: str, tags: list[str], limit: int = XHS_CONTENT_LIMIT) -> str:
    """裁剪正文，给内联标签留出额度，尽量在句末 / 换行处收断。"""
    content = content.strip()
    budget = limit - _tag_inline_len(tags) - 5  # 留 5 字余量，防后台计数与估算有出入
    if budget < 1:
        budget = limit // 2
    if len(content) <= budget:
        return content
    cut = content[:budget]
    best = -1
    for sep in ("\n", "。", "！", "？", "；"):
        i = cut.rfind(sep)
        if i > best:
            best = i
    if best >= budget // 2:
        return cut[: best + 1].rstrip()
    return cut.rstrip()


def schedule_slots(now: datetime, count: int) -> list[str]:
    hh, mm = (int(x) for x in PUBLISH_AT.split(":"))
    base = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if base < now + timedelta(minutes=65):  # MCP 要求至少 1 小时后
        base += timedelta(days=1)
    return [(base + timedelta(minutes=PUBLISH_GAP_MIN * i)).isoformat() for i in range(count)]


def publish_scheduled(export: dict[str, Any], schedule_at: str) -> dict[str, Any]:
    title = fit_title(export.get("title") or "")
    tags = (export.get("tags") or [])[:10]  # MCP/小红书最多 10 个
    content = fit_content(export.get("content") or "", tags)
    body = {
        "title": title,
        "content": content,
        "images": export["images"],
        "tags": tags,
        "schedule_at": schedule_at,
    }
    return _request("POST", f"{XHS_MCP_BASE}/api/v1/publish", body, timeout=420)


# ---------- 主流程 ----------

def run_job(date: str | None, limit: int, force: bool, dry_run: bool) -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    # 单实例锁：cron 的 @reboot 与 12:00、systemd timer、手动触发可能撞在一起，
    # 抢不到锁的直接退出，避免同一批论文被重复生成/排期。
    lock_path = STATE_DIR / "job.lock"
    lock_fh = open(lock_path, "w")
    try:
        import fcntl
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("已有一个实例在跑（job.lock 被占），跳过本次。")
        lock_fh.close()
        return 0
    lock_fh.write(str(os.getpid()))
    lock_fh.flush()

    today = datetime.now().strftime("%F")
    done_marker = STATE_DIR / f"{today}.done"
    if done_marker.exists() and not force:
        log(f"当天（{today}）已跑过，跳过。要重跑加 --force。")
        return 0

    # "到点才跑"：定时器/开机自启都可能在任何时刻触发，未到 RUN_AFTER 且今天没跑过时
    # 不提前生成。开机补跑就靠这条：过了点、当天又没 .done，才真正跑。
    now = datetime.now()
    want = tuple(int(x) for x in RUN_AFTER.split(":"))
    if not force and not dry_run and (now.hour, now.minute) < (want[0], want[1]):
        log(f"未到每天 {RUN_AFTER}，跳过（开机补跑逻辑：到点后若当天没跑过会自动补）。")
        return 0

    if not health_ok(PAPERCAST_BASE):
        log(f"papercast-server 不可达：{PAPERCAST_BASE}（先 ./ops/start_all.sh backend）")
        return 2
    if not dry_run and not mcp_health_ok():
        log(f"小红书 MCP 不可达：{XHS_MCP_BASE}（先 ./ops/start_all.sh mcp）")
        return 2

    seen = load_seen()
    processed: set[str] = set(seen.get("papers", {}).keys())

    papers = fetch_papers(date, limit)
    fresh = [p for p in papers if p.get("arxivId") and p["arxivId"] not in processed]
    log(f"取前 {limit} 篇，去重后剩 {len(fresh)} 篇新论文。")
    if not fresh:
        if not dry_run:
            done_marker.write_text(datetime.now().isoformat(), "utf-8")
        return 0

    slots = schedule_slots(datetime.now().astimezone(), len(fresh))
    ok = failed = 0

    # 先为每篇建 run（快），再按有界并发轮询到完成；每完成一篇立即排期。
    # run 与 paper 的序号绑定，排期时段按榜单名次分配，不随完成顺序乱。
    def generate(index: int, paper: dict[str, Any]) -> tuple[int, dict[str, Any], str, dict[str, Any]]:
        run_id = create_run(paper)
        log(f"  [{index + 1}/{len(fresh)}] {paper['arxivId']} 建 run {run_id}")
        run = wait_run(run_id, RUN_TIMEOUT_SEC)
        if run.get("status") != "done":
            raise RuntimeError(f"run 状态 {run.get('status')}：{run.get('error')}")
        return index, paper, run_id, read_export(run_id)

    log(f"并发生成（最多 {CONCURRENCY} 篇同时跑）…")
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {pool.submit(generate, i, p): (i, p) for i, p in enumerate(fresh)}
        for fut in as_completed(futures):
            i, paper = futures[fut]
            aid = paper["arxivId"]
            try:
                _, _, run_id, export = fut.result()
                log(f"  [{i + 1}/{len(fresh)}] {aid} 生成完成：标题「{export.get('title')}」 图 {len(export['images'])} 张")
                if dry_run:
                    log(f"  [{i + 1}/{len(fresh)}] [dry-run] 跳过排期，计划时间 {slots[i]}")
                else:
                    resp = publish_scheduled(export, slots[i])
                    log(f"  [{i + 1}/{len(fresh)}] 已排期 {slots[i]}：{json.dumps(resp, ensure_ascii=False)[:200]}")
                if not dry_run:
                    # dry-run 不消费台账：否则试跑一次就再也不会真正投递这篇了。
                    seen.setdefault("papers", {})[aid] = {
                        "runId": run_id,
                        "title": export.get("title") or (paper.get("title") or aid),
                        "scheduledAt": slots[i],
                        "recordedAt": int(time.time()),
                    }
                    save_seen(seen)
                ok += 1
            except Exception as exc:  # 单篇失败不拖垮整批
                failed += 1
                log(f"  [{i + 1}/{len(fresh)}] {aid} 失败：{type(exc).__name__}: {exc}")

    if failed == 0 and not dry_run:
        done_marker.write_text(datetime.now().isoformat(), "utf-8")
    log(f"完成：成功 {ok}，失败 {failed}。")
    return 0 if failed == 0 else 1


def due_check() -> int:
    """轻量判断"现在该不该跑"：未到 RUN_AFTER 或当天已打卡 → 不该跑（返回 1）。
    不需要后端/MCP 在线，专供开机自启/登录自启在启动服务前先行判断，避免白起一堆服务。"""
    today = datetime.now().strftime("%F")
    if (STATE_DIR / f"{today}.done").exists():
        log("当天已完成，不必跑。")
        return 1
    now = datetime.now()
    want = tuple(int(x) for x in RUN_AFTER.split(":"))
    if (now.hour, now.minute) < (want[0], want[1]):
        log(f"未到每天 {RUN_AFTER}，不必跑。")
        return 1
    return 0


def check() -> int:
    log(f"WS={WS}")
    log(f"PAPERCAST_BASE={PAPERCAST_BASE} {'OK' if health_ok(PAPERCAST_BASE) else 'DOWN'}")
    log(f"XHS_MCP_BASE={XHS_MCP_BASE} {'OK' if mcp_health_ok() else 'DOWN'}")
    log(f"STATE_DIR={STATE_DIR} exists={STATE_DIR.exists()}")
    seen = load_seen()
    log(f"已记录论文数={len(seen.get('papers', {}))}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="HF daily papers → 小红书定时发布")
    ap.add_argument("--date", default=None, help="HF 日期 YYYY-MM-DD，留空取最新")
    ap.add_argument("--limit", type=int, default=TOP_N, help=f"取前几篇（默认 {TOP_N}）")
    ap.add_argument("--force", action="store_true", help="忽略当天 .done 卡")
    ap.add_argument("--dry-run", action="store_true", help="只生成，不调 MCP 排期")
    ap.add_argument("--check", action="store_true", help="只体检依赖与状态")
    ap.add_argument("--due-check", action="store_true", help="只判断现在该不该跑（0=该跑，1=跳过）")
    args = ap.parse_args()
    if args.due_check:
        return due_check()
    if args.check:
        return check()
    return run_job(args.date, args.limit, args.force, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
