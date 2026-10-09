import { clinic } from '@/content/site'
import { addDays, dateInZone, toDateString, type DateString } from '@/lib/dates'

/** Today in the clinic's calendar. */
export const clinicToday = (): DateString => dateInZone(new Date().toISOString(), clinic.timeZone)

/** Minutes after midnight, clinic time, of an instant. */
export function minutesOfDay(iso: string): number {
  const parts = new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: clinic.timeZone,
  }).formatToParts(new Date(iso))
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0)
  return (get('hour') % 24) * 60 + get('minute')
}

/** The offset of the clinic's zone from UTC at an instant, in minutes (negative in New York). */
function offsetMinutes(at: number): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: clinic.timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).formatToParts(new Date(at))
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value)
  const asUtc = Date.UTC(get('year'), get('month') - 1, get('day'), get('hour'), get('minute'))
  return Math.round((asUtc - at) / 60_000)
}

/** The instant at which the clinic's clock shows `minutes` after midnight on `date`. */
export function instantAt(date: DateString, minutes: number): string {
  const [y = 1970, m = 1, d = 1] = date.split('-').map(Number)
  const wall = Date.UTC(y, m - 1, d, 0, minutes)
  let instant = wall - offsetMinutes(wall) * 60_000
  instant = wall - offsetMinutes(instant) * 60_000
  return new Date(instant).toISOString()
}

/** Monday of the week containing a date. */
export function mondayOf(date: DateString): DateString {
  const [y = 1970, m = 1, d = 1] = date.split('-').map(Number)
  const day = new Date(y, m - 1, d).getDay()
  return addDays(date, -((day + 6) % 7))
}

export const weekDates = (date: DateString): DateString[] =>
  Array.from({ length: 7 }, (_, i) => addDays(mondayOf(date), i))

export const hhmm = (minutes: number): string =>
  `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`

export const parseHhmm = (value: string): number => {
  const [h = 0, m = 0] = value.split(':').map(Number)
  return h * 60 + m
}

export { toDateString }
