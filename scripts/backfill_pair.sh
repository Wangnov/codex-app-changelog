#!/usr/bin/env bash
# 历史回填:对超出 appcast 增量(delta)窗口的两个历史版本,下载两个官方全量包直接比较。
# 与 delta 模式的区别:没有官方增量包,也没有 appcast 的 EdDSA 签名;信任根改为
# Apple 公证 + OpenAI Developer ID 代码签名(codesign / spctl)+ 全量包 SHA-256。
#
# 用法: backfill_pair.sh <from_version> <to_version> <work_dir> [from_date] [to_date]
#   日期(YYYY-MM-DD)可选,用于 changelog 的发布日期;一般从 Homebrew cask commit 取。
set -euo pipefail
FROM="${1:?from version}"; TO="${2:?to version}"; WORK="${3:?work dir}"
FROM_DATE="${4:-}"; TO_DATE="${5:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="https://persistent.oaistatic.com/codex-app-prod"
mkdir -p "$WORK"

dl() {  # url dest —— 已存在且非空则跳过(便于复用/续跑)
  [ -s "$2" ] && return 0
  curl -fL --retry 5 --retry-all-errors --connect-timeout 20 --speed-time 60 --speed-limit 1024 "$1" -o "$2"
}
PREV_ZIP="$WORK/previous-$FROM.zip"; LATEST_ZIP="$WORK/latest-$TO.zip"
echo "[backfill ${FROM} -> ${TO}] 下载全量包…"
dl "$BASE/Codex-darwin-arm64-$FROM.zip" "$PREV_ZIP"
dl "$BASE/Codex-darwin-arm64-$TO.zip" "$LATEST_ZIP"

PREV_ROOT="$WORK/previous-extract"; LATEST_ROOT="$WORK/latest-reconstructed"
PREV_APP="$PREV_ROOT/Codex.app"; LATEST_APP="$LATEST_ROOT/Codex.app"
rm -rf "$PREV_ROOT" "$LATEST_ROOT"; mkdir -p "$PREV_ROOT" "$LATEST_ROOT"
echo "[backfill ${FROM} -> ${TO}] 解包…"
ditto -x -k "$PREV_ZIP" "$PREV_ROOT"
ditto -x -k "$LATEST_ZIP" "$LATEST_ROOT"
for spec in "$PREV_ROOT|$PREV_APP" "$LATEST_ROOT|$LATEST_APP"; do
  root="${spec%%|*}"; app="${spec##*|}"
  if [ ! -d "$app" ]; then
    found="$(find "$root" -maxdepth 2 -name '*.app' -type d | head -1)"
    [ -n "$found" ] || { echo "未解出 .app($root)" >&2; exit 1; }
    mv "$found" "$app"
  fi
done

# 记录签名/公证状态作为信任根,但不作硬性门槛:早期版本的签名证书可能已被吊销
# (CSSMERR_TP_CERT_REVOKED),这只影响"能否安全安装",不影响对 bundle 内容做差异分析。
echo "[backfill ${FROM} -> ${TO}] 记录签名/公证状态…"
codesign --verify --deep --strict "$LATEST_APP" 2>&1 | tee "$WORK/latest-codesign.txt" || true
spctl -a -vv "$LATEST_APP"  2>&1 | tee "$WORK/latest-spctl.txt"   || true
spctl -a -vv "$PREV_APP"    2>&1 | tee "$WORK/previous-spctl.txt" || true

PREV_BUILD=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$PREV_APP/Contents/Info.plist")
TO_BUILD=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$LATEST_APP/Contents/Info.plist")
PREV_SHA=$(shasum -a 256 "$PREV_ZIP" | awk '{print $1}')
TO_SHA=$(shasum -a 256 "$LATEST_ZIP" | awk '{print $1}')
{
  printf 'mode\tfull-pair\n'
  printf 'previous_short\t%s\n' "$FROM"
  printf 'previous_build\t%s\n' "$PREV_BUILD"
  printf 'previous_pub\t%s\n' "$FROM_DATE"
  printf 'latest_short\t%s\n' "$TO"
  printf 'latest_build\t%s\n' "$TO_BUILD"
  printf 'latest_pub\t%s\n' "$TO_DATE"
  printf 'previous_full_url\t%s\n' "$BASE/Codex-darwin-arm64-$FROM.zip"
  printf 'previous_full_sha256\t%s\n' "$PREV_SHA"
  printf 'latest_full_url\t%s\n' "$BASE/Codex-darwin-arm64-$TO.zip"
  printf 'latest_full_sha256\t%s\n' "$TO_SHA"
} > "$WORK/metadata.tsv"

echo "[backfill ${FROM} -> ${TO}] 解包 app.asar…"
npx --yes @electron/asar list "$PREV_APP/Contents/Resources/app.asar"   > "$WORK/asar-prev-list.txt"
npx --yes @electron/asar list "$LATEST_APP/Contents/Resources/app.asar" > "$WORK/asar-latest-list.txt"
rm -rf "$WORK/asar-prev-extract" "$WORK/asar-latest-extract"
npx --yes @electron/asar extract "$PREV_APP/Contents/Resources/app.asar"   "$WORK/asar-prev-extract"
npx --yes @electron/asar extract "$LATEST_APP/Contents/Resources/app.asar" "$WORK/asar-latest-extract"

echo "[backfill ${FROM} -> ${TO}] 分层 diff + 事实包…"
python3 "$ROOT/scripts/diff_bundle.py"   --work "$WORK"
node    "$ROOT/scripts/diff_asar.mjs"     "$WORK"
node    "$ROOT/scripts/diff_packages.mjs" "$WORK"
python3 "$ROOT/scripts/diff_targeted.py" --work "$WORK"
python3 "$ROOT/scripts/build_llm_input.py" --work "$WORK"
echo "[backfill ${FROM} -> ${TO}] 事实包就绪: $WORK/llm-input.md"
