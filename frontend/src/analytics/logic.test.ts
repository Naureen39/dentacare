import { describe, expect, it } from 'vitest'

import type {
  Forecast,
  Kpi,
  RevenueTrend,
  ServiceTrends,
  StatusTrend,
  Summary,
} from '@/analytics/api'
import { defaultGranularity, lastYear, presetRange } from '@/analytics/filters'
import { formatKpi, lastDayOfMonth, periodLabel } from '@/analytics/format'
import { change, insights, priceVolumeMix, targetProgress } from '@/analytics/insights'
import {
  cohortHeatmap,
  payerMix,
  revenueCombo,
  revenuePerVisit,
  waterfall,
  weekdayBars,
} from '@/analytics/options'

const meta = (granularity = 'month') =>
  ({
    date_from: '2026-01-01',
    date_to: '2026-03-31',
    granularity,
    data_as_of: null,
    cached: false,
  }) as RevenueTrend['meta']

const service = (key: string, invoices: number, billed: number) =>
  ({
    key,
    label: key,
    category: 'x',
    billed: String(billed),
    collected: '0',
    invoices,
    visits: 0,
    minutes: 0,
    revenue_per_hour: null,
    series: [],
  }) as ServiceTrends['rows'][number]

describe('price, volume and mix', () => {
  it('adds up exactly to the change in revenue', () => {
    const before = [service('a', 10, 1000), service('b', 5, 1500)]
    const after = [service('a', 14, 1540), service('b', 4, 1280), service('c', 2, 300)]
    const s = priceVolumeMix(before, after)
    expect(s.start).toBe(2500)
    expect(s.end).toBe(3120)
    expect(s.volume + s.mix + s.price).toBeCloseTo(s.end - s.start, 6)
  })

  it('puts a pure price rise in the price step', () => {
    const s = priceVolumeMix([service('a', 10, 1000)], [service('a', 10, 1200)])
    expect(s.volume).toBeCloseTo(0)
    expect(s.mix).toBeCloseTo(0)
    expect(s.price).toBeCloseTo(200)
  })

  it('puts more invoices of the same kind in the volume step', () => {
    const s = priceVolumeMix([service('a', 10, 1000)], [service('a', 15, 1500)])
    expect(s.volume).toBeCloseTo(500)
    expect(s.mix).toBeCloseTo(0)
    expect(s.price).toBeCloseTo(0)
  })

  it('shows a move to dearer services as mix', () => {
    const s = priceVolumeMix(
      [service('a', 10, 1000), service('b', 10, 3000)],
      [service('a', 5, 500), service('b', 15, 4500)],
    )
    expect(s.volume).toBeCloseTo(0)
    expect(s.mix).toBeCloseTo(1000)
    expect(s.price).toBeCloseTo(0)
  })

  it('treats everything as volume when there was nothing before', () => {
    expect(priceVolumeMix([], [service('a', 3, 300)])).toMatchObject({
      start: 0,
      volume: 300,
      mix: 0,
      price: 0,
      end: 300,
    })
  })
})

