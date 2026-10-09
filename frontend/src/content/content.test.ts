import { describe, expect, it } from 'vitest'

import { buildRobots, buildSitemap, sitemapPaths, staticPaths } from '../../vite-plugins/seo'
import { articles, dentists } from '@/content/people'
import { groups, serviceByCode, serviceBySlug, services, slugify } from '@/content/services'
import {
  clinic,
  hours,
  homeFaqs,
  insuranceCategories,
  legalLinks,
  mainNav,
  patientJourney,
  pillars,
} from '@/content/site'
import { imageSet } from '@/lib/images'
import { articleSchema, breadcrumbSchema, faqSchema, localBusinessSchema } from '@/lib/schema'

// The catalogue the database is seeded with (plan section 4.3).
const catalogue: [string, string, number, number][] = [
  ['SV01', 'Comprehensive Exam and X-rays', 60, 145],
  ['SV02', 'Routine Exam and Cleaning', 45, 120],
  ['SV03', 'Deep Cleaning (per quadrant)', 60, 220],
  ['SV04', 'Tooth Colored Filling', 45, 210],
  ['SV05', 'Porcelain Crown', 90, 1150],
  ['SV06', 'Root Canal Therapy', 90, 980],
  ['SV07', 'Simple Extraction', 45, 240],
  ['SV08', 'Surgical Extraction', 60, 480],
  ['SV09', 'Dental Implant Consultation', 45, 90],
  ['SV10', 'Dental Implant Placement', 120, 3200],
  ['SV11', 'Professional Teeth Whitening', 60, 420],
  ['SV12', 'Orthodontic Consultation', 45, 75],
  ['SV13', 'Clear Aligner Treatment (plan fee)', 30, 4800],
  ['SV14', 'Emergency Visit', 30, 160],
]

describe('service content', () => {
  it('matches the catalogue in the database', () => {
    expect(services.map((s) => [s.code, s.name, s.minutes, s.price])).toEqual(catalogue)
  })

  it('has unique, readable slugs', () => {
    const slugs = services.map((s) => s.slug)
    expect(new Set(slugs).size).toBe(14)
    for (const slug of slugs) expect(slug).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/)
    expect(slugify('Deep Cleaning (per quadrant)')).toBe('deep-cleaning')
    expect(serviceBySlug('porcelain-crown')?.code).toBe('SV05')
    expect(serviceBySlug('nothing')).toBeUndefined()
  })

  it('gives every service the sections a detail page needs', () => {
    for (const s of services) {
      expect(s.overview.length, s.code).toBeGreaterThan(80)
      expect(s.helps.length, s.code).toBeGreaterThanOrEqual(2)
      expect(s.steps.length, s.code).toBeGreaterThanOrEqual(3)
      expect(s.aftercare.length, s.code).toBeGreaterThanOrEqual(2)
      expect(s.faqs.length, s.code).toBeGreaterThanOrEqual(2)
      expect(s.related.length, s.code).toBeGreaterThanOrEqual(1)
      expect(s.range[0], s.code).toBeLessThanOrEqual(s.range[1])
      expect(s.range[0], s.code).toBeGreaterThanOrEqual(s.price <= 90 ? s.price : 0)
      for (const code of s.related)
        expect(serviceByCode(code), `${s.code} -> ${code}`).toBeDefined()
      expect(s.related).not.toContain(s.code)
      expect(groups[s.group]).toBeDefined()
    }
  })

  it('spreads services over the four menu categories', () => {
    expect(Object.keys(groups)).toEqual([
      'preventive',
      'restorative',
      'cosmetic',
      'surgical-orthodontic',
    ])
    for (const key of Object.keys(groups))
      expect(
        services.some((s) => s.group === key),
        key,
      ).toBe(true)
  })
})

describe('people, articles and site facts', () => {
  it('lists the seven dentists of the demonstration database', () => {
    expect(dentists.map((d) => d.name)).toEqual([
      'Dr. Priya Raman',
      'Dr. Marcus Lindqvist',
      'Dr. Hannah Okafor',
      'Dr. Daniel Reyes',
      'Dr. Sofia Marchetti',
      'Dr. Theodore Whitfield',
      'Dr. Amara Nwosu',
    ])
    expect(new Set(dentists.map((d) => d.slug)).size).toBe(7)
    for (const d of dentists) expect(d.education.length).toBeGreaterThan(0)
  })

  it('has three to five original articles with a reading time', () => {
    expect(articles.length).toBeGreaterThanOrEqual(3)
    expect(articles.length).toBeLessThanOrEqual(5)
    for (const a of articles) {
      expect(a.minutes).toBeGreaterThan(0)
      expect(a.body.length).toBeGreaterThan(1)
      expect(a.source).toMatch(/public/i)
    }
  })

  it('has the pieces the home page promises', () => {
    expect(homeFaqs).toHaveLength(8)
    expect(patientJourney.map((p) => p.title)).toEqual([
      'Book',
      'Visit',
      'Treatment plan',
      'Follow up',
    ])
    expect(pillars.length).toBeGreaterThanOrEqual(3)
    expect(insuranceCategories.map((c) => c.title)).toEqual(
      expect.arrayContaining(['PPO plans', 'HMO style plans', 'Self pay', 'Payment plans']),
    )
    expect(mainNav.patientInfo.map((i) => i.label)).toEqual([
      'New patients',
      'Insurance and payment',
      'Pricing',
      'FAQ',
      'Forms',
    ])
    expect(legalLinks.map((l) => l.to)).toEqual([
      '/privacy',
      '/terms',
      '/accessibility',
      '/notice-of-privacy-practices',
    ])
    expect(hours.map((h) => h.days)).toEqual(['Monday to Friday', 'Saturday', 'Sunday'])
  })

  it('never names a real accrediting body or uses brand logos', () => {
    const text = JSON.stringify({ homeFaqs, pillars, insuranceCategories, services, articles })
    expect(text).not.toMatch(/\bADA\b|Delta Dental|Cigna|Aetna|MetLife|Blue Cross/)
  })
})

