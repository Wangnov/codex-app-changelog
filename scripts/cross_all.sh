#!/usr/bin/env bash
# 批量跨平台回填:遍历 mirror 里"含 macOS 配对"的 release,对相邻对跑 cross_pair。
# 幂等(已是双平台则跳过)+ 流式删(每对跑完删 ~4GB 大文件,46GB 不囤)。
# 用法: cross_all.sh [limit]   limit=最多跑几对(0/省略=全部 22 对)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIMIT="${1:-0}"

# 含 macOS 配对的 release tags。关键:按 macOS short version(而非 build)去重。
# 官方全量包按 Codex-darwin-arm64-<short>.zip 命名(URL 不含 build),同一 short 的多个
# build(如 26.609.41114 的 b3888/b3942)下载的是同一个 zip,backfill_pair 无法区分;
# 若两者都保留,相邻对会退化成 short 自比 —— backfill 把同一个包和自己 diff,macOS 侧
# 全空、零发现,还可能用空篇覆盖好篇。故每个 short 只留最大 build 的 tag(代表该 short 的
# 最终状态),再按 build 递增排序(build 全局单调 = 版本顺序;不用 createdAt,force 重镜像会乱序)。
TAGS=()
while IFS= read -r t; do TAGS+=("$t"); done < <(
  gh release list --repo Wangnov/codex-app-mirror --limit 60 --json tagName \
    --jq '.[].tagName' | grep -E '\-mac(-arm64)?-[0-9]' \
    | sed -nE 's/.*-win-([0-9.]+)-mac(-arm64)?-([0-9.]+)-b([0-9]+).*/\3\t\4\t\1\t&/p' \
    | sort -t$'\t' -k1,1V -k2,2n -k3,3V \
    | awk -F'\t' '{keep[$1]=$0} END{for (k in keep) print keep[k]}' \
    | sort -t$'\t' -k2,2n | cut -f4)

echo "含 macOS 配对的 release: ${#TAGS[@]} 个 → $(( ${#TAGS[@]} - 1 )) 对"
done_n=0; i=1
while [ $i -lt ${#TAGS[@]} ]; do
  from="${TAGS[$((i-1))]}"; to="${TAGS[$i]}"; i=$((i+1))
  short=$(echo "$to" | sed -nE 's/.*-mac(-arm64)?-([0-9.]+)-b[0-9]+.*/\2/p')
  [ -z "$short" ] && continue
  mkdir -p "$ROOT/work/regen"
  if [ -f "$ROOT/work/regen/${short}.done" ]; then echo "[skip] v${short}(本批已完成)"; continue; fi
  # FORCE=1 绕过"已是双平台"跳过,用于全量重生成(配合 work/regen/*.done 断点续跑)。
  if [ "${FORCE:-0}" != "1" ] && [ -f "$ROOT/releases/v${short}.md" ] && grep -q 'win_version' "$ROOT/releases/v${short}.md" 2>/dev/null; then
    echo "[skip] v${short}(已是双平台)"; continue
  fi
  W="$ROOT/work/cross/$short"; mkdir -p "$W"
  echo "[cross] $from -> $to"
  if bash "$ROOT/scripts/cross_pair.sh" "$from" "$to" "$W" > "$W/run.log" 2>&1; then
    cp "$W/changelog.md" "$ROOT/releases/v${short}.md"
    mkdir -p "$ROOT/releases/en"
    cp "$W/changelog-en.md" "$ROOT/releases/en/v${short}.md" 2>/dev/null || true
    touch "$ROOT/work/regen/${short}.done"
    echo "[ok] v${short}"
  else
    echo "[FAIL] v${short}(见 $W/run.log)"
  fi
  rm -rf "$W/mac" "$W/win"   # 流式删大文件,保留 run.log
  done_n=$((done_n+1))
  [ "$LIMIT" -gt 0 ] && [ "$done_n" -ge "$LIMIT" ] && break
done
echo "完成。releases/ 现有 $(ls "$ROOT/releases"/v*.md | wc -l | tr -d ' ') 篇。"
