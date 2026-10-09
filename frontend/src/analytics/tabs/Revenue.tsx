import * as React from 'react'

import {
  useDentistServices,
  useServiceTrends,
  useStatusTrend,
  useSummary,
  useTrend,
  useWeekdays,
} from '@/analytics/api'
import { useAnalytics } from '@/analytics/context'
import { ChartCard } from '@/analytics/ChartCard'
import { lastFullDay } from '@/analytics/filters'
import { lastDayOfMonth, money, percent } from '@/analytics/format'
import { priceVolumeMix, targetProgress } from '@/analytics/insights'
import {
  dentistStack,
  payerMix,
  revenuePerVisit,
  waterfall,
  weekdayBars,
} from '@/analytics/options'
import { Card, Skeleton } from '@/components/ui/display'
import { DataTable, type Column } from '@/components/ui/data-table'
import { Sparkline } from '@/components/ui/metrics'
import { useSettings } from '@/console/api'
import { addMonths, startOfMonth } from '@/lib/dates'

type ServiceRow = NonNullable<ReturnType<typeof useServiceTrends>['data']>['rows'][number]
const empty = { columns: [], rows: [] }

/** The last month that is complete at the end of the chosen range, and the month before it. */
function monthPair(to: string) {
  const end = lastDayOfMonth(to) <= to ? to : addMonths(startOfMonth(to), -1)
  const latest = startOfMonth(end)
  const earlier = addMonths(latest, -1)
  return {
    latest: { from: latest, to: lastDayOfMonth(latest) },
    earlier: { from: earlier, to: lastDayOfMonth(earlier) },
  }
}

export function RevenueTab() {
  const { filters } = useAnalytics()
  const months = React.useMemo(() => monthPair(filters.to), [filters.to])
  const monthly = { ...filters, granularity: 'month' as const }
  const now = useServiceTrends({ ...monthly, ...months.latest })
  const before = useServiceTrends({ ...monthly, ...months.earlier })
  const matrix = useDentistServices(filters)
  const patient = useTrend({ ...filters, payer: 'patient' })
  const insurer = useTrend({ ...filters, payer: 'insurer' })
  const trend = useTrend(filters)
  const status = useStatusTrend(filters)
  const weekdays = useWeekdays(filters)
  const services = useServiceTrends(filters)
  const settings = useSettings()
  const year = `${filters.to.slice(0, 4)}-01-01`
  const ytd = useSummary({
    ...filters,
    from: year,
    to: filters.to > lastFullDay() ? lastFullDay() : filters.to,
    granularity: 'month',
  })

  const steps = React.useMemo(() => {
    if (!now.data || !before.data) return null
    const s = priceVolumeMix(before.data.rows, now.data.rows)
    return waterfall([
      { name: 'Previous month', value: s.start, total: true },
      { name: 'More or fewer invoices', value: s.volume },
      { name: 'Shift in services', value: s.mix },
      { name: 'Prices', value: s.price },
      { name: 'Latest month', value: s.end, total: true },
    ])
  }, [now.data, before.data])

  const stack = matrix.data ? dentistStack(matrix.data) : null
  const mix = patient.data && insurer.data ? payerMix(patient.data, insurer.data) : null
  const perVisit = trend.data && status.data ? revenuePerVisit(trend.data, status.data) : null
  const days = weekdays.data ? weekdayBars(weekdays.data) : null

  const collectedYtd = ytd.data?.kpis.find((k) => k.key === 'collected')?.value ?? 0
  const monthlyTarget = Number(settings.data?.billing.monthly_revenue_target ?? 0)
  const progress =
    monthlyTarget > 0 ? targetProgress(monthlyTarget, collectedYtd, new Date(filters.to)) : null

  const columns: Column<ServiceRow>[] = [
    { key: 'service', header: 'Service', sortValue: (r) => r.label, cell: (r) => r.label },
    {
      key: 'billed',
      header: 'Billed',
      align: 'right',
      sortValue: (r) => Number(r.billed),
      cell: (r) => money(r.billed),
    },
    {
      key: 'visits',
      header: 'Visits',
      align: 'right',
      sortValue: (r) => r.visits,
      cell: (r) => r.visits,
    },
    {
      key: 'hour',
      header: 'Per chair hour',
      align: 'right',
      sortValue: (r) => r.revenue_per_hour ?? 0,
      cell: (r) => (r.revenue_per_hour == null ? 'No data' : money(r.revenue_per_hour)),
    },
    {
      key: 'trend',
      header: 'Trend',
      cell: (r) => (
        <span className="text-accent-strong">
          <Sparkline values={r.series.map((p) => p.value)} />
          <span className="sr-only">{r.series.map((p) => money(p.value)).join(', ')}</span>
        </span>
      ),
    },
  ]

  return (
    <div className="grid gap-6">
      <Card className="p-5" role="region" aria-label="Progress toward target">
        <h2 className="font-heading text-base font-bold">Year to date against target</h2>
        {settings.isLoading || ytd.isLoading ? (
          <Skeleton className="mt-3 h-10 w-full" />
        ) : progress ? (
          <>
            <p className="mt-1 text-sm text-muted-foreground">
              {money(collectedYtd)} collected of {money(progress.target)} expected so far (
              {percent(progress.ratio)}). The target is {money(monthlyTarget)} a month.
            </p>
            <div
              className="mt-3 h-3 rounded-full bg-muted"
              role="progressbar"
              aria-label="Year to date collected against target"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.min(100, Math.round((progress.ratio ?? 0) * 100))}
            >
              <div
                className="h-3 rounded-full bg-accent-strong"
                style={{ width: `${Math.min(100, (progress.ratio ?? 0) * 100)}%` }}
              />
            </div>
          </>
        ) : (
          <p className="mt-1 text-sm text-muted-foreground">
            Set a monthly revenue target in Settings to see progress here.
          </p>
        )}
      </Card>

      <ChartCard
        title="What changed since last month"
        description="Billed revenue of the latest complete month against the month before, split into the invoices, the services and the prices."
        option={steps?.option ?? null}
        table={steps?.table ?? empty}
        loading={now.isLoading || before.isLoading}
        error={now.isError || before.isError}
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard
          title="Revenue by dentist and service"
          option={stack?.option ?? null}
          table={stack?.table ?? empty}
          loading={matrix.isLoading}
          error={matrix.isError}
        />
        <ChartCard
          title="Who pays"
          description="Share of billed revenue owed by patients and by insurers."
          option={mix?.option ?? null}
          table={mix?.table ?? empty}
          loading={patient.isLoading || insurer.isLoading}
          error={patient.isError || insurer.isError}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard
          title="Average revenue per visit"
          option={perVisit?.option ?? null}
          table={perVisit?.table ?? empty}
          loading={trend.isLoading || status.isLoading}
          error={trend.isError || status.isError}
        />
        <ChartCard
          title="Revenue by day of the week"
          description="Average billed on each kind of day."
          option={days?.option ?? null}
          table={days?.table ?? empty}
          loading={weekdays.isLoading}
          error={weekdays.isError}
        />
      </div>

      <section aria-labelledby="top-services">
        <h2 id="top-services" className="mb-3 font-heading text-lg font-bold">
          Top ten services
        </h2>
        <DataTable
          caption="Top ten services by billed revenue"
          columns={columns}
          rows={(services.data?.rows ?? []).slice(0, 10)}
          getRowId={(r) => r.key}
          loading={services.isLoading}
          pageSize={10}
        />
      </section>
    </div>
  )
}
