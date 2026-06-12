#!/usr/bin/env python3
"""对两版重建后的 .app 做文件树清单差异(逐文件 sha256),产出 file-diff-summary.json。

注意:added/removed/changed_top 各取体积 top-80。体积小的新增文件(如 Dock 插件)
不会进这个截断列表 —— 那类组件由 diff_targeted.py 直接扫目录补全。
"""
import argparse, hashlib, json, os, pathlib


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def manifest(root: pathlib.Path) -> dict:
    out = {}
    for p in root.rglob("*"):
        rp = str(p.relative_to(root))
        if p.is_symlink():
            out[rp] = {"type": "symlink", "size": 0, "sha": "SYMLINK:" + os.readlink(p)}
        elif p.is_file():
            out[rp] = {"type": "file", "size": p.lstat().st_size, "sha": sha(p)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    args = ap.parse_args()
    w = pathlib.Path(args.work)
    pm = manifest(w / "previous-extract/Codex.app")
    nm = manifest(w / "latest-reconstructed/Codex.app")
    added = sorted(set(nm) - set(pm))
    removed = sorted(set(pm) - set(nm))
    common = set(pm) & set(nm)
    changed = [p for p in common
               if pm[p]["sha"] != nm[p]["sha"] or pm[p]["size"] != nm[p]["size"]
               or pm[p]["type"] != nm[p]["type"]]

    changed_rows = sorted(
        ({"path": p, "old_size": pm[p]["size"], "new_size": nm[p]["size"],
          "delta_size": nm[p]["size"] - pm[p]["size"]} for p in changed),
        key=lambda r: abs(r["delta_size"]), reverse=True)
    added_rows = sorted(({"path": p, "size": nm[p]["size"]} for p in added),
                        key=lambda r: r["size"], reverse=True)
    removed_rows = sorted(({"path": p, "size": pm[p]["size"]} for p in removed),
                          key=lambda r: r["size"], reverse=True)

    report = {
        "summary": {"prev_files": len(pm), "new_files": len(nm),
                    "added_count": len(added), "removed_count": len(removed),
                    "changed_count": len(changed)},
        "changed_top": changed_rows[:80], "added": added_rows[:80],
        "removed": removed_rows[:80]}
    (w / "file-diff-summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False))
    print(f"[diff_bundle] {report['summary']}")


if __name__ == "__main__":
    main()
