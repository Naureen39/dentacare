import type { EChartsCoreOption } from 'echarts/core'

import type {
  ArAging,
  Channels,
  Chatbot,
  Collection,
  Demographics,
  DentistServices,
  Forecast,
  Heatmap,
  LeadTime,
  Leaderboard,
  NewVsReturning,
  Retention,
  RevenueTrend,
  ServiceTrends,
  StatusTrend,
  Weekdays,
} from '@/analytics/api'
import {
  compactMoney,
  hourLabel,
  integer,
  money,
  monthLabel,
  percent,
  periodLabel,
  weekdayNames,
} from '@/analytics/format'
import type { ChartTable } from '@/components/ui/chart'
import { chartColors } from '@/components/ui/chart'

export type ChartOption = EChartsCoreOption
export interface Built {
  option: ChartOption
  table: ChartTable
}

const INK = '#334155'
const GRID = '#e2e8f0'
const GOOD = '#1e9e6a'
const BAD = '#d64545'
const NAVY = '#0b2545'

/** What every chart shares: brand colours, type, spacing and a short animation. */
const base: ChartOption = {
  color: [...chartColors],
  textStyle: { fontFamily: 'Inter Variable, ui-sans-serif, system-ui, sans-serif', color: INK },
  animationDuration: 300,
  grid: { left: 8, right: 16, top: 40, bottom: 8, containLabel: true },
  legend: { top: 0, textStyle: { color: INK } },
}
const themed = (option: ChartOption): ChartOption => ({ ...base, ...option })

const axisLine = { lineStyle: { color: GRID } }
const valueAxis = (formatter?: (v: number) => string, extra: object = {}) => ({
  type: 'value',
  splitLine: { lineStyle: { color: GRID } },
  axisLabel: formatter ? { formatter } : undefined,
  ...extra,
})
const categoryAxis = (data: string[], extra: object = {}) => ({
  type: 'category',
  data,
  axisLine,
  axisTick: { show: false },
  ...extra,
})

const n = (value: string | number) => Number(value)
const pct = (v: number | null | undefined) => (v == null ? null : Math.round(v * 1000) / 10)

// --- overview --------------------------------------------------------------------------------------------

export function revenueCombo(
  trend: RevenueTrend,
  forecast: Forecast | undefined,
  showPrior: boolean,
): Built {
  const granularity = trend.meta.granularity
  const labels = trend.points.map((p) => periodLabel(p.period, granularity))
  const last = trend.points.at(-1)?.period ?? ''
  const future =
    granularity === 'month' && forecast ? forecast.forecast.filter((f) => f.month > last) : []
  const all = [...labels, ...future.map((f) => monthLabel(f.month))]
  const pad = (values: (number | null)[]) => [...values, ...future.map(() => null)]
  const history = trend.points.length
  const series: object[] = [
    {
      name: 'Collected',
      type: 'bar',
      data: pad(trend.points.map((p) => n(p.collected))),
      barMaxWidth: 28,
    },
    {
      name: 'Billed',
      type: 'line',
      data: pad(trend.points.map((p) => n(p.billed))),
      symbol: 'circle',
      symbolSize: 6,
    },
  ]
  if (showPrior)
    series.push({
      name: 'Billed, a year earlier',
      type: 'line',
      data: pad(trend.points.map((p) => n(p.prior_year_billed))),
      lineStyle: { type: 'dotted', width: 2 },
      symbol: 'none',
    })
  if (future.length) {
    const lead = Array<number | null>(history - 1).fill(null)
    const anchor = n(trend.points.at(-1)?.collected ?? 0)
    series.push(
      {
        name: 'Forecast',
        type: 'line',
        data: [...lead, anchor, ...future.map((f) => f.value)],
        lineStyle: { type: 'dashed', width: 2 },
        itemStyle: { color: chartColors[1] },
      },
      {
        name: 'Low estimate',
        type: 'line',
        stack: 'band',
        data: [...lead, anchor, ...future.map((f) => f.lower ?? f.value)],
        lineStyle: { opacity: 0 },
        symbol: 'none',
        tooltip: { show: false },
      },
      {
        name: `Likely range (${Math.round((forecast?.interval_level ?? 0.8) * 100)}%)`,
        type: 'line',
        stack: 'band',
        data: [...lead, 0, ...future.map((f) => (f.upper ?? f.value) - (f.lower ?? f.value))],
        lineStyle: { opacity: 0 },
        areaStyle: { opacity: 0.15 },
        symbol: 'none',
      },
    )
  }
  const columns = ['Period', 'Collected', 'Billed']
  if (showPrior) columns.push('Billed a year earlier')
  const rows: (string | number)[][] = trend.points.map((p, i) => [
    labels[i] ?? '',
    money(p.collected),
    money(p.billed),
    ...(showPrior ? [money(p.prior_year_billed)] : []),
  ])
  if (future.length) {
    columns.push('Forecast', 'Low', 'High')
    for (const f of future)
      rows.push([
        monthLabel(f.month),
        '',
        '',
        ...(showPrior ? [''] : []),
        money(f.value),
        money(f.lower ?? f.value),
        money(f.upper ?? f.value),
      ])
  }
  return {
    option: themed({
      tooltip: {
        trigger: 'axis',
        valueFormatter: (v: number | null) => (v == null ? '' : money(v)),
      },
      xAxis: categoryAxis(all),
      yAxis: valueAxis(compactMoney),
      series,
    }),
    table: { columns, rows },
  }
}

