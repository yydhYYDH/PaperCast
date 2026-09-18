#!/usr/bin/env bash
# 用法：
#   ./ops/sync_upstream.sh --list     # 只核对：登记 HEAD vs 本地 HEAD，不动任何文件
#   ./ops/sync_upstream.sh            # 缺失的按登记 commit 取回来（固定 commit）
#
# 作用：按 docs/research/upstream-repos.md 的登记表复现 reference/upstream/ 下的只读参考克隆。
# 登记表是唯一输入（解析表格的「目录 | 上游链接 | HEAD」列），本脚本不维护第二份清单。
# 幂等且非破坏性：已存在的目录只核对，不覆盖、不更新、不删除；不一致只报告。
# 上游是纯参考资料（conventions.md §7），所以固定的是**登记的 commit**，不是默认分支 HEAD。
# 测试用：UPSTREAM_DEST=<目录>、UPSTREAM_REG=<单行登记表> 可缩小作用范围。
#
# 为什么不是 `git fetch --depth 1 origin <sha>`：GitHub 不允许按任意 sha 取对象
# （实测报 `fatal: couldn't find remote ref <sha>`，服务端未开 allowReachableSHA1InWant）。
# 所以固定 commit 的做法是 treeless 部分克隆拿到提交图，再 checkout 目标 sha。
set -euo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
REG="${UPSTREAM_REG:-$WS/docs/research/upstream-repos.md}"
DEST="${UPSTREAM_DEST:-$WS/reference/upstream}"
SCRATCH="$WS/var/scratch"
MODE="${1:-sync}"

[ -f "$REG" ] || { echo "找不到登记表：$REG" >&2; exit 1; }
mkdir -p "$DEST" "$SCRATCH"
# 每次运行用独立的临时文件：固定文件名会被上一次（尤其是单仓测试）的残留覆盖，
# 排查「怎么一个都没匹配上」时正好踩过这个坑。
LIST="$(mktemp "$SCRATCH/upstream.list.XXXXXX")"
trap 'rm -f "$LIST"' EXIT

# 只收「链接列含 https://」且「HEAD 列是 7..40 位十六进制」的行，避免把说明性表格也当成仓库
# 用 match() 取子串，而不是 gsub 去反引号：单元格形如 `2bb9d7e` 被包裹，
# 靠 gsub 清理会被反引号/转义规则咬到（第一版就在那里静默漏掉了全部 23 行）。
awk -F'|' '
  NF >= 5 {
    if ($3 !~ /https:\/\//) next;
    if (!match($2, /[A-Za-z0-9_.-]+/)) next;
    name = substr($2, RSTART, RLENGTH);
    if (!match($4, /[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]+/)) next;
    cm = substr($4, RSTART, RLENGTH);
    if (!match($3, /https:\/\/[^)]+/)) next;
    printf "%s\t%s\t%s\n", name, substr($3, RSTART, RLENGTH), cm;
  }' "$REG" > "$LIST"

total=0; ok=0; missing=0; mismatch=0; failed=0
while IFS="$(printf '\t')" read -r name url cm; do
  [ -n "$name" ] || continue
  total=$((total + 1))
  dir="$DEST/$name"

  if [ -d "$dir/.git" ]; then
    cur="$(git -C "$dir" log -1 --format=%h 2>/dev/null || echo '?')"
    case "$cm" in
      "$cur"*) echo "[一致] $name  $cm"; ok=$((ok + 1)) ;;
      *)       echo "[不符] $name  登记=$cm 本地=$cur  （不自动改，请人工核对后改登记表或重克隆）"; mismatch=$((mismatch + 1)) ;;
    esac
    continue
  fi

  missing=$((missing + 1))
  if [ "$MODE" = "--list" ]; then
    echo "[缺失] $name  $url  $cm"
    continue
  fi

  echo "[克隆] $name  $url  $cm"
  rm -rf "$dir"
  if git clone -q --filter=blob:none --no-checkout "$url" "$dir" \
    && git -C "$dir" checkout -q "$cm"; then
    echo "       -> 已固定到 $(git -C "$dir" log -1 --format='%h %cs' 2>/dev/null || echo "$cm")"
  else
    echo "       -> 固定 commit 失败，退回默认分支浅克隆（快，但只在登记后上游未动时才等于登记 commit）"
    rm -rf "$dir"
    if git clone -q --depth 1 --no-tags "$url" "$dir"; then
      echo "       -> 已克隆默认分支 $(git -C "$dir" log -1 --format=%h 2>/dev/null || echo '?')；若与登记不符，请更新本表 HEAD"
    else
      echo "       -> 克隆失败：$name" >&2
      failed=$((failed + 1))
    fi
  fi
done < "$LIST"

echo
echo "共 $total 个：一致 $ok · 不符 $mismatch · 缺失 $missing · 失败 $failed"
if [ "$mismatch" -eq 0 ] && [ "$failed" -eq 0 ]; then exit 0; else exit 1; fi
