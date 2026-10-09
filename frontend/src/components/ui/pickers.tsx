import * as PopoverPrimitive from '@radix-ui/react-popover'
import { CalendarDays } from 'lucide-react'
import * as React from 'react'

import { Calendar, type CalendarProps } from '@/components/ui/calendar'
import { controlClasses } from '@/components/ui/input'
import { formatDate, type DateString } from '@/lib/dates'
import { cn } from '@/lib/utils'

// --- DatePicker -----------------------------------------------------------------------------

export interface DatePickerProps extends Omit<CalendarProps, 'onSelect' | 'className'> {
  onChange: (date: DateString) => void
  placeholder?: string
  id?: string
  disabled?: boolean
  'aria-describedby'?: string
  'aria-invalid'?: boolean | 'true' | 'false'
}

/** A button that opens a calendar. The chosen day is written out in full on the button. */
export function DatePicker({
  value,
  onChange,
  placeholder = 'Choose a date',
  id,
  disabled,
  'aria-describedby': describedBy,
  'aria-invalid': invalid,
  ...calendar
}: DatePickerProps) {
  const [open, setOpen] = React.useState(false)
  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Trigger asChild>
        <button
          type="button"
          id={id}
          disabled={disabled}
          aria-describedby={describedBy}
          aria-invalid={invalid}
          className={cn(controlClasses, 'flex h-11 items-center justify-between gap-2 text-left')}
        >
          <span className={cn(!value && 'text-muted-foreground')}>
            {value
              ? formatDate(value, { month: 'long', day: 'numeric', year: 'numeric' })
              : placeholder}
          </span>
          <CalendarDays className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        </button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          sideOffset={6}
          align="start"
          aria-label="Choose a date"
          className="z-50 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95"
        >
          <Calendar
            {...calendar}
            value={value}
            onSelect={(date) => {
              onChange(date)
              setOpen(false)
            }}
          />
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  )
}

// --- SlotPicker -----------------------------------------------------------------------------

export interface Slot {
  /** Unique within the picker; sent back when the visitor chooses. */
  id: string
  /** The time as it should be read, such as "9:30 AM". */
  label: string
  /** Shown under the time when several dentists offer it. */
  detail?: string
}

export interface SlotDay {
  date: DateString
  slots: Slot[]
}

export interface SlotPickerProps {
  days: SlotDay[]
  value?: string
  onChange: (slotId: string, date: DateString) => void
  /** The day shown first. Defaults to the first day with openings. */
  initialDate?: DateString
  className?: string
}

/**
 * Pick a day on the calendar (days without openings are disabled), then pick one of its times.
 * Times are a radio group, so a keyboard user moves between them with the arrow keys.
 */
export function SlotPicker({ days, value, onChange, initialDate, className }: SlotPickerProps) {
  const open = React.useMemo(
    () => new Map(days.filter((d) => d.slots.length > 0).map((d) => [d.date, d.slots])),
    [days],
  )
  const first = [...open.keys()].sort()[0]
  const [date, setDate] = React.useState<DateString | undefined>(initialDate ?? first)
  const slots = date ? (open.get(date) ?? []) : []
  const marked = React.useMemo(() => new Set(open.keys()), [open])
  const sorted = [...open.keys()].sort()

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const keys = ['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp']
    if (!keys.includes(event.key)) return
    event.preventDefault()
    const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]')]
    const index = buttons.findIndex((b) => b === document.activeElement)
    const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : -1
    buttons[(index + step + buttons.length) % buttons.length]?.focus()
  }

  return (
    <div className={cn('grid gap-6 md:grid-cols-[auto_1fr]', className)}>
      <Calendar
        value={date}
        marked={marked}
        isDisabled={(d) => !open.has(d)}
        min={sorted[0]}
        max={sorted[sorted.length - 1]}
        onSelect={setDate}
      />
      <div>
        <h3 className="font-heading text-base font-bold">
          {date ? `Times on ${formatDate(date)}` : 'No times available'}
        </h3>
        {date && slots.length === 0 && (
          <p className="mt-2 text-sm text-muted-foreground">There are no openings on this day.</p>
        )}
        <div
          role="radiogroup"
          aria-label={date ? `Available times on ${formatDate(date)}` : 'Available times'}
          onKeyDown={onKeyDown}
          className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4"
        >
          {slots.map((slot, index) => {
            const selected = slot.id === value
            const stop = selected || (!slots.some((s) => s.id === value) && index === 0)
            return (
              <button
                key={slot.id}
                type="button"
                role="radio"
                aria-checked={selected}
                tabIndex={stop ? 0 : -1}
                onClick={() => date && onChange(slot.id, date)}
                className={cn(
                  'flex min-h-11 flex-col items-center justify-center rounded-lg border px-3 py-1.5 text-sm font-semibold transition-colors hover:border-accent-strong hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring',
                  selected && 'border-primary bg-primary text-primary-foreground hover:bg-primary',
                )}
              >
                {slot.label}
                {slot.detail && (
                  <span
                    className={cn(
                      'text-xs font-normal',
                      selected ? 'text-primary-foreground/80' : 'text-muted-foreground',
                    )}
                  >
                    {slot.detail}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
