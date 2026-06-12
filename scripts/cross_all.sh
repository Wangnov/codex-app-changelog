#!/usr/bin/env bash
# 批量跨平台回填:遍历 mirror 里"含 macOS 配对"的 release,对相邻对跑 cross_pair。
# 幂等(已是双平台则跳过)+ 流式删(每对跑完删 ~4GB 大文件,46GB 不囤)。
# 用法: cross_all.sh [limit]   limit=最多跑几对(0/省略=全部 22 对)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIMIT="${1:-0}"

# 含 macOS 配对的 release tags,按时间正序(bash 3.2 兼容,不用 mapfile)
TAGS=()
while IFS= read -r t; do TAGS+=("$t"); done < <(
  gh release list --repo Wangnov/codex-app-mirror --limit 60 --json tagName,createdAt \
    --jq 'sort_by(.createdAt)|.[].tagName' | grep -E '\-mac(-arm64)?-[0-9]')

echo "含 macOS 配对的 release: ${#TAGS[@]} 个 → $(( ${#TAGS[@]} - 1 )) 对"
done_n=0; i=1
while [ $i -lt ${#TAGS[@]} ]; do
  from="${TAGS[$((i-1))]}"; to="${TAGS[$i]}"; i=$((i+1))
  short=$(echo "$to" | sed -nE 's/.*-mac(-arm64)?-([0-9.]+)-b[0-9]+.*/\2/p')
  [ -z "$short" ] && continue
  if [ -f "$ROOT/releases/v${short}.md" ] && grep -q 'win_version' "$ROOT/releases/v${short}.md" 2>/dev/null; then
    echo "[skip] v${short}(已是双平台)"; continue
  fi
  W="$ROOT/work/cross/$short"; mkdir -p "$W"
  echo "[cross] $from -> $to"
  if bash "$ROOT/scripts/cross_pair.sh" "$from" "$to" "$W" > "$W/run.log" 2>&1; then
    cp "$W/changelog.md" "$ROOT/releases/v${short}.md"
    mkdir -p "$ROOT/releases/en"
    cp "$W/changelog-en.md" "$ROOT/releases/en/v${short}.md" 2>/dev/null || true
    echo "[ok] v${short}"
  else
    echo "[FAIL] v${short}(见 $W/run.log)"
  fi
  rm -rf "$W/mac" "$W/win"   # 流式删大文件,保留 run.log
  done_n=$((done_n+1))
  [ "$LIMIT" -gt 0 ] && [ "$done_n" -ge "$LIMIT" ] && break
done
echo "完成。releases/ 现有 $(ls "$ROOT/releases"/v*.md | wc -l | tr -d ' ') 篇。"
