#!/usr/bin/env bash
# 用法：
#   ./ops/install_skills.sh --list     # 只列计划：源目录是否存在、目标路径是什么，不动文件
#   ./ops/install_skills.sh            # 安装（幂等：同名技能目录先清后拷）
#
# 作用：把 reference/upstream/ 里的技能装进 DSH 的技能根，
# 让 dsh 会话的 skill 工具能按名字直接加载。
#
# 现在两批：
#   · 4 个前端设计技能（anthropic/impeccable/taste/spacing）—— 设计审查与规则用；
#   · guizang-social-card-skill（op7418，AGPL-3.0）—— **出图技能**：文章/文案 → 小红书 3:4 图文组图、
#     公众号 21:9 + 1:1 封面对。它的 `validate-social-deck.mjs` 用 playwright 渲染+自检，
#     所以这个技能要多一步：把 `<技能>/node_modules` 软链到 `ops/shot/node_modules`
#     （本机的 playwright 在那里；`~/.npm` 只读，装不了新包，见 apps/papercast-server/docs/07 §5）。
#     出图入口是 `ops/shot/render_social_deck.mjs`（我们自己写的，不是上游的）。
#
# DSH 的技能根（见 @deepseek-ai/dsh-skill-filesystem 的 roots()），按优先级：
#   <repo>/.dsh/skills  >  <repo>/.agents/skills  >  ~/.dsh/skills  >  ~/.agents/skills
# 本脚本默认装到用户级 ~/.agents/skills（不往仓库根目录塞新目录，AGENTS.md §1），
# 可用 SKILLS_ROOT=<dir> 覆盖。每个技能就是一个 <root>/<name>/SKILL.md 目录包；
# 目录名无所谓，dsh 用 SKILL.md frontmatter 里的 name 当技能名（须匹配 ^[a-z0-9]+(-[a-z0-9]+)*$）。
#
# 源仓库的只读克隆与登记见 docs/research/upstream-repos.md（E 组），缺失时先跑 ./ops/sync_upstream.sh。
set -euo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
UP="$WS/reference/upstream"
ROOT="${SKILLS_ROOT:-$HOME/.agents/skills}"
MODE="${1:-install}"

# 安装名(frontmatter name) | 源目录 | 技能说明 | 依赖（可空；playwright = 软链 ops/shot/node_modules）
ENTRIES=(
  "frontend-design|$UP/anthropic-skills/skills/frontend-design|anthropics/skills 官方：审美方向与反模板纪律|"
  "impeccable|$UP/impeccable/.agent/skills/impeccable|pbakaus/impeccable：审计 + 修复分册（layout/typeset/quieter/distill…）|"
  "minimalist-ui|$UP/taste-skill/skills/minimalist-skill|Leonxlnx/taste-skill：简洁高级的禁令清单|"
  "design-spacing-rhythm|$UP/spacing-skill/skills/spacing-skill|buidangminh23/spacing-skill：间距刻度与垂直韵律|"
  "guizang-social-card-skill|$UP/guizang-social-card-skill|op7418/guizang-social-card-skill（AGPL-3.0）：小红书 3:4 图文组图 + 公众号封面对，Editorial × Swiss 两套视觉系统|playwright"
)

echo "技能根：$ROOT"
miss=0
for e in "${ENTRIES[@]}"; do
  IFS='|' read -r name src desc deps <<<"$e"
  if [ -f "$src/SKILL.md" ]; then
    # 去 \r：spacing-skill 的 SKILL.md 是 CRLF，直接取 $2 会带一个回车，导致与安装名比对失败
    fm="$(awk '/^name:/{gsub(/\r/, ""); print $2; exit}' "$src/SKILL.md")"
    printf '[源就绪] %-22s <- %s\n' "$name" "${src#"$UP"/}"
    printf '           frontmatter name=%s · %s\n' "${fm:-?}" "$desc"
    [ "$fm" = "$name" ] || { echo "           !! frontmatter name 与安装名不一致" >&2; miss=$((miss + 1)); }
  else
    echo "[源缺失] $name  ($src/SKILL.md 不存在，先跑 ./ops/sync_upstream.sh)" >&2
    miss=$((miss + 1))
  fi
done

if [ "$MODE" = "--list" ]; then
  [ "$miss" -eq 0 ] && echo "全部就绪（--list 不写文件）" || echo "有 $miss 处问题"
  exit "$([ "$miss" -eq 0 ] && echo 0 || echo 1)"
fi

[ "$miss" -eq 0 ] || { echo "源不齐，放弃安装" >&2; exit 1; }