export function categoryDonut(rows: { label: string; value: number }[], centre: string): Built {
  return {
    option: themed({
      tooltip: { trigger: 'item', valueFormatter: (v: number) => money(v) },
      legend: { bottom: 0, top: undefined },
      title: {
        text: centre,
        left: 'center',
        top: '40%',
        textStyle: { fontSize: 20, fontWeight: 800, color: NAVY },
      },
      series: [
        {
          type: 'pie',
          radius: ['55%', '78%'],
          center: ['50%', '45%'],
          label: { show: false },
          data: rows.map((r) => ({ name: r.label, value: r.value })),
        },
      ],
    }),
    table: { columns: ['Group', 'Billed'], rows: rows.map((r) => [r.label, money(r.value)]) },
  }
}

export function statusArea(trend: StatusTrend): Built {
  const labels = trend.points.map((p) => periodLabel(p.period, trend.meta.granularity))
  const line = (
    name: string,
    pick: (p: StatusTrend['points'][number]) => number,
    color: string,
  ) => ({
    name,
    type: 'line',
    stack: 'status',
    areaStyle: { opacity: 0.55 },
    symbol: 'none',
    itemStyle: { color },
    data: trend.points.map(pick),
  })
  return {
    option: themed({
      tooltip: { trigger: 'axis' },
      xAxis: categoryAxis(labels, { boundaryGap: false }),
      yAxis: valueAxis(),
      series: [
        line('Completed', (p) => p.completed, GOOD),
        line('Still to come', (p) => p.open, chartColors[0]),
        line('Cancelled', (p) => p.cancelled, chartColors[2]),
        line('No show', (p) => p.no_show, BAD),
      ],
    }),
    table: {
      columns: ['Period', 'Completed', 'Still to come', 'Cancelled', 'No show'],
      rows: trend.points.map((p, i) => [
        labels[i] ?? '',
        p.completed,
        p.open,
        p.cancelled,
        p.no_show,
      ]),
    },
  }
}

export function utilizationGauge(value: number | null): Built {
  const shown = value == null ? 0 : Math.round(value * 1000) / 10
  return {
    option: themed({
      series: [
        {
          type: 'gauge',
          min: 0,
          max: 100,
          progress: { show: true, width: 14 },
          axisLine: { lineStyle: { width: 14, color: [[1, GRID]] } },
          pointer: { show: false },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: false },
          detail: {
            valueAnimation: true,
            formatter: '{value}%',
            fontSize: 28,
            fontWeight: 800,
            color: NAVY,
            offsetCenter: [0, '10%'],
          },
          data: [{ value: shown }],
        },
      ],
    }),
    table: { columns: ['Measure', 'Value'], rows: [['Utilization', percent(value)]] },
  }
}

// --- revenue ---------------------------------------------------------------------------------------------------

