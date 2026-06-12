import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

// changelog 条目来自仓库根的 releases/*.md(由 scripts/sync-releases.mjs 同步进来)。
const changelog = defineCollection({
  loader: glob({ pattern: '*.md', base: './src/content/changelog' }),
  schema: z.object({
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
  }),
});

export const collections = { changelog };
