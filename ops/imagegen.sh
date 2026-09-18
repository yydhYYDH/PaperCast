#!/usr/bin/env bash
# ops/imagegen.sh —— 文生图入口（跨组件）：调 baoyu-image-gen 的官方 API 后端出图。
#
# 密钥：var/secrets/imagegen.env（gitignored，建议 chmod 600），内容形如
#   DASHSCOPE_API_KEY=sk-xxx
# 也可换成任意 baoyu-image-gen 支持的 provider 的 key（OPENAI_API_KEY / GOOGLE_API_KEY / ...）。
#
# 用法：
#   ops/imagegen.sh --prompt-file prompts/01-hero.md --image out.png --ar 16:9
#   ops/imagegen.sh --prompt "a cat" --image cat.png --size 1024x1024
#   IMAGEGEN_PROVIDER=google IMAGEGEN_MODEL=gemini-3-pro-image ops/imagegen.sh ...
#
# 约定：
# - 默认 provider/model 走千问（dashscope）；命令行再传 --provider/--model 会覆盖它（参数后者胜）。
# - 出图前必须先把完整 prompt 落盘成文件（prompts/NN-*.md），这是可复现与换后端的前提。
# - 不在这里打印任何 key。
set -euo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
SKILL="$WS/reference/baoyu-research/repo/skills/baoyu-image-gen/scripts/main.ts"
SECRETS="${IMAGEGEN_ENV:-$WS/var/secrets/imagegen.env}"

[ -f "$SKILL" ] || { echo "找不到 baoyu-image-gen：$SKILL" >&2; exit 2; }

if [ -f "$SECRETS" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$SECRETS"
  set +a
else
  echo "警告：没有 $SECRETS —— 未配置任何图像 API key 时出图会失败" >&2
fi

# 沙箱下 ~/.npm 只读，npx 会直接失败；缓存必须落在 var/ 内（见 docs/conventions.md）
export npm_config_cache="${npm_config_cache:-$WS/var/cache/npm}"
export npm_config_tmp="${npm_config_tmp:-$WS/var/npm-tmp}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$WS/var/cache}"
mkdir -p "$npm_config_cache" "$npm_config_tmp"

# 默认后端放前面，用户参数放后面 —— baoyu-image-gen 按 argv 顺序解析，后者覆盖前者
exec npx -y bun "$SKILL" \
  --provider "${IMAGEGEN_PROVIDER:-dashscope}" \
  --model "${IMAGEGEN_MODEL:-qwen-image-2.0-pro}" \
  "$@"