export function waterfall(steps: { name: string; value: number; total?: boolean }[]): Built {
  let running = 0
  const base: number[] = []
  const rise: (number | null)[] = []
  const fall: (number | null)[] = []
  const total: (number | null)[] = []
  for (const s of steps) {
    if (s.total) {
      base.push(0)
      rise.push(null)
      fall.push(null)
      total.push(s.value)
      running = s.value
    } else {
      const next = running + s.value
      base.push(Math.min(running, next))
      rise.push(s.value >= 0 ? s.value : null)
      fall.push(s.value < 0 ? -s.value : null)
      total.push(null)
      running = next
    }
  }
  return {
    option: themed({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        valueFormatter: (v: number | null) => (v == null ? '' : money(v)),
      },
      legend: { show: false },
      xAxis: categoryAxis(steps.map((s) => s.name)),
      yAxis: valueAxis(compactMoney),
      series: [
        {
          name: 'Base',
          type: 'bar',
          stack: 'wf',
          itemStyle: { color: 'transparent' },
          data: base,
          tooltip: { show: false },
        },
        {
          name: 'Total',
          type: 'bar',
          stack: 'wf',
          itemStyle: { color: NAVY },
          data: total,
          barMaxWidth: 56,
        },
        { name: 'Increase', type: 'bar', stack: 'wf', itemStyle: { color: GOOD }, data: rise },
        { name: 'Decrease', type: 'bar', stack: 'wf', itemStyle: { color: BAD }, data: fall },
      ],
    }),
    table: {
      columns: ['Step', 'Amount'],
      rows: steps.map((s) => [
        s.name,
        `${s.value < 0 ? '-' : s.total ? '' : '+'}${money(Math.abs(s.value))}`,
      ]),
    },
  }
}

export function dentistStack(matrix: DentistServices, keep = 6): Built {
  const byService = new Map<string, number>()
  for (const c of matrix.cells)
    byService.set(c.service, (byService.get(c.service) ?? 0) + n(c.billed))
  const leaders = [...byService.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, keep)
    .map(([name]) => name)
  const dentists = [...new Set(matrix.cells.map((c) => c.dentist))]
  const value = (dentist: string, service: string | null) =>
    matrix.cells
      .filter(
        (c) =>
          c.dentist === dentist &&
          (service === null ? !leaders.includes(c.service) : c.service === service),
      )
      .reduce((sum, c) => sum + n(c.billed), 0)
  const names = [...leaders, ...(byService.size > keep ? ['Other services'] : [])]
  return {
    option: themed({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        valueFormatter: (v: number) => money(v),
      },
      legend: { type: 'scroll', top: 0 },
      xAxis: categoryAxis(dentists),
      yAxis: valueAxis(compactMoney),
      series: names.map((name, i) => ({
        name,
        type: 'bar',
        stack: 'dentist',
        data: dentists.map((d) => value(d, i < leaders.length ? name : null)),
      })),
    }),
    table: {
      columns: ['Dentist', ...names],
      rows: dentists.map((d) => [
        d,
        ...names.map((name, i) => money(value(d, i < leaders.length ? name : null))),
      ]),
    },
  }
}

export function payerMix(patient: RevenueTrend, insurer: RevenueTrend): Built {
  const periods = [...new Set([...patient.points, ...insurer.points].map((p) => p.period))].sort()
  const labels = periods.map((p) => periodLabel(p, patient.meta.granularity))
  const at = (t: RevenueTrend, period: string) =>
    n(t.points.find((p) => p.period === period)?.billed ?? 0)
  const share = (period: string, who: 'patient' | 'insurer') => {
    const a = at(patient, period)
    const b = at(insurer, period)
    const total = a + b
    return total ? Math.round(((who === 'patient' ? a : b) / total) * 1000) / 10 : 0
  }
  return {
    option: themed({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        valueFormatter: (v: number) => `${v}%`,
      },
      xAxis: categoryAxis(labels),
      yAxis: valueAxis((v) => `${v}%`, { max: 100 }),
      series: [
        {
          name: 'Patient share',
          type: 'bar',
          stack: 'mix',
          data: periods.map((p) => share(p, 'patient')),
        },
        {
          name: 'Insurance share',
          type: 'bar',
          stack: 'mix',
          data: periods.map((p) => share(p, 'insurer')),
        },
      ],
    }),
    table: {
      columns: ['Period', 'Patient share', 'Insurance share'],
      rows: periods.map((p, i) => [
        labels[i] ?? '',
        `${share(p, 'patient')}%`,
        `${share(p, 'insurer')}%`,
      ]),
    },
  }
}