describe('images', () => {
  it('has every picture the site refers to, as WebP with a srcset and a real size', () => {
    const names = [
      'hero',
      'interior',
      'technology',
      'about',
      'gallery-1',
      'gallery-2',
      'gallery-3',
      'gallery-4',
      ...Object.values(groups).map((g) => g.image),
      ...dentists.map((d) => d.image),
      ...articles.map((a) => a.image),
    ]
    for (const name of names) {
      const image = imageSet(name)
      expect(image.src, name).toMatch(/\.webp$/)
      expect(image.srcSet.split(',').length, name).toBeGreaterThanOrEqual(2)
      expect(image.width).toBeGreaterThan(0)
      expect(image.height).toBeGreaterThan(0)
    }
    expect(() => imageSet('nope')).toThrow(/Unknown image/)
  })

  it('keeps the shape of each picture', () => {
    const hero = imageSet('hero')
    expect(hero.width / hero.height).toBeCloseTo(16 / 9, 1)
    const portrait = imageSet('dentist-1')
    expect(portrait.width).toBe(portrait.height)
  })
})

describe('structured data', () => {
  it('describes the practice as a Dentist and a LocalBusiness', () => {
    const data = localBusinessSchema() as Record<string, unknown>
    expect(data['@type']).toEqual(['Dentist', 'LocalBusiness'])
    expect(data.telephone).toBe(clinic.phone)
    expect((data.address as Record<string, string>).postalCode).toBe(clinic.address.postalCode)
    const opening = data.openingHoursSpecification as {
      dayOfWeek: string[]
      opens: string
      closes: string
    }[]
    expect(opening).toHaveLength(2)
    expect(opening[0]?.dayOfWeek).toEqual(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'])
    expect(opening[1]).toMatchObject({ dayOfWeek: ['Saturday'], opens: '09:00', closes: '14:00' })
    expect(JSON.stringify(data)).not.toContain('aggregateRating') // demonstration reviews are not marked up as real
  })

  it('builds FAQ, breadcrumb and article data', () => {
    const faq = faqSchema(homeFaqs) as {
      mainEntity: { name: string; acceptedAnswer: { text: string } }[]
    }
    expect(faq.mainEntity).toHaveLength(8)
    expect(faq.mainEntity[0]?.acceptedAnswer.text).toBe(homeFaqs[0]?.a)
    const crumbs = breadcrumbSchema([
      { label: 'Home', to: '/' },
      { label: 'Services', to: '/services' },
      { label: 'Crown' },
    ]) as { itemListElement: { position: number; item?: string }[] }
    expect(crumbs.itemListElement.map((i) => i.position)).toEqual([1, 2, 3])
    expect(crumbs.itemListElement[2]?.item).toBeUndefined()
    const article = articles[0] as (typeof articles)[number]
    expect(articleSchema(article)).toMatchObject({ '@type': 'Article', headline: article.title })
  })
})

describe('sitemap and robots', () => {
  it('lists every public page once and no private page', () => {
    const paths = sitemapPaths()
    expect(new Set(paths).size).toBe(paths.length)
    expect(paths).toHaveLength(
      staticPaths.length + services.length + dentists.length + articles.length,
    )
    for (const s of services) expect(paths).toContain(`/services/${s.slug}`)
    for (const d of dentists) expect(paths).toContain(`/dentists/${d.slug}`)
    for (const a of articles) expect(paths).toContain(`/resources/${a.slug}`)
    for (const hidden of ['/login', '/register', '/account', '/styleguide', '/book'])
      expect(paths).not.toContain(hidden)
  })

  it('writes valid sitemap and robots files', () => {
    const xml = buildSitemap('https://clinic.example/', ['/', '/faq'], '2026-10-01')
    expect(xml).toContain('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    expect(xml).toContain('<loc>https://clinic.example/</loc>')
    expect(xml).toContain('<loc>https://clinic.example/faq</loc>')
    expect(xml.match(/<url>/g)).toHaveLength(2)
    const robots = buildRobots('https://clinic.example/')
    expect(robots).toContain('Sitemap: https://clinic.example/sitemap.xml')
    expect(robots).toContain('Disallow: /login')
    expect(robots).toContain('User-agent: *')
  })
})
