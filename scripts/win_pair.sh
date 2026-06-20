#!/usr/bin/env bash
# Windows full-pair diff:从 mirror GitHub release 按 tag 拿两个 MSIX,解包 app/ payload,
# 跑参数化的 diff(复用 macOS 的 diff_bundle / diff_asar / diff_packages)。
# MSIX 是 zip,app/ 是 Electron payload,app/resources 对应 macOS Contents/Resources。
# 用法: win_pair.sh <from_tag> <to_tag> <work_dir>
set -euo pipefail
FROM_TAG="${1:?from release tag}"; TO_TAG="${2:?to release tag}"; WORK="${3:?work dir}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="Wangnov/codex-app-mirror"
mkdir -p "$WORK"

dl_msix() {  # tag dest —— gh release download 无内置重试,网络抖动(EOF/DNS timeout)会直接失败;
             # 包一层重试 + 指数退避,避免瞬时抖动让整对 FAIL(mac 侧 curl 已有 --retry)。
  local tag="$1" dest="$2" tmp i
  [ -s "$dest" ] && return 0
  tmp="$WORK/.dl-$tag"
  for i in 1 2 3 4 5; do
    rm -rf "$tmp"; mkdir -p "$tmp"
    if gh release download "$tag" --repo "$REPO" --pattern '*.Msix' --dir "$tmp" \
       && mv "$tmp"/*.Msix "$dest" 2>/dev/null; then
      rm -rf "$tmp"; return 0
    fi
    echo "[win] MSIX 下载失败(第 $i/5 次),$((i*10))s 后重试…" >&2
    sleep $((i*10))
  done
  rm -rf "$tmp"; echo "[win] MSIX 下载重试 5 次仍失败: $tag" >&2; return 1
}
echo "[win] 下载 MSIX($FROM_TAG → $TO_TAG)…"
dl_msix "$FROM_TAG" "$WORK/prev.msix"
dl_msix "$TO_TAG" "$WORK/latest.msix"

echo "[win] 解包 app/ payload…"
rm -rf "$WORK/previous-extract" "$WORK/latest-reconstructed"
mkdir -p "$WORK/previous-extract" "$WORK/latest-reconstructed"
unzip -q "$WORK/prev.msix"   'app/*' -d "$WORK/previous-extract"
unzip -q "$WORK/latest.msix" 'app/*' -d "$WORK/latest-reconstructed"
# MSIX(OPC 格式)把特殊字符 URL 编码(@→%40 等);解包后还原,否则 asar 找不到 unpacked
# 的原生模块,而且两版路径名不一致会让文件树 diff 误判。自底向上重命名。
python3 - "$WORK/previous-extract/app" "$WORK/latest-reconstructed/app" <<'PY'
import sys, os, urllib.parse
for root in sys.argv[1:]:
    for dp, dirs, files in os.walk(root, topdown=False):
        for name in files + dirs:
            dec = urllib.parse.unquote(name)
            if dec != name:
                os.rename(os.path.join(dp, name), os.path.join(dp, dec))
PY
# AppxManifest(Windows 的 Info.plist 等价物)留作定向 diff 用
unzip -p "$WORK/prev.msix"   AppxManifest.xml > "$WORK/AppxManifest-prev.xml" 2>/dev/null || true
unzip -p "$WORK/latest.msix" AppxManifest.xml > "$WORK/AppxManifest-new.xml"  2>/dev/null || true

# metadata(供 build_llm_input 读);Windows 版本号取自 AppxManifest 的 Identity Version
ver_of() { sed -nE 's/.*<Identity[^>]* Version="([^"]+)".*/\1/p' "$1" | head -1; }
PREV_VER="$(ver_of "$WORK/AppxManifest-prev.xml")"; TO_VER="$(ver_of "$WORK/AppxManifest-new.xml")"
{
  printf 'mode\tfull-pair\nplatform\twindows\n'
  printf 'previous_short\t%s\nprevious_build\t%s\n' "$PREV_VER" "$PREV_VER"
  printf 'latest_short\t%s\nlatest_build\t%s\n' "$TO_VER" "$TO_VER"
  printf 'previous_full_url\thttps://github.com/%s/releases/tag/%s\n' "$REPO" "$FROM_TAG"
  printf 'latest_full_url\thttps://github.com/%s/releases/tag/%s\n' "$REPO" "$TO_TAG"
  printf 'previous_full_sha256\t%s\n' "$(shasum -a 256 "$WORK/prev.msix" | awk '{print $1}')"
  printf 'latest_full_sha256\t%s\n' "$(shasum -a 256 "$WORK/latest.msix" | awk '{print $1}')"
} > "$WORK/metadata.tsv"

echo "[win] 解包 app.asar…"
PREV_ASAR="$WORK/previous-extract/app/resources/app.asar"
LATEST_ASAR="$WORK/latest-reconstructed/app/resources/app.asar"
rm -rf "$WORK/asar-prev-extract" "$WORK/asar-latest-extract"
npx --yes @electron/asar extract "$PREV_ASAR"   "$WORK/asar-prev-extract"
npx --yes @electron/asar extract "$LATEST_ASAR" "$WORK/asar-latest-extract"
npx --yes @electron/asar list "$PREV_ASAR"   > "$WORK/asar-prev-list.txt"
npx --yes @electron/asar list "$LATEST_ASAR" > "$WORK/asar-latest-list.txt"

echo "[win] 分层 diff(复用 macOS 逻辑,传 Windows 路径)…"
python3 "$ROOT/scripts/diff_bundle.py" --work "$WORK" \
  --prev-root previous-extract/app --new-root latest-reconstructed/app
node "$ROOT/scripts/diff_asar.mjs" "$WORK"
node "$ROOT/scripts/diff_packages.mjs" "$WORK" \
  previous-extract/app/resources/cua_node/bin/node_modules \
  latest-reconstructed/app/resources/cua_node/bin/node_modules
# 定向文本 diff(关键文件 unified diff / CSP / AppxManifest 权限 / 前端 stem 增删)。
# 此前 Windows 路径漏调本步,导致 Windows 事实包没有最强的【实证】层。依赖上面两步的 JSON。
CL_PLATFORM=windows python3 "$ROOT/scripts/diff_targeted.py" --work "$WORK"
echo "[win] 完成。Windows diff JSON 已就绪。"