/** Average revenue per completed visit in each period: billed divided by completed visits. */
export function revenuePerVisit(trend: RevenueTrend, status: StatusTrend): Built {
  const done = new Map(status.points.map((p) => [p.period, p.completed]))
  const rows = trend.points.map((p) => {
    const visits = done.get(p.period) ?? 0
    return { period: p.period, value: visits ? n(p.billed) / visits : null }
  })
  const labels = rows.map((r) => periodLabel(r.period, trend.meta.granularity))
  return {
    option: themed({
      tooltip: {
        trigger: 'axis',
        valueFormatter: (v: number | null) => (v == null ? 'No visits' : money(v)),
      },
      legend: { show: false },
      xAxis: categoryAxis(labels),
      yAxis: valueAxis(compactMoney, { scale: true }),
      series: [
        {
          name: 'Revenue per visit',
          type: 'line',
          data: rows.map((r) => r.value),
          symbol: 'circle',
          smooth: true,
        },
      ],
    }),
    table: {
      columns: ['Period', 'Revenue per visit'],
      rows: rows.map((r, i) => [labels[i] ?? '', r.value == null ? 'No visits' : money(r.value)]),
    },
  }
}

export function weekdayBars(data: Weekdays): Built {
  const average = data.rows.map((r) => (r.days ? n(r.billed) / r.days : 0))
  return {
    option: themed({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        valueFormatter: (v: number) => money(v),
      },
      legend: { show: false },
      xAxis: categoryAxis(weekdayNames),
      yAxis: valueAxis(compactMoney),
      series: [{ name: 'Billed per day', type: 'bar', data: average, barMaxWidth: 40 }],
    }),
    table: {
      columns: ['Day', 'Billed in total', 'Average per day', 'Invoices'],
      rows: data.rows.map((r, i) => [
        weekdayNames[r.weekday] ?? '',
        money(r.billed),
        money(average[i] ?? 0),
        integer(r.invoices),
      ]),
    },
  }
}

// --- appointments -------------------------------------------------------------------------------------------------

export function heatmap(data: Heatmap): Built {
  const hours = [...new Set(data.cells.map((c) => c.hour))].sort((a, b) => a - b)
  const first = hours[0] ?? 8
  const last = hours.at(-1) ?? 17
  const range = Array.from({ length: last - first + 1 }, (_, i) => first + i)
  return {
    option: themed({
      tooltip: {
        formatter: (p: { data: [number, number, number, number | null] }) => {
          const [x, y, count, rate] = p.data
          return `${weekdayNames[y] ?? ''} ${hourLabel(range[x] ?? 0)}: ${count} visits, no show rate ${percent(rate)}`
        },
      },
      grid: { left: 8, right: 16, top: 8, bottom: 40, containLabel: true },
      legend: { show: false },
      xAxis: { type: 'category', data: range.map(hourLabel), splitArea: { show: true } },
      yAxis: { type: 'category', data: weekdayNames, inverse: true, splitArea: { show: true } },
      visualMap: {
        min: 0,
        max: Math.max(data.max_appointments, 1),
        calculable: false,
        orient: 'horizontal',
        left: 'center',
        bottom: 0,
        inRange: { color: ['#e8f1f8', '#0b7371', '#0b2545'] },
      },
      series: [
        {
          type: 'heatmap',
          data: data.cells.map((c) => [
            range.indexOf(c.hour),
            c.weekday,
            c.appointments,
            c.no_show_rate,
          ]),
          label: { show: false },
        },
      ],
    }),
    table: {
      columns: ['Day', 'Hour', 'Visits', 'No show rate'],
      rows: data.cells.map((c) => [
        weekdayNames[c.weekday] ?? '',
        hourLabel(c.hour),
        c.appointments,
        percent(c.no_show_rate),
      ]),
    },
  }
}

export function statusFunnel(trend: StatusTrend): Built {
  const sum = (pick: (p: StatusTrend['points'][number]) => number) =>
    trend.points.reduce((a, p) => a + pick(p), 0)
  const booked = sum((p) => p.total)
  const kept = booked - sum((p) => p.cancelled)
  const done = sum((p) => p.completed)
  const steps = [
    { name: 'Booked', value: booked },
    { name: 'Not cancelled', value: kept },
    { name: 'Completed', value: done },
  ]
  return {
    option: themed({
      tooltip: { trigger: 'item' },
      legend: { show: false },
      series: [
        {
          type: 'funnel',
          left: '10%',
          width: '80%',
          top: 8,
          bottom: 8,
          sort: 'none',
          label: { formatter: '{b}: {c}' },
          data: steps,
        },
      ],
    }),
    table: {
      columns: ['Stage', 'Visits', 'Share of booked'],
      rows: steps.map((s) => [s.name, s.value, percent(booked ? s.value / booked : null)]),
    },
  }
}

