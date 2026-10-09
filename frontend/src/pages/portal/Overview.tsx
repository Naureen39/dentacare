import { CalendarPlus, Receipt, RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Card, Skeleton } from '@/components/ui/display'
import { useMyAppointments } from '@/lib/booking-api'
import { useInvoices } from '@/lib/portal-api'
import { clock, longDay, money } from '@/pages/portal/format'
import { StatusBadge } from '@/pages/portal/shared'

/** Whole months between an instant and now. */
function monthsSince(iso: string): number {
  const then = new Date(iso)
  const now = new Date()
  return (now.getFullYear() - then.getFullYear()) * 12 + (now.getMonth() - then.getMonth())
}

export function OverviewPage() {
  const upcoming = useMyAppointments('upcoming')
  const past = useMyAppointments('past')
  const invoices = useInvoices()

  const next = upcoming.data?.find((a) => a.status === 'booked' || a.status === 'confirmed')
  const visits = past.data?.filter((a) => a.status === 'completed') ?? []
  const owed = (invoices.data ?? []).reduce((sum, invoice) => sum + Number(invoice.balance), 0)
  const last = visits[0]
  const overdue = past.isSuccess && !next && (!last || monthsSince(last.start) >= 6)

  return (
    <div className="grid gap-6">
      <h1 className="text-3xl">Welcome back</h1>

      <Card variant="elevated" className="p-6">
        <h2 className="text-xl">Your next appointment</h2>
        {upcoming.isLoading ? (
          <Skeleton className="mt-4 h-16 w-full" />
        ) : next ? (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="font-heading text-lg font-bold text-primary">{next.service_name}</p>
              <p>
                {longDay(next.start)} at {clock(next.start)}
              </p>
              <p className="text-sm text-muted-foreground">with {next.dentist_name}</p>
            </div>
            <div className="flex items-center gap-3">
              <StatusBadge status={next.status} />
              <Button asChild variant="secondary">
                <Link to="/portal/appointments">Change or cancel</Link>
              </Button>
            </div>
          </div>
        ) : (
          <p className="mt-3 text-muted-foreground">You have nothing booked at the moment.</p>
        )}
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-6">
          <h2 className="flex items-center gap-2 text-lg">
            <CalendarPlus className="size-5 text-accent-strong" aria-hidden="true" /> Quick book
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Choose a service and a time in about two minutes.
          </p>
          <Button asChild className="mt-4">
            <Link to="/book">Book an appointment</Link>
          </Button>
        </Card>
        <Card className="p-6">
          <h2 className="flex items-center gap-2 text-lg">
            <Receipt className="size-5 text-accent-strong" aria-hidden="true" /> Balance
          </h2>
          {invoices.isLoading ? (
            <Skeleton className="mt-4 h-10 w-full" />
          ) : owed > 0 ? (
            <>
              <p className="mt-2 text-3xl font-bold text-primary">{money(owed)}</p>
              <p className="text-sm text-muted-foreground">outstanding on your invoices</p>
              <Button asChild className="mt-4" variant="secondary">
                <Link to="/portal/billing">View and pay</Link>
              </Button>
            </>
          ) : (
            <p className="mt-2 text-muted-foreground">You have nothing to pay. Thank you.</p>
          )}
        </Card>
      </div>

      {overdue && (
        <Card className="flex flex-wrap items-center justify-between gap-4 border-accent-strong bg-secondary p-6">
          <div className="flex items-start gap-3">
            <RefreshCw className="mt-1 size-5 text-accent-strong" aria-hidden="true" />
            <div>
              <h2 className="text-lg">Time for a check-up</h2>
              <p className="text-sm">
                {last
                  ? `Your last visit was ${monthsSince(last.start)} months ago. Most people come every six months.`
                  : 'We have no visit on record yet. A first check-up is the best place to start.'}
              </p>
            </div>
          </div>
          <Button asChild>
            <Link to="/book">Book a check-up</Link>
          </Button>
        </Card>
      )}

      <section aria-labelledby="recent">
        <h2 id="recent" className="text-xl">
          Recent visits
        </h2>
        {past.isLoading ? (
          <Skeleton className="mt-3 h-20 w-full" />
        ) : visits.length === 0 ? (
          <p className="mt-3 text-muted-foreground">Your completed visits will appear here.</p>
        ) : (
          <ul className="mt-3 grid gap-2">
            {visits.slice(0, 3).map((visit) => (
              <li
                key={visit.id}
                className="flex flex-wrap justify-between gap-2 rounded-lg border bg-card p-3"
              >
                <span className="font-semibold">{visit.service_name}</span>
                <span className="text-sm text-muted-foreground">
                  {longDay(visit.start)} with {visit.dentist_name}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
