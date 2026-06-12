import rss from '@astrojs/rss';
import { getCollection } from 'astro:content';

export async function GET(context) {
  const entries = (await getCollection('changelog')).sort(
    (a, b) => b.data.build - a.data.build,
  );
  return rss({
    title: 'Codex App Changelog(非官方)',
    description: '第三方、自动化的 OpenAI Codex 桌面版逆向变更日志',
    site: context.site,
    items: entries.map((e) => ({
      title: `${e.data.version} (build ${e.data.build})`,
      description: e.data.summary,
      pubDate: new Date(e.data.released),
      link: `/${e.data.version}/`,
    })),
  });
}
