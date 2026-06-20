#!/usr/bin/env bash
# 重生成指定的 macOS-only changelog 篇:从该篇现有 frontmatter 读 previous_version /
# compared_from / released,用 full-pair 管线(含修复后的 viteStringDiff)重建中英双语。
# 断点续跑(work/regen/<ver>.done)。git 已推送的旧篇是兜底,失败可 checkout 恢复。
# 用法: regen_maconly.sh <version> [<version>...]
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MARK="$ROOT/work/regen"; mkdir -p "$MARK"
get(){ grep -m1 "^$1:" "$2" | sed -E "s/^$1:[[:space:]]*//; s/\"//g"; }
for to in "$@"; do
  [ -f "$MARK/${to}.done" ] && { echo "[skip] v${to}(本批已完成)"; continue; }
  f="$ROOT/releases/v${to}.md"
  [ -f "$f" ] || { echo "[FAIL] v${to} 无现有篇,取不到 from/日期"; continue; }
  from=$(get previous_version "$f"); fd=$(get compared_from "$f"); td=$(get released "$f")
  [ -z "$from" ] && { echo "[FAIL] v${to} 缺 previous_version"; continue; }
  W="$ROOT/work/macregen/${to}"; mkdir -p "$W"
  echo "[mac] ${from} -> ${to} (${fd} -> ${td})"
  if bash "$ROOT/scripts/backfill_pair.sh" "$from" "$to" "$W" "$fd" "$td" > "$W/run.log" 2>&1 \
     && bash "$ROOT/scripts/analyze.sh" "$W" >> "$W/run.log" 2>&1; then
    cp "$W/changelog.md" "$ROOT/releases/v${to}.md"
    mkdir -p "$ROOT/releases/en"
    [ -f "$W/changelog-en.md" ] && cp "$W/changelog-en.md" "$ROOT/releases/en/v${to}.md"
    touch "$MARK/${to}.done"; echo "[ok] v${to}"
  else
    echo "[FAIL] v${to}(见 $W/run.log)"
  fi
  rm -rf "$W"/*.zip "$W/previous-extract" "$W/latest-reconstructed" \
         "$W/asar-prev-extract" "$W/asar-latest-extract"
done
echo "=== REGEN MACONLY DONE ==="
