import rss from '@astrojs/rss';
import { getCollection } from 'astro:content';

export async function GET(context) {
  const entries = (await getCollection('changelog_en')).sort(
    (a, b) => b.data.build - a.data.build,
  );
  return rss({
    title: 'Codex App Changelog (Unofficial)',
    description:
      'Automated third-party reverse-engineered changelog for the OpenAI Codex desktop app',
    site: context.site,
    items: entries.map((e) => ({
      title: `${e.data.version} (build ${e.data.build})`,
      description: e.data.summary,
      pubDate: new Date(e.data.released),
      link: `/changelog/en/${e.data.version}/`,
    })),
  });
}
