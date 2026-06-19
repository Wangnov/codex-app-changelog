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

// ---- 主进程 bundle(.vite/build/*.js)新增可读字符串 ----
// 这些文件名带构建 hash(main-<hash>.js),每版改名。按精确路径配对时它们落入 added/removed,
// 看起来只是"重命名噪音",真正的代码变化(新增 messageId / UI 文案 / 迁移逻辑)被埋没——
// 这正是 26.609.41114 的 SQLite backfill 一度被漏判的原因。改为提取 .vite/build 下所有 *.js 的
// 可读字符串字面量做集合差,surface 新增的高信号字符串([实证]:字面量确凿存在)。
function viteStrings(map, root) {
  const acc = new Set();
  for (const rel of Object.keys(map)) {
    if (!rel.startsWith(".vite/build/") || !rel.endsWith(".js")) continue;
    const txt = fs.readFileSync(path.join(root, rel), "utf8");
    for (const m of txt.matchAll(/[`'"]([^`'"\n]{4,90})[`'"]/g)) {
      const s = m[1];
      // messageId / 事件名:点分命名(如 codex.sqliteBackfillProgress.title)
      if (/^[a-z][a-zA-Z0-9]+(\.[a-zA-Z0-9_]+){1,4}$/.test(s)) { acc.add(s); continue; }
      // 自然语言 UI 文案:含空格、仅可读标点、排除代码片段
      if (s.includes(" ") && /^[A-Za-z(]/.test(s)
          && /^[A-Za-z0-9 ,.:;!?()'"/—-]+$/.test(s)
          && !/[;{}]|=>|:return|\bcase\b|\bfunction\b|prototype|\(0,|\?[A-Za-z]|\([a-z]\)/.test(s)
          && (s.match(/[A-Za-z]{2,}/g) || []).length >= 2) { acc.add(s); continue; }
    }
  }
  return acc;
}
const vp = viteStrings(pm, prev), vn = viteStrings(nm, next);
const viteAdded = [...vn].filter(s => !vp.has(s)).sort();
const viteRemoved = [...vp].filter(s => !vn.has(s)).sort();

// ---- 前端资产 stem 级内容线索 ----
// webview/assets 下的大多数文件每版都会因为 hash 改名落入 added/removed。
// 只看 stem 的新增/删除会漏掉“同一个组件内部样式或文案改变”的 UI 变化。
// 这里把同名 stem 的新旧文件配对,抽取少量可读字符串和样式类名集合差。
function assetStemMap(map) {
  const out = new Map();
  const rx = /^webview\/assets\/(.+)-[A-Za-z0-9_-]{8}\.(js|css)$/;
  for (const rel of Object.keys(map)) {
    const m = rel.match(rx);
    if (!m) continue;
    const key = `${m[1]}.${m[2]}`;
    out.set(key, { stem: m[1], ext: m[2], rel, size: map[rel].size, sha: map[rel].sha });
  }
  return out;
}

function literalSet(txt) {
  const acc = new Set();
  for (const m of txt.matchAll(/[`'"]([^`'"\n]{3,140})[`'"]/g)) {
    const s = m[1].trim();
    if (!s) continue;
    if (looksLikeClassList(s)) continue;
    if (/^\.\.?\//.test(s) || /^https?:\/\//.test(s) || /^data:/.test(s)) continue;
    if (/\.(js|css|svg|png|jpg|jpeg|webp|gif|woff2?|ttf|wasm)$/i.test(s)) continue;
    if (/^[A-Za-z0-9_-]{8,}$/.test(s)) continue;
    if (/^[A-Za-z_$][\w$]*$/.test(s) && s.length < 18) continue;
    if (/[{};=<>]/.test(s) || /=>|\(0,|prototype|\bfunction\b|\bthrow\b|\breturn\b/.test(s)) continue;
    if (/^[a-z][a-zA-Z0-9]+(\.[a-zA-Z0-9_]+){1,6}$/.test(s)) {
      acc.add(s);
      continue;
    }
    if (s.includes(" ") && /^[A-Za-z0-9 ,.:;!?()'"/—–-]+$/.test(s)
        && (s.match(/[A-Za-z]{2,}/g) || []).length >= 2) {
      acc.add(s);
    }
  }
  return acc;
}

function looksLikeClassList(s) {
  const tokens = s.split(/\s+/).filter(Boolean);
  if (tokens.length < 2) return false;
  let hits = 0;
  for (let token of tokens) {
    token = token.replace(/^!/, "");
    if (/[-:\[\]\/]/.test(token)
        || /^(flex|grid|block|inline|hidden|relative|absolute|fixed|sticky|items|justify|gap|w|h|size|px|py|pt|pr|pb|pl|mx|my|mt|mr|mb|ml|rounded|border|bg|text|font|leading|opacity|shadow|ring|outline|overflow|truncate|whitespace|cursor|transition|z|top|right|bottom|left|inset)$/.test(token)) {
      hits++;
    }
  }
  return hits / tokens.length >= 0.7;
}

function classTokenSet(txt) {
  const acc = new Set();
  for (const m of txt.matchAll(/[`'"]([^`'"\n]{3,260})[`'"]/g)) {
    const s = m[1];
    if (!/[-:\[\]\/ ]/.test(s)) continue;
    for (let raw of s.split(/\s+/)) {
      raw = raw.trim().replace(/^!/, "");
      if (raw.length < 3 || raw.length > 90) continue;
      if (raw.includes("${") || raw.includes("{") || raw.includes("}")) continue;
      if (/[=;,()]/.test(raw) || raw.endsWith(":") || raw.includes("Symbol.for")) continue;
      if (!/[-:\[\]\/]/.test(raw)) continue;
      if (!/^(?:@?container|group|peer|aria-|data-|dark|electron-dark|hover|focus|active|disabled|enabled|has-|not-|motion-|sm|md|lg|xl|2xl|flex|grid|block|inline|hidden|relative|absolute|fixed|sticky|items|justify|content|self|gap|space|w|h|min|max|size|p|px|py|pt|pr|pb|pl|m|mx|my|mt|mr|mb|ml|rounded|border|bg|text|font|leading|tracking|opacity|shadow|ring|outline|overflow|truncate|line-clamp|whitespace|break|select|cursor|transition|duration|ease|animate|z|top|right|bottom|left|inset|translate|scale|rotate|origin|object|aspect|divide|backdrop|blur|sr-only)/.test(raw)) continue;
      acc.add(raw);
    }
  }
  return acc;
}

function sampleDiff(a, b, limit) {
  return [...b].filter(x => !a.has(x)).sort().slice(0, limit);
}

function frontendStemDiffs() {
  const pp = assetStemMap(pm);
  const nn = assetStemMap(nm);
  const rows = [];
  const visibleRx = /(composer|status|run|task|progress|toast|tooltip|button|dialog|panel|sidebar|header|footer|input|voice|browser|download|permission|settings|model|reasoning|plugin|skill|record|replay|automation|worktree|pull-request|usage|rate-limit|environment|session|history|home|onboarding)/i;
  for (const [key, pinfo] of pp.entries()) {
    const ninfo = nn.get(key);
    if (!ninfo || pinfo.sha === ninfo.sha) continue;
    const ptxt = fs.readFileSync(path.join(prev, pinfo.rel), "utf8");
    const ntxt = fs.readFileSync(path.join(next, ninfo.rel), "utf8");
    const ps = literalSet(ptxt), ns = literalSet(ntxt);
    const pc = classTokenSet(ptxt), nc = classTokenSet(ntxt);
    const addedStrings = sampleDiff(ps, ns, 12);
    const removedStrings = sampleDiff(ns, ps, 8);
    const addedClasses = sampleDiff(pc, nc, 18);
    const removedClasses = sampleDiff(nc, pc, 12);
    if (!addedStrings.length && !removedStrings.length && !addedClasses.length && !removedClasses.length) continue;
    const visibleText = [pinfo.stem, ...addedStrings, ...removedStrings].join(" ");
    const score = addedStrings.length * 8 + removedStrings.length * 3
      + addedClasses.length * 2 + removedClasses.length
      + (visibleRx.test(visibleText) ? 40 : 0)
      + Math.min(20, Math.abs(ninfo.size - pinfo.size) / 200);
    rows.push({
      stem: pinfo.stem, ext: pinfo.ext,
      oldPath: pinfo.rel, newPath: ninfo.rel,
      oldSize: pinfo.size, newSize: ninfo.size, delta: ninfo.size - pinfo.size,
      addedStrings, removedStrings, addedClasses, removedClasses, score
    });
  }
  return rows.sort((a, b) => b.score - a.score || Math.abs(b.delta) - Math.abs(a.delta)).slice(0, 40);
}

const report = {
  summary: { prev: Object.keys(pm).length, next: Object.keys(nm).length,
             added: added.length, removed: removed.length, changed: changed.length },
  addedGroups: byGroup(added, nm), removedGroups: byGroup(removed, pm),
  changedGroups: byGroup(changed, nm), changedTop: changedRows.slice(0, 100),
  addedSample: added.slice(0, 100), removedSample: removed.slice(0, 100),
  viteStringDiff: { added: viteAdded.slice(0, 150), removed: viteRemoved.slice(0, 80) },
  frontendStemDiff: frontendStemDiffs() };
fs.writeFileSync(path.join(lab, "asar-content-diff.json"), JSON.stringify(report, null, 2));
console.log("[diff_asar]", JSON.stringify({
  ...report.summary,
  viteAdded: viteAdded.length,
  viteRemoved: viteRemoved.length,
  frontendStemDiff: report.frontendStemDiff.length
}));
