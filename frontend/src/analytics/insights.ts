import type { Kpi, ServiceTrends, Summary } from '@/analytics/api'
import { formatKpi } from '@/analytics/format'
import type { Compare } from '@/analytics/filters'

type ServiceRows = ServiceTrends['rows']

export interface Steps {
  start: number
  volume: number
  mix: number
  price: number
  end: number
}

/**
 * Why revenue moved between two periods, in three parts that add up exactly to the change.
 * Quantity is the number of invoices and price is the average invoice, service by service.
 *   volume: more or fewer invoices overall, at last period's average invoice
 *   mix:    a shift toward dearer or cheaper services, at last period's prices
 *   price:  the same services billing more or less than before
 * A service that did not exist before has no price change by definition.
 */
export function priceVolumeMix(previous: ServiceRows, current: ServiceRows): Steps {
  const qty = (r: ServiceRows[number]) => r.invoices
  const rev = (r: ServiceRows[number]) => Number(r.billed)
  const before = new Map(previous.map((r) => [r.key, r]))
  const qa = previous.reduce((s, r) => s + qty(r), 0)
  const ra = previous.reduce((s, r) => s + rev(r), 0)
  const qb = current.reduce((s, r) => s + qty(r), 0)
  const rb = current.reduce((s, r) => s + rev(r), 0)
  if (qa === 0) return { start: ra, volume: rb - ra, mix: 0, price: 0, end: rb }
  const averageBefore = ra / qa
  const priceBefore = (r: ServiceRows[number]) => {
    const old = before.get(r.key)
    return old && qty(old) ? rev(old) / qty(old) : qty(r) ? rev(r) / qty(r) : 0
  }
  const volume = (qb - qa) * averageBefore
  const mix = current.reduce((s, r) => s + qty(r) * priceBefore(r), 0) - qb * averageBefore
  const price = current.reduce((s, r) => s + (rev(r) - qty(r) * priceBefore(r)), 0)
  return { start: ra, volume, mix, price, end: rb }
}

/** The change shown beside a KPI under the chosen comparison. */
export function change(
  kpi: Kpi,
  mode: Compare,
  year: Summary | undefined,
): { value: number | null | undefined; unit: '%' | ' points' } {
  const unit = kpi.change_kind === 'points' ? ' points' : '%'
  if (mode === 'none') return { value: undefined, unit }
  if (mode === 'previous') return { value: kpi.change_percent, unit }
  const earlier = year?.kpis.find((k) => k.key === kpi.key)?.value
  if (kpi.value == null || earlier == null) return { value: null, unit }
  if (kpi.change_kind === 'points') return { value: (kpi.value - earlier) * 100, unit }
  return { value: earlier ? ((kpi.value - earlier) / earlier) * 100 : null, unit }
}

/**
 * Plain observations from the headline figures, most notable first. Each is a rule, not a model:
 * a KPI that moved by more than its threshold, or a figure that is outside a healthy range.
 */
export function insights(summary: Summary, limit = 5): string[] {
  const found: { score: number; text: string }[] = []
  for (const k of summary.kpis) {
    if (k.change_percent == null) continue
    const size = Math.abs(k.change_percent)
    const points = k.change_kind === 'points'
    if (size < (points ? 1 : 5)) continue
    const up = k.change_percent > 0
    const good = up === k.higher_is_better
    const amount = points ? `${size.toFixed(1)} points` : `${size.toFixed(0)} percent`
    found.push({
      score: points ? size * 5 : size,
      text: `${k.label} ${up ? 'rose' : 'fell'} ${amount} compared with the previous period${good ? '.' : '. That needs attention.'}`,
    })
  }
  const utilization = summary.kpis.find((k) => k.key === 'utilization')
  if (utilization?.value != null && utilization.value < 0.6)
    found.push({
      score: 40,
      text: `Utilization is ${formatKpi('percent', utilization.value)}, so there is room for more bookings.`,
    })
  const collection = summary.kpis.find((k) => k.key === 'collection_rate')
  if (collection?.value != null && collection.value < 0.9)
    found.push({
      score: 45,
      text: `Only ${formatKpi('percent', collection.value)} of billed revenue has been collected so far.`,
    })
  return found
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((f) => f.text)
}

/** Where the year to date stands against a monthly target. */
export function targetProgress(monthly: number, ytdCollected: number, today: Date) {
  const month = today.getMonth()
  const days = new Date(today.getFullYear(), month + 1, 0).getDate()
  const months = month + today.getDate() / days
  const target = monthly * months
  return { target, ratio: target ? ytdCollected / target : null }
}