export function leadTimeBars(data: LeadTime): Built {
  return {
    option: themed({
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { show: false },
      xAxis: categoryAxis(data.buckets.map((b) => b.label)),
      yAxis: valueAxis(),
      series: [
        {
          name: 'Visits',
          type: 'bar',
          data: data.buckets.map((b) => b.appointments),
          barMaxWidth: 48,
        },
      ],
    }),
    table: {
      columns: ['Booked ahead', 'Visits', 'Share'],
      rows: data.buckets.map((b) => [b.label, b.appointments, percent(b.share)]),
    },
  }
}

export function rateLines(trend: StatusTrend): Built {
  const labels = trend.points.map((p) => periodLabel(p.period, trend.meta.granularity))
  return {
    option: themed({
      tooltip: {
        trigger: 'axis',
        valueFormatter: (v: number | null) => (v == null ? '' : `${v}%`),
      },
      xAxis: categoryAxis(labels),
      yAxis: valueAxis((v) => `${v}%`),
      series: [
        {
          name: 'Cancellation rate',
          type: 'line',
          data: trend.points.map((p) => pct(p.cancellation_rate)),
          symbol: 'circle',
        },
        {
          name: 'No show rate',
          type: 'line',
          data: trend.points.map((p) => pct(p.no_show_rate)),
          symbol: 'circle',
          itemStyle: { color: BAD },
        },
      ],
    }),
    table: {
      columns: ['Period', 'Cancellation rate', 'No show rate'],
      rows: trend.points.map((p, i) => [
        labels[i] ?? '',
        percent(p.cancellation_rate),
        percent(p.no_show_rate),
      ]),
    },
  }
}

export function channelDonut(data: Channels): Built {
  return {
    option: themed({
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, top: undefined },
      series: [
        {
          type: 'pie',
          radius: ['45%', '72%'],
          center: ['50%', '45%'],
          label: { formatter: '{b}: {d}%' },
          data: data.rows.map((r) => ({ name: r.label, value: r.appointments })),
        },
      ],
    }),
    table: {
      columns: ['Channel', 'Visits', 'Completed', 'Share'],
      rows: data.rows.map((r) => [r.label, r.appointments, r.completed, percent(r.share)]),
    },
  }
}

// --- patients --------------------------------------------------------------------------------------------------------

export function newReturning(data: NewVsReturning): Built {
  const labels = data.points.map((p) => periodLabel(p.period, data.meta.granularity))
  return {
    option: themed({
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: categoryAxis(labels),
      yAxis: valueAxis(),
      series: [
        {
          name: 'New patients',
          type: 'bar',
          stack: 'p',
          data: data.points.map((p) => p.new_patients),
        },
        {
          name: 'Returning patients',
          type: 'bar',
          stack: 'p',
          data: data.points.map((p) => p.returning_patients),
        },
      ],
    }),
    table: {
      columns: ['Period', 'New', 'Returning'],
      rows: data.points.map((p, i) => [labels[i] ?? '', p.new_patients, p.returning_patients]),
    },
  }
}

export function cohortHeatmap(data: Retention, months = 12): Built {
  const cohorts = data.cohorts
  const labels = cohorts.map((c) => monthLabel(c.cohort_month))
  const cells: [number, number, number][] = []
  cohorts.forEach((c, y) =>
    c.retention.slice(0, months + 1).forEach((v, x) => {
      if (v != null) cells.push([x, y, Math.round(v * 1000) / 10])
    }),
  )
  return {
    option: themed({
      tooltip: {
        formatter: (p: { data: [number, number, number] }) =>
          `${labels[p.data[1]] ?? ''}, month ${p.data[0]}: ${p.data[2]}% came back`,
      },
      grid: { left: 8, right: 16, top: 8, bottom: 44, containLabel: true },
      legend: { show: false },
      xAxis: {
        type: 'category',
        data: Array.from({ length: months + 1 }, (_, i) => `${i}`),
        name: 'Months since first visit',
        nameLocation: 'middle',
        nameGap: 26,
      },
      yAxis: { type: 'category', data: labels, inverse: true },
      visualMap: {
        min: 0,
        max: 100,
        show: false,
        inRange: { color: ['#eef4f8', '#0b7371', '#0b2545'] },
      },
      series: [
        {
          type: 'heatmap',
          data: cells,
          label: {
            show: cohorts.length <= 14,
            formatter: (p: { data: [number, number, number] }) => `${Math.round(p.data[2])}`,
          },
        },
      ],
    }),
    table: {
      columns: [
        'First visit month',
        'Patients',
        ...Array.from({ length: months + 1 }, (_, i) => `Month ${i}`),
      ],
      rows: cohorts.map((c) => [
        monthLabel(c.cohort_month),
        c.cohort_size,
        ...c.retention.slice(0, months + 1).map((v) => percent(v, 0)),
      ]),
    },
  }
}

