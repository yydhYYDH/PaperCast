#!/usr/bin/env bash
# 一轮监督：把「两个 agent 并行改前后端」这件事里我该看的东西一次看完。
#
# 为什么要脚本：监督的价值在于每轮口径一致、可比对，而不是我每次凭记忆抽查。
# 每轮固定看六件事：
#   1) 看板增量（他们回了什么、问我什么，必须第一时间答/裁决）
#   2) 接口对账（前端调了后端没有的 = 一定 404；后端加了前端没接 = 待接项）
#   3) 前端类型检查（并发改动的第一道破口）
#   4) 后端能否干净导入（语法/循环导入被改坏的信号）
#   5) 合并冲突标记残留（两边同时写同一文件的直接痕迹）
#   6) 最近 10 分钟被改的文件（谁在动哪块，判断是否撞车）
#   7) 在途 run 状态（重启后端前必看：02:35 真发生过一次重启，把别人的在途 run 判死了）
#   8) 后端单测（AGENTS.md §4 的口径；红要重跑一次再判定，中途状态很常见）
#   9) 静默时长（按源码量「谁还在改」，排除我跑 pytest 产生的 __pycache__）
#
# 用法：./ops/supervise.sh [--fast]     --fast 跳过 vue-tsc（约 40s），只做接口与增量
set -euo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
cd "$WS"
FAST=0
[ "${1:-}" = "--fast" ] && FAST=1
SEEN="$WS/var/board/.last_seen"
mkdir -p "$WS/var/board"
touch "$SEEN"

echo "=== 1) 看板增量（自上次监督）==="
python3 - "$WS/var/board/messages.jsonl" "$SEEN" <<'PY'
import json, pathlib, sys
msgs, seen_path = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
rows = [json.loads(l) for l in msgs.read_text(encoding="utf-8").splitlines() if l.strip()] if msgs.exists() else []
seen = int(seen_path.read_text().strip() or 0) if seen_path.exists() else 0
fresh = rows[seen:]
who = [r for r in fresh if r["from"] != "master"]
print(f"  新帖 {len(fresh)} 条，其中别人发的 {len(who)} 条")
for r in who:
    to = f" -> {r['to']}" if r.get("to") else ""
    print(f"  [{r['kind']}] {r['from']}{to}: {r['text'][:400]}")
if not who:
    print("  （他们没回话 —— 可能还没读写看板，需要人转达）")
seen_path.write_text(str(len(rows)), encoding="utf-8")
PY

echo
echo "=== 2) 接口对账 ==="
python3 ops/check_api_contract.py 2>&1 | head -20 || true

