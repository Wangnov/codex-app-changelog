// 把仓库根的 releases/*.md 同步进 Astro content 目录(构建前自动跑)。
// 让网站始终以 releases/ 为唯一数据源,无需手工维护两份。
import fs from 'node:fs';
import path from 'node:path';

const src = path.resolve('../releases');
const dst = path.resolve('src/content/changelog');
fs.mkdirSync(dst, { recursive: true });

for (const f of fs.readdirSync(dst)) {
  if (f.endsWith('.md')) fs.rmSync(path.join(dst, f));
}
let n = 0;
for (const f of fs.readdirSync(src)) {
  if (f.endsWith('.md')) {
    fs.copyFileSync(path.join(src, f), path.join(dst, f));
    n++;
  }
}
console.log(`[sync] ${n} 篇 changelog → website/src/content/changelog/`);
