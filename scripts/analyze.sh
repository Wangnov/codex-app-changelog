#!/usr/bin/env bash
# 用本地 codex exec 把事实包(llm-input.md)归纳成第三方 changelog。
# 用法: scripts/analyze.sh <work-dir>
# 可选环境变量: CODEX_MODEL 覆盖模型(默认用 codex 配置里的模型)。
set -euo pipefail

WORK="${1:?用法: analyze.sh <work-dir>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROMPT_FILE="$ROOT/prompts/changelog.md"
INPUT="$WORK/llm-input.md"
OUT="$WORK/changelog.md"          # 中文版
EN="$WORK/changelog-en.md"        # 英文版
BI="$WORK/changelog-bi.md"        # codex 一次输出的双语合并体

[ -f "$INPUT" ] || { echo "缺少 $INPUT —— 先跑 build_llm_input.py" >&2; exit 1; }
[ -f "$PROMPT_FILE" ] || { echo "缺少提示词 $PROMPT_FILE" >&2; exit 1; }

# 固定 reasoning effort,避免 CI(无 config.toml)退化到 none 而拉低质量。
ARGS=(exec --skip-git-repo-check -s read-only --color never -o "$BI"
      -c "model_reasoning_effort=${CODEX_REASONING:-xhigh}")
[ -n "${CODEX_MODEL:-}" ] && ARGS+=(-m "$CODEX_MODEL")

echo "[analyze] codex exec → $BI (双语, model=${CODEX_MODEL:-codex 默认}, 事实包 $(wc -c < "$INPUT") 字节)"
codex "${ARGS[@]}" "$(cat "$PROMPT_FILE")" < "$INPUT"

# 按分隔符把双语合并体拆成中文版 + 英文版
awk -v zh="$OUT" -v en="$EN" '
  /^===CODEX-CHANGELOG-LANG-SPLIT===[[:space:]]*$/ { seen=1; next }
  !seen { print > zh }
  seen  { print > en }
' "$BI"
[ -s "$EN" ] || echo "[analyze] ⚠️ 英文版为空,检查提示词/分隔符" >&2
echo "[analyze] 完成: 中文 $(wc -l < "$OUT") 行 / 英文 $(wc -l < "$EN" 2>/dev/null || echo 0) 行"
