import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const schema = z.object({
  title: z.string(),
  version: z.string(),
  build: z.number(),
  previous_version: z.string().optional(),
  previous_build: z.number().optional(),
  platform: z.string().optional(),
  released: z.string(),
  compared_from: z.string().optional(),
  method: z.string().optional(),
  summary: z.string(),
  official_release_notes: z.boolean().optional(),
  // 跨平台篇额外字段(单平台篇没有,故 optional)
  mac_version: z.string().optional(),
  mac_build: z.number().optional(),
  win_version: z.string().optional(),
  platforms: z.array(z.string()).optional(),
});

// 中英两套(由 scripts/sync-releases.mjs 从 releases/ 与 releases/en/ 同步进来)。
const changelog_zh = defineCollection({
  loader: glob({ pattern: '*.md', base: './src/content/changelog-zh' }),
  schema,
});
const changelog_en = defineCollection({
  loader: glob({ pattern: '*.md', base: './src/content/changelog-en' }),
  schema,
});

export const collections = { changelog_zh, changelog_en };
