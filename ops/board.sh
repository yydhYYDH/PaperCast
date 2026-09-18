#!/usr/bin/env bash
# 临时协作看板：让同时开工的多个 agent 在一个地方留言、提问、回答。
#
# 为什么用文件而不是服务：两个 agent 同时写，服务要额外端口和守护进程；
# 追加式 jsonl + O_APPEND 单次写入在 POSIX 上是原子的：谁都不覆盖谁，且零依赖。
# 数据在 var/board/（运行态，不入库），不碰任何人的源码文件。
#
# 用法：
#   ./ops/board.sh say    <我> <内容>                 # 留言
#   ./ops/board.sh ask    <我> <问谁> <内容>          # 提问
#   ./ops/board.sh answer <我> <回谁> <内容>          # 回答
#   ./ops/board.sh read [n]                          # 看最近 n 条（0=全部，默认 20）
#   ./ops/board.sh who                               # 谁说过话
#   ./ops/board.sh render                            # 生成 var/board/board.html 与 digest.md
#
# 建议流程：开工前 read，改完 say（改了哪个文件、对外契约有无变化），
#          跨端的分歧用 ask/answer，不要靠猜。
set -euo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
BOARD="$WS/var/board"
FILE="$BOARD/messages.jsonl"
mkdir -p "$BOARD"

usage() { sed -n '2,20p' "$0"; exit 1; }

cmd="${1:-}"; shift || true
from=""; to=""; text=""
case "$cmd" in
  say)    from="${1:-}"; text="${2:-}";;
  ask)    from="${1:-}"; to="${2:-}"; text="${3:-}";;
  answer) from="${1:-}"; to="${2:-}"; text="${3:-}";;
  read|who|render) ;;
  *) usage;;
esac

case "$cmd" in
  say|ask|answer)
    [ -n "$from" ] && [ -n "$text" ] || usage
    python3 - "$FILE" "$from" "$to" "$cmd" "$text" <<'PY'
import json, os, sys, time
path, sender, to, kind, text = sys.argv[1:6]
rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "from": sender,
       "to": to, "kind": kind, "text": text}
line = (json.dumps(rec, ensure_ascii=False) + "\n").encode()
fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
try:
    os.write(fd, line)      # 单次 write + O_APPEND：并发写不会互相截断
finally:
    os.close(fd)
arrow = (" -> " + to) if to else ""
print(f"[board] {sender}{arrow} ({kind}) 已记入")
PY
    ;;

  read)
    python3 - "$FILE" "${1:-20}" <<'PY'
import json, sys
rows = []
try:
    rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
except FileNotFoundError:
    pass
n = int(sys.argv[2])
if n:
    rows = rows[-n:]
if not rows:
    print("(看板还是空的)"); raise SystemExit
for r in rows:
    mark = {"ask": "?", "answer": "=", "say": "\u00b7"}.get(r.get("kind"), "-")
    to = ("  -> " + r["to"]) if r.get("to") else ""
    print(f"{r['ts']} [{mark}] {r['from']:9}{to:12} {r['text']}")
PY
    ;;

  who)
    python3 - "$FILE" <<'PY'
import json, sys, collections
rows = []
try:
    rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
except FileNotFoundError:
    pass
c = collections.Counter(r["from"] for r in rows)
print("参与者:", ", ".join(f"{k}({v})" for k, v in c.most_common()) or "(无)")
PY
    ;;

  render)
    python3 - "$FILE" "$BOARD" <<'PY'
import html, json, pathlib, sys
rows = []
try:
    rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
except FileNotFoundError:
    pass
board = pathlib.Path(sys.argv[2])
color = {"frontend": "#58a6ff", "backend": "#3fb950", "master": "#d29922"}
out = ['<!doctype html><meta charset="utf-8"><title>协作看板</title>',
       '<style>body{background:#0d1117;color:#e6edf3;font:14px/1.75 ui-monospace,monospace;'
       'max-width:920px;margin:0 auto;padding:32px}.m{border-left:3px solid #30363d;padding:6px 0 6px 12px;'
       'margin:10px 0}.ts{color:#7d8590;font-size:12px}.tag{font-size:11px;padding:1px 6px;'
       'border-radius:99px;background:#21262d;margin-left:6px}</style>',
       f'<h2>协作看板 <span class="ts">{len(rows)} 条</span></h2>']
for r in rows:
    col = color.get(r["from"], "#8b949e")
    to = f' <span class="ts">-&gt; {html.escape(r["to"])}</span>' if r.get("to") else ""
    out.append(f'<div class="m" style="border-color:{col}"><span class="ts">{html.escape(r["ts"])}</span>'
               f'<span class="tag" style="color:{col}">{html.escape(r["from"])}</span>{to}'
               f'<div>{html.escape(r["text"])}</div></div>')
(board / "board.html").write_text("\n".join(out), encoding="utf-8")
(board / "digest.md").write_text("\n".join(
    f'- **{r["ts"]} · {r["from"]}' + (f' -> {r["to"]}' if r.get("to") else "") + f'** {r["text"]}'
    for r in rows) or "(空)", encoding="utf-8")
print("已生成:", board / "board.html", board / "digest.md")
PY
    ;;

  *) usage;;
esac
