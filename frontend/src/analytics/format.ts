import { addDays, formatDate, type DateString } from '@/lib/dates'

const usd0 = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})
const usd2 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
const compact = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })
const whole = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

export type Unit = 'usd' | 'percent' | 'count' | 'days'

export const money = (value: number | string): string => usd0.format(Number(value))
export const moneyExact = (value: number | string): string => usd2.format(Number(value))
export const compactNumber = (value: number): string => compact.format(value)
export const compactMoney = (value: number): string => `$${compact.format(value)}`
export const integer = (value: number | string): string => whole.format(Number(value))
export const percent = (value: number | null | undefined, digits = 1): string =>
  value == null ? 'No data' : `${(value * 100).toFixed(digits)}%`

/** A KPI value written the way its unit asks. */
export function formatKpi(unit: Unit, value: number | null): string {
  if (value == null) return 'No data'
  if (unit === 'usd') return money(value)
  if (unit === 'percent') return percent(value)
  if (unit === 'days') return `${value.toFixed(1)} days`
  return integer(value)
}

/** The label of a period on an axis, in the clinic's calendar. */
export function periodLabel(period: DateString, granularity: string): string {
  if (granularity === 'month') return formatDate(period, { month: 'short', year: '2-digit' })
  if (granularity === 'quarter') {
    const month = Number(period.slice(5, 7))
    return `Q${Math.floor((month - 1) / 3) + 1} ${period.slice(2, 4)}`
  }
  if (granularity === 'week') return formatDate(period, { month: 'short', day: 'numeric' })
  return formatDate(period, { month: 'short', day: 'numeric' })
}

export const monthLabel = (period: DateString): string =>
  formatDate(period, { month: 'short', year: '2-digit' })

export const weekdayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export const hourLabel = (hour: number): string =>
  `${hour % 12 === 0 ? 12 : hour % 12}${hour >= 12 ? 'pm' : 'am'}`

export const lastDayOfMonth = (month: DateString): DateString => {
  const first = `${month.slice(0, 7)}-01`
  const [y = 1970, m = 1] = first.split('-').map(Number)
  return addDays(`${m === 12 ? y + 1 : y}-${String(m === 12 ? 1 : m + 1).padStart(2, '0')}-01`, -1)
}

/** Whether a timestamp is older than a number of hours (read when called). */
export const isStale = (iso: string, hours: number): boolean =>
  Date.now() - new Date(iso).getTime() > hours * 3_600_000
