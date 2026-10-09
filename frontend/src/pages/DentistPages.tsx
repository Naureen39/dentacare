import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { Picture } from '@/components/site/Picture'
import { CtaBand, PageHeader, Section } from '@/components/site/parts'
import { Button } from '@/components/ui/button'
import { Badge, Card } from '@/components/ui/display'
import { dentistBySlug, dentists } from '@/content/people'
import { serviceByCode } from '@/content/services'
import { addDays, dateInZone, formatDate, formatTime, toDateString } from '@/lib/dates'
import { apiGet } from '@/lib/api-client'
import type { components } from '@/lib/api-types'
import { NotFoundPage } from '@/pages/NotFoundPage'

const ZONE = 'America/New_York'

export function DentistsPage() {
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Our dentists' }]}
        title="Our dentists"
        intro="Seven specialists across general, pediatric, orthodontic, endodontic, periodontal, surgical and cosmetic dentistry."
        seo={{
          description:
            'Meet the dentists of Meridian Dental Care: general, pediatric, orthodontic, endodontic, periodontal, oral surgery and cosmetic specialists.',
          path: '/dentists',
          image: 'dentist-1',
        }}
      />
      <Section>
        <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {dentists.map((d) => (
            <li key={d.slug}>
              <Card variant="interactive" className="flex h-full flex-col overflow-hidden">
                <Picture
                  name={d.image}
                  alt={`Portrait of ${d.name}`}
                  sizes="(min-width: 1024px) 33vw, (min-width: 640px) 50vw, 100vw"
                  className="aspect-square"
                />
                <div className="flex flex-1 flex-col gap-2 p-5">
                  <h2 className="font-heading text-xl font-bold">{d.name}</h2>
                  <p className="text-sm font-semibold text-accent-strong">{d.specialty}</p>
                  <p className="flex-1 text-sm text-muted-foreground">{d.bio}</p>
                  <div className="flex flex-wrap gap-2 pt-2">
                    <Button asChild size="sm">
                      <Link to={`/book?dentist=${d.slug}`}>Book with {d.short}</Link>
                    </Button>
                    <Button asChild size="sm" variant="secondary">
                      <Link to={`/dentists/${d.slug}`}>
                        View profile <span className="sr-only">of {d.name}</span>
                      </Link>
                    </Button>
                  </div>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      </Section>
      <CtaBand />
    </>
  )
}

type Day = components['schemas']['DayAvailabilityOut']

/** The next few days with openings for this dentist, when the booking service answers. */
function AvailabilityPreview({ name, serviceCode }: { name: string; serviceCode: string }) {
  const { data, isPending } = useQuery({
    queryKey: ['public', 'availability-preview', name],
    retry: false,
    staleTime: 60_000,
    queryFn: async () => {
      const [list, offered] = await Promise.all([
        apiGet<components['schemas']['DentistOut'][]>('/public/dentists', { auth: false }),
        apiGet<components['schemas']['ServiceOut'][]>('/public/services', { auth: false }),
      ])
      const dentist = list.find((d) => d.full_name === name)
      const service = offered.find((s) => s.code === serviceCode)
      if (!dentist || !service) return []
      const today = toDateString(new Date())
      const days = await apiGet<Day[]>(
        `/public/availability?service_id=${service.id}&dentist_id=${dentist.id}&from=${today}&to=${addDays(today, 14)}`,
        { auth: false },
      )
      return days.filter((d) => d.slots.length > 0).slice(0, 3)
    },
  })
  return (
    <section aria-labelledby="next-times" className="rounded-xl border bg-card p-6">
      <h2 id="next-times" className="text-lg">
        Next available times
      </h2>
      {isPending && (
        <p className="mt-2 text-sm text-muted-foreground" role="status">
          Checking the diary
        </p>
      )}
      {!isPending && (!data || data.length === 0) && (
        <p className="mt-2 text-sm text-muted-foreground">
          Open times are shown when you book online. You can also call us and we will find one.
        </p>
      )}
      {data && data.length > 0 && (
        <ul className="mt-3 space-y-3">
          {data.map((day) => (
            <li key={day.date}>
              <p className="text-sm font-semibold">
                {formatDate(dateInZone(day.slots[0]?.start ?? '', ZONE), {
                  weekday: 'long',
                  month: 'long',
                  day: 'numeric',
                })}
              </p>
              <p className="mt-1 flex flex-wrap gap-2">
                {day.slots.slice(0, 5).map((slot) => (
                  <Badge key={slot.start} tone="brand">
                    {formatTime(slot.start, ZONE)}
                  </Badge>
                ))}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function DentistProfilePage() {
  const { slug = '' } = useParams()
  const dentist = dentistBySlug(slug)
  if (!dentist) return <NotFoundPage />
  const person = {
    '@context': 'https://schema.org',
    '@type': 'Physician',
    name: dentist.name,
    medicalSpecialty: dentist.specialty,
    description: dentist.bio,
    knowsLanguage: dentist.languages,
  }
  const sample =
    dentist.specialty === 'Orthodontics'
      ? 'SV12'
      : dentist.specialty === 'Pediatric dentistry'
        ? 'SV02'
        : dentist.specialty === 'Endodontics'
          ? 'SV06'
          : dentist.specialty === 'Oral surgery'
            ? 'SV09'
            : dentist.specialty === 'Cosmetic dentistry'
              ? 'SV11'
              : 'SV02'
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Our dentists', to: '/dentists' }, { label: dentist.name }]}
        title={dentist.name}
        intro={`${dentist.credentials}, ${dentist.specialty}`}
        seo={{
          description: `${dentist.name}, ${dentist.specialty} at Meridian Dental Care. ${dentist.bio}`,
          path: `/dentists/${dentist.slug}`,
          image: dentist.image,
          jsonLd: [person],
        }}
      />
      <Section>
        <div className="grid gap-10 lg:grid-cols-[320px_1fr]">
          <div>
            <Picture
              name={dentist.image}
              alt={`Portrait of ${dentist.name}`}
              sizes="(min-width: 1024px) 320px, 100vw"
              priority
              className="aspect-square rounded-xl"
            />
            <Button asChild size="lg" className="mt-5 w-full">
              <Link to={`/book?dentist=${dentist.slug}`}>Book with {dentist.short}</Link>
            </Button>
          </div>
          <div className="space-y-8">
            <section aria-labelledby="about">
              <h2 id="about" className="text-2xl">
                About
              </h2>
              <p className="mt-3 text-lg">{dentist.bio}</p>
            </section>
            <section aria-labelledby="focus">
              <h2 id="focus" className="text-2xl">
                Areas of focus
              </h2>
              <ul className="mt-3 list-disc space-y-1 pl-6">
                {dentist.focus.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </section>
            <section aria-labelledby="education">
              <h2 id="education" className="text-2xl">
                Education and training
              </h2>
              <ul className="mt-3 list-disc space-y-1 pl-6">
                {dentist.education.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </section>
            <section aria-labelledby="languages">
              <h2 id="languages" className="text-2xl">
                Languages
              </h2>
              <p className="mt-3">{dentist.languages.join(', ')}</p>
            </section>
            <AvailabilityPreview
              name={dentist.name}
              serviceCode={serviceByCode(sample)?.code ?? 'SV02'}
            />
          </div>
        </div>
      </Section>
      <CtaBand />
    </>
  )
}
