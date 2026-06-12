#!/usr/bin/env python3
"""拉取官方 Sparkle appcast,选定一对版本(from→to),解析出全量包与增量包的
URL / 大小 / EdDSA 签名,写入 work/metadata.tsv 与 work/metadata.json。

默认 to=最新 build,from=次新 build(即相邻一版);也可用 --to-build / --from-build
指定任意一对(只要 to 的 appcast item 里存在 deltaFrom==from 的增量包)。
"""
import argparse, json, pathlib, sys, urllib.request

SP = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"
DEFAULT_FEED = "https://persistent.oaistatic.com/codex-app-prod/appcast.xml"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "codex-app-changelog/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def parse_items(xml_bytes: bytes):
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.iter("item"):
        ver = item.find(f"{SP}version")
        short = item.find(f"{SP}shortVersionString")
        pub = item.find("pubDate")
        enc = item.find("enclosure")
        if ver is None or enc is None:
            continue
        deltas = []
        dwrap = item.find(f"{SP}deltas")
        if dwrap is not None:
            for d in dwrap.findall("enclosure"):
                deltas.append({
                    "from": d.get(f"{SP}deltaFrom"),
                    "url": d.get("url"),
                    "len": d.get("length"),
                    "sig": d.get(f"{SP}edSignature")})
        items.append({
            "build": int(ver.text),
            "short": short.text if short is not None else "",
            "pub": pub.text if pub is not None else "",
            "full_url": enc.get("url"),
            "full_len": enc.get("length"),
            "full_sig": enc.get(f"{SP}edSignature"),
            "deltas": deltas})
    items.sort(key=lambda x: x["build"], reverse=True)
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default=DEFAULT_FEED)
    ap.add_argument("--to-build", type=int, default=None)
    ap.add_argument("--from-build", type=int, default=None)
    ap.add_argument("--work", required=True)
    args = ap.parse_args()

    work = pathlib.Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    xml_bytes = fetch(args.feed)
    (work / "appcast.xml").write_bytes(xml_bytes)
    items = parse_items(xml_bytes)
    if len(items) < 2:
        sys.exit("appcast 至少需要 2 个版本才能比较")

    by_build = {it["build"]: it for it in items}
    to = by_build[args.to_build] if args.to_build else items[0]
    if args.from_build:
        frm = by_build.get(args.from_build)
        if not frm:
            sys.exit(f"appcast 里找不到 from build {args.from_build}")
    else:
        # to 的下一个更低 build
        lower = [it for it in items if it["build"] < to["build"]]
        if not lower:
            sys.exit("找不到比 to 更早的版本")
        frm = lower[0]

    delta = next((d for d in to["deltas"] if d["from"] == str(frm["build"])), None)
    if not delta:
        sys.exit(f"to={to['build']} 的 appcast 没有 deltaFrom={frm['build']} 的增量包;"
                 f"可用: {[d['from'] for d in to['deltas']]}")

    meta = {
        "latest_build": to["build"], "latest_short": to["short"], "latest_pub": to["pub"],
        "previous_build": frm["build"], "previous_short": frm["short"], "previous_pub": frm["pub"],
        "previous_full_url": frm["full_url"], "previous_full_len": frm["full_len"],
        "previous_full_sig": frm["full_sig"],
        "latest_delta_url": delta["url"], "latest_delta_len": delta["len"],
        "latest_delta_sig": delta["sig"],
        "latest_full_url": to["full_url"], "latest_full_len": to["full_len"],
        "feed": args.feed}
    (work / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    with (work / "metadata.tsv").open("w") as f:
        for k, v in meta.items():
            f.write(f"{k}\t{v}\n")

    print(f"[fetch] {frm['short']} (build {frm['build']}) → {to['short']} (build {to['build']})")
    print(f"[fetch] 全量包 {meta['previous_full_len']}B + 增量包 {meta['latest_delta_len']}B")


if __name__ == "__main__":
    main()
