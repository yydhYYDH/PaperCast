#!/usr/bin/env bash
# 重建 ops/bin 下的三个 Go 二进制（小红书 MCP / 本地 auth 版 / 扫码登录工具）。
#
# 为什么需要这个脚本：这三个二进制曾经来路不明（文档没记怎么编译的），
# 2026-09-19 还因为一次批量 sed 改坏过（改坏了二进制里内嵌的源码路径），只能靠源码重建。
#
# 用法：./ops/build_mcp.sh
# 依赖：var/toolchains 里的 Go 工具链与模块缓存（GOPROXY=off，离线编译）。
set -euo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$WS/apps/xiaohongshu-mcp"
OUT="$WS/ops/bin"
CLEAN="$WS/var/build/xhs-clean"

export GOROOT="$WS/var/toolchains/go"
export GOPATH="$WS/var/toolchains/gopath"
export GOCACHE="$WS/var/toolchains/gocache"
export GOPROXY=off GOFLAGS=-mod=mod

GO="$GOROOT/bin/go"
[ -x "$GO" ] || { echo "缺少 Go 工具链：$GOROOT" >&2; exit 1; }
[ -d "$SRC/.git" ] || { echo "缺少源码仓库：$SRC" >&2; exit 1; }
mkdir -p "$OUT" "$WS/var/build"

echo "== 1/3 干净版（git archive HEAD，不含本地未提交改动）-> $OUT/xiaohongshu-mcp =="
rm -rf "$CLEAN"; mkdir -p "$CLEAN"
git -C "$SRC" archive HEAD | tar -x -C "$CLEAN"
( cd "$CLEAN" && "$GO" build -buildvcs=false -o "$OUT/xiaohongshu-mcp" . )

echo "== 2/3 工作树版（含 auth.go 等本地改动）-> $OUT/xiaohongshu-mcp-auth =="
( cd "$SRC" && "$GO" build -buildvcs=false -o "$OUT/xiaohongshu-mcp-auth" . )

echo "== 3/3 扫码登录工具 -> $OUT/xiaohongshu-login =="
( cd "$SRC" && "$GO" build -buildvcs=false -o "$OUT/xiaohongshu-login" ./cmd/login )

rm -rf "$CLEAN"
echo
ls -la "$OUT"
echo "--- 冒烟：能否打印用法 ---"
"$OUT/xiaohongshu-mcp" -h 2>&1 | head -3
