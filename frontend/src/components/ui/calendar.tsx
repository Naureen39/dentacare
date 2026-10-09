import { ChevronLeft, ChevronRight } from 'lucide-react'
import * as React from 'react'

import {
  addDays,
  addMonths,
  formatDate,
  monthGrid,
  startOfMonth,
  type DateString,
} from '@/lib/dates'
import { cn } from '@/lib/utils'

export interface CalendarProps {
  value?: DateString
  onSelect: (date: DateString) => void
  /** Earliest and latest selectable days, inclusive. */
  min?: DateString
  max?: DateString
  /** Return true for days that cannot be chosen, such as days with no openings. */
  isDisabled?: (date: DateString) => boolean
  /** Days to mark with a dot, such as days that have openings. */
  marked?: ReadonlySet<DateString>
  weekStartsOn?: 0 | 1
  /** Called with the first day of the month whenever another month is shown. */
  onMonthChange?: (firstDay: DateString) => void
  className?: string
}

const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

/**
 * A month grid for picking a day. It follows the ARIA date grid pattern: one day is in the tab
 * order, the arrow keys move by day and week, Home and End jump to the ends of the week, and
 * Page Up and Page Down change month.
 */
export function Calendar({
  value,
  onSelect,
  min,
  max,
  isDisabled,
  marked,
  weekStartsOn = 0,
  onMonthChange,
  className,
}: CalendarProps) {
  const today = React.useMemo(() => {
    const now = new Date()
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  }, [])
  const [focused, setFocused] = React.useState<DateString>(value ?? min ?? today)
  const [visible, setVisible] = React.useState<DateString>(startOfMonth(value ?? min ?? today))
  const gridRef = React.useRef<HTMLTableElement>(null)
  const notify = React.useRef(onMonthChange)
  React.useEffect(() => {
    notify.current = onMonthChange
  })
  React.useEffect(() => notify.current?.(visible), [visible])
  const shouldFocus = React.useRef(false)

  const disabled = React.useCallback(
    (date: DateString) =>
      (min !== undefined && date < min) ||
      (max !== undefined && date > max) ||
      (isDisabled?.(date) ?? false),
    [min, max, isDisabled],
  )

  React.useEffect(() => {
    if (!shouldFocus.current) return
    shouldFocus.current = false
    gridRef.current?.querySelector<HTMLButtonElement>(`[data-date="${focused}"]`)?.focus()
  }, [focused, visible])

  const move = (next: DateString) => {
    shouldFocus.current = true
    setFocused(next)
    setVisible(startOfMonth(next))
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    const keys: Record<string, DateString | undefined> = {
      ArrowLeft: addDays(focused, -1),
      ArrowRight: addDays(focused, 1),
      ArrowUp: addDays(focused, -7),
      ArrowDown: addDays(focused, 7),
      PageUp: addMonths(focused, event.shiftKey ? -12 : -1),
      PageDown: addMonths(focused, event.shiftKey ? 12 : 1),
    }
    const offset = (new Date(`${focused}T00:00:00`).getDay() - weekStartsOn + 7) % 7
    keys.Home = addDays(focused, -offset)
    keys.End = addDays(focused, 6 - offset)
    const next = keys[event.key]
    if (next) {
      event.preventDefault()
      move(next)
    }
  }

  const label = formatDate(visible, { month: 'long', year: 'numeric' })
  const weeks = monthGrid(visible, weekStartsOn)
  const heads = [...WEEKDAYS.slice(weekStartsOn), ...WEEKDAYS.slice(0, weekStartsOn)]
  // The focus target must exist in the visible month, otherwise the grid leaves the tab order.
  const tabTarget = focused.slice(0, 7) === visible.slice(0, 7) ? focused : visible

  return (
    <div className={cn('w-full max-w-sm rounded-xl border bg-card p-4 shadow-soft', className)}>
      <div className="mb-3 flex items-center justify-between">
        <button
          type="button"
          onClick={() => setVisible(addMonths(visible, -1))}
          className="inline-flex size-10 items-center justify-center rounded-full text-primary hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring"
          aria-label="Previous month"
        >
          <ChevronLeft className="size-5" aria-hidden="true" />
        </button>
        <h3 className="font-heading text-base font-bold" aria-live="polite">
          {label}
        </h3>
        <button
          type="button"
          onClick={() => setVisible(addMonths(visible, 1))}
          className="inline-flex size-10 items-center justify-center rounded-full text-primary hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring"
          aria-label="Next month"
        >
          <ChevronRight className="size-5" aria-hidden="true" />
        </button>
      </div>
      <table ref={gridRef} role="grid" aria-label={label} onKeyDown={onKeyDown} className="w-full">
        <thead>
          <tr>
            {heads.map((name) => (
              <th
                key={name}
                scope="col"
                abbr={name}
                className="pb-2 text-xs font-semibold text-muted-foreground"
              >
                {name.slice(0, 2)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((week, row) => (
            <tr key={row}>
              {week.map((date, col) => (
                <td
                  key={col}
                  role="gridcell"
                  className="p-0.5 text-center"
                  aria-selected={date === value}
                >
                  {date && (
                    <button
                      type="button"
                      data-date={date}
                      tabIndex={date === tabTarget ? 0 : -1}
                      disabled={disabled(date)}
                      aria-label={formatDate(date)}
                      aria-pressed={date === value}
                      aria-current={date === today ? 'date' : undefined}
                      onClick={() => {
                        setFocused(date)
                        onSelect(date)
                      }}
                      className={cn(
                        'relative inline-flex size-10 items-center justify-center rounded-full text-sm transition-colors hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring disabled:pointer-events-none disabled:text-muted-foreground/60 disabled:line-through',
                        date === today && 'border border-accent-strong',
                        date === value &&
                          'bg-primary font-semibold text-primary-foreground hover:bg-primary',
                      )}
                    >
                      {Number(date.slice(8))}
                      {marked?.has(date) && date !== value && (
                        <span
                          className="absolute bottom-1 size-1 rounded-full bg-accent-strong"
                          aria-hidden="true"
                        />
                      )}
                    </button>
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
