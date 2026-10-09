import { Clock, DollarSign, Search } from 'lucide-react'
import * as React from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { Picture } from '@/components/site/Picture'
import { CtaBand, PageHeader, Section } from '@/components/site/parts'
import { Badge, Card } from '@/components/ui/display'
import { Button } from '@/components/ui/button'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/disclosure'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { groups, serviceBySlug, type ServiceGroup } from '@/content/services'
import { useCatalog } from '@/lib/public-api'
import { faqSchema } from '@/lib/schema'
import { NotFoundPage } from '@/pages/NotFoundPage'

const money = (value: number) => `$${value.toLocaleString('en-US')}`
const groupKeys = Object.keys(groups) as ServiceGroup[]

export function ServicesPage() {
  const { services } = useCatalog()
  const [params, setParams] = useSearchParams()
  const group = groupKeys.find((g) => g === params.get('group'))
  const [query, setQuery] = React.useState('')
  const needle = query.trim().toLowerCase()
  const shown = services.filter(
    (s) =>
      (!group || s.group === group) &&
      (!needle || `${s.name} ${s.summary}`.toLowerCase().includes(needle)),
  )
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Services' }]}
        title="Our services"
        intro="Preventive, restorative, cosmetic, surgical and orthodontic care, with the prices and times shown up front."
        seo={{
          description:
            'Dental services in Springfield: checkups and cleanings, fillings, crowns, root canals, whitening, implants and aligners, with starting prices.',
          path: '/services',
          image: 'service-preventive',
        }}
      />
      <Section>
        <div className="mb-8 grid gap-6 md:grid-cols-[1fr_auto] md:items-end">
          <div role="group" aria-label="Filter by category" className="flex flex-wrap gap-2">
            {[
              { key: undefined, label: 'All services' },
              ...groupKeys.map((k) => ({ key: k, label: groups[k].title })),
            ].map(({ key, label }) => (
              <Button
                key={label}
                size="sm"
                variant={group === key ? 'primary' : 'secondary'}
                aria-pressed={group === key}
                onClick={() => setParams(key ? { group: key } : {})}
              >
                {label}
              </Button>
            ))}
          </div>
          <Field label="Search services" className="md:w-72">
            {(c) => (
              <div className="relative">
                <Search
                  className="pointer-events-none absolute top-3.5 left-3 size-4 text-muted-foreground"
                  aria-hidden="true"
                />
                <Input
                  {...c}
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="pl-9"
                  placeholder="For example, crown"
                />
              </div>
            )}
          </Field>
        </div>
        <p role="status" className="mb-4 text-sm text-muted-foreground">
          {shown.length} {shown.length === 1 ? 'service' : 'services'} shown
        </p>
        {shown.length === 0 ? (
          <p className="rounded-xl border border-dashed p-8 text-center">
            No service matches that search. Try a shorter word, or <Link to="/contact">ask us</Link>
            .
          </p>
        ) : (
          <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {shown.map((s) => (
              <li key={s.code}>
                <Card variant="interactive" className="flex h-full flex-col overflow-hidden">
                  <Picture
                    name={groups[s.group].image}
                    alt=""
                    sizes="(min-width: 1024px) 33vw, (min-width: 640px) 50vw, 100vw"
                    className="aspect-[3/2]"
                  />
                  <div className="flex flex-1 flex-col gap-3 p-5">
                    <Badge tone="brand" className="w-fit">
                      {groups[s.group].title}
                    </Badge>
                    <h2 className="font-heading text-lg font-bold">{s.name}</h2>
                    <p className="flex-1 text-sm text-muted-foreground">{s.summary}</p>
                    <p className="text-sm font-semibold">
                      From {money(s.price)} &middot; {s.minutes} min
                    </p>
                    <Link
                      to={`/services/${s.slug}`}
                      className="text-sm font-semibold text-accent-strong underline underline-offset-4"
                    >
                      Learn more <span className="sr-only">about {s.name}</span>
                    </Link>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <CtaBand />
    </>
  )
}

export function ServiceDetailPage() {
  const { slug = '' } = useParams()
  const { services } = useCatalog()
  const base = serviceBySlug(slug)
  const service = services.find((s) => s.code === base?.code) ?? base
  if (!service) return <NotFoundPage />
  const related = service.related
    .map((code) => services.find((s) => s.code === code))
    .filter((s) => s !== undefined)
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Services', to: '/services' }, { label: service.name }]}
        title={service.name}
        intro={service.summary}
        seo={{
          description: `${service.summary} ${service.minutes} minutes, from ${money(service.price)}. Book online at Meridian Dental Care.`,
          path: `/services/${service.slug}`,
          image: groups[service.group].image,
          jsonLd: [faqSchema(service.faqs)],
        }}
      >
        <ul className="mt-6 flex flex-wrap gap-6 text-sm font-semibold">
          <li className="inline-flex items-center gap-2">
            <Clock className="size-5 text-accent-strong" aria-hidden="true" />
            About {service.minutes} minutes
          </li>
          <li className="inline-flex items-center gap-2">
            <DollarSign className="size-5 text-accent-strong" aria-hidden="true" />
            From {money(service.price)}
          </li>
        </ul>
      </PageHeader>
      <Section>
        <div className="grid gap-10 lg:grid-cols-[2fr_1fr]">
          <div className="space-y-10">
            <section aria-labelledby="overview">
              <h2 id="overview" className="text-2xl">
                Overview
              </h2>
              <p className="mt-3 text-lg">{service.overview}</p>
            </section>
            <section aria-labelledby="helps">
              <h2 id="helps" className="text-2xl">
                Who it helps
              </h2>
              <ul className="mt-3 list-disc space-y-1.5 pl-6">
                {service.helps.map((h) => (
                  <li key={h}>{h}</li>
                ))}
              </ul>
            </section>
            <section aria-labelledby="steps">
              <h2 id="steps" className="text-2xl">
                What happens
              </h2>
              <ol className="mt-3 space-y-3">
                {service.steps.map((step, i) => (
                  <li key={step} className="flex gap-3">
                    <span
                      className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent-strong text-sm font-bold text-white"
                      aria-hidden="true"
                    >
                      {i + 1}
                    </span>
                    <span>
                      <span className="sr-only">Step {i + 1}: </span>
                      {step}
                    </span>
                  </li>
                ))}
              </ol>
            </section>
            <section aria-labelledby="aftercare">
              <h2 id="aftercare" className="text-2xl">
                Aftercare
              </h2>
              <ul className="mt-3 list-disc space-y-1.5 pl-6">
                {service.aftercare.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </section>
            <section aria-labelledby="questions">
              <h2 id="questions" className="text-2xl">
                Questions
              </h2>
              <Accordion type="single" collapsible className="mt-2">
                {service.faqs.map((f, i) => (
                  <AccordionItem key={f.q} value={`f${i}`}>
                    <AccordionTrigger>{f.q}</AccordionTrigger>
                    <AccordionContent>{f.a}</AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            </section>
          </div>
          <aside aria-label="Cost and booking" className="h-fit space-y-4 lg:sticky lg:top-28">
            <Card variant="elevated" className="p-6">
              <h2 className="text-lg">Typical cost</h2>
              <p className="mt-2 font-heading text-3xl font-extrabold text-primary">
                {service.range[0] === service.range[1]
                  ? money(service.range[0])
                  : `${money(service.range[0])} to ${money(service.range[1])}`}
              </p>
              <p className="mt-2 text-sm text-muted-foreground">
                The final cost depends on your exam and your insurance. We give you a written
                estimate before treatment.
              </p>
              <Button asChild size="lg" className="mt-5 w-full">
                <Link to={`/book?service=${service.code}`}>Book this service</Link>
              </Button>
            </Card>
          </aside>
        </div>
      </Section>
      {related.length > 0 && (
        <Section title="Related services" tint>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {related.map((r) => (
              <li key={r.code}>
                <Card variant="interactive" className="h-full">
                  <Link to={`/services/${r.slug}`} className="block h-full rounded-xl p-5">
                    <span className="font-heading font-bold">{r.name}</span>
                    <span className="mt-1 block text-sm text-muted-foreground">{r.summary}</span>
                  </Link>
                </Card>
              </li>
            ))}
          </ul>
        </Section>
      )}
      <CtaBand />
    </>
  )
}