export function growthLine(data: NewVsReturning): Built {
  let total = 0
  const cumulative = data.points.map((p) => (total += p.new_patients))
  const labels = data.points.map((p) => periodLabel(p.period, data.meta.granularity))
  return {
    option: themed({
      tooltip: { trigger: 'axis' },
      legend: { show: false },
      xAxis: categoryAxis(labels, { boundaryGap: false }),
      yAxis: valueAxis(),
      series: [
        {
          name: 'New patients so far',
          type: 'line',
          data: cumulative,
          areaStyle: { opacity: 0.15 },
          symbol: 'none',
        },
      ],
    }),
    table: {
      columns: ['Period', 'New patients so far'],
      rows: labels.map((l, i) => [l, cumulative[i] ?? 0]),
    },
  }
}

export function sliceBars(data: Demographics): Built {
  return {
    option: themed({
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { show: false },
      xAxis: categoryAxis(data.age_bands.map((b) => b.label)),
      yAxis: valueAxis(),
      series: [
        {
          name: 'Patients',
          type: 'bar',
          data: data.age_bands.map((b) => b.patients),
          barMaxWidth: 48,
        },
      ],
    }),
    table: {
      columns: ['Age', 'Patients', 'Share'],
      rows: data.age_bands.map((b) => [b.label, b.patients, percent(b.share)]),
    },
  }
}

export function sourceDonut(data: Demographics): Built {
  return {
    option: themed({
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, top: undefined },
      series: [
        {
          type: 'pie',
          radius: ['45%', '72%'],
          center: ['50%', '45%'],
          label: { formatter: '{b}: {d}%' },
          data: data.sources.map((s) => ({ name: s.label, value: s.patients })),
        },
      ],
    }),
    table: {
      columns: ['Source', 'Patients', 'Share'],
      rows: data.sources.map((s) => [s.label, s.patients, percent(s.share)]),
    },
  }
}

// --- dentists and services --------------------------------------------------------------------------------------------

export function utilizationBars(data: Leaderboard): Built {
  const rows = data.rows
  return {
    option: themed({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        valueFormatter: (v: number) => `${v}%`,
      },
      legend: { show: false },
      xAxis: categoryAxis(
        rows.map((r) => r.dentist),
        { axisLabel: { interval: 0, rotate: rows.length > 5 ? 25 : 0 } },
      ),
      yAxis: valueAxis((v) => `${v}%`, { max: 100 }),
      series: [
        {
          name: 'Chair time used',
          type: 'bar',
          data: rows.map((r) => pct(r.utilization)),
          barMaxWidth: 40,
        },
      ],
    }),
    table: {
      columns: ['Dentist', 'Hours booked', 'Hours available', 'Utilization'],
      rows: rows.map((r) => [r.dentist, r.booked_hours, r.available_hours, percent(r.utilization)]),
    },
  }
}

export function dentistRadar(data: Leaderboard, limit = 5): Built {
  const rows = data.rows.slice(0, limit)
  const top = (pick: (r: Leaderboard['rows'][number]) => number) => Math.max(...rows.map(pick), 1)
  const maxRevenue = top((r) => n(r.billed))
  const maxPerVisit = top((r) => r.revenue_per_visit ?? 0)
  const maxVisits = top((r) => r.visits)
  const score = (r: Leaderboard['rows'][number]) => [
    Math.round((n(r.billed) / maxRevenue) * 100),
    Math.round(((r.revenue_per_visit ?? 0) / maxPerVisit) * 100),
    Math.round((r.visits / maxVisits) * 100),
    Math.round((r.utilization ?? 0) * 100),
    Math.round((1 - (r.no_show_rate ?? 0)) * 100),
  ]
  const axes = ['Revenue', 'Revenue per visit', 'Visits', 'Utilization', 'Kept appointments']
  return {
    option: themed({
      tooltip: {},
      legend: { bottom: 0, top: undefined, type: 'scroll' },
      radar: {
        indicator: axes.map((name) => ({ name, max: 100 })),
        radius: '62%',
        center: ['50%', '46%'],
      },
      series: [{ type: 'radar', data: rows.map((r) => ({ name: r.dentist, value: score(r) })) }],
    }),
    table: {
      columns: ['Dentist', ...axes],
      rows: rows.map((r) => [r.dentist, ...score(r).map((v) => `${v}`)]),
    },
  }
}

