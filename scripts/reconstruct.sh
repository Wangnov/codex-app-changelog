#!/usr/bin/env bash
# 解包上一版全量包,用 Sparkle BinaryDelta 重建最新版,验证签名/公证,再解包 app.asar。
# 仅 macOS:依赖 ditto / codesign / spctl / BinaryDelta。
# 用法: scripts/reconstruct.sh <work-dir>
set -euo pipefail
WORK="${1:?用法: reconstruct.sh <work-dir>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 定位 BinaryDelta:优先本项目 vendor,其次 codex-app-manager 的 resources。
BINDELTA=""
for c in "$ROOT/vendor/BinaryDelta" "$HOME/codex-app-manager/src-tauri/resources/BinaryDelta"; do
  [ -x "$c" ] && BINDELTA="$c" && break
done
[ -n "$BINDELTA" ] || { echo "找不到 BinaryDelta —— 先跑 scripts/vendor_binary_delta.sh" >&2; exit 1; }

meta() { awk -F '\t' -v k="$1" '$1==k{print $2}' "$WORK/metadata.tsv"; }
FROM="$(meta previous_build)"; TO="$(meta latest_build)"
PREV_ZIP="$WORK/previous-$FROM.zip"
DELTA="$WORK/latest-$TO-from-$FROM.delta"
PREV_ROOT="$WORK/previous-extract"; LATEST_ROOT="$WORK/latest-reconstructed"
PREV_APP="$PREV_ROOT/Codex.app"; LATEST_APP="$LATEST_ROOT/Codex.app"

rm -rf "$PREV_ROOT" "$LATEST_ROOT"; mkdir -p "$PREV_ROOT" "$LATEST_ROOT"
echo "[reconstruct] 解包上一版全量包 (build $FROM)…"
ditto -x -k "$PREV_ZIP" "$PREV_ROOT"
if [ ! -d "$PREV_APP" ]; then
  FOUND="$(find "$PREV_ROOT" -maxdepth 2 -name '*.app' -type d | head -n1)"
  [ -n "$FOUND" ] || { echo "未解出 .app" >&2; exit 1; }
  mv "$FOUND" "$PREV_APP"
fi

echo "[reconstruct] BinaryDelta 重建最新版 (build $TO)…"
"$BINDELTA" apply "$PREV_APP" "$LATEST_APP" "$DELTA"

echo "[reconstruct] 校验重建产物签名与公证…"
codesign --verify --deep --strict --verbose=2 "$LATEST_APP"
spctl -a -vv "$LATEST_APP" 2>&1 | tee "$WORK/latest-spctl.txt"

echo "[reconstruct] 解包 app.asar(清单 + 内容)…"
PREV_ASAR="$PREV_APP/Contents/Resources/app.asar"
LATEST_ASAR="$LATEST_APP/Contents/Resources/app.asar"
npx --yes @electron/asar list "$PREV_ASAR"   > "$WORK/asar-prev-list.txt"
npx --yes @electron/asar list "$LATEST_ASAR" > "$WORK/asar-latest-list.txt"
rm -rf "$WORK/asar-prev-extract" "$WORK/asar-latest-extract"
npx --yes @electron/asar extract "$PREV_ASAR"   "$WORK/asar-prev-extract"
npx --yes @electron/asar extract "$LATEST_ASAR" "$WORK/asar-latest-extract"
echo "[reconstruct] 完成"
