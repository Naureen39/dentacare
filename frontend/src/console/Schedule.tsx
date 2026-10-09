import { ChevronLeft, ChevronRight, Plus } from 'lucide-react'
import * as React from 'react'

import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/display'
import { Input, controlClasses } from '@/components/ui/input'
import { useToast } from '@/components/ui/toast'
import {
  useAllDentists,
  useMoveAppointment,
  useSchedule,
  type Appointment,
  type Status,
} from '@/console/api'
import { AppointmentDrawer } from '@/console/AppointmentDrawer'
import { NewAppointmentDialog, type NewAppointmentDefaults } from '@/console/NewAppointment'
import { clinicToday, hhmm, instantAt, minutesOfDay, weekDates } from '@/console/time'
import { clinic } from '@/content/site'
import { ApiError } from '@/lib/api-client'
import { useAuth } from '@/lib/auth'
import { addDays, dateInZone, formatDate, type DateString } from '@/lib/dates'
import { cn } from '@/lib/utils'
import { clock } from '@/pages/portal/format'

const FIRST_HOUR = 7
const LAST_HOUR = 19
const PX_PER_MINUTE = 1.3
const SNAP = 15
const HEIGHT = (LAST_HOUR - FIRST_HOUR) * 60 * PX_PER_MINUTE

/** Colour by status: a soft fill, a strong edge and dark text, so it reads without colour too. */
const look: Record<Status, string> = {
  booked: 'border-l-primary bg-secondary',
  confirmed: 'border-l-success-strong bg-success-soft',
  checked_in: 'border-l-warning-strong bg-warning-soft',
  completed: 'border-l-muted-foreground bg-muted',
  cancelled: 'border-l-muted-foreground bg-card opacity-60 line-through',
  no_show: 'border-l-destructive bg-destructive-soft',
}
const names: Record<Status, string> = {
  booked: 'Booked',
  confirmed: 'Confirmed',
  checked_in: 'Checked in',
  completed: 'Completed',
  cancelled: 'Cancelled',
  no_show: 'No show',
}

interface Column {
  id: string
  title: string
  date: DateString
  dentistId: string | undefined
}

interface Drag {
  id: string
  /** Pointer position inside the block when it was picked up. */
  grabY: number
  originX: number
  originY: number
  dx: number
  dy: number
  moved: boolean
}

const topOf = (minutes: number) => (minutes - FIRST_HOUR * 60) * PX_PER_MINUTE

