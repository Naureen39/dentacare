import * as React from 'react'

import { clinicToday } from '@/lib/booking-time'
import { Calendar } from '@/components/ui/calendar'
import { Skeleton } from '@/components/ui/display'
import { clinic } from '@/content/site'
import type { TimeChoice } from '@/lib/booking-api'
import { formatDate, startOfMonth, type DateString } from '@/lib/dates'
import { cn } from '@/lib/utils'

const PERIODS: { key: TimeChoice['period']; label: string }[] = [
  { key: 'morning', label: 'Morning' },
  { key: 'afternoon', label: 'Afternoon' },
  { key: 'evening', label: 'Evening' },
]

/**
 * A month calendar with dots on days that have openings, then the times of the chosen day in
 * groups for morning, afternoon and evening. The parent loads the openings for the month shown.
 */
export function TimePicker({
  choices,
  loading,
  value,
  onSelect,
  onMonthChange,
  showDentist,
}: {
  choices: TimeChoice[]
  loading: boolean
  value: string | undefined
  onSelect: (choice: TimeChoice) => void
  onMonthChange: (firstDay: DateString) => void
  /** Show the dentist under each time, for "first available". */
  showDentist: boolean
}) {
  const today = React.useMemo(() => clinicToday(), [])
  const byDay = React.useMemo(() => {
    const map = new Map<DateString, TimeChoice[]>()
    for (const choice of choices) map.set(choice.date, [...(map.get(choice.date) ?? []), choice])
    return map
  }, [choices])
  const [picked, setPicked] = React.useState<DateString | undefined>()
  // Until a day is picked, show the earliest day with openings (the chosen time's day if any).
  const chosen = choices.find((c) => c.id === value)
  const date = picked ?? chosen?.date ?? [...byDay.keys()].sort()[0]
  const times = date ? (byDay.get(date) ?? []) : []
  const marked = React.useMemo(() => new Set(byDay.keys()), [byDay])
  const [month, setMonth] = React.useState<DateString>(startOfMonth(today))

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp'].includes(event.key)) return
    event.preventDefault()
    const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]')]
    const index = buttons.findIndex((b) => b === document.activeElement)
    const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : -1
    buttons[(index + step + buttons.length) % buttons.length]?.focus()
  }

  const stop = value && times.some((t) => t.id === value) ? value : times[0]?.id
  return (
    <div className="grid gap-6 md:grid-cols-[auto_1fr]">
      <Calendar
        value={date}
        min={today}
        marked={marked}
        isDisabled={(d) => !byDay.has(d)}
        onSelect={setPicked}
        onMonthChange={(first) => {
          setMonth(first)
          onMonthChange(first)
        }}
      />
      <div aria-busy={loading}>
        <h3 className="font-heading text-base font-bold">
          {date ? `Times on ${formatDate(date)}` : 'Choose a day'}
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Times are in the clinic&apos;s time zone ({clinic.address.city}).
        </p>
        {loading && (
          <div className="mt-4 grid grid-cols-3 gap-2" role="status" aria-label="Loading times">
            {[1, 2, 3, 4, 5, 6].map((n) => (
              <Skeleton key={n} className="h-11" />
            ))}
          </div>
        )}
        {!loading && byDay.size === 0 && (
          <p className="mt-4 rounded-md bg-secondary p-3 text-sm" role="status">
            There are no openings in {formatDate(month, { month: 'long', year: 'numeric' })}. Use
            the arrows above the calendar to look at another month.
          </p>
        )}
        <div
          onKeyDown={onKeyDown}
          role="radiogroup"
          aria-label={date ? `Available times on ${formatDate(date)}` : 'Available times'}
          className="mt-4 grid gap-4"
        >
          {PERIODS.map(({ key, label }) => {
            const group = times.filter((t) => t.period === key)
            if (group.length === 0) return null
            return (
              <div key={key} role="group" aria-label={label}>
                <h4 className="mb-2 text-sm font-semibold text-muted-foreground">{label}</h4>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
                  {group.map((choice) => {
                    const selected = choice.id === value
                    return (
                      <button
                        key={choice.id}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        tabIndex={choice.id === stop ? 0 : -1}
                        onClick={() => onSelect(choice)}
                        className={cn(
                          'flex min-h-11 flex-col items-center justify-center rounded-lg border px-3 py-1.5 text-sm font-semibold transition-colors hover:border-accent-strong hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring',
                          selected &&
                            'border-primary bg-primary text-primary-foreground hover:bg-primary',
                        )}
                      >
                        {choice.label}
                        {showDentist && (
                          <span
                            className={cn(
                              'text-xs font-normal',
                              selected ? 'text-primary-foreground/80' : 'text-muted-foreground',
                            )}
                          >
                            {choice.dentistName}
                          </span>
                        )}
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
