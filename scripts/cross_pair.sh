#!/usr/bin/env bash
# 跨平台对照:对一对 mirror release(tag 编码 win+mac 版本),分别 diff macOS 与 Windows,
# 合并两份事实包,喂同一个 codex 会话产出双平台对照 changelog(双语)。
# 用法: cross_pair.sh <from_tag> <to_tag> <work_dir>
set -euo pipefail
FROM_TAG="${1:?from release tag}"; TO_TAG="${2:?to release tag}"; WORK="${3:?work dir}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$WORK"

# 从 mirror tag 解析 macOS arm64 版本(支持 -mac-X 与 -mac-arm64-X 两种格式)
mac_ver() { echo "$1" | sed -nE 's/.*-mac(-arm64)?-([0-9.]+)-b[0-9]+.*/\2/p'; }
MAC_FROM="$(mac_ver "$FROM_TAG")"; MAC_TO="$(mac_ver "$TO_TAG")"
[ -n "$MAC_FROM" ] && [ -n "$MAC_TO" ] || { echo "tag 里没有 macOS 版本,跳过(可能是纯 Windows 批次)" >&2; exit 2; }

echo "== [macOS] $MAC_FROM → $MAC_TO =="
/bin/bash "$ROOT/scripts/backfill_pair.sh" "$MAC_FROM" "$MAC_TO" "$WORK/mac"   # 含 build_llm_input

echo "== [Windows] $FROM_TAG → $TO_TAG =="
/bin/bash "$ROOT/scripts/win_pair.sh" "$FROM_TAG" "$TO_TAG" "$WORK/win"
CL_PLATFORM=windows python3 "$ROOT/scripts/build_llm_input.py" --work "$WORK/win"

echo "== 合并跨平台事实包 =="
REL_DATE="$(gh release view "$TO_TAG" --repo Wangnov/codex-app-mirror --json createdAt --jq '.createdAt[0:10]' 2>/dev/null || echo '')"
{
  echo "本批次发布日期(请用于 frontmatter 的 released 字段): ${REL_DATE:-未知}"
  echo "=== PLATFORM: macOS ==="; cat "$WORK/mac/llm-input.md"
  echo; echo "=== PLATFORM: Windows ==="; cat "$WORK/win/llm-input.md"
} > "$WORK/cross-input.md"

echo "== codex 跨平台对照(双语)=="
BI="$WORK/cross-bi.md"
ARGS=(exec --skip-git-repo-check -s read-only --color never -o "$BI"
      -c "model_reasoning_effort=${CODEX_REASONING:-xhigh}")
[ -n "${CODEX_MODEL:-}" ] && ARGS+=(-m "$CODEX_MODEL")
codex "${ARGS[@]}" "$(cat "$ROOT/prompts/cross-changelog.md")" < "$WORK/cross-input.md"
awk -v zh="$WORK/changelog.md" -v en="$WORK/changelog-en.md" '
  /^===CODEX-CHANGELOG-LANG-SPLIT===[[:space:]]*$/ {seen=1; next}
  !seen {print > zh} seen {print > en}' "$BI"
echo "✓ 完成: $WORK/changelog.md(中) / $WORK/changelog-en.md(英)"