export function serviceScatter(data: ServiceTrends): Built {
  const rows = data.rows.filter((r) => r.revenue_per_hour != null && r.visits > 0)
  const maxBilled = Math.max(...rows.map((r) => n(r.billed)), 1)
  return {
    option: themed({
      tooltip: {
        formatter: (p: { data: [number, number, number, string] }) =>
          `${p.data[3]}: ${p.data[0]} visits, ${money(p.data[1])} per chair hour, ${money(p.data[2])} billed`,
      },
      legend: { show: false },
      xAxis: valueAxis(undefined, { name: 'Visits', nameLocation: 'middle', nameGap: 26 }),
      yAxis: valueAxis(compactMoney, { name: 'Revenue per chair hour', scale: true }),
      series: [
        {
          type: 'scatter',
          data: rows.map((r) => [r.visits, r.revenue_per_hour ?? 0, n(r.billed), r.label]),
          symbolSize: (v: number[]) => 10 + Math.sqrt((v[2] ?? 0) / maxBilled) * 34,
          itemStyle: { opacity: 0.75 },
        },
      ],
    }),
    table: {
      columns: ['Service', 'Visits', 'Revenue per chair hour', 'Billed'],
      rows: rows.map((r) => [r.label, r.visits, money(r.revenue_per_hour ?? 0), money(r.billed)]),
    },
  }
}

// --- finance ----------------------------------------------------------------------------------------------------------

export function agingBars(data: ArAging): Built {
  const labels = data.buckets.map((b) => b.label)
  return {
    option: themed({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        valueFormatter: (v: number) => money(v),
      },
      xAxis: categoryAxis(labels),
      yAxis: valueAxis(compactMoney),
      series: [
        {
          name: 'Insurers owe',
          type: 'bar',
          stack: 'ar',
          data: data.buckets.map((b) => n(b.insurer)),
        },
        {
          name: 'Patients owe',
          type: 'bar',
          stack: 'ar',
          data: data.buckets.map((b) => n(b.patient)),
        },
      ],
    }),
    table: {
      columns: ['Age of invoice', 'Invoices', 'Insurers owe', 'Patients owe', 'Total'],
      rows: data.buckets.map((b) => [
        b.label,
        b.invoices,
        money(b.insurer),
        money(b.patient),
        money(b.total),
      ]),
    },
  }
}

export function collectionLine(data: Collection): Built {
  const labels = data.points.map((p) => periodLabel(p.period, data.meta.granularity))
  return {
    option: themed({
      tooltip: {
        trigger: 'axis',
        valueFormatter: (v: number | null) => (v == null ? '' : `${v}%`),
      },
      legend: { show: false },
      xAxis: categoryAxis(labels),
      yAxis: valueAxis((v) => `${v}%`, { max: 100, min: 0 }),
      series: [
        {
          name: 'Collected so far',
          type: 'line',
          data: data.points.map((p) => pct(p.rate)),
          symbol: 'circle',
          areaStyle: { opacity: 0.1 },
        },
      ],
    }),
    table: {
      columns: ['Period', 'Billed', 'Collected so far', 'Rate'],
      rows: data.points.map((p, i) => [
        labels[i] ?? '',
        money(p.billed),
        money(p.collected_to_date),
        percent(p.rate),
      ]),
    },
  }
}