describe('chart options', () => {
  const trend = {
    meta: meta(),
    points: [
      {
        period: '2026-01-01',
        billed: '1000',
        collected: '800',
        prior_year_billed: '900',
        prior_year_collected: '700',
      },
      {
        period: '2026-02-01',
        billed: '1200',
        collected: '1100',
        prior_year_billed: '950',
        prior_year_collected: '800',
      },
    ],
  } as RevenueTrend
  const forecast = {
    meta: meta(),
    method: 'holt_winters',
    method_note: '',
    interval_level: 0.8,
    history: [],
    forecast: [
      { month: '2026-03-01', value: 1300, lower: 1100, upper: 1500 },
      { month: '2026-04-01', value: 1350, lower: 1100, upper: 1600 },
    ],
  } as Forecast

  it('draws the values the server sent, in order', () => {
    const { option, table } = revenueCombo(trend, undefined, false)
    const series = (option as { series: { name: string; data: (number | null)[] }[] }).series
    expect(series.map((s) => s.name)).toEqual(['Collected', 'Billed'])
    expect(series[0]?.data).toEqual([800, 1100])
    expect(series[1]?.data).toEqual([1000, 1200])
    expect(table.rows).toHaveLength(2)
    expect(table.columns).toEqual(['Period', 'Collected', 'Billed'])
  })

  it('adds the prior year and the forecast with its range only when asked', () => {
    const { option, table } = revenueCombo(trend, forecast, true)
    const o = option as {
      xAxis: { data: string[] }
      series: { name: string; data: (number | null)[] }[]
    }
    expect(o.xAxis.data).toHaveLength(4)
    expect(o.series.map((s) => s.name)).toContain('Billed, a year earlier')
    const line = o.series.find((s) => s.name === 'Forecast')
    expect(line?.data).toEqual([null, 1100, 1300, 1350])
    const band = o.series.find((s) => s.name.startsWith('Likely range'))
    expect(band?.data.slice(2)).toEqual([400, 500])
    expect(table.rows.at(-1)).toContain('$1,350')
  })

  it('ignores a forecast that is not monthly', () => {
    const weekly = { ...trend, meta: meta('week') } as RevenueTrend
    const { option } = revenueCombo(weekly, forecast, false)
    expect((option as { series: unknown[] }).series).toHaveLength(2)
  })

  it('builds a waterfall whose steps start where the last one ended', () => {
    const { option } = waterfall([
      { name: 'Start', value: 1000, total: true },
      { name: 'Up', value: 300 },
      { name: 'Down', value: -100 },
      { name: 'End', value: 1200, total: true },
    ])
    const s = (option as { series: { name: string; data: (number | null)[] }[] }).series
    const get = (name: string) => s.find((x) => x.name === name)?.data
    expect(get('Base')).toEqual([0, 1000, 1200, 0])
    expect(get('Increase')).toEqual([null, 300, null, null])
    expect(get('Decrease')).toEqual([null, null, 100, null])
    expect(get('Total')).toEqual([1000, null, null, 1200])
  })

  it('makes the payer shares add up to one hundred', () => {
    const patient = {
      meta: meta(),
      points: [
        {
          period: '2026-01-01',
          billed: '300',
          collected: '0',
          prior_year_billed: '0',
          prior_year_collected: '0',
        },
      ],
    } as RevenueTrend
    const insurer = {
      meta: meta(),
      points: [
        {
          period: '2026-01-01',
          billed: '700',
          collected: '0',
          prior_year_billed: '0',
          prior_year_collected: '0',
        },
      ],
    } as RevenueTrend
    const { option } = payerMix(patient, insurer)
    const data = (option as { series: { data: number[] }[] }).series.map((s) => s.data[0])
    expect(data).toEqual([30, 70])
  })

  it('divides billed revenue by completed visits and says so when there were none', () => {
    const status = {
      meta: meta(),
      points: [
        { period: '2026-01-01', completed: 4 },
        { period: '2026-02-01', completed: 0 },
      ],
    } as StatusTrend
    const { option, table } = revenuePerVisit(trend, status)
    expect((option as { series: { data: (number | null)[] }[] }).series[0]?.data).toEqual([
      250,
      null,
    ])
    expect(table.rows[1]?.[1]).toBe('No visits')
  })

  it('leaves out cohort cells that have not happened yet', () => {
    const { option } = cohortHeatmap({
      meta: meta(),
      cohorts: [
        {
          cohort_month: '2026-01-01',
          cohort_size: 10,
          retention: [1, 0.5, null, null],
          returned_within_6_months: null,
        },
      ],
      six_month_retention: null,
      mature_cohorts: 0,
    } as never)
    const cells = (option as { series: { data: number[][] }[] }).series[0]?.data
    expect(cells).toEqual([
      [0, 0, 100],
      [1, 0, 50],
    ])
  })

  it('shows the average billed on each kind of day', () => {
    const rows = Array.from({ length: 7 }, (_, weekday) => ({
      weekday,
      billed: String(weekday === 0 ? 1000 : 0),
      collected: '0',
      invoices: 0,
      days: weekday === 0 ? 4 : 0,
    }))
    const { option } = weekdayBars({ meta: meta(), rows } as never)
    expect((option as { series: { data: number[] }[] }).series[0]?.data[0]).toBe(250)
  })
})

