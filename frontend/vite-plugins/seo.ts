import type { Plugin } from 'vite'

import { articles, dentists } from '../src/content/people'
import { services } from '../src/content/services'

/** Public pages that search engines should know about. Sign in, account and booking are left out. */
export const staticPaths = [
  '/',
  '/services',
  '/dentists',
  '/about',
  '/new-patients',
  '/insurance-and-payment',
  '/pricing',
  '/faq',
  '/reviews',
  '/contact',
  '/resources',
  '/privacy',
  '/terms',
  '/accessibility',
  '/notice-of-privacy-practices',
]

export function sitemapPaths(): string[] {
  return [
    ...staticPaths,
    ...services.map((s) => `/services/${s.slug}`),
    ...dentists.map((d) => `/dentists/${d.slug}`),
    ...articles.map((a) => `/resources/${a.slug}`),
  ]
}

export function buildSitemap(base: string, paths: string[], lastmod: string): string {
  const root = base.replace(/\/$/, '')
  const rows = paths
    .map(
      (path) =>
        `  <url><loc>${root}${path === '/' ? '/' : path}</loc><lastmod>${lastmod}</lastmod></url>`,
    )
    .join('\n')
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${rows}\n</urlset>\n`
}

export function buildRobots(base: string): string {
  const root = base.replace(/\/$/, '')
  return [
    'User-agent: *',
    'Allow: /',
    'Disallow: /login',
    'Disallow: /register',
    'Disallow: /forgot-password',
    'Disallow: /reset-password',
    'Disallow: /verify-email',
    'Disallow: /account',
    'Disallow: /styleguide',
    '',
    `Sitemap: ${root}/sitemap.xml`,
    '',
  ].join('\n')
}

/** Writes sitemap.xml and robots.txt into the build, using VITE_SITE_URL as the address. */
export function seoFiles(): Plugin {
  const base = process.env.VITE_SITE_URL ?? 'https://meridian.example'
  let serverBuild = false
  return {
    name: 'seo-files',
    apply: 'build',
    configResolved(config) {
      serverBuild = Boolean(config.build.ssr)
    },
    generateBundle() {
      if (serverBuild) return
      this.emitFile({
        type: 'asset',
        fileName: 'sitemap.xml',
        source: buildSitemap(base, sitemapPaths(), new Date().toISOString().slice(0, 10)),
      })
      this.emitFile({ type: 'asset', fileName: 'robots.txt', source: buildRobots(base) })
    },
  }
}
