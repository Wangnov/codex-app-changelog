#!/usr/bin/env python3
"""把"文件体积变了"还原成"具体改了什么":对两版重建后的 bundle 做定向文本差异。

输入(--work 目录,布局沿用上游流水线产物):
  previous-extract/Codex.app        上一版 bundle
  latest-reconstructed/Codex.app    重建出的最新版 bundle
  asar-prev-extract/                上一版 app.asar 解包
  asar-latest-extract/              最新版 app.asar 解包
  file-diff-summary.json            bundle 文件树差异(diff_bundle.py 产物)
  asar-content-diff.json            app.asar 内容差异(diff_asar.mjs 产物)
  asar-prev-list.txt / asar-latest-list.txt

输出:
  targeted-diff.json   结构化定向差异,供 build_llm_input.py 聚合给 LLM

设计原则:对任意版本对通用,不写死任何具体文件名。
"""
import argparse, json, os, re, sys, difflib, plistlib, pathlib, subprocess

TEXT_EXT = {".md", ".json", ".ts", ".js", ".mjs", ".cjs", ".txt",
            ".html", ".htm", ".css", ".yml", ".yaml", ".toml", ".d.ts"}
MAX_FILE_BYTES = 96 * 1024          # 超过视为压缩/构建产物,跳过文本 diff
MAX_DIFF_LINES = 200                # 单个 unified diff 截断行数
NOISE_SUBSTR = ("webview/assets/", "_CodeSignature", "CodeResources",
                "/Assets.car", ".vite/build/")  # hash 命名 / 签名噪音

# 平台口径与 build_llm_input.py 保持一致:Windows 走 MSIX 的 app/ 布局与 AppxManifest,
# macOS 走 .app 的 Contents/ 布局与 Info.plist。asar/CSP/关键文本 diff 两平台共用。
IS_WIN = os.environ.get("CL_PLATFORM") == "windows"


def is_text(path: str) -> bool:
    low = path.lower()
    if low.endswith(".plist"):
        return False  # plist 走结构化分支
    return any(low.endswith(e) for e in TEXT_EXT)


def read_text(p: pathlib.Path):
    try:
        return p.read_text(errors="replace")
    except Exception:
        return None


def unified(a: str, b: str, path: str):
    diff = list(difflib.unified_diff(
        a.splitlines(), b.splitlines(),
        fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""))
    if len(diff) > MAX_DIFF_LINES:
        diff = diff[:MAX_DIFF_LINES] + [f"... [截断,共 {len(diff)} 行]"]
    return "\n".join(diff)


