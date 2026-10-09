import { useInView } from 'motion/react'
import { Car, Clock, MapPin } from 'lucide-react'
import * as React from 'react'

import { Section } from '@/components/site/parts'
import { Button } from '@/components/ui/button'
import { clinic, directionsUrl, fullAddress, hours } from '@/content/site'

const ClinicMap = React.lazy(() => import('@/components/site/ClinicMap'))

export function HoursTable() {
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">Opening hours</caption>
      <tbody>
        {hours.map((row) => (
          <tr key={row.days} className="border-b last:border-0">
            <th scope="row" className="py-2 pr-4 text-left font-semibold">
              {row.days}
            </th>
            <td className="py-2">
              {row.opens ? `${row.opens} to ${row.closes}` : 'Closed'}
              {row.note && <span className="block text-muted-foreground">{row.note}</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function LocationSection({ heading = 'Visit us' }: { heading?: string }) {
  const ref = React.useRef<HTMLDivElement>(null)
  const near = useInView(ref, { once: true, margin: '300px' })
  return (
    <Section
      id="location"
      title={heading}
      intro="Find us on Harbor View Drive, with parking on site."
    >
      <div className="grid gap-8 md:grid-cols-2">
        <div className="flex flex-col gap-6">
          <p className="flex gap-3">
            <MapPin className="mt-1 size-5 shrink-0 text-accent-strong" aria-hidden="true" />
            {fullAddress}
          </p>
          <div className="flex gap-3">
            <Clock className="mt-1 size-5 shrink-0 text-accent-strong" aria-hidden="true" />
            <div className="w-full max-w-sm">
              <HoursTable />
            </div>
          </div>
          <p className="flex gap-3">
            <Car className="mt-1 size-5 shrink-0 text-accent-strong" aria-hidden="true" />
            Free parking in the lot behind the building. Two accessible spaces are next to the rear
            entrance.
          </p>
          <div className="flex flex-wrap gap-3">
            <Button asChild>
              <a href={directionsUrl} target="_blank" rel="noopener noreferrer">
                Get directions <span className="sr-only">(opens in a new tab)</span>
              </a>
            </Button>
            <Button asChild variant="secondary">
              <a href={clinic.phoneHref}>Call {clinic.phone}</a>
            </Button>
          </div>
        </div>
        <div ref={ref} className="min-h-80 overflow-hidden rounded-xl border bg-muted">
          {near ? (
            <React.Suspense
              fallback={
                <div
                  className="grid h-80 place-items-center text-sm text-muted-foreground"
                  role="status"
                >
                  Loading map
                </div>
              }
            >
              <ClinicMap />
            </React.Suspense>
          ) : (
            <div className="grid h-80 place-items-center text-sm text-muted-foreground">Map</div>
          )}
        </div>
      </div>
    </Section>
  )
}
