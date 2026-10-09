import * as React from 'react'
import { useSearchParams } from 'react-router-dom'

import { clinicToday } from '@/console/time'
import { addDays, addMonths, startOfMonth, type DateString } from '@/lib/dates'

export type Preset = '30d' | 'qtd' | 'ytd' | '12m' | '24m' | 'custom'
export type Granularity = 'day' | 'week' | 'month' | 'quarter'
export type Compare = 'none' | 'previous' | 'year'
export type Payer = '' | 'patient' | 'insurer'

export const presets: { value: Preset; label: string }[] = [
  { value: '30d', label: 'Last 30 days' },
  { value: 'qtd', label: 'Quarter to date' },
  { value: 'ytd', label: 'Year to date' },
  { value: '12m', label: 'Last 12 months' },
  { value: '24m', label: 'Last 24 months' },
  { value: 'custom', label: 'Custom range' },
]

export interface Filters {
  preset: Preset
  from: DateString
  to: DateString
  granularity: Granularity
  compare: Compare
  dentist: string
  service: string
  payer: Payer
}

/** Figures are complete up to yesterday, so a range ends then. */
export const lastFullDay = (): DateString => addDays(clinicToday(), -1)

export function presetRange(preset: Exclude<Preset, 'custom'>, end = lastFullDay()) {
  const [y = 1970, m = 1] = end.split('-').map(Number)
  const quarterStart = `${y}-${String(Math.floor((m - 1) / 3) * 3 + 1).padStart(2, '0')}-01`
  const from: Record<typeof preset, DateString> = {
    '30d': addDays(end, -29),
    qtd: quarterStart,
    ytd: `${y}-01-01`,
    '12m': addDays(addMonths(startOfMonth(end), -11), 0),
    '24m': addDays(addMonths(startOfMonth(end), -23), 0),
  }
  return { from: from[preset], to: end }
}

/** A sensible bucket size for how much time is shown. */
export function defaultGranularity(from: DateString, to: DateString): Granularity {
  const days = (new Date(to).getTime() - new Date(from).getTime()) / 86_400_000 + 1
  if (days <= 45) return 'day'
  if (days <= 200) return 'week'
  return 'month'
}

const PRESET_VALUES = presets.map((p) => p.value)
const GRANULARITIES: Granularity[] = ['day', 'week', 'month', 'quarter']
const date = /^\d{4}-\d{2}-\d{2}$/

/** The filters live in the address, so a view can be shared and the back button works. */
export function useFilters(): [Filters, (changes: Partial<Filters>) => void] {
  const [params, setParams] = useSearchParams()
  const raw = params.get('range') as Preset | null
  const preset: Preset = raw && PRESET_VALUES.includes(raw) ? raw : '12m'
  const fromParam = params.get('from')
  const toParam = params.get('to')

  const filters = React.useMemo<Filters>(() => {
    const range =
      preset === 'custom' && fromParam && toParam && date.test(fromParam) && date.test(toParam)
        ? { from: fromParam, to: toParam }
        : presetRange(preset === 'custom' ? '12m' : preset)
    const g = params.get('by') as Granularity | null
    const compare = params.get('compare') as Compare | null
    const payer = params.get('payer') as Payer | null
    return {
      preset: preset === 'custom' && range.from !== fromParam ? '12m' : preset,
      ...range,
      granularity: g && GRANULARITIES.includes(g) ? g : defaultGranularity(range.from, range.to),
      compare: compare && ['none', 'previous', 'year'].includes(compare) ? compare : 'previous',
      dentist: params.get('dentist') ?? '',
      service: params.get('service') ?? '',
      payer: payer === 'patient' || payer === 'insurer' ? payer : '',
    }
  }, [params, preset, fromParam, toParam])

  const update = React.useCallback(
    (changes: Partial<Filters>) => {
      setParams(
        (current) => {
          const next = new URLSearchParams(current)
          const set = (key: string, value: string | undefined, fallback = '') => {
            if (value === undefined || value === fallback) next.delete(key)
            else next.set(key, value)
          }
          if ('preset' in changes) {
            set('range', changes.preset, '12m')
            if (changes.preset !== 'custom') {
              next.delete('from')
              next.delete('to')
              next.delete('by')
            }
          }
          if ('from' in changes) next.set('from', changes.from ?? '')
          if ('to' in changes) next.set('to', changes.to ?? '')
          if ('from' in changes || 'to' in changes) next.set('range', 'custom')
          if ('granularity' in changes) set('by', changes.granularity)
          if ('compare' in changes) set('compare', changes.compare, 'previous')
          if ('dentist' in changes) set('dentist', changes.dentist)
          if ('service' in changes) set('service', changes.service)
          if ('payer' in changes) set('payer', changes.payer)
          return next
        },
        { replace: true },
      )
    },
    [setParams],
  )
  return [filters, update]
}

/** The same range one year earlier, for "same period last year". */
export const lastYear = (f: Pick<Filters, 'from' | 'to'>) => ({
  from: addDays(f.from, -365),
  to: addDays(f.to, -365),
})
