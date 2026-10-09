import { clinic } from '@/content/site'
import { addDays, dateInZone, daysInMonth, startOfMonth, type DateString } from '@/lib/dates'

/** The first and last day to ask the server about for a month: never in the past. */
export function monthRange(
  month: DateString,
  today: DateString,
): { from: DateString; to: DateString } {
  const first = startOfMonth(month)
  const last = addDays(first, daysInMonth(first) - 1)
  return { from: first < today ? today : first, to: last < today ? today : last }
}

export const clinicToday = (): DateString => dateInZone(new Date().toISOString(), clinic.timeZone)
