import * as React from 'react'

import { useByService, useForecast, useStatusTrend, useSummary, useTrend } from '@/analytics/api'
import { useAnalytics } from '@/analytics/context'
import { ChartCard } from '@/analytics/ChartCard'
import { lastYear } from '@/analytics/filters'
import { change, insights } from '@/analytics/insights'
import { formatKpi, money, percent, type Unit } from '@/analytics/format'
import { categoryDonut, revenueCombo, statusArea, utilizationGauge } from '@/analytics/options'
import { Card, Skeleton } from '@/components/ui/display'
import { StatCard } from '@/components/ui/metrics'
import { useAllServices } from '@/console/api'

const KPI_KEYS = ['collected', 'billed', 'completed', 'utilization', 'no_show_rate', 'new_patients']

export function OverviewTab() {
  const { filters } = useAnalytics()
  const summary = useSummary(filters)
  const earlier = useSummary({ ...filters, ...lastYear(filters) }, filters.compare === 'year')
  const trend = useTrend(filters)
  const forecast = useForecast(filters, filters.granularity === 'month')
  const status = useStatusTrend(filters)
  const byService = useByService(filters)
  const catalogue = useAllServices()

  const kpis = KPI_KEYS.flatMap((key) => summary.data?.kpis.find((k) => k.key === key) ?? [])
  const combo = React.useMemo(
    () => (trend.data ? revenueCombo(trend.data, forecast.data, filters.compare !== 'none') : null),
    [trend.data, forecast.data, filters.compare],
  )
  const categories = React.useMemo(() => {
    const category = new Map((catalogue.data ?? []).map((s) => [s.id, s.category]))
    const totals = new Map<string, number>()
    for (const r of byService.data?.rows ?? []) {
      const name = category.get(r.key) ?? 'Other'
      totals.set(name, (totals.get(name) ?? 0) + Number(r.billed))
    }
    return [...totals.entries()]
      .map(([label, value]) => ({ label: label[0]?.toUpperCase() + label.slice(1), value }))
      .sort((a, b) => b.value - a.value)
  }, [byService.data, catalogue.data])
  const total = categories.reduce((s, c) => s + c.value, 0)
  const donut = categoryDonut(categories, money(total))
  const statusChart = status.data ? statusArea(status.data) : null
  const utilization = summary.data?.kpis.find((k) => k.key === 'utilization')
  const notes = summary.data ? insights(summary.data) : []

  return (
    <div className="grid gap-6">
      <section aria-label="Key figures" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {summary.isLoading
          ? KPI_KEYS.map((k) => <Skeleton key={k} className="h-36 w-full" />)
          : kpis.map((k) => {
              const c = change(k, filters.compare, earlier.data)
              return (
                <StatCard
                  key={k.key}
                  label={k.label}
                  value={k.value ?? 0}
                  format={(v) => formatKpi(k.unit as Unit, k.value == null ? null : v)}
                  change={c.value}
                  changeUnit={c.unit}
                  lowerIsBetter={!k.higher_is_better}
                  sparkline={k.sparkline.map((p) => p.value)}
                  hint={
                    filters.compare === 'none'
                      ? undefined
                      : filters.compare === 'previous'
                        ? `Before: ${formatKpi(k.unit as Unit, k.previous)}`
                        : `A year earlier: ${formatKpi(k.unit as Unit, earlier.data?.kpis.find((e) => e.key === k.key)?.value ?? null)}`
                  }
                />
              )
            })}
      </section>

      <ChartCard
        title="Revenue over time"
        description={
          filters.granularity === 'month'
            ? 'Collected and billed, with the next three months forecast.'
            : 'Collected and billed. Group by month to see the forecast.'
        }
        option={combo?.option ?? null}
        table={combo?.table ?? { columns: [], rows: [] }}
        loading={trend.isLoading}
        error={trend.isError}
        height={340}
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard
          title="Revenue by type of care"
          description="Billed in the period."
          option={categories.length ? donut.option : null}
          table={donut.table}
          loading={byService.isLoading}
          error={byService.isError}
          aside={
            <ol className="grid content-start gap-2 text-sm" aria-label="Ranked categories">
              {categories.map((c) => (
                <li key={c.label} className="grid gap-1">
                  <span className="flex justify-between gap-2">
                    <span className="font-medium">{c.label}</span>
                    <span>{money(c.value)}</span>
                  </span>
                  <span className="h-2 rounded-full bg-muted" aria-hidden="true">
                    <span
                      className="block h-2 rounded-full bg-accent-strong"
                      style={{ width: `${total ? (c.value / total) * 100 : 0}%` }}
                    />
                  </span>
                </li>
              ))}
            </ol>
          }
        />
        <ChartCard
          title="Appointments by status"
          option={statusChart?.option ?? null}
          table={statusChart?.table ?? { columns: [], rows: [] }}
          loading={status.isLoading}
          error={status.isError}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard
          title="Utilization"
          description="Share of working hours that were booked."
          option={utilization ? utilizationGauge(utilization.value).option : null}
          table={utilizationGauge(utilization?.value ?? null).table}
          loading={summary.isLoading}
          height={240}
        />
        <Card className="p-5" role="region" aria-label="Insights">
          <h2 className="font-heading text-base font-bold">What stands out</h2>
          <p className="text-sm text-muted-foreground">Observations from the figures above.</p>
          {summary.isLoading ? (
            <Skeleton className="mt-4 h-32 w-full" />
          ) : notes.length === 0 ? (
            <p className="mt-4 text-sm">Nothing has moved much since the previous period.</p>
          ) : (
            <ul className="mt-4 grid list-disc gap-2 pl-5 text-sm">
              {notes.map((text) => (
                <li key={text}>{text}</li>
              ))}
            </ul>
          )}
          {utilization?.value != null && (
            <p className="mt-4 text-xs text-muted-foreground">
              Utilization {percent(utilization.value)}.
            </p>
          )}
        </Card>
      </div>
    </div>
  )
}
