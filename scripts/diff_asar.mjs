#!/usr/bin/env node
// 对两版 app.asar 解包内容做逐文件 sha256 差异,按目录分组,产出 asar-content-diff.json。
// 用法: node scripts/diff_asar.mjs <work-dir>
import fs from "node:fs";
import crypto from "node:crypto";
import path from "node:path";

const lab = process.argv[2];
if (!lab) { console.error("用法: diff_asar.mjs <work-dir>"); process.exit(1); }
const prev = path.join(lab, "asar-prev-extract");
const next = path.join(lab, "asar-latest-extract");

function walk(root, base = root, out = {}) {
  for (const e of fs.readdirSync(root, { withFileTypes: true })) {
    const p = path.join(root, e.name);
    if (e.isDirectory()) walk(p, base, out);
    else if (e.isFile()) {
      const rel = path.relative(base, p);
      const buf = fs.readFileSync(p);
      out[rel] = { size: buf.length, sha: crypto.createHash("sha256").update(buf).digest("hex") };
    }
  }
  return out;
}

const pm = walk(prev), nm = walk(next);
const ps = new Set(Object.keys(pm)), ns = new Set(Object.keys(nm));
const added = [...ns].filter(x => !ps.has(x)).sort();
const removed = [...ps].filter(x => !ns.has(x)).sort();
const changed = [...ps].filter(x => ns.has(x) && (pm[x].sha !== nm[x].sha || pm[x].size !== nm[x].size)).sort();

function group(p) {
  if (p.startsWith("webview/assets/")) return "webview/assets";
  if (p.startsWith(".vite/build/")) return ".vite/build";
  if (p.startsWith("node_modules/")) return "node_modules";
  if (p.startsWith("native-menu-locales/")) return "native-menu-locales";
  return p.split("/")[0];
}
function byGroup(list, src) {
  const m = new Map();
  for (const p of list) {
    const g = group(p); const c = m.get(g) || { count: 0, bytes: 0 };
    c.count++; c.bytes += (src[p]?.size || 0); m.set(g, c);
  }
  return [...m.entries()].sort((a, b) => b[1].bytes - a[1].bytes || b[1].count - a[1].count);
}

const changedRows = changed
  .map(p => ({ path: p, old: pm[p].size, new: nm[p].size, delta: nm[p].size - pm[p].size }))
  .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));

const report = {
  summary: { prev: Object.keys(pm).length, next: Object.keys(nm).length,
             added: added.length, removed: removed.length, changed: changed.length },
  addedGroups: byGroup(added, nm), removedGroups: byGroup(removed, pm),
  changedGroups: byGroup(changed, nm), changedTop: changedRows.slice(0, 100),
  addedSample: added.slice(0, 100), removedSample: removed.slice(0, 100) };
fs.writeFileSync(path.join(lab, "asar-content-diff.json"), JSON.stringify(report, null, 2));
console.log("[diff_asar]", JSON.stringify(report.summary));