export function paymentsByPayer(patient: RevenueTrend, insurer: RevenueTrend): Built {
  const periods = [...new Set([...patient.points, ...insurer.points].map((p) => p.period))].sort()
  const labels = periods.map((p) => periodLabel(p, patient.meta.granularity))
  const at = (t: RevenueTrend, period: string) =>
    n(t.points.find((p) => p.period === period)?.collected ?? 0)
  return {
    option: themed({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        valueFormatter: (v: number) => money(v),
      },
      xAxis: categoryAxis(labels),
      yAxis: valueAxis(compactMoney),
      series: [
        {
          name: 'From patients',
          type: 'bar',
          stack: 'pay',
          data: periods.map((p) => at(patient, p)),
        },
        {
          name: 'From insurers',
          type: 'bar',
          stack: 'pay',
          data: periods.map((p) => at(insurer, p)),
        },
      ],
    }),
    table: {
      columns: ['Period', 'From patients', 'From insurers'],
      rows: periods.map((p, i) => [labels[i] ?? '', money(at(patient, p)), money(at(insurer, p))]),
    },
  }
}

// --- assistant ---------------------------------------------------------------------------------------------------------

export function chatDaily(data: Chatbot): Built {
  const labels = data.days.map((d) => periodLabel(d.day, 'day'))
  return {
    option: themed({
      tooltip: { trigger: 'axis' },
      xAxis: categoryAxis(labels),
      yAxis: [valueAxis(), valueAxis((v) => `${v}%`, { max: 100, splitLine: { show: false } })],
      series: [
        {
          name: 'Conversations',
          type: 'bar',
          data: data.days.map((d) => d.conversations),
          barMaxWidth: 20,
        },
        {
          name: 'Answered without a model',
          type: 'line',
          yAxisIndex: 1,
          symbol: 'none',
          data: data.days.map((d) =>
            d.turns ? Math.round((d.zero_llm_turns / d.turns) * 1000) / 10 : null,
          ),
        },
      ],
    }),
    table: {
      columns: ['Day', 'Conversations', 'Turns', 'Answered without a model'],
      rows: data.days.map((d, i) => [
        labels[i] ?? '',
        d.conversations,
        d.turns,
        percent(d.turns ? d.zero_llm_turns / d.turns : null),
      ]),
    },
  }
}

export function bookingFunnel(data: Chatbot): Built {
  const steps = [
    { name: 'Started booking', value: data.booking_started },
    { name: 'Chose a time', value: data.booking_slot_chosen },
    { name: 'Confirmed', value: data.booking_confirmed },
  ]
  return {
    option: themed({
      tooltip: { trigger: 'item' },
      legend: { show: false },
      series: [
        {
          type: 'funnel',
          left: '10%',
          width: '80%',
          top: 8,
          bottom: 8,
          sort: 'none',
          label: { formatter: '{b}: {c}' },
          data: steps,
        },
      ],
    }),
    table: {
      columns: ['Stage', 'Conversations', 'Share of started'],
      rows: steps.map((s) => [
        s.name,
        s.value,
        percent(data.booking_started ? s.value / data.booking_started : null),
      ]),
    },
  }
}

export function providerDonut(data: Chatbot): Built {
  return {
    option: themed({
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, top: undefined },
      series: [
        {
          type: 'pie',
          radius: ['45%', '72%'],
          center: ['50%', '45%'],
          label: { formatter: '{b}: {d}%' },
          data: data.providers.map((p) => ({ name: p.provider, value: p.tokens })),
        },
      ],
    }),
    table: {
      columns: ['Provider', 'Calls', 'Tokens', 'Failovers'],
      rows: data.providers.map((p) => [p.provider, p.calls, integer(p.tokens), p.failovers]),
    },
  }
}

export function tokensVsLimit(data: Chatbot, dailyLimit: number | null): Built {
  const labels = data.days.map((d) => periodLabel(d.day, 'day'))
  return {
    option: themed({
      tooltip: { trigger: 'axis', valueFormatter: (v: number) => integer(v) },
      legend: { show: false },
      xAxis: categoryAxis(labels),
      yAxis: valueAxis((v) => (v >= 1000 ? `${v / 1000}k` : `${v}`)),
      series: [
        {
          name: 'Tokens',
          type: 'line',
          data: data.days.map((d) => d.tokens),
          symbol: 'none',
          areaStyle: { opacity: 0.12 },
          markLine: dailyLimit
            ? {
                symbol: 'none',
                lineStyle: { color: BAD, type: 'dashed' },
                label: { formatter: 'Daily limit' },
                data: [{ yAxis: dailyLimit }],
              }
            : undefined,
        },
      ],
    }),
    table: {
      columns: ['Day', 'Tokens', 'Daily limit'],
      rows: data.days.map((d, i) => [
        labels[i] ?? '',
        integer(d.tokens),
        dailyLimit ? integer(dailyLimit) : 'None set',
      ]),
    },
  }
}
