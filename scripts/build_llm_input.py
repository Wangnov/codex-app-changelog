#!/usr/bin/env python3
"""把流水线产出的所有结构化差异,聚合成一份给 LLM 的"事实包"(llm-input.md)。

LLM 只能基于这份事实包写 changelog —— 所以这里决定了 changelog 能有多准、多细。
既给 codex exec 当 stdin,也方便人工审阅"模型看到了什么"。
"""
import argparse, json, os, pathlib


def load_tsv(p: pathlib.Path):
    meta = {}
    if p.exists():
        for line in p.read_text().splitlines():
            if "\t" in line:
                k, v = line.split("\t", 1)
                meta[k] = v
    return meta


def mb(n):
    try:
        return f"{int(n)/1e6:.1f} MB"
    except Exception:
        return "?"


def dir_size(root: pathlib.Path):
    total = 0
    if not root.exists():
        return None
    for dirpath, _, files in os.walk(root):
        for f in files:
            fp = pathlib.Path(dirpath) / f
            try:
                total += fp.stat().st_size
            except OSError:
                pass
    return total


def read_json(p: pathlib.Path):
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(errors="replace"))
    except Exception:
        return None


def read_text_excerpt(p: pathlib.Path, max_lines=80, max_chars=6000):
    if not p.exists():
        return None
    text = p.read_text(errors="replace")
    lines = text.splitlines()
    excerpt = "\n".join(lines[:max_lines])
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars] + "\n... [截断]"
    elif len(lines) > max_lines:
        excerpt += f"\n... [截断,共 {len(lines)} 行]"
    return excerpt


def bundle_roots(w: pathlib.Path):
    if os.environ.get("CL_PLATFORM") == "windows":
        return (
            w / "previous-extract" / "app",
            w / "latest-reconstructed" / "app",
            pathlib.Path("resources/plugins/openai-bundled/plugins"),
        )
    return (
        w / "previous-extract" / "Codex.app",
        w / "latest-reconstructed" / "Codex.app",
        pathlib.Path("Contents/Resources/plugins/openai-bundled/plugins"),
    )


def top_files(root: pathlib.Path, limit=8):
    rows = []
    if not root.exists():
        return rows
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            rows.append((p.stat().st_size, str(p.relative_to(root))))
        except OSError:
            pass
    rows.sort(reverse=True)
    return [{"path": path, "size": size} for size, path in rows[:limit]]


def plugin_summary(plugin_root: pathlib.Path):
    manifest = read_json(plugin_root / ".codex-plugin" / "plugin.json")
    mcp = read_json(plugin_root / ".mcp.json")
    skills = []
    skills_dir = plugin_root / "skills"
    if skills_dir.exists():
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            skills.append({
                "path": str(skill_md.relative_to(plugin_root)),
                "excerpt": read_text_excerpt(skill_md, max_lines=70, max_chars=5000),
            })
    iface = (manifest or {}).get("interface") or {}
    return {
        "name": (manifest or {}).get("name") or plugin_root.name,
        "version": (manifest or {}).get("version"),
        "description": (manifest or {}).get("description"),
        "keywords": (manifest or {}).get("keywords") or [],
        "displayName": iface.get("displayName"),
        "shortDescription": iface.get("shortDescription"),
        "longDescription": iface.get("longDescription"),
        "category": iface.get("category"),
        "defaultPrompt": iface.get("defaultPrompt") or [],
        "manifest": manifest,
        "mcp": mcp,
        "skills": skills,
        "fileCount": sum(1 for p in plugin_root.rglob("*") if p.is_file()) if plugin_root.exists() else 0,
        "totalSize": dir_size(plugin_root),
        "topFiles": top_files(plugin_root),
    }


