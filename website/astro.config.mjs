import { defineConfig } from 'astro/config';

export default defineConfig({
  // 部署后改成实际域名(Cloudflare Pages 默认 *.pages.dev,或自定义域名)
  site: 'https://codex-app-changelog.pages.dev',
  output: 'static',
});
