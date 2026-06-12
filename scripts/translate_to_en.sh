#!/usr/bin/env bash
# 把现有中文 changelog 翻译成英文,补齐 releases/en/。
# 仅用于历史补齐 —— 新版本由 analyze.sh 一次出双语,不走这里。并发 + 幂等。
# 用法:
#   translate_to_en.sh [并发数(默认4)]
#   translate_to_en.sh --one <中文 md 路径>   (内部并发单元)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ROOT

PROMPT='把下面 <stdin> 里这篇中文的 OpenAI Codex 桌面版第三方逆向变更日志,翻译成地道、专业的英文 Markdown。严格要求:
- 保持 YAML frontmatter 结构;title 与 summary 译成英文,其余字段(version/build/released 等)原样不变。
- 章节结构、表格、代码块、链接、数字、版本号、依赖清单完全保留。
- 证据等级标记:【实证】→ [Confirmed],【信号】→ [Signal]。
- 术语用英文,不要中文注解。
- 只输出翻译后的英文 Markdown,从 frontmatter 开始,不要任何前言或说明。
不要执行任何命令,直接输出。'

if [ "${1:-}" = "--one" ]; then
  zh="$2"; base="$(basename "$zh")"; en="$ROOT/releases/en/$base"
  mkdir -p "$ROOT/releases/en"
  [ -f "$en" ] && { echo "[skip] $base"; exit 0; }
  ARGS=(exec --skip-git-repo-check -s read-only --color never -o "$en"
        -c "model_reasoning_effort=${CODEX_REASONING:-medium}")
  [ -n "${CODEX_MODEL:-}" ] && ARGS+=(-m "$CODEX_MODEL")
  if codex "${ARGS[@]}" "$PROMPT" < "$zh" >/dev/null 2>&1; then
    echo "[ok] $base"
  else
    echo "[FAIL] $base"; rm -f "$en"
  fi
  exit 0
fi

CONC="${1:-4}"
mkdir -p "$ROOT/releases/en"
ls "$ROOT"/releases/v*.md | xargs -P "$CONC" -I LINE \
  bash -c '"$ROOT/scripts/translate_to_en.sh" --one "LINE"'
echo "翻译完成。releases/en/ 现有 $(ls "$ROOT/releases/en"/*.md 2>/dev/null | wc -l | tr -d ' ') 篇。"
