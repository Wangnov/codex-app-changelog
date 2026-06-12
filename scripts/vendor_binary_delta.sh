#!/usr/bin/env bash
# 把 Sparkle 的 BinaryDelta CLI 取到 vendor/BinaryDelta(供 reconstruct.sh 重建增量)。
# 钉死 Sparkle 2.9.1:与 OpenAI Codex.app 内嵌的 Sparkle 版本一致,能精确读官方
# delta 补丁格式(v4.2)。tarball 与二进制都用 pinned SHA-256 校验,防供应链投毒。
# 二进制本身已是 universal + 签名,原样复制,切勿 lipo(会破坏签名)。
set -euo pipefail

SPARKLE_VERSION="2.9.1"
TARBALL="Sparkle-${SPARKLE_VERSION}.tar.xz"
TARBALL_URL="https://github.com/sparkle-project/Sparkle/releases/download/${SPARKLE_VERSION}/${TARBALL}"
TARBALL_SHA256="c0dde519fd2a43ddfc6a1eb76aec284d7d888fe281414f9177de3164d98ba4c7"
BINARY_SHA256="5c31312b5dd6bbfa4d3adf79360f0851b9369a72b5facf7f7b4df0906f4fcf67"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${ROOT}/vendor/BinaryDelta"
log() { printf '\033[36m[vendor-binary-delta]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[vendor-binary-delta] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || { log "非 macOS($(uname -s)),跳过 —— delta 仅 macOS"; exit 0; }
sha256() { shasum -a 256 "$1" | awk '{print $1}'; }

if [[ -f "$DEST" ]] && [[ "$(sha256 "$DEST")" == "$BINARY_SHA256" ]]; then
  log "已就位(sha256 匹配): ${DEST#"$ROOT"/}"; exit 0
fi

mkdir -p "$(dirname "$DEST")"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
log "下载 Sparkle ${SPARKLE_VERSION}…"
curl -fsSL "$TARBALL_URL" -o "${TMP}/${TARBALL}" || die "下载失败: $TARBALL_URL"
got="$(sha256 "${TMP}/${TARBALL}")"
[[ "$got" == "$TARBALL_SHA256" ]] || die "tarball sha256 不符(得到 $got)"
log "tarball 校验通过。"
tar -xJf "${TMP}/${TARBALL}" -C "$TMP" bin/BinaryDelta || die "解包失败 —— tarball 里没有 bin/BinaryDelta?"
got="$(sha256 "${TMP}/bin/BinaryDelta")"
[[ "$got" == "$BINARY_SHA256" ]] || die "BinaryDelta sha256 不符(得到 $got)"
cp "${TMP}/bin/BinaryDelta" "$DEST"; chmod +x "$DEST"
log "已安装: ${DEST#"$ROOT"/}"
