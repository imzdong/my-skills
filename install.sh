#!/usr/bin/env bash
#
# my-skills 一键安装脚本
#
#   ./install.sh                          # 装全部 skill 到用户级全局目录
#   ./install.sh <skill-name>...          # 只装指定 skill
#   ./install.sh --agent <agent> ...      # 装为 agent-private（仅该 agent 可见）
#   ./install.sh --dir <path> ...         # 装到自定义目录
#   ./install.sh --force                  # 覆盖已存在的同名 skill
#   ./install.sh --list                   # 列出仓库里可装的 skill
#
# 安装位置规则（未显式指定时）：
#   用户级全局   ~/.minimax/skills/<skill-name>/        ← 默认，所有 agent 可见
#   agent 私有   ~/.minimax/agents/<agent>/skills/<name>/
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_SRC="$REPO_ROOT/skills"
DATA_DIR="${DATA_DIR:-$HOME/.minimax}"
TARGET_ROOT=""
AGENT=""
FORCE=0
REQUESTED=()

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage ;;
    --agent)   AGENT="${2:-}"; shift 2 ;;
    --dir)     TARGET_ROOT="${2:-}"; shift 2 ;;
    --force)   FORCE=1; shift ;;
    --list)
      echo "仓库内可安装的 skill："
      for d in "$SKILLS_SRC"/*/; do
        [ -f "$d/SKILL.md" ] || continue
        echo "  - $(basename "$d")"
      done
      exit 0 ;;
    -*) echo "未知参数：$1（用 --help 看用法）" >&2; exit 2 ;;
    *)  REQUESTED+=("$1"); shift ;;
  esac
done

if [ -z "$TARGET_ROOT" ]; then
  if [ -n "$AGENT" ]; then
    TARGET_ROOT="$DATA_DIR/agents/$AGENT/skills"
  else
    TARGET_ROOT="$DATA_DIR/skills"
  fi
fi

# ---- 选取要安装的 skill ----
if [ ${#REQUESTED[@]} -eq 0 ]; then
  SELECTED=()
  for d in "$SKILLS_SRC"/*/; do
    [ -f "$d/SKILL.md" ] || continue
    SELECTED+=("$(basename "$d")")
  done
else
  SELECTED=("${REQUESTED[@]}")
fi

if [ ${#SELECTED[@]} -eq 0 ]; then
  echo "❌ $SKILLS_SRC 下没找到任何含 SKILL.md 的 skill" >&2
  exit 1
fi

echo "安装位置：$TARGET_ROOT"
echo "DATA_DIR ：$DATA_DIR"
echo

installed=0
skipped=0

for name in "${SELECTED[@]}"; do
  src="$SKILLS_SRC/$name"
  if [ ! -f "$src/SKILL.md" ]; then
    echo "❌ 仓库里没有 skill '$name'（用 --list 看可选项）" >&2
    skipped=$((skipped + 1))
    continue
  fi

  dst="$TARGET_ROOT/$name"
  if [ -e "$dst" ] && [ "$FORCE" -ne 1 ]; then
    echo "⚠️  已存在，跳过：$dst（要覆盖加 --force）"
    skipped=$((skipped + 1))
    continue
  fi

  if [ -e "$dst" ]; then
    rm -rf "$dst"
  fi
  mkdir -p "$TARGET_ROOT"
  cp -R "$src" "$dst"
  echo "✅ 已安装 $name → $dst"
  installed=$((installed + 1))
done

echo
echo "──────────────────────────────────────────────"
echo "安装完成：新装 $installed 个，跳过 $skipped 个"

# ---- 依赖自检（只提示，不自动安装）----
PY=""
for p in $(command -v -a python3 2>/dev/null || which -a python3 2>/dev/null || echo python3); do
  if "$p" -c "import ssl, requests" 2>/dev/null; then PY="$p"; break; fi
done
if [ -n "$PY" ]; then
  echo "✅ Python 依赖正常：$PY（ssl + requests 均可用）"
else
  echo "⚠️  没找到同时具备 ssl 和 requests 的 python3。"
  echo "   脚本依赖这两个模块，装依赖前 skill 无法联网工作。"
  echo "   建议：python3 -m venv ~/.venvs/wx && ~/.venvs/wx/bin/pip install requests"
  echo "   详见 docs/INSTALL.md 的「依赖」一节。"
fi

echo
echo "📌 Skill 在【下一个会话】生效，无需重启运行时。"
echo "   验证：让 agent 执行 skill({ name: \"<skill-name>\" })，"
echo "   或在新会话里说「用 <skill-name> 帮我做 X」。"
