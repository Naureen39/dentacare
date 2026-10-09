import * as React from 'react'

import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/display'
import { controlClasses } from '@/components/ui/input'
import { StatCard } from '@/components/ui/metrics'
import { useToast } from '@/components/ui/toast'
import {
  useChangeStatus,
  usePerformance,
  useSchedule,
  type Appointment,
  type Status,
} from '@/console/api'
import { AppointmentDrawer } from '@/console/AppointmentDrawer'
import { NewAppointmentDialog } from '@/console/NewAppointment'
import { clinicToday } from '@/console/time'
import { useAuth } from '@/lib/auth'
import { addDays, formatDate } from '@/lib/dates'
import { clock } from '@/pages/portal/format'
import { money } from '@/pages/portal/format'
import { StatusBadge } from '@/pages/portal/shared'

function Section({
  title,
  empty,
  rows,
  action,
  onOpen,
}: {
  title: string
  empty: string
  rows: Appointment[]
  action?: (a: Appointment) => React.ReactNode
  onOpen: (id: string) => void
}) {
  const id = React.useId()
  return (
    <section aria-labelledby={id}>
      <h2 id={id} className="text-xl">
        {title} <span className="text-base text-muted-foreground">({rows.length})</span>
      </h2>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="mt-3 grid gap-2">
          {rows.map((a) => (
            <li
              key={a.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card p-3"
            >
              <button
                type="button"
                onClick={() => onOpen(a.id)}
                className="text-left focus-visible:outline-2 focus-visible:outline-ring"
              >
                <span className="block font-semibold">
                  {clock(a.start)} {a.patient_name}
                </span>
                <span className="block text-sm text-muted-foreground">
                  {a.service_name} with {a.dentist_name}
                </span>
              </button>
              <div className="flex items-center gap-2">
                <StatusBadge status={a.status} />
                {action?.(a)}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function DentistNumbers() {
  const [days, setDays] = React.useState(30)
  const performance = usePerformance(days, true)
  const data = performance.data
  return (
    <section aria-label="My numbers" className="grid gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-xl">My numbers</h2>
        <select
          aria-label="Period"
          className={`${controlClasses} h-10 w-44`}
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        >
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
          <option value={365}>Last 12 months</option>
        </select>
      </div>
      {performance.isLoading || !data ? (
        <Skeleton className="h-24 w-full" />
      ) : (
        <div className="grid gap-4 sm:grid-cols-3">
          <StatCard label="Visits completed" value={data.visits} />
          <StatCard label="Revenue produced" value={Number(data.revenue)} format={money} />
          <StatCard
            label="No show rate"
            value={data.no_show_rate * 100}
            format={(v) => `${v.toFixed(1)}%`}
            hint={`${data.no_shows} missed`}
            lowerIsBetter
          />
        </div>
      )}
    </section>
  )
}

export function TodayPage() {
  const { user } = useAuth()
  const { toast } = useToast()
  const dentist = user?.role === 'dentist'
  const today = clinicToday()
  const todayQuery = useSchedule('day', today)
  const tomorrowQuery = useSchedule('day', addDays(today, 1))
  const change = useChangeStatus()
  const [open, setOpen] = React.useState<string | null>(null)
  const [creating, setCreating] = React.useState(false)

  const todays = (todayQuery.data?.appointments ?? []).filter((a) => a.status !== 'cancelled')
  const soon = [...todays, ...(tomorrowQuery.data?.appointments ?? [])]
  const arrivals = todays.filter((a) => a.status === 'booked' || a.status === 'confirmed')
  const waiting = todays.filter((a) => a.status === 'checked_in')
  const unconfirmed = soon.filter((a) => a.status === 'booked' && new Date(a.start) > new Date())

  const set = (a: Appointment, status: Status, done: string) =>
    change.mutate(
      { id: a.id, status },
      {
        onSuccess: () => toast({ tone: 'success', title: done }),
        onError: () => toast({ tone: 'error', title: 'That did not work. Please try again.' }),
      },
    )

  return (
    <div className="grid gap-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl">{dentist ? 'My day' : 'Today'}</h1>
          <p className="text-muted-foreground">{formatDate(today)}</p>
        </div>
        {!dentist && <Button onClick={() => setCreating(true)}>New appointment</Button>}
      </div>

      {todayQuery.isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Visits today" value={todays.length} />
          <StatCard label="Still to arrive" value={arrivals.length} />
          <StatCard label="Waiting now" value={waiting.length} />
          <StatCard label="Need confirming" value={unconfirmed.length} />
        </div>
      )}

      {dentist && <DentistNumbers />}

      <Section
        title="Arrivals"
        empty="Nobody else is expected today."
        rows={arrivals}
        onOpen={setOpen}
        action={(a) =>
          dentist ? null : a.status === 'booked' ? (
            <Button size="sm" variant="secondary" onClick={() => set(a, 'confirmed', 'Confirmed.')}>
              Confirm
            </Button>
          ) : (
            <Button size="sm" onClick={() => set(a, 'checked_in', 'Checked in.')}>
              Check in <span className="sr-only">{a.patient_name}</span>
            </Button>
          )
        }
      />
      <Section
        title="Check-in queue"
        empty="Nobody is waiting."
        rows={waiting}
        onOpen={setOpen}
        action={(a) => (
          <Button size="sm" variant="secondary" onClick={() => setOpen(a.id)}>
            Open <span className="sr-only">{a.patient_name}</span>
          </Button>
        )}
      />
      {!dentist && (
        <Section
          title="Needs a confirmation call"
          empty="Every visit in the next two days is confirmed."
          rows={unconfirmed}
          onOpen={setOpen}
          action={(a) => (
            <Button size="sm" variant="secondary" onClick={() => setOpen(a.id)}>
              Call details <span className="sr-only">{a.patient_name}</span>
            </Button>
          )}
        />
      )}
      <AppointmentDrawer id={open} onClose={() => setOpen(null)} />
      <NewAppointmentDialog open={creating} onOpenChange={setCreating} />
    </div>
  )
}
