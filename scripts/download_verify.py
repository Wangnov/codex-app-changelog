#!/usr/bin/env python3
"""下载上一版全量包 + 官方增量包,做大小校验与 Sparkle EdDSA 验签。

验签是整条链路的信任根:证明拿到的是 OpenAI Sparkle 私钥签过的原始字节,
而不只是 HTTPS 传输可信。公钥与 codex-app-manager 的 verify.rs 一致,
来源是 Codex.app 的 SUPublicEDKey。
"""
import argparse, base64, hashlib, pathlib, subprocess, sys
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# OpenAI 的 Sparkle EdDSA 公钥(pinned,来自 Codex.app 的 SUPublicEDKey)
SPARKLE_ED_PUBKEY_B64 = "mNfr1v9t63BfgDtlw4C8lRvSY6uMggIXABDOCi3tS6k="


def load_meta(work: pathlib.Path) -> dict:
    meta = {}
    for line in (work / "metadata.tsv").read_text().splitlines():
        if "\t" in line:
            k, v = line.split("\t", 1)
            meta[k] = v
    return meta


def curl(url: str, dest: pathlib.Path):
    subprocess.run(
        ["curl", "-fL", "--retry", "5", "--retry-all-errors",
         "--connect-timeout", "20", "--speed-time", "60", "--speed-limit", "1024",
         url, "-o", str(dest)],
        check=True)


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    args = ap.parse_args()
    work = pathlib.Path(args.work)
    meta = load_meta(work)

    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(SPARKLE_ED_PUBKEY_B64))
    prev_zip = work / f"previous-{meta['previous_build']}.zip"
    delta = work / f"latest-{meta['latest_build']}-from-{meta['previous_build']}.delta"

    jobs = [
        (meta["previous_full_url"], prev_zip, int(meta["previous_full_len"]), meta["previous_full_sig"], "全量包"),
        (meta["latest_delta_url"], delta, int(meta["latest_delta_len"]), meta["latest_delta_sig"], "增量包"),
    ]
    for url, dest, exp_len, sig_b64, label in jobs:
        if not dest.exists() or dest.stat().st_size != exp_len:
            print(f"[download] {label} ← {url}")
            curl(url, dest)
        data = dest.read_bytes()
        if len(data) != exp_len:
            sys.exit(f"{label}: 大小不符 {len(data)} != {exp_len}")
        pub.verify(base64.b64decode(sig_b64), data)   # 失败抛异常
        print(f"[verify] {label}: 大小 OK, EdDSA 验签通过 ({len(data)} bytes)")

    # 记录指针文件,便于 reconstruct.sh 找到制品
    (work / "artifacts.txt").write_text(f"{prev_zip.name}\n{delta.name}\n")
    sha_lines = [f"{sha256(prev_zip)}  {prev_zip}", f"{sha256(delta)}  {delta}"]
    (work / "download-sha256.txt").write_text("\n".join(sha_lines) + "\n")
    print("[verify] SHA-256 写入 download-sha256.txt")


if __name__ == "__main__":
    main()
