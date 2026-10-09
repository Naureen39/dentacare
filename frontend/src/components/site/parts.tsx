import { ChevronLeft, ChevronRight, Phone } from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'

import { Seo, type SeoProps } from '@/components/site/Seo'
import { Button } from '@/components/ui/button'
import { Rating } from '@/components/ui/metrics'
import { Breadcrumbs, type Crumb } from '@/components/ui/navigation'
import { clinic } from '@/content/site'
import { breadcrumbSchema } from '@/lib/schema'
import { cn } from '@/lib/utils'

/** Top of every inner page: SEO tags, breadcrumbs (also as structured data), title and intro. */
export function PageHeader({
  crumbs,
  title,
  intro,
  seo,
  children,
}: {
  crumbs: Crumb[]
  title: string
  intro?: string
  seo: Omit<SeoProps, 'title' | 'jsonLd'> & { title?: string; jsonLd?: Record<string, unknown>[] }
  children?: React.ReactNode
}) {
  const trail: Crumb[] = [{ label: 'Home', to: '/' }, ...crumbs]
  return (
    <>
      <Seo
        {...seo}
        title={seo.title ?? title}
        jsonLd={[breadcrumbSchema(trail), ...(seo.jsonLd ?? [])]}
      />
      <div className="bg-secondary">
        <div className="container-page py-10 md:py-14">
          <Breadcrumbs items={trail} />
          <h1 className="mt-4 text-3xl md:text-5xl">{title}</h1>
          {intro && <p className="mt-4 max-w-3xl text-lg text-muted-foreground">{intro}</p>}
          {children}
        </div>
      </div>
    </>
  )
}

export function Section({
  id,
  title,
  intro,
  tint,
  children,
  className,
}: {
  id?: string
  title?: string
  intro?: string
  tint?: boolean
  children: React.ReactNode
  className?: string
}) {
  const heading = id ? `${id}-heading` : undefined
  return (
    <section
      id={id}
      aria-labelledby={title ? heading : undefined}
      className={cn('scroll-mt-24 section-space', tint && 'bg-secondary/60', className)}
    >
      <div className="container-page">
        {title && (
          <div className="mb-8 max-w-3xl md:mb-12">
            <h2 id={heading} className="text-2xl md:text-4xl">
              {title}
            </h2>
            {intro && <p className="mt-3 text-lg text-muted-foreground">{intro}</p>}
          </div>
        )}
        {children}
      </div>
    </section>
  )
}

export function CtaBand({
  title = 'Ready when you are',
  text = 'Book online in a minute, or call and we will find a time that suits you.',
}: {
  title?: string
  text?: string
}) {
  return (
    <section aria-label="Book an appointment" className="bg-primary text-primary-foreground">
      <div className="container-page flex flex-col items-start justify-between gap-6 py-12 md:flex-row md:items-center">
        <div>
          <h2 className="text-2xl text-white md:text-3xl">{title}</h2>
          <p className="mt-2 max-w-xl text-primary-foreground/90">{text}</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button asChild size="lg" variant="accent">
            <Link to="/book">Book an appointment</Link>
          </Button>
          <Button
            asChild
            size="lg"
            variant="secondary"
            className="border-white text-white hover:bg-white/10"
          >
            <a href={clinic.phoneHref}>
              <Phone className="size-5" aria-hidden="true" />
              {clinic.phone}
            </a>
          </Button>
        </div>
      </div>
    </section>
  )
}

/** A row of cards that scrolls sideways, with previous and next buttons and keyboard access. */
export function Carousel({ label, children }: { label: string; children: React.ReactNode[] }) {
  const track = React.useRef<HTMLDivElement>(null)
  const scroll = (direction: 1 | -1) => {
    const el = track.current
    if (el)
      el.scrollBy({
        left: direction * el.clientWidth * 0.85,
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
      })
  }
  const button =
    'inline-flex size-11 items-center justify-center rounded-full border bg-card text-primary shadow-soft hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring'
  return (
    <div role="region" aria-roledescription="carousel" aria-label={label}>
      <div className="mb-4 flex justify-end gap-2">
        <button
          type="button"
          className={button}
          onClick={() => scroll(-1)}
          aria-label={`Previous, ${label}`}
        >
          <ChevronLeft className="size-5" aria-hidden="true" />
        </button>
        <button
          type="button"
          className={button}
          onClick={() => scroll(1)}
          aria-label={`Next, ${label}`}
        >
          <ChevronRight className="size-5" aria-hidden="true" />
        </button>
      </div>
      <div
        ref={track}
        tabIndex={0}
        aria-label={`${label}, scrollable`}
        className="-mx-4 flex snap-x snap-mandatory [scrollbar-width:thin] gap-5 overflow-x-auto px-4 pb-4 focus-visible:outline-2 focus-visible:outline-ring"
      >
        {children.map((child, index) => (
          <div
            key={index}
            role="group"
            aria-roledescription="slide"
            aria-label={`${index + 1} of ${children.length}`}
            className="w-[85%] shrink-0 snap-start sm:w-[45%] lg:w-[31%]"
          >
            {child}
          </div>
        ))}
      </div>
    </div>
  )
}

export function ReviewCard({
  review,
}: {
  review: {
    firstName: string
    lastInitial: string
    treatment: string | null
    rating: number
    body: string
  }
}) {
  return (
    <figure className="flex h-full flex-col gap-3 rounded-xl border bg-card p-6 shadow-soft">
      <Rating value={review.rating} />
      <blockquote className="flex-1 text-base">&ldquo;{review.body}&rdquo;</blockquote>
      <figcaption className="text-sm">
        <span className="font-semibold text-primary">
          {review.firstName} {review.lastInitial}.
        </span>
        {review.treatment && (
          <span className="text-muted-foreground"> &middot; {review.treatment}</span>
        )}
        <span className="mt-1 block text-xs font-medium text-success-strong">
          Verified patient (demonstration review)
        </span>
      </figcaption>
    </figure>
  )
}