mkdir -p "$ROOT"
for e in "${ENTRIES[@]}"; do
  IFS='|' read -r name src desc deps <<<"$e"
  rm -rf "${ROOT:?}/$name"
  mkdir -p "$ROOT/$name"
  cp -R "$src/." "$ROOT/$name/"
  echo "[已安装] $ROOT/$name  ($(du -sh "$ROOT/$name" | cut -f1))"
done

# --- 需要 node 依赖的技能：把 node_modules 软链到工作区里已有的那份 ---
# 为什么不 npm install：`~/.npm` 只读（本沙箱），装新包会失败；而 ops/shot 里已有 playwright。
for e in "${ENTRIES[@]}"; do
  IFS='|' read -r name _ _ deps <<<"$e"
  [ "$deps" = playwright ] || continue
  if [ -d "$WS/ops/shot/node_modules/playwright" ]; then
    ln -sfn "$WS/ops/shot/node_modules" "$ROOT/$name/node_modules"
    echo "[依赖] $name/node_modules -> $WS/ops/shot/node_modules (playwright $(node -p "require('$WS/ops/shot/node_modules/playwright/package.json').version" 2>/dev/null || echo '?'))"
  else
    echo "[依赖] $name 需要 playwright，但 $WS/ops/shot/node_modules 不在 —— 先跑 ./ops/install.sh" >&2
  fi
done

# --- impeccable 的引擎二进制 ---
# SKILL.md 里的命令形如 <skill 目录>/scripts/impeccable，launcher 找引擎的顺序是：
#   $IMPECCABLE_BIN > <scripts>/bin/<os>-<arch>/impeccable > ~/.impeccable/bin/... > PATH
# 上游仓库不带二进制，首次要联网下载。为了不写死绝对路径、也不污染 $HOME，
# 先下到工作区 var/toolchains/impeccable（conventions：工具链进 var/），
# 再放到 skill 的兄弟目录 —— 这样任何会话直接用即可，无需设环境变量。
ENGINE_HOME="$WS/var/toolchains/impeccable"
SKILL_SCRIPTS="$ROOT/impeccable/scripts"
case "$(uname -s 2>/dev/null || echo unknown)" in
  Darwin) os=darwin ;; Linux) os=linux ;; *) os=unknown ;; esac
case "$(uname -m 2>/dev/null || echo unknown)" in
  arm64|aarch64) arch=arm64 ;; x86_64|amd64) arch=x64 ;; *) arch=unknown ;; esac
engine_src="$(ls -1 "$ENGINE_HOME"/bin/*/impeccable 2>/dev/null | tail -1 || true)"
if [ -z "$engine_src" ] && [ "$os" != unknown ] && [ "$arch" != unknown ]; then
  echo "[引擎] 本地无缓存，先用 IMPECCABLE_HOME=$ENGINE_HOME 拉取（需联网）"
  mkdir -p "$ENGINE_HOME"
  IMPECCABLE_HOME="$ENGINE_HOME" "$SKILL_SCRIPTS/impeccable" --version >/dev/null 2>&1 || true
  engine_src="$(ls -1 "$ENGINE_HOME"/bin/*/impeccable 2>/dev/null | tail -1 || true)"
fi
if [ -n "$engine_src" ] && [ "$os" != unknown ] && [ "$arch" != unknown ]; then
  mkdir -p "$SKILL_SCRIPTS/bin/$os-$arch"
  cp "$engine_src" "$SKILL_SCRIPTS/bin/$os-$arch/impeccable"
  chmod +x "$SKILL_SCRIPTS/bin/$os-$arch/impeccable"
  echo "[引擎] 已就位：$SKILL_SCRIPTS/bin/$os-$arch/impeccable（$(du -sh "$engine_src" | cut -f1)）"
elif [ -z "$engine_src" ]; then
  echo "[引擎] 没拿到引擎（离线或平台不支持）：impeccable 的 CLI 命令暂不可用，但 SKILL.md 的规则/分册照常可读可用" >&2
fi

echo
echo "装好了。dsh 会话里用 skill 工具按名字加载："
for e in "${ENTRIES[@]}"; do IFS='|' read -r name _ _ _ <<<"$e"; echo "  - $name"; done
echo
echo "出图（guizang）用工作区自己的入口，产物落到 var/ 里："
echo "  node ops/shot/render_social_deck.mjs <task-dir|index.html> [--scale 2]"
echo "  node ~/.agents/skills/guizang-social-card-skill/validate-social-deck.mjs <task-dir>"
