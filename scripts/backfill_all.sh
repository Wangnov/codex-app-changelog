#!/usr/bin/env bash
# 历史回填编排:枚举 Homebrew cask 记录的全部版本,对相邻对并发跑 full-pair diff + changelog。
# 每对跑完即删大文件(zip/解包),只保留 changelog 与 diff JSON,把磁盘峰值压在并发数 × ~3GB。
#
# 用法:
#   backfill_all.sh --list-only                 只打印待回填的版本对
#   backfill_all.sh [--concurrency N] [--limit K]  跑回填(默认并发 3,K>0 时只跑最近 K 对)
#   backfill_all.sh --one <from> <to> <fd> <td>  内部并发单元(勿手动调用)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ROOT

# ---- 内部单元:跑一对 ----
if [ "${1:-}" = "--one" ]; then
  FROM="$2"; TO="$3"; FD="${4:-}"; TD="${5:-}"
  [ -f "$ROOT/releases/v${TO}.md" ] && { echo "[skip] v${TO} 已存在"; exit 0; }
  W="$ROOT/work/backfill/${FROM}__${TO}"; mkdir -p "$W"
  if /bin/bash "$ROOT/scripts/backfill_pair.sh" "$FROM" "$TO" "$W" "$FD" "$TD" > "$W/run.log" 2>&1 \
     && bash "$ROOT/scripts/analyze.sh" "$W" >> "$W/run.log" 2>&1; then
    cp "$W/changelog.md" "$ROOT/releases/v${TO}.md"
    mkdir -p "$ROOT/releases/en"
    [ -f "$W/changelog-en.md" ] && cp "$W/changelog-en.md" "$ROOT/releases/en/v${TO}.md"
    echo "[ok] $FROM -> $TO"
  else
    echo "[FAIL] $FROM -> $TO  (见 $W/run.log)"
  fi
  # 流式清理:删大文件,保留 changelog/json/log 便于复核
  rm -rf "$W"/*.zip "$W/previous-extract" "$W/latest-reconstructed" \
         "$W/asar-prev-extract" "$W/asar-latest-extract"
  exit 0
fi

# ---- 编排 ----
CONC=3; LIMIT=0; LIST_ONLY=0
while [ $# -gt 0 ]; do case "$1" in
  --concurrency) CONC="$2"; shift 2;;
  --limit) LIMIT="$2"; shift 2;;
  --list-only) LIST_ONLY=1; shift;;
  *) echo "未知参数: $1" >&2; exit 1;;
esac; done

# 从 cask commit 历史枚举 "version date"(按版本升序、每版取最早一次记录)
TSV="$(gh api '/repos/Homebrew/homebrew-cask/commits?path=Casks/c/codex-app.rb&per_page=100' \
  --jq '.[] | "\(.commit.committer.date[0:10]) \(.commit.message | split("\n")[0])"' \
  | sed -nE 's/^([0-9-]+) codex-app (26\.[0-9]+\.[0-9]+)$/\2 \1/p' \
  | awk '!seen[$1]++' \
  | sort -t. -k2,2n -k3,3n)"

# 相邻对:上一行=from,当前行=to(不用关联数组,兼容 bash 3.2)
TASKS=(); prev_v=""; prev_d=""
while read -r v d; do
  [ -z "$v" ] && continue
  [ -n "$prev_v" ] && TASKS+=("$prev_v $v $prev_d $d")
  prev_v="$v"; prev_d="$d"
done <<< "$TSV"

if [ "$LIMIT" -gt 0 ] && [ ${#TASKS[@]} -gt "$LIMIT" ]; then
  TASKS=("${TASKS[@]: -$LIMIT}")
fi

echo "枚举 $(echo "$TSV" | grep -c .) 个版本,${#TASKS[@]} 对待回填,并发 ${CONC}"
if [ "$LIST_ONLY" = "1" ]; then printf '%s\n' "${TASKS[@]}"; exit 0; fi

printf '%s\n' "${TASKS[@]}" | xargs -P "$CONC" -I LINE \
  bash -c 'set -- LINE; "$ROOT/scripts/backfill_all.sh" --one "$1" "$2" "$3" "$4"'

echo ""
echo "回填完成。releases/ 下现有 $(ls "$ROOT/releases" | wc -l | tr -d ' ') 篇 changelog。"
