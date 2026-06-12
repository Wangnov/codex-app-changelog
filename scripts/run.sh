#!/usr/bin/env bash
# 端到端编排:appcast → 下载验签 → 重建 → 分层 diff → 事实包 → codex exec 写 changelog。
# 用法:
#   scripts/run.sh                      比较最新两版
#   scripts/run.sh --to-build 3808 --from-build 3722
#   scripts/run.sh --skip-llm           只产出事实包,不调 LLM
#   scripts/run.sh --work <dir>         指定工作目录(默认 work/<from>-<to>)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK=""; TO=""; FROM=""; SKIP_LLM=0; FEED=""
while [[ $# -gt 0 ]]; do case "$1" in
  --work) WORK="$2"; shift 2;;
  --to-build) TO="$2"; shift 2;;
  --from-build) FROM="$2"; shift 2;;
  --feed) FEED="$2"; shift 2;;
  --skip-llm) SKIP_LLM=1; shift;;
  *) echo "未知参数: $1" >&2; exit 1;;
esac; done

FETCH_ARGS=()
[[ -n "$TO" ]]   && FETCH_ARGS+=(--to-build "$TO")
[[ -n "$FROM" ]] && FETCH_ARGS+=(--from-build "$FROM")
[[ -n "$FEED" ]] && FETCH_ARGS+=(--feed "$FEED")

# 先在临时目录拉 appcast 定版本,再据 from/to 决定正式 work 目录名。
TMP_WORK="$(mktemp -d)"
echo "== [1/8] 拉取 appcast,确定版本对 =="
python3 "$ROOT/scripts/fetch_appcast.py" --work "$TMP_WORK" ${FETCH_ARGS[@]+"${FETCH_ARGS[@]}"}
F="$(awk -F'\t' '$1=="previous_build"{print $2}' "$TMP_WORK/metadata.tsv")"
T="$(awk -F'\t' '$1=="latest_build"{print $2}' "$TMP_WORK/metadata.tsv")"
[[ -z "$WORK" ]] && WORK="$ROOT/work/${F}-${T}"
mkdir -p "$WORK"; cp "$TMP_WORK"/metadata.* "$TMP_WORK"/appcast.xml "$WORK/"; rm -rf "$TMP_WORK"
echo "   work = $WORK"

echo "== [2/8] 获取 BinaryDelta =="
bash "$ROOT/scripts/vendor_binary_delta.sh"
echo "== [3/8] 下载 + EdDSA 验签 =="
python3 "$ROOT/scripts/download_verify.py" --work "$WORK"
echo "== [4/8] 解包 + BinaryDelta 重建 + 公证校验 =="
bash "$ROOT/scripts/reconstruct.sh" "$WORK"
echo "== [5/8] 分层 diff:bundle / asar / packages =="
python3 "$ROOT/scripts/diff_bundle.py" --work "$WORK"
node "$ROOT/scripts/diff_asar.mjs" "$WORK"
node "$ROOT/scripts/diff_packages.mjs" "$WORK"
echo "== [6/8] 定向文本 diff(plist / CSP / 技能文档 / 类型声明)=="
python3 "$ROOT/scripts/diff_targeted.py" --work "$WORK"
echo "== [7/8] 聚合 LLM 事实包 =="
python3 "$ROOT/scripts/build_llm_input.py" --work "$WORK"
if [[ "$SKIP_LLM" == "1" ]]; then
  echo "已跳过 LLM。事实包: $WORK/llm-input.md"; exit 0
fi
echo "== [8/8] codex exec 生成 changelog =="
bash "$ROOT/scripts/analyze.sh" "$WORK"
echo "✅ 完成: $WORK/changelog.md"
