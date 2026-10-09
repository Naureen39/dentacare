/**
 * Calendar dates are handled as plain `YYYY-MM-DD` strings in the clinic's own calendar, never as
 * instants. That keeps "Tuesday the 14th" the same for every visitor whatever their time zone.
 */
export type DateString = string

const pad = (n: number) => String(n).padStart(2, '0')

export function toDateString(date: Date): DateString {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function parseDate(value: DateString): Date {
  const [year = 1970, month = 1, day = 1] = value.split('-').map(Number)
  return new Date(year, month - 1, day)
}

export function addDays(value: DateString, days: number): DateString {
  const date = parseDate(value)
  date.setDate(date.getDate() + days)
  return toDateString(date)
}

export function addMonths(value: DateString, months: number): DateString {
  const date = parseDate(value)
  const day = date.getDate()
  date.setDate(1)
  date.setMonth(date.getMonth() + months)
  const last = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate()
  date.setDate(Math.min(day, last))
  return toDateString(date)
}

export const startOfMonth = (value: DateString): DateString => `${value.slice(0, 7)}-01`

export function daysInMonth(value: DateString): number {
  const date = parseDate(value)
  return new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate()
}

/** 0 for Sunday through 6 for Saturday. */
export const weekday = (value: DateString): number => parseDate(value).getDay()

export function formatDate(
  value: DateString,
  options: Intl.DateTimeFormatOptions = {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  },
  locale = 'en-US',
): string {
  return new Intl.DateTimeFormat(locale, options).format(parseDate(value))
}

/** A time of day in the clinic's time zone, such as "9:30 AM", from an ISO instant. */
export function formatTime(iso: string, timeZone: string, locale = 'en-US'): string {
  return new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit', timeZone }).format(
    new Date(iso),
  )
}

/** The calendar date of an instant in the clinic's time zone. */
export function dateInZone(iso: string, timeZone: string): DateString {
  const parts = new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    timeZone,
  }).format(new Date(iso))
  return parts
}

/** The weeks of a month as rows of seven cells; days outside the month are null. */
export function monthGrid(month: DateString, weekStartsOn: 0 | 1 = 0): (DateString | null)[][] {
  const first = startOfMonth(month)
  const lead = (weekday(first) - weekStartsOn + 7) % 7
  const total = daysInMonth(first)
  const cells: (DateString | null)[] = [
    ...Array<null>(lead).fill(null),
    ...Array.from({ length: total }, (_, i) => addDays(first, i)),
  ]
  while (cells.length % 7 !== 0) cells.push(null)
  const weeks: (DateString | null)[][] = []
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7))
  return weeks
}