describe('filters and formatting', () => {
  it('works out the presets from the last full day', () => {
    expect(presetRange('30d', '2026-06-30')).toEqual({ from: '2026-06-01', to: '2026-06-30' })
    expect(presetRange('qtd', '2026-06-30')).toEqual({ from: '2026-04-01', to: '2026-06-30' })
    expect(presetRange('ytd', '2026-06-30')).toEqual({ from: '2026-01-01', to: '2026-06-30' })
    expect(presetRange('12m', '2026-06-30').from).toBe('2025-07-01')
    expect(presetRange('24m', '2026-06-30').from).toBe('2024-07-01')
  })

  it('picks a bucket size from the length of the range', () => {
    expect(defaultGranularity('2026-06-01', '2026-06-30')).toBe('day')
    expect(defaultGranularity('2026-01-01', '2026-06-30')).toBe('week')
    expect(defaultGranularity('2025-01-01', '2026-06-30')).toBe('month')
  })

  it('shifts a range back a year', () => {
    expect(lastYear({ from: '2026-01-01', to: '2026-01-31' })).toEqual({
      from: '2025-01-01',
      to: '2025-01-31',
    })
  })

  it('writes figures the way their unit asks', () => {
    expect(formatKpi('usd', 12345.6)).toBe('$12,346')
    expect(formatKpi('percent', 0.1234)).toBe('12.3%')
    expect(formatKpi('count', 1234)).toBe('1,234')
    expect(formatKpi('days', 3.456)).toBe('3.5 days')
    expect(formatKpi('usd', null)).toBe('No data')
    expect(periodLabel('2026-03-01', 'quarter')).toBe('Q1 26')
    expect(lastDayOfMonth('2026-02-10')).toBe('2026-02-28')
    expect(lastDayOfMonth('2028-02-10')).toBe('2028-02-29')
    expect(lastDayOfMonth('2026-12-05')).toBe('2026-12-31')
  })
})

describe('comparisons and insights', () => {
  const kpi = (over: Partial<Kpi>): Kpi => ({
    key: 'collected',
    label: 'Collected revenue',
    unit: 'usd',
    value: 110,
    previous: 100,
    change_percent: 10,
    change_kind: 'relative',
    higher_is_better: true,
    sparkline: [],
    ...over,
  })
  const summary = (kpis: Kpi[]) =>
    ({ meta: meta(), previous_from: '', previous_to: '', kpis }) as Summary

  it('uses the server change for the previous period and works out the year change itself', () => {
    expect(change(kpi({}), 'previous', undefined)).toEqual({ value: 10, unit: '%' })
    expect(change(kpi({}), 'none', undefined).value).toBeUndefined()
    expect(change(kpi({}), 'year', summary([kpi({ value: 80 })])).value).toBeCloseTo(37.5)
    const rate = kpi({ key: 'no_show_rate', unit: 'percent', value: 0.08, change_kind: 'points' })
    expect(
      change(
        rate,
        'year',
        summary([
          kpi({ key: 'no_show_rate', unit: 'percent', value: 0.05, change_kind: 'points' }),
        ]),
      ),
    ).toEqual({ value: expect.closeTo(3, 5), unit: ' points' })
    expect(change(kpi({}), 'year', undefined).value).toBeNull()
  })

  it('writes the biggest movements first and flags the bad ones', () => {
    const notes = insights(
      summary([
        kpi({ change_percent: 12 }),
        kpi({
          key: 'no_show_rate',
          label: 'No show rate',
          unit: 'percent',
          value: 0.09,
          change_kind: 'points',
          change_percent: 2.1,
          higher_is_better: false,
        }),
        kpi({ key: 'completed', label: 'Completed visits', change_percent: 1 }),
      ]),
    )
    // The twelve percent rise outranks a 2.1 point change, and the bad one is flagged.
    expect(notes[0]).toBe('Collected revenue rose 12 percent compared with the previous period.')
    expect(notes).toContain(
      'No show rate rose 2.1 points compared with the previous period. That needs attention.',
    )
    expect(notes.some((n) => n.startsWith('Completed visits'))).toBe(false)
  })

  it('warns about low utilization and weak collection', () => {
    const notes = insights(
      summary([
        kpi({
          key: 'utilization',
          label: 'Utilization',
          unit: 'percent',
          value: 0.5,
          change_percent: null,
        }),
        kpi({
          key: 'collection_rate',
          label: 'Collection rate',
          unit: 'percent',
          value: 0.8,
          change_percent: null,
        }),
      ]),
    )
    expect(notes).toHaveLength(2)
    expect(notes.join(' ')).toMatch(/room for more bookings/)
    expect(notes.join(' ')).toMatch(/80.0% of billed revenue/)
  })

  it('measures the year to date against the target for the days gone', () => {
    const half = targetProgress(10_000, 50_000, new Date(2026, 5, 15)) // half way through June
    expect(half.target).toBeCloseTo(10_000 * (5 + 15 / 30))
    expect(half.ratio).toBeCloseTo(50_000 / half.target)
    expect(targetProgress(0, 100, new Date(2026, 0, 10)).ratio).toBeNull()
  })
})