def section(title):
    return f"\n## {title}\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    args = ap.parse_args()
    w = pathlib.Path(args.work)
    meta = load_tsv(w / "metadata.tsv")
    out = []

    # ---- 版本与验证 ----
    out.append("# Codex 桌面版差异事实包（machine-extracted facts）\n")
    out.append("> 以下全部为对官方签名分发产物逆向重建后机器提取的事实。"
               "撰写时只能使用这些事实,不得编造。\n")
    out.append(section("版本与渠道"))
    out.append(f"- 平台/架构: macOS arm64")
    out.append(f"- 上一版: {meta.get('previous_short','?')} (build {meta.get('previous_build','?')}), "
               f"发布 {meta.get('previous_pub','?')}")
    out.append(f"- 最新版: {meta.get('latest_short','?')} (build {meta.get('latest_build','?')}), "
               f"发布 {meta.get('latest_pub','?')}")

    out.append(section("验证与可复现"))
    if meta.get("mode") == "full-pair":
        # full-pair:下载两个官方全量包直接比较。措辞按「官方是否为这一对提供增量包」分流,
        # 避免对仍在增量窗口内的当前版本谎称"超出增量窗口"(违背只用事实的原则):
        #   official_delta_available=true  → 官方有增量包,我们主动选全量包 → 中性表述;
        #   official_delta_available=false → 官方无增量包(真·历史回填,超窗口)→ 保留原表述。
        # 信任根均为 Apple 公证 + OpenAI Developer ID 代码签名(codesign/spctl)+ 全量包 SHA-256。
        if meta.get("official_delta_available") == "true":
            out.append("本版采用两个官方全量包直接比较(full-pair):官方 appcast 对这一对版本提供了增量包,"
                       "但本流程主动选择完整全量包以覆盖完整 bundle 内容,代价是不引用官方增量包自带的 "
                       "EdDSA 验签。下方给出两个全量包的 SHA-256 与代码签名/公证的实际验证结果。")
        else:
            out.append("本版为历史回填:官方 appcast 未对这一对版本提供增量包(通常因已超出 Sparkle 增量窗口),"
                       "改为下载两个官方全量包直接比较。下方给出两个全量包的 SHA-256 与代码签名/公证的实际验证结果。"
                       "注意:部分早期版本的签名证书后来被吊销,验证会显示 `CSSMERR_TP_CERT_REVOKED` —— "
                       "这只影响该版本能否被系统安全安装,不影响对其 bundle 内容做差异分析;若出现请如实说明。")
        out.append(f"- 上一版全量包: {meta.get('previous_full_url','?')}")
        out.append(f"  - SHA-256: `{meta.get('previous_full_sha256','?')}`")
        out.append(f"- 最新版全量包: {meta.get('latest_full_url','?')}")
        out.append(f"  - SHA-256: `{meta.get('latest_full_sha256','?')}`")
        for label, fn in [("上一版", "previous-spctl.txt"), ("最新版", "latest-spctl.txt")]:
            p = w / fn
            if p.exists():
                out.append(f"- {label}公证验证:\n```\n" + p.read_text().strip() + "\n```")
    else:
        sha = (w / "download-sha256.txt")
        if sha.exists():
            out.append("下载制品 SHA-256:\n```\n" + sha.read_text().strip() + "\n```")
        out.append(f"- 上一版全量包: {meta.get('previous_full_url','?')} "
                   f"({meta.get('previous_full_len','?')} bytes)")
        out.append(f"  - EdDSA 签名: `{meta.get('previous_full_sig','?')}`")
        out.append(f"- 官方增量包: {meta.get('latest_delta_url','?')} "
                   f"({meta.get('latest_delta_len','?')} bytes)")
        out.append(f"  - EdDSA 签名: `{meta.get('latest_delta_sig','?')}`")
        out.append("- 两个制品均通过官方 Sparkle 公钥 EdDSA 验签。")
        spctl = (w / "latest-spctl.txt")
        if spctl.exists():
            out.append("- 重建产物签名验证(codesign --deep --strict 通过):\n```\n"
                       + spctl.read_text().strip() + "\n```")

    # ---- bundle 文件树概览 ----
    fds = w / "file-diff-summary.json"
    if fds.exists():
        rep = json.loads(fds.read_text())
        s = rep["summary"]
        out.append(section("Bundle 文件树概览"))
        out.append(f"- 文件数: {s['prev_files']} → {s['new_files']}")
        out.append(f"- 新增 {s['added_count']} / 移除 {s['removed_count']} / 内容改动 {s['changed_count']}")
        out.append("\n体积变化最大的组件(已剔除 0 字节变化与 hash 噪音):")
        out.append("\n| 组件路径 | 旧 | 新 | 变化 |\n| --- | --- | --- | --- |")
        shown = 0
        for r in rep["changed_top"]:
            if r["delta_size"] == 0 or "webview/assets/" in r["path"]:
                continue
            out.append(f"| `{r['path']}` | {mb(r['old_size'])} | {mb(r['new_size'])} "
                       f"| {'+' if r['delta_size']>=0 else ''}{r['delta_size']/1e6:.2f} MB |")
            shown += 1
            if shown >= 18:
                break
        out.append("\n体积最大的新增文件(节选):")
        for r in rep["added"][:14]:
            out.append(f"- `{r['path']}` ({mb(r['size'])})")
        for r in rep.get("removed", []):
            out.append(f"- 移除: `{r['path']}` ({mb(r['size'])})")

    # ---- 内置插件清单变化 ----
    # 新增插件通常代表一个完整能力面,不能只靠体积 top-N 或 marketplace diff 间接提示。
    # 对任意新增/移除的 openai-bundled plugin,直接暴露 manifest、MCP 入口、技能说明和主要文件。
    prev_bundle_root, new_bundle_root, plugin_rel = bundle_roots(w)
    prev_plugin_root = prev_bundle_root / plugin_rel
    new_plugin_root = new_bundle_root / plugin_rel
    if prev_plugin_root.exists() and new_plugin_root.exists():
        prev_plugins = {p.name: p for p in prev_plugin_root.iterdir() if p.is_dir()}
        new_plugins = {p.name: p for p in new_plugin_root.iterdir() if p.is_dir()}
        added_plugins = sorted(set(new_plugins) - set(prev_plugins))
        removed_plugins = sorted(set(prev_plugins) - set(new_plugins))
        if added_plugins or removed_plugins:
            out.append(section("内置插件清单变化"))
            out.append("- 上一版内置插件: " + ", ".join(f"`{x}`" for x in sorted(prev_plugins)))
            out.append("- 最新版内置插件: " + ", ".join(f"`{x}`" for x in sorted(new_plugins)))
            if added_plugins:
                out.append("\n新增内置插件明细:")
                for name in added_plugins:
                    summary = plugin_summary(new_plugins[name])
                    out.append(f"\n### `{name}`")
                    out.append(f"- 文件数: {summary['fileCount']}, 总大小: {mb(summary['totalSize'])}")
                    if summary.get("version"):
                        out.append(f"- 版本: `{summary['version']}`")
                    for key, label in [
                        ("displayName", "显示名"),
                        ("description", "插件描述"),
                        ("shortDescription", "短描述"),
                        ("longDescription", "长描述"),
                        ("category", "分类"),
                    ]:
                        if summary.get(key):
                            out.append(f"- {label}: {summary[key]}")
                    if summary.get("keywords"):
                        out.append("- 关键词: " + ", ".join(f"`{x}`" for x in summary["keywords"]))
                    if summary.get("defaultPrompt"):
                        out.append("- 默认提示:")
                        for prompt in summary["defaultPrompt"]:
                            out.append(f"  - {prompt}")
                    if summary.get("mcp"):
                        out.append("- MCP 服务:")
                        for server_name, server in (summary["mcp"].get("mcpServers") or {}).items():
                            cmd = server.get("command")
                            args_ = " ".join(server.get("args") or [])
                            out.append(f"  - `{server_name}`: `{cmd}` {args_}".rstrip())
                    if summary.get("skills"):
                        out.append("- 技能说明摘录:")
                        for skill in summary["skills"]:
                            out.append(f"\n`{skill['path']}`:\n```markdown\n{skill['excerpt']}\n```")
                    if summary.get("topFiles"):
                        out.append("- 最大文件:")
                        for row in summary["topFiles"]:
                            out.append(f"  - `{row['path']}` ({mb(row['size'])})")
            if removed_plugins:
                out.append("\n移除内置插件:")
                for name in removed_plugins:
                    summary = plugin_summary(prev_plugins[name])
                    desc = f" — {summary['description']}" if summary.get("description") else ""
                    out.append(f"- `{name}`{desc}")

    # ---- cua_node 总量 ----
    _cua = ("app/resources/cua_node" if os.environ.get("CL_PLATFORM") == "windows"
            else "Codex.app/Contents/Resources/cua_node")
    prev_cua = dir_size(w / "previous-extract" / _cua)
    new_cua = dir_size(w / "latest-reconstructed" / _cua)
    if prev_cua and new_cua:
        out.append(section("Computer Use 运行时(cua_node)总量"))
        out.append(f"- {mb(prev_cua)} → {mb(new_cua)} "
                   f"(+{(new_cua-prev_cua)/1e6:.0f} MB, +{(new_cua-prev_cua)/prev_cua*100:.0f}%)"
                   f" — 口径:累加全部文件内容大小(非磁盘块占用),跨平台可复现")

    # ---- cua_node 依赖 diff ----
    cpd = w / "cua-package-diff.json"
    if cpd.exists():
        rep = json.loads(cpd.read_text())
        out.append(section("cua_node 依赖变化"))
        out.append(f"新增 {len(rep['added'])} 个包:")
        for p in rep["added"]:
            out.append(f"- `{p['name']}@{p.get('version','')}` — {p.get('desc','')}")
        if rep["removed"]:
            out.append("移除:")
            for p in rep["removed"]:
                out.append(f"- `{p['name']}@{p.get('version','')}`")
        if rep["changed"]:
            out.append("版本变化:")
            for p in rep["changed"]:
                out.append(f"- `{p['name']}`: {p['from']} → {p['to']}")

    # ---- ASAR 概览 + 前端 stem ----
    acd = w / "asar-content-diff.json"
    td = w / "targeted-diff.json"
    tgt = json.loads(td.read_text()) if td.exists() else {}
    if acd.exists():
        rep = json.loads(acd.read_text())
        out.append(section("应用层(app.asar)概览"))
        s = rep["summary"]
        out.append(f"- 内部文件: {s['prev']} → {s['next']} "
                   f"(新增 {s['added']} / 移除 {s['removed']} / 改动 {s['changed']})")
        out.append("- 注:webview/assets 下大量增减是 Vite 构建 hash 重命名,属噪音,不要据此判断新功能。")
    if tgt.get("asar_added_stems") or tgt.get("asar_removed_stems"):
        out.append("\n去掉 hash 噪音后,前端代码模块的真实增删(模块名未混淆,可反推方向,"
                   "但出现≠对用户开放):")
        if tgt.get("asar_added_stems"):
            out.append("新增模块: " + ", ".join(f"`{x}`" for x in tgt["asar_added_stems"]))
        if tgt.get("asar_removed_stems"):
            out.append("移除模块: " + ", ".join(f"`{x}`" for x in tgt["asar_removed_stems"]))

    fsd = rep.get("frontendStemDiff", []) if acd.exists() else []
    if fsd:
        out.append(section("同名前端模块改动线索"))
        out.append("> 这些模块在新旧版本都存在,但 hash 文件名不同且内容有变化。下面只列新增/移除的可读字符串"
                   "和样式类名集合差。它们是 UI、状态或交互方向的【信号】,需要与文案、模块名、权限或配置互相印证,"
                   "不能单独当作源码级事实。")
        for row in fsd[:30]:
            out.append(f"\n### `{row['stem']}` `{row['ext']}`")
            out.append(f"- 文件: `{row['oldPath']}` → `{row['newPath']}`")
            out.append(f"- 体积: {mb(row['oldSize'])} → {mb(row['newSize'])} "
                       f"({row['delta']:+} bytes)")
            if row.get("addedStrings"):
                out.append("- 新增可读字符串: " + ", ".join(f"`{x}`" for x in row["addedStrings"]))
            if row.get("removedStrings"):
                out.append("- 移除可读字符串: " + ", ".join(f"`{x}`" for x in row["removedStrings"]))
            if row.get("addedClasses"):
                out.append("- 新增样式/状态类名: " + ", ".join(f"`{x}`" for x in row["addedClasses"]))
            if row.get("removedClasses"):
                out.append("- 移除样式/状态类名: " + ", ".join(f"`{x}`" for x in row["removedClasses"]))

    # ---- 主进程 bundle 新增可读字符串(.vite/build 改名文件里的真实代码变化)----
    # main-<hash>.js 每版改名,逐文件 hash 配对会把它当重命名噪音而漏掉代码变化。
    # diff_asar.mjs 已提取新增字符串字面量,这里作为"关键信号"喂给 LLM——这是发现
    # SQLite 迁移这类后端/主进程变化的主要线索(26.609.41114 曾因缺此段而漏判)。
    vsd = rep.get("viteStringDiff", {}) if acd.exists() else {}
    if vsd.get("added"):
        out.append(section("主进程/前端 bundle 新增可读字符串(关键信号)"))
        out.append("> `.vite/build/main-<hash>.js` 等主进程 bundle 每版改名,逐文件 hash 配对会漏掉其"
                   "真实代码变化。下面是新版 bundle 里**新增的可读字符串字面量**(messageId 与英文 UI 文案)"
                   "——[实证]:字符串确凿存在于二进制,可据此判断新增功能方向;但仍是压缩代码,无法还原"
                   "完整源码语义。这是发现迁移/新功能最重要的线索之一,请重点分析,勿当噪音略过。")
        for s in vsd["added"]:
            out.append(f"- `{s}`")
        if vsd.get("removed"):
            out.append("\n移除的可读字符串(供参考): " + ", ".join(f"`{x}`" for x in vsd["removed"]))

    # ---- Info.plist ----
    ip = tgt.get("info_plist")
    if ip and not ip.get("error"):
        out.append(section("Info.plist 变化"))
        for r in ip.get("added", []):
            out.append(f"- 新增 `{r['key']}` = {r['new']}")
        for r in ip.get("removed", []):
            out.append(f"- 移除 `{r['key']}` (旧值 {r['old']})")
        for r in ip.get("changed", []):
            out.append(f"- `{r['key']}`: {r['old']} → {r['new']}")

    # ---- AppxManifest(Windows 权限/协议/文件类型)----
    # Windows 的 Info.plist 等价物:capability 是高价值的权限【实证】信号。
    am = tgt.get("appx_manifest")
    if am and not am.get("error") and any(am.get(k) for k in (
            "added_capabilities", "removed_capabilities", "added_protocols",
            "removed_protocols", "added_file_types", "removed_file_types")):
        out.append(section("AppxManifest 变化(Windows 权限/协议/文件类型)"))
        for key, label in [
            ("added_capabilities", "新增 capability(权限声明)"),
            ("removed_capabilities", "移除 capability"),
            ("added_protocols", "新增协议关联"),
            ("removed_protocols", "移除协议关联"),
            ("added_file_types", "新增文件类型关联"),
            ("removed_file_types", "移除文件类型关联"),
        ]:
            if am.get(key):
                out.append(f"- {label}: " + ", ".join(f"`{x}`" for x in am[key]))

    # ---- CSP ----
    if tgt.get("csp"):
        out.append(section("内容安全策略(CSP)connect-src 变化"))
        for c in tgt["csp"]:
            if c["added_domains"]:
                out.append(f"- `{c['file']}` 新增放行: {', '.join(c['added_domains'])}")
            if c["removed_domains"]:
                out.append(f"- `{c['file']}` 移除放行: {', '.join(c['removed_domains'])}")

    # ---- 新增插件 / 资源 ----
    if tgt.get("added_plugins") or tgt.get("added_resources"):
        out.append(section("新增组件与资源"))
        for p in tgt.get("added_plugins", []):
            sig = (f" — 签名 identifier `{p['identifier']}`, authority {p['authority']}"
                   if p.get("identifier") else "")
            out.append(f"- 新增插件 `{p['path']}`{sig}")
        for r in tgt.get("added_resources", []):
            out.append(f"- 新增资源 `{r['path']}` ({mb(r['size'])})")

    # ---- 关键文本 diff ----
    diffs = [d for d in (tgt.get("bundle_text_diffs", []) + tgt.get("asar_text_diffs", []))
             if d.get("diff", "").strip()]
    if diffs:
        out.append(section("关键文件的具体改动(unified diff)"))
        out.append("> 这些是人类可读的源文件/配置/技能文档差异,是判断「具体改了什么」的最强证据。")
        # 体积上限:双平台事实包合并后要喂给 LLM(约 1MB 输入硬限制),关键文件 diff 是体积大头
        # (尤其补上 Windows 实证层后,大变化版本曾撑爆 1MB 致整对 LLM 失败)。小而精的 diff 优先
        # (信息密度高、覆盖更多改动点),超预算的整文件级大 diff 省略并计数——宁可显式注明省略,
        # 也不静默截断、更不让事实包超限。单平台预算留足双平台合并余量。
        DIFF_BUDGET = 320_000
        diffs.sort(key=lambda d: len(d["diff"]))
        used, omitted = 0, []
        for d in diffs:
            block = (f"\n### `{d['path']}`  ({mb(d.get('old_size',0))} → {mb(d.get('new_size',0))})\n\n"
                     f"```diff\n{d['diff']}\n```")
            if used and used + len(block) > DIFF_BUDGET:
                omitted.append(d["path"])
                continue
            out.append(block)
            used += len(block)
        if omitted:
            out.append(f"\n> 注:另有 {len(omitted)} 个文件的 diff 因体积上限省略(已优先保留体积小、"
                       f"信息密度高的改动,以免事实包超出 LLM 输入限制):"
                       + ", ".join(f"`{p}`" for p in omitted[:40]))

    text = "\n".join(out) + "\n"
    (w / "llm-input.md").write_text(text)
    print(f"llm-input.md written: {len(text)} chars ({len(text)/1024:.1f} KB), "
          f"{len(diffs)} text diffs")


if __name__ == "__main__":
    main()
