import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://codexapp.agentsmirror.com',
  base: '/changelog',
  // 输出到 dist/changelog/,这样 Workers assets(directory=./dist)能按
  // URL /changelog/* 直接命中 dist/changelog/* 文件。
  outDir: './dist/changelog',
  output: 'static',
});