echo
echo "=== 3) 后端能否干净导入 ==="
( cd apps/papercast-server && timeout 60 .venv/bin/python -c "
from app.main import app
p = app.openapi()['paths']
print(f'  ok: {len(p)} 条路由')
" 2>&1 | tail -3 ) || echo "  !! 导入失败（看上面 traceback）"

echo
echo "=== 4) 合并冲突标记残留 ==="
if grep -rn -e '^<<<<<<< ' -e '^>>>>>>> ' apps/ docs/ 2>/dev/null | head -5; then
  echo "  !! 有冲突标记，立刻处理"
else
  echo "  ok: 无残留"
fi

echo
echo "=== 5) 最近 10 分钟被改的文件 ==="
find apps -type f \( -name '*.py' -o -name '*.ts' -o -name '*.vue' \) -newermt '-10 minutes' 2>/dev/null | sed 's|^|  |' | head -25

echo
echo "=== 6) 在途 run 状态（重启后端前必看）==="
python3 - "$WS" <<'PY'
import glob, json, os, sys
WS = sys.argv[1]
rows = []
for f in glob.glob(os.path.join(WS, "var", "runs", "*", "run.json")):
    try:
        d = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    # 光有 id/标题看不出「卡在哪一段」，而重启要不要等正是由这一段决定的：
    # 在 video 段重启 = 白扔几分钟 ffmpeg 渲染。所以带上当前段与已完成段数。
    stages = d.get("stages") or []
    cur = next((s.get("id") for s in stages if s.get("status") == "running"), "")
    fin = len([s for s in stages if s.get("status") in ("done", "skipped")])
    rows.append((d.get("createdAt") or 0, d.get("id", "?"), d.get("status", "?"), (d.get("title") or "")[:28], cur, fin, len(stages)))
def n(st):
    return len([r for r in rows if r[2] == st])
print("  共 %d 条 | running %d | waiting %d | failed %d | done %d" % (len(rows), n("running"), n("waiting"), n("failed"), n("done")))
for ts, rid, st, t, cur, fin, tot in sorted([r for r in rows if r[2] in ("running", "waiting")]):
    where = ("当前段 %s（已完成 %d/%d 段）" % (cur, fin, tot)) if cur else "（无正在跑的段）"
    print("   %-8s %s %s %s" % (st, rid, t, where))
if n("running"):
    print("  !! 有 run 正在跑：现在重启后端 = 它们会被判 failed(INTERRUPTED)；先等，或先在看板喊一声再动")
if n("waiting"):
    print("  !! 有 run 卡在 waiting：B1 旧伤（重启前留下的），重启也不会自己继续 —— 别当成「在跑」")
PY

echo
echo "=== 7) 后端单测（AGENTS.md §4 的口径）==="
# 并发改动中「红」常是改到一半的中间态：红一次不算数，隔开重跑仍红才报。
BACK="$WS/apps/papercast-server"
if [ -x "$BACK/.venv/bin/python" ]; then
  ( cd "$BACK" && timeout 150 .venv/bin/python -m pytest -q 2>&1 | tail -3 | sed 's|^|  |' )
  echo "  （提示：若红，先隔一两分钟重跑再判定 —— 实测有过 2 failed→14 passed 的中间态）"
else
  echo "  !! 找不到 .venv/bin/python，跳过"
fi

if [ "$FAST" = "0" ]; then
  echo
  echo "=== 8) 前端类型检查 ==="
  ( cd apps/papercast && timeout 150 npx vue-tsc --noEmit 2>&1 | tail -8 ) && echo "  ok: vue-tsc 通过" || echo "  !! vue-tsc 有错（看上面）"
fi

echo
echo "=== 9) 静默时长（判断「两端是否已停止改动」的口径）==="
# 为什么单列一项：我第一版量「最后改动」时量到了 __pycache__/*.pyc（那是我自己跑 pytest 生成的），
# 差点把「我在跑测试」误判成「后端在改代码」。这里按源码后缀 walk，且跳过 __pycache__/node_modules。
python3 - "$WS" <<'PY'
import os, sys, time
WS = sys.argv[1]
areas = (
    ("前端 src", "apps/papercast/src", (".ts", ".vue")),
    ("后端 app", "apps/papercast-server/app", (".py",)),
    ("后端 tests", "apps/papercast-server/tests", (".py",)),
    ("ops", "ops", (".sh", ".py")),
    ("docs", "docs", (".md",)),
)
now = time.time()
for label, rel, exts in areas:
    newest, path = 0.0, ""
    for root, dirs, files in os.walk(os.path.join(WS, rel)):
        if "__pycache__" in root or "node_modules" in root or ".venv" in root:
            continue
        for fn in files:
            if not fn.endswith(exts):
                continue
            p = os.path.join(root, fn)
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if m > newest:
                newest, path = m, os.path.relpath(p, WS)
    if not newest:
        print("  %-10s 无文件" % label)
        continue
    print("  %-10s %s（%d 分钟前）%s" % (label, time.strftime("%H:%M:%S", time.localtime(newest)), int((now - newest) // 60), path))
PY

echo
echo "=== 监督口径提醒 ==="
echo "  前端调后端没有的 = 一定 404，最高优先级，立刻在看板问责"
echo "  两套接口并存（/api/channels vs /api/platforms）= 迟早漂移，必须定归属"
echo "  同一文件被两条轨道同时改 = 直接裁决单一写者，别让它们自己商量"