export function SchedulePage() {
  const { user } = useAuth()
  const { toast } = useToast()
  const dentist = user?.role === 'dentist'
  const frontDesk = !dentist
  const [view, setView] = React.useState<'day' | 'week'>('day')
  const [date, setDate] = React.useState<DateString>(clinicToday())
  const [weekDentist, setWeekDentist] = React.useState<string>('')
  const [showCancelled, setShowCancelled] = React.useState(false)
  const [open, setOpen] = React.useState<string | null>(null)
  const [creating, setCreating] = React.useState<NewAppointmentDefaults | null>(null)
  const dentists = useAllDentists()
  const move = useMoveAppointment()

  const chosenDentist = weekDentist || dentists.data?.[0]?.id || ''
  const query = useSchedule(
    view,
    date,
    view === 'week' && frontDesk ? chosenDentist || undefined : undefined,
  )

  const columns = React.useMemo<Column[]>(() => {
    if (view === 'week')
      return weekDates(date).map((d) => ({
        id: d,
        title: formatDate(d, { weekday: 'short', month: 'short', day: 'numeric' }),
        date: d,
        dentistId: frontDesk ? chosenDentist : undefined,
      }))
    if (dentist) return [{ id: 'me', title: 'My schedule', date, dentistId: undefined }]
    return (dentists.data ?? []).map((d) => ({
      id: d.id,
      title: d.full_name,
      date,
      dentistId: d.id,
    }))
  }, [view, date, dentist, dentists.data, frontDesk, chosenDentist])

  const columnOf = (a: Appointment): string =>
    view === 'week' ? dateInZone(a.start, clinic.timeZone) : dentist ? 'me' : a.dentist_id

  const visible = (query.data?.appointments ?? []).filter(
    (a) => showCancelled || a.status !== 'cancelled',
  )

  // --- dragging a visit to another time or dentist --------------------------------------------------
  const body = React.useRef<HTMLDivElement>(null)
  const [drag, setDrag] = React.useState<Drag | null>(null)
  const movable = (a: Appointment) =>
    frontDesk && (a.status === 'booked' || a.status === 'confirmed')

  const dropTarget = (clientX: number, clientY: number, a: Appointment, grabY: number) => {
    const grid = body.current
    if (!grid) return null
    const cells = [...grid.querySelectorAll<HTMLElement>('[data-column]')]
    const cell = cells.find((c) => {
      const r = c.getBoundingClientRect()
      return clientX >= r.left && clientX < r.right
    })
    if (!cell) return null
    const column = columns.find((c) => c.id === cell.dataset.column)
    if (!column) return null
    const rect = cell.getBoundingClientRect()
    const raw = (clientY - grabY - rect.top) / PX_PER_MINUTE + FIRST_HOUR * 60
    const start = Math.round(raw / SNAP) * SNAP
    const length = minutesOfDay(a.end) - minutesOfDay(a.start)
    if (start < FIRST_HOUR * 60 || start + length > LAST_HOUR * 60) return null
    return { column, start, length }
  }

  const finishDrag = async (a: Appointment, event: React.PointerEvent) => {
    const target = dropTarget(event.clientX, event.clientY, a, drag?.grabY ?? 0)
    if (!target) return
    const day = target.column.date
    const sameSpot =
      day === dateInZone(a.start, clinic.timeZone) &&
      target.start === minutesOfDay(a.start) &&
      (target.column.dentistId ?? a.dentist_id) === a.dentist_id
    if (sameSpot) return
    // A quick check here saves a round trip. The server still has the last word.
    const clash = visible.some(
      (o) =>
        o.id !== a.id &&
        o.status !== 'cancelled' &&
        columnOf(o) === target.column.id &&
        minutesOfDay(o.start) < target.start + target.length &&
        minutesOfDay(o.end) > target.start,
    )
    if (clash) {
      toast({ tone: 'error', title: 'That time is already taken.' })
      return
    }
    try {
      await move.mutateAsync({
        id: a.id,
        start: instantAt(day, target.start),
        dentistId: target.column.dentistId,
      })
      toast({ tone: 'success', title: `Moved to ${hhmm(target.start)}.` })
    } catch (error) {
      toast({
        tone: 'error',
        title: error instanceof ApiError && error.status < 500 ? error.message : 'The move failed.',
      })
    }
  }

  const step = view === 'week' ? 7 : 1
  const label =
    view === 'week'
      ? `${formatDate(weekDates(date)[0] ?? date, { month: 'short', day: 'numeric' })} to ${formatDate(weekDates(date)[6] ?? date, { month: 'short', day: 'numeric', year: 'numeric' })}`
      : formatDate(date)
  const hours = Array.from({ length: LAST_HOUR - FIRST_HOUR }, (_, i) => FIRST_HOUR + i)

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl">{dentist ? 'My schedule' : 'Schedule'}</h1>
        {frontDesk && (
          <Button onClick={() => setCreating({ date })}>
            <Plus aria-hidden="true" /> New appointment
          </Button>
        )}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <div role="group" aria-label="View" className="inline-flex rounded-full bg-muted p-1">
          {(['day', 'week'] as const).map((v) => (
            <Button
              key={v}
              size="sm"
              variant={view === v ? 'primary' : 'ghost'}
              aria-pressed={view === v}
              onClick={() => setView(v)}
            >
              {v === 'day' ? 'Day' : 'Week'}
            </Button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            aria-label={view === 'week' ? 'Previous week' : 'Previous day'}
            onClick={() => setDate(addDays(date, -step))}
          >
            <ChevronLeft aria-hidden="true" />
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setDate(clinicToday())}>
            Today
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={view === 'week' ? 'Next week' : 'Next day'}
            onClick={() => setDate(addDays(date, step))}
          >
            <ChevronRight aria-hidden="true" />
          </Button>
        </div>
        <Input
          type="date"
          aria-label="Go to date"
          value={date}
          onChange={(e) => e.target.value && setDate(e.target.value)}
          className="w-44"
        />
        {view === 'week' && frontDesk && (
          <select
            aria-label="Dentist"
            className={cn(controlClasses, 'h-11 w-56')}
            value={chosenDentist}
            onChange={(e) => setWeekDentist(e.target.value)}
          >
            {dentists.data?.map((d) => (
              <option key={d.id} value={d.id}>
                {d.full_name}
              </option>
            ))}
          </select>
        )}
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={showCancelled}
            onChange={(e) => setShowCancelled(e.target.checked)}
          />
          Show cancelled
        </label>
      </div>
      <p className="mt-3 font-semibold" aria-live="polite">
        {label}
      </p>
      <ul className="mt-2 flex flex-wrap gap-3 text-xs" aria-label="Status colours">
        {(Object.keys(names) as Status[]).map((s) => (
          <li key={s} className="flex items-center gap-1.5">
            <span className={cn('size-3 rounded-sm border-l-4', look[s])} aria-hidden="true" />
            {names[s]}
          </li>
        ))}
      </ul>

      {query.isLoading || (view === 'day' && frontDesk && dentists.isLoading) ? (
        <Skeleton className="mt-4 h-96 w-full" />
      ) : query.isError ? (
        <p role="alert" className="mt-4 rounded-md bg-destructive-soft p-3 text-destructive">
          We could not load the schedule. Please try again.
        </p>
      ) : (
        <div
          className="mt-4 overflow-x-auto rounded-xl border bg-card"
          role="group"
          aria-label="Schedule grid"
        >
          <div style={{ minWidth: 64 + columns.length * 150 }}>
            <div className="flex border-b bg-muted/50 text-sm font-semibold">
              <div className="w-16 shrink-0" />
              {columns.map((c) => (
                <div key={c.id} className="flex-1 border-l px-2 py-2 text-center">
                  {c.title}
                </div>
              ))}
            </div>
            <div className="flex" ref={body}>
              <div className="relative w-16 shrink-0" style={{ height: HEIGHT }} aria-hidden="true">
                {hours.map((h) => (
                  <span
                    key={h}
                    className="absolute right-2 -translate-y-2 text-xs text-muted-foreground"
                    style={{ top: topOf(h * 60) }}
                  >
                    {formatHour(h)}
                  </span>
                ))}
              </div>
              {columns.map((c) => (
                <div
                  key={c.id}
                  data-column={c.id}
                  className="relative flex-1 border-l"
                  style={{ height: HEIGHT }}
                  onDoubleClick={(event) => {
                    if (!frontDesk) return
                    const rect = event.currentTarget.getBoundingClientRect()
                    const minutes =
                      Math.floor(
                        ((event.clientY - rect.top) / PX_PER_MINUTE + FIRST_HOUR * 60) / SNAP,
                      ) * SNAP
                    setCreating({ date: c.date, time: hhmm(minutes), dentistId: c.dentistId })
                  }}
                >
                  {hours.map((h) => (
                    <div
                      key={h}
                      className="absolute inset-x-0 border-t"
                      style={{ top: topOf(h * 60) }}
                      aria-hidden="true"
                    />
                  ))}
                  {visible
                    .filter((a) => columnOf(a) === c.id)
                    .map((a) => {
                      const start = minutesOfDay(a.start)
                      const length = Math.max(minutesOfDay(a.end) - start, 15)
                      const dragging = drag?.id === a.id && drag.moved
                      return (
                        <button
                          key={a.id}
                          type="button"
                          aria-label={`${clock(a.start)}, ${a.patient_name}, ${a.service_name}, ${names[a.status]}`}
                          onClick={() => !drag?.moved && setOpen(a.id)}
                          onPointerDown={(event) => {
                            if (!movable(a) || event.button !== 0) return
                            const rect = event.currentTarget.getBoundingClientRect()
                            event.currentTarget.setPointerCapture(event.pointerId)
                            setDrag({
                              id: a.id,
                              grabY: event.clientY - rect.top,
                              originX: event.clientX,
                              originY: event.clientY,
                              dx: 0,
                              dy: 0,
                              moved: false,
                            })
                          }}
                          onPointerMove={(event) => {
                            if (drag?.id !== a.id) return
                            const dx = event.clientX - drag.originX
                            const dy = event.clientY - drag.originY
                            setDrag({
                              ...drag,
                              dx,
                              dy,
                              moved: drag.moved || Math.hypot(dx, dy) > 5,
                            })
                          }}
                          onPointerUp={(event) => {
                            const wasDragging = drag?.id === a.id && drag.moved
                            if (wasDragging) void finishDrag(a, event)
                            // Let the click that follows a drag pass without opening the drawer.
                            setTimeout(() => setDrag(null), 0)
                          }}
                          className={cn(
                            'absolute inset-x-1 overflow-hidden rounded-md border border-l-4 px-2 py-1 text-left text-xs shadow-xs focus-visible:outline-2 focus-visible:outline-ring',
                            look[a.status],
                            movable(a) && 'cursor-grab touch-none',
                            dragging && 'z-20 cursor-grabbing opacity-70 ring-2 ring-primary',
                          )}
                          style={{
                            top: topOf(start),
                            height: length * PX_PER_MINUTE - 2,
                            transform: dragging
                              ? `translate(${drag.dx}px, ${drag.dy}px)`
                              : undefined,
                          }}
                        >
                          <span className="block font-semibold">
                            {clock(a.start)} {a.patient_name}
                          </span>
                          <span className="block truncate text-muted-foreground">
                            {a.service_name}
                          </span>
                        </button>
                      )
                    })}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
      {frontDesk && (
        <p className="mt-3 text-sm text-muted-foreground">
          Drag a booked or confirmed visit to move it, or open it and choose &ldquo;Move to another
          time&rdquo;. Double click an empty space to book.
        </p>
      )}
      <AppointmentDrawer id={open} onClose={() => setOpen(null)} />
      <NewAppointmentDialog
        open={creating !== null}
        onOpenChange={(value) => !value && setCreating(null)}
        defaults={creating ?? undefined}
      />
    </div>
  )
}

function formatHour(h: number): string {
  const suffix = h >= 12 ? 'PM' : 'AM'
  return `${h % 12 === 0 ? 12 : h % 12} ${suffix}`
}