def plist_flat(d, prefix=""):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(plist_flat(v, f"{prefix}/{k}"))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            out.update(plist_flat(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = d
    return out


def diff_plist(prev: pathlib.Path, new: pathlib.Path):
    try:
        a = plist_flat(plistlib.loads(prev.read_bytes()))
        b = plist_flat(plistlib.loads(new.read_bytes()))
    except Exception as e:
        return {"error": str(e)}
    changed, added, removed = [], [], []
    for k in sorted(set(a) | set(b)):
        va, vb = a.get(k, None), b.get(k, None)
        if k not in a:
            added.append({"key": k, "new": repr(vb)})
        elif k not in b:
            removed.append({"key": k, "old": repr(va)})
        elif va != vb:
            changed.append({"key": k, "old": repr(va), "new": repr(vb)})
    return {"changed": changed, "added": added, "removed": removed}


def diff_appxmanifest(prev: pathlib.Path, new: pathlib.Path):
    """AppxManifest.xml 是 Windows 的 Info.plist 等价物。提取 capabilities(权限)、
    协议关联、文件类型关联做集合差 —— 比整树拍平噪音小、信号强。这些是 Windows 侧
    最高价值的【实证】权限信号,此前完全没有任何脚本提取(纯盲区)。"""
    import xml.etree.ElementTree as ET

    def parse(p: pathlib.Path):
        if not p.exists():
            return None
        try:
            root = ET.fromstring(p.read_bytes())
        except Exception as e:
            return {"error": str(e)}
        caps, protocols, exts = set(), set(), set()
        for el in root.iter():
            tag = el.tag.rsplit("}", 1)[-1]  # 去 XML namespace
            if tag in ("Capability", "DeviceCapability"):
                if el.get("Name"):
                    caps.add(el.get("Name"))
            elif tag == "Protocol" and el.get("Name"):
                protocols.add(el.get("Name"))
            elif tag == "FileType" and (el.text or "").strip():
                exts.add(el.text.strip())
        return {"caps": caps, "protocols": protocols, "exts": exts}

    a, b = parse(prev), parse(new)
    if a is None or b is None:
        return None
    if "error" in a or "error" in b:
        return {"error": a.get("error") or b.get("error")}
    return {
        "added_capabilities": sorted(b["caps"] - a["caps"]),
        "removed_capabilities": sorted(a["caps"] - b["caps"]),
        "added_protocols": sorted(b["protocols"] - a["protocols"]),
        "removed_protocols": sorted(a["protocols"] - b["protocols"]),
        "added_file_types": sorted(b["exts"] - a["exts"]),
        "removed_file_types": sorted(a["exts"] - b["exts"]),
    }


CSP_RE = re.compile(r'Content-Security-Policy"\s+content="([^"]*)"', re.I)
CONNECT_RE = re.compile(r"connect-src([^;]*)")


def extract_connect_src(html: str):
    m = CSP_RE.search(html)
    if not m:
        return None
    csp = m.group(1).replace("&#39;", "'")
    cm = CONNECT_RE.search(csp)
    if not cm:
        return None
    return sorted(t for t in cm.group(1).split() if "://" in t or t.startswith("wss"))


def codesign_info(path: pathlib.Path):
    """best-effort 读取签名 identifier 与 authority,作为新增组件的实证。"""
    try:
        r = subprocess.run(["codesign", "-dv", "--verbose=2", str(path)],
                           capture_output=True, text=True, timeout=15)
        blob = r.stderr + r.stdout
        ident = re.search(r"Identifier=(\S+)", blob)
        auth = re.search(r"Authority=([^\n]+)", blob)
        return {"identifier": ident.group(1) if ident else None,
                "authority": auth.group(1) if auth else None}
    except Exception:
        return {}


def stem_set(list_file: pathlib.Path):
    """从 asar 文件清单里提取去 hash 的前端模块名(stem)。"""
    rx = re.compile(r"webview/assets/(.+)-[A-Za-z0-9_-]{8}\.(?:js|css)$")
    s = set()
    if not list_file.exists():
        return s
    for line in list_file.read_text(errors="replace").splitlines():
        m = rx.search(line.strip())
        if m and not m.group(1).startswith("_"):
            s.add(m.group(1))
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    args = ap.parse_args()
    work = pathlib.Path(args.work)
    if IS_WIN:
        prev_app = work / "previous-extract" / "app"
        new_app = work / "latest-reconstructed" / "app"
    else:
        prev_app = work / "previous-extract" / "Codex.app"
        new_app = work / "latest-reconstructed" / "Codex.app"
    prev_asar = work / "asar-prev-extract"
    new_asar = work / "asar-latest-extract"

    out = {"info_plist": None, "appx_manifest": None, "csp": [], "bundle_text_diffs": [],
           "asar_text_diffs": [], "added_plugins": [], "added_resources": [],
           "asar_added_stems": [], "asar_removed_stems": []}

    # 1) Info.plist(macOS)/ AppxManifest(Windows)结构化差异
    if IS_WIN:
        out["appx_manifest"] = diff_appxmanifest(
            work / "AppxManifest-prev.xml", work / "AppxManifest-new.xml")
    else:
        pp, np_ = prev_app / "Contents/Info.plist", new_app / "Contents/Info.plist"
        if pp.exists() and np_.exists():
            out["info_plist"] = diff_plist(pp, np_)

    # 2) bundle 内文本文件 diff(来自 file-diff-summary.changed_top)
    fds = work / "file-diff-summary.json"
    if fds.exists():
        rep = json.loads(fds.read_text())
        for r in rep.get("changed_top", []):
            path = r["path"]
            if any(n in path for n in NOISE_SUBSTR) or not is_text(path):
                continue
            if max(r.get("old_size", 0), r.get("new_size", 0)) > MAX_FILE_BYTES:
                continue
            a, b = read_text(prev_app / path), read_text(new_app / path)
            if a is None or b is None or a == b:
                continue
            out["bundle_text_diffs"].append({
                "path": path, "old_size": r.get("old_size"),
                "new_size": r.get("new_size"), "diff": unified(a, b, path)})
    # 新增插件 / 顶层资源:依赖 .app 的 Contents/ 结构与 codesign,macOS 专属。
    # Windows(MSIX app/ 布局)的新增组件改由 file-diff-summary 的 added 列表覆盖。
    if not IS_WIN:
        # 新增插件:直接扫 Contents/PlugIns 目录对比(不依赖被截断的 added 列表)
        pp_dir, np_dir = prev_app / "Contents/PlugIns", new_app / "Contents/PlugIns"
        prev_plugins = {p.name for p in pp_dir.iterdir()} if pp_dir.exists() else set()
        new_plugins = {p.name for p in np_dir.iterdir()} if np_dir.exists() else set()
        for name in sorted(new_plugins - prev_plugins):
            entry = {"path": f"Contents/PlugIns/{name}"}
            entry.update(codesign_info(np_dir / name))
            out["added_plugins"].append(entry)

        # 新增顶层资源(图标等):扫 Contents/Resources 顶层文件对比
        pr_dir, nr_dir = prev_app / "Contents/Resources", new_app / "Contents/Resources"
        if pr_dir.exists() and nr_dir.exists():
            prev_top = {p.name for p in pr_dir.iterdir() if p.is_file()}
            for p in nr_dir.iterdir():
                if (p.is_file() and p.name not in prev_top
                        and p.suffix.lower() in {".png", ".icns", ".jpg", ".jpeg", ".svg"}):
                    out["added_resources"].append(
                        {"path": f"Contents/Resources/{p.name}", "size": p.stat().st_size})

    # 3) app.asar 内文本文件 diff + CSP(来自 asar-content-diff.changedTop)
    acd = work / "asar-content-diff.json"
    if acd.exists():
        rep = json.loads(acd.read_text())
        for r in rep.get("changedTop", []):
            path = r["path"]
            if r.get("delta", 1) == 0 or any(n in path for n in ("node_modules/",)):
                continue
            if max(r.get("old", 0), r.get("new", 0)) > MAX_FILE_BYTES:
                continue
            a, b = read_text(prev_asar / path), read_text(new_asar / path)
            if a is None or b is None or a == b:
                continue
            if path.endswith((".html", ".htm")):
                pa, pb = extract_connect_src(a), extract_connect_src(b)
                if pa is not None and pb is not None and pa != pb:
                    out["csp"].append({
                        "file": path,
                        "added_domains": sorted(set(pb) - set(pa)),
                        "removed_domains": sorted(set(pa) - set(pb))})
            if not is_text(path):
                continue
            out["asar_text_diffs"].append({
                "path": path, "old_size": r.get("old"),
                "new_size": r.get("new"), "diff": unified(a, b, path)})

    # 4) 前端模块 stem 级真实增删(去 Vite hash 噪音)
    pa = stem_set(work / "asar-prev-list.txt")
    nb = stem_set(work / "asar-latest-list.txt")
    out["asar_added_stems"] = sorted(nb - pa)
    out["asar_removed_stems"] = sorted(pa - nb)

    (work / "targeted-diff.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False))
    am = out["appx_manifest"] if isinstance(out["appx_manifest"], dict) else {}
    manifest_stat = (f"appx_caps=+{len(am.get('added_capabilities', []))}"
                     f"/-{len(am.get('removed_capabilities', []))}" if IS_WIN
                     else f"info_plist={'ok' if out['info_plist'] else 'n/a'}")
    print(f"targeted-diff.json: {manifest_stat} "
          f"bundle_diffs={len(out['bundle_text_diffs'])} "
          f"asar_diffs={len(out['asar_text_diffs'])} "
          f"csp={len(out['csp'])} plugins={len(out['added_plugins'])} "
          f"stems +{len(out['asar_added_stems'])}/-{len(out['asar_removed_stems'])}")


if __name__ == "__main__":
    main()
