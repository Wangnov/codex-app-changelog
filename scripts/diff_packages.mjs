#!/usr/bin/env node
// 对比两版 cua_node/lib/node_modules 的 npm 包(含 @scope),产出 cua-package-diff.json。
// 这是判断"能力扩张"的最强信号(新增依赖群往往揭示新功能)。
// 用法: node scripts/diff_packages.mjs <work-dir>
import fs from "node:fs";
import path from "node:path";

const lab = process.argv[2];
if (!lab) { console.error("用法: diff_packages.mjs <work-dir>"); process.exit(1); }
const roots = {
  prev: path.join(lab, "previous-extract/Codex.app/Contents/Resources/cua_node/lib/node_modules"),
  next: path.join(lab, "latest-reconstructed/Codex.app/Contents/Resources/cua_node/lib/node_modules") };

function packages(root) {
  const out = new Map();
  if (!fs.existsSync(root)) return out;
  const add = (dir, name) => {
    const pkg = path.join(dir, "package.json");
    if (!fs.existsSync(pkg)) return;
    try { const j = JSON.parse(fs.readFileSync(pkg, "utf8"));
      out.set(name, { version: j.version || "", desc: j.description || "" }); }
    catch { out.set(name, { version: "", desc: "" }); }
  };
  for (const e of fs.readdirSync(root, { withFileTypes: true })) {
    if (!e.isDirectory() || e.name.startsWith(".")) continue;
    const p = path.join(root, e.name);
    if (e.name.startsWith("@")) {
      for (const s of fs.readdirSync(p, { withFileTypes: true }))
        if (s.isDirectory()) add(path.join(p, s.name), `${e.name}/${s.name}`);
    } else add(p, e.name);
  }
  return out;
}

const p = packages(roots.prev), n = packages(roots.next);
const added = [...n.keys()].filter(k => !p.has(k)).sort();
const removed = [...p.keys()].filter(k => !n.has(k)).sort();
const changed = [...n.keys()].filter(k => p.has(k) && p.get(k).version !== n.get(k).version).sort();

const report = {
  added: added.map(k => ({ name: k, ...n.get(k) })),
  removed: removed.map(k => ({ name: k, ...p.get(k) })),
  changed: changed.map(k => ({ name: k, from: p.get(k).version, to: n.get(k).version })) };
fs.writeFileSync(path.join(lab, "cua-package-diff.json"), JSON.stringify(report, null, 2));
console.log(`[diff_packages] +${added.length} -${removed.length} ~${changed.length}`);
