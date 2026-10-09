import { clinic, fullAddress, hours } from '@/content/site'

type Json = Record<string, unknown>

/** The practice as both a Dentist and a LocalBusiness. */
export function localBusinessSchema(): Json {
  return {
    '@context': 'https://schema.org',
    '@type': ['Dentist', 'LocalBusiness'],
    '@id': `${clinic.siteUrl}/#practice`,
    name: clinic.name,
    url: clinic.siteUrl,
    telephone: clinic.phone,
    email: clinic.email,
    description: `${clinic.tagline}. General, pediatric, orthodontic, endodontic, periodontic, surgical and cosmetic dentistry.`,
    address: {
      '@type': 'PostalAddress',
      streetAddress: clinic.address.street,
      addressLocality: clinic.address.city,
      addressRegion: clinic.address.region,
      postalCode: clinic.address.postalCode,
      addressCountry: clinic.address.country,
    },
    geo: { '@type': 'GeoCoordinates', latitude: clinic.geo.lat, longitude: clinic.geo.lng },
    openingHoursSpecification: hours
      .filter((h) => h.schema.length > 0)
      .map((h) => ({
        '@type': 'OpeningHoursSpecification',
        dayOfWeek: [...h.schema],
        opens: h.from,
        closes: h.to,
      })),
    areaServed: clinic.address.city,
    priceRange: '$$',
    // Shown on the map and in results as the practice's address line.
    location: fullAddress,
  }
}

export function faqSchema(items: readonly { q: string; a: string }[]): Json {
  return {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: items.map((item) => ({
      '@type': 'Question',
      name: item.q,
      acceptedAnswer: { '@type': 'Answer', text: item.a },
    })),
  }
}

export function breadcrumbSchema(items: { label: string; to?: string }[]): Json {
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items.map((item, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      name: item.label,
      ...(item.to ? { item: `${clinic.siteUrl}${item.to}` } : {}),
    })),
  }
}

export function articleSchema(article: {
  title: string
  summary: string
  published: string
  slug: string
}): Json {
  return {
    '@context': 'https://schema.org',
    '@type': 'Article',
    headline: article.title,
    description: article.summary,
    datePublished: article.published,
    mainEntityOfPage: `${clinic.siteUrl}/resources/${article.slug}`,
    publisher: { '@type': 'Organization', name: clinic.name },
  }
}
