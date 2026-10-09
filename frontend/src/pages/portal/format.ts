import { clinic } from '@/content/site'
import type { Appointment } from '@/lib/booking-api'
import { dateInZone, formatDate, formatTime } from '@/lib/dates'

const dollars = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
export const money = (value: string | number) => dollars.format(Number(value))

export const longDay = (iso: string) => formatDate(dateInZone(iso, clinic.timeZone))
export const shortDay = (iso: string) =>
  formatDate(dateInZone(iso, clinic.timeZone), { weekday: 'short', month: 'short', day: 'numeric' })
export const clock = (iso: string) => formatTime(iso, clinic.timeZone)

/** True once the moment has passed (read when called, not stored). */
export const hasPassed = (iso: string) => new Date(iso).getTime() < Date.now()

/** An appointment that can still be changed or cancelled. */
export const isActive = (appointment: Appointment) =>
  (appointment.status === 'booked' || appointment.status === 'confirmed') &&
  !hasPassed(appointment.start)
