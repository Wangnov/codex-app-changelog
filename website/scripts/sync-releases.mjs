// 把仓库根的 changelog 同步进 Astro content 目录(构建前自动跑)。
// 中文 releases/*.md → content/changelog-zh/,英文 releases/en/*.md → content/changelog-en/。
import fs from 'node:fs';
import path from 'node:path';

function sync(srcRel, dstRel) {
  const src = path.resolve(srcRel);
  const dst = path.resolve(dstRel);
  fs.mkdirSync(dst, { recursive: true });
  for (const f of fs.readdirSync(dst)) if (f.endsWith('.md')) fs.rmSync(path.join(dst, f));
  let n = 0;
  if (fs.existsSync(src)) {
    for (const f of fs.readdirSync(src)) {
      if (f.endsWith('.md')) {
        fs.copyFileSync(path.join(src, f), path.join(dst, f));
        n++;
      }
    }
  }
  return n;
}

const zh = sync('../releases', 'src/content/changelog-zh');
const en = sync('../releases/en', 'src/content/changelog-en');
console.log(`[sync] 中文 ${zh} 篇,英文 ${en} 篇`);
