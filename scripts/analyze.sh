#!/usr/bin/env bash
# 用本地 codex exec 把事实包(llm-input.md)归纳成第三方 changelog。
# 用法: scripts/analyze.sh <work-dir>
# 可选环境变量: CODEX_MODEL 覆盖模型(默认用 codex 配置里的模型)。
set -euo pipefail

WORK="${1:?用法: analyze.sh <work-dir>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROMPT_FILE="$ROOT/prompts/changelog.md"
INPUT="$WORK/llm-input.md"
OUT="$WORK/changelog.md"

[ -f "$INPUT" ] || { echo "缺少 $INPUT —— 先跑 build_llm_input.py" >&2; exit 1; }
[ -f "$PROMPT_FILE" ] || { echo "缺少提示词 $PROMPT_FILE" >&2; exit 1; }

ARGS=(exec --skip-git-repo-check -s read-only --color never -o "$OUT")
[ -n "${CODEX_MODEL:-}" ] && ARGS+=(-m "$CODEX_MODEL")

echo "[analyze] codex exec → $OUT (model=${CODEX_MODEL:-codex 默认}, 事实包 $(wc -c < "$INPUT") 字节)"
codex "${ARGS[@]}" "$(cat "$PROMPT_FILE")" < "$INPUT"
echo "[analyze] 完成: $OUT ($(wc -l < "$OUT") 行)"
