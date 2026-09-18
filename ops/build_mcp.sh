#!/usr/bin/env bash
# 重建 ops/bin 下的 Go 二进制（小红书 MCP / 本地 auth 版 / 扫码登录工具），并交叉编译 Windows 版。
#
# 为什么需要这个脚本：这些二进制曾经来路不明（文档没记怎么编译的），
# 2026-09-19 还因为一次批量 sed 改坏过（改坏了二进制里内嵌的源码路径），只能靠源码重建。
#
# 用法：./ops/build_mcp.sh              # 编出 Linux 版 + Windows 版 .exe
#       ./ops/deploy_mcp_windows.sh     # 再把 .exe 部署到 Windows（独立脚本）
# 依赖：var/toolchains 里的 Go 工具链与模块缓存（GOPROXY=off，离线编译）。
set -euo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$WS/apps/xiaohongshu-mcp"
OUT="$WS/ops/bin"
CLEAN="$WS/var/build/xhs-clean"

# Go 工具链：优先用工作区自带的（var/toolchains/go + 模块缓存 → 默认离线可编）；
# 新机器上通常没有它，就回落到系统 go，这时要联网拉模块（GOPROXY 默认开）。
if [ -x "$WS/var/toolchains/go/bin/go" ]; then
  export GOROOT="$WS/var/toolchains/go"
  GO="$WS/var/toolchains/go/bin/go"
  : "${GOPROXY:=off}"
else
  command -v go >/dev/null 2>&1 || {
    echo "缺少 Go 工具链。两条路：" >&2
    echo "  1) 装 Go >= 1.24（https://go.dev/dl/）后重跑本脚本；" >&2
    echo "  2) 或把工具链解压到 var/toolchains/go（离线编译用）。" >&2
    echo "  详见 docs/INSTALL.md §5.2。" >&2
    exit 1
  }
  GO="$(command -v go)"
  : "${GOPROXY:=https://proxy.golang.org,direct}"
fi
export GOPATH="${GOPATH:-$WS/var/toolchains/gopath}"
export GOCACHE="${GOCACHE:-$WS/var/toolchains/gocache}"
export GOPROXY GOFLAGS=-mod=mod
echo "Go: $GO（$("$GO" version | awk '{print $3}')，GOPROXY=$GOPROXY）"

[ -d "$SRC/.git" ] || {
  echo "缺少源码仓库：$SRC" >&2
  echo "一条命令补齐（clone 上游 + 切到登记的 commit + 打本地补丁）：" >&2
  echo "  ./ops/install.sh --with-mcp" >&2
  echo "或手工：见 docs/INSTALL.md §5.2。" >&2
  exit 1
}
mkdir -p "$OUT" "$WS/var/build"

# 编到暂存目录再 mv 改名：直接 `-o` 覆盖一个**正在运行**的二进制会 ETXTBSY（text file busy），
# 而服务没停就要重建是常态（改完 MCP 不想中断前端/后端联调）。改名不受运行中的进程影响。
STAGE="$WS/var/build/stage"
mkdir -p "$STAGE"

echo "== 1/4 干净版（git archive HEAD，不含本地未提交改动）-> $OUT/xiaohongshu-mcp =="
rm -rf "$CLEAN"; mkdir -p "$CLEAN"
git -C "$SRC" archive HEAD | tar -x -C "$CLEAN"
( cd "$CLEAN" && "$GO" build -buildvcs=false -o "$STAGE/mcp-clean" . )
mv -f "$STAGE/mcp-clean" "$OUT/xiaohongshu-mcp"

echo "== 2/4 工作树版（含 auth.go / guard.go 等本地改动）-> $OUT/xiaohongshu-mcp-auth =="
( cd "$SRC" && "$GO" build -buildvcs=false -o "$STAGE/mcp-auth" . )
mv -f "$STAGE/mcp-auth" "$OUT/xiaohongshu-mcp-auth"

echo "== 3/4 扫码登录工具 -> $OUT/xiaohongshu-login =="
( cd "$SRC" && "$GO" build -buildvcs=false -o "$STAGE/login" ./cmd/login )
mv -f "$STAGE/login" "$OUT/xiaohongshu-login"

# 为什么要 Windows 版：Linux 侧是「无头 Chromium + 指纹伪装成 Windows」（见 browser/browser.go 的
# WithFingerprint("")），这本身是可检测特征；在原生 Windows 上可以用真实有头 Chrome，指纹与真实
# OS 一致，风控暴露面更小。交叉编译不需要 cgo，CGO_ENABLED=0 即可产出纯静态 PE。
echo "== 4/4 交叉编译 Windows amd64 -> $OUT/*.exe =="
( cd "$SRC" && CGO_ENABLED=0 GOOS=windows GOARCH=amd64 "$GO" build -buildvcs=false -trimpath -o "$STAGE/mcp.exe" . )
mv -f "$STAGE/mcp.exe" "$OUT/xiaohongshu-mcp.exe"
( cd "$SRC" && CGO_ENABLED=0 GOOS=windows GOARCH=amd64 "$GO" build -buildvcs=false -trimpath -o "$STAGE/login.exe" ./cmd/login )
mv -f "$STAGE/login.exe" "$OUT/xiaohongshu-login.exe"

rm -rf "$CLEAN"
echo
ls -la "$OUT"
echo "--- 冒烟：Linux 版能否打印用法 ---"
# 注意：这里不能直接 `| head -3`。Go 的 usage 较长，head 提前退出会让左侧进程吃到
# SIGPIPE，配上 set -o pipefail 会让整个脚本以 141 退出（明明编译是成功的）。
USAGE="$WS/var/build/mcp-usage.txt"
"$OUT/xiaohongshu-mcp" -h > "$USAGE" 2>&1 || true
head -3 "$USAGE"
echo "--- Windows 版类型校验（应为 PE32+ ... for MS Windows）---"
for f in "$OUT/xiaohongshu-mcp.exe" "$OUT/xiaohongshu-login.exe"; do
  printf '  %-28s %s\n' "$(basename "$f")" "$(file -b "$f")"
done
echo
echo "下一步（可选）：./ops/deploy_mcp_windows.sh   # 把 .exe 部署到 Windows 的 E:\\xhs-test"
