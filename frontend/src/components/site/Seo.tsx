import { Helmet } from 'react-helmet-async'

import { clinic } from '@/content/site'
import { imageSet } from '@/lib/images'

export interface SeoProps {
  /** The page name. The clinic name is added after it. */
  title: string
  description: string
  /** Path of this page, such as `/services`. Used for the canonical link and sharing. */
  path: string
  /** Image shown when the page is shared. */
  image?: string
  /** Structured data to include as JSON-LD. */
  jsonLd?: Record<string, unknown>[]
  /** Keep a page out of search results (sign in and account pages). */
  noindex?: boolean
  type?: 'website' | 'article'
}

const absolute = (value: string) => (value.startsWith('http') ? value : `${clinic.siteUrl}${value}`)

export function Seo({
  title,
  description,
  path,
  image = 'hero',
  jsonLd = [],
  noindex = false,
  type = 'website',
}: SeoProps) {
  const full = title === clinic.name ? title : `${title} | ${clinic.name}`
  const url = absolute(path)
  const picture = absolute(imageSet(image).src)
  return (
    <Helmet>
      <title>{full}</title>
      <meta name="description" content={description} />
      <link rel="canonical" href={url} />
      {noindex && <meta name="robots" content="noindex, nofollow" />}
      <meta property="og:site_name" content={clinic.name} />
      <meta property="og:type" content={type} />
      <meta property="og:title" content={full} />
      <meta property="og:description" content={description} />
      <meta property="og:url" content={url} />
      <meta property="og:image" content={picture} />
      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:title" content={full} />
      <meta name="twitter:description" content={description} />
      {jsonLd.map((data, index) => (
        <script key={index} type="application/ld+json">
          {JSON.stringify(data)}
        </script>
      ))}
    </Helmet>
  )
}
