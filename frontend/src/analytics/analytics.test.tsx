import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { axe } from 'vitest-axe'

import { runtime } from '@/analytics/runtime'
import { tokenStore } from '@/lib/api-client'
import { analyticsApi, forecast, meta, summary, trend } from '@/test/analytics-fixtures'
import { RAMAN } from '@/test/booking-fixtures'
import { json, mockApi, renderApp } from '@/test/utils'

interface Drawn {
  el: HTMLElement
  options: Record<string, unknown>[]
}

// The real charts need a canvas, which the test browser does not have. This stand in records what
// each chart was asked to draw, so the tests can check the numbers that reach the picture.
const registry: Drawn[] = []
runtime.load = async () =>
  ({
    init: (el: HTMLElement) => {
      const drawn: Drawn = { el, options: [] }
      registry.push(drawn)
      return {
        setOption: (option: Record<string, unknown>) => drawn.options.push(option),
        resize: () => undefined,
        dispose: () => undefined,
        getDataURL: () => 'data:image/png;base64,AAAA',
      }
    },
  }) as never

const charts = () => registry
const slow = { timeout: 10_000 }

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.set(null)
  charts().length = 0
})

/** What the chart inside the figure with this title was last asked to draw. */
async function drawn(title: string) {
  const figure = await screen.findByRole('figure', { name: title }, slow)
  let found: Drawn | undefined
  await waitFor(() => {
    found = charts()
      .filter((c) => figure.contains(c.el) && c.options.length > 0)
      .at(-1)
    expect(found).toBeDefined()
  })
  return {
    figure,
    option: found?.options.at(-1) as { series: { name?: string; data: unknown[] }[] } & Record<
      string,
      unknown
    >,
  }
}

const open = (path = '/admin/analytics', role: 'admin' | 'receptionist' = 'admin') => {
  const api = mockApi(analyticsApi(role))
  renderApp(path, { hasSession: true })
  return api
}

describe('overview', () => {
  it('shows the six headline figures with their change and sends the filters in the request', async () => {
    const { calls } = open()
    const cards = await screen.findByRole('region', { name: 'Key figures' }, slow)
    for (const label of [
      'Collected revenue',
      'Gross billed revenue',
      'Completed visits',
      'Utilization',
      'No show rate',
      'New patients',
    ])
      expect(await within(cards).findByText(label)).toBeInTheDocument()
    expect(within(cards).queryByText('Collection rate')).not.toBeInTheDocument()
    expect(within(cards).getByText('+10.0%')).toBeInTheDocument()
    const request = calls.find((c) => c.path.startsWith('/analytics/summary'))
    const q = new URLSearchParams(request?.path.split('?')[1])
    expect(q.get('granularity')).toBe('month')
    expect(q.get('from') && q.get('to')).toBeTruthy()
  })

  it('draws the revenue the server sent plus the forecast months', async () => {
    open()
    const { option } = await drawn('Revenue over time')
    const bars = option.series.find((s) => s.name === 'Collected')
    expect(bars?.data.slice(0, 3)).toEqual(trend.points.map((p) => Number(p.collected)))
    const line = option.series.find((s) => s.name === 'Forecast')
    expect(line?.data.slice(-3)).toEqual(forecast.forecast.map((f) => f.value))
  })

  it('shows the same numbers as a table on request', async () => {
    const user = userEvent.setup()
    open()
    const figure = await screen.findByRole('figure', { name: 'Revenue over time' }, slow)
    await user.click(within(figure).getByRole('button', { name: 'Show data' }))
    const table = within(figure).getByRole('table', { name: 'Revenue over time' })
    expect(within(table).getAllByRole('row').length).toBeGreaterThan(3)
    expect(within(table).getAllByText('$9,900').length).toBeGreaterThan(0)
  })

  it('lists observations and ranks the types of care', async () => {
    open()
    const notes = await screen.findByRole('region', { name: 'Insights' }, slow)
    expect(await within(notes).findByText(/Utilization fell 5.0 points/)).toBeInTheDocument()
    expect(within(notes).getByText(/Only 88.0% of billed revenue/)).toBeInTheDocument()
    expect(within(notes).getAllByRole('listitem')).toHaveLength(5)
    const ranked = await screen.findByRole('list', { name: 'Ranked categories' })
    expect(
      within(ranked)
        .getAllByRole('listitem')
        .map((li) => li.textContent),
    ).toEqual(['Restorative$50,000', 'Preventive$30,000'])
  })

  it('shows a badge when the figures are out of date and refreshes on request', async () => {
    const user = userEvent.setup()
    const old = new Date(Date.now() - 72 * 3_600_000).toISOString()
    const { calls } = (() => {
      const api = mockApi(
        analyticsApi('admin', { 'GET /analytics/summary*': () => json(summary(1, old)) }),
      )
      renderApp('/admin/analytics', { hasSession: true })
      return api
    })()
    expect(await screen.findByText('Out of date', undefined, slow)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Refresh figures/ }))
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.path === '/analytics/refresh')).toBe(true),
    )
    expect(meta(old).data_as_of).toBe(old)
  })
})

describe('filters', () => {
  it('keeps the filters in the address and sends them with every figure', async () => {
    const user = userEvent.setup()
    const { calls } = open('/admin/analytics/revenue?range=ytd&dentist=' + RAMAN.id)
    await screen.findByRole('heading', { name: 'Analytics' }, slow)
    await waitFor(() =>
      expect(calls.some((c) => c.path.startsWith('/analytics/revenue/by-weekday'))).toBe(true),
    )
    const weekday = calls.find((c) => c.path.startsWith('/analytics/revenue/by-weekday'))
    const q = new URLSearchParams(weekday?.path.split('?')[1])
    expect(q.get('dentist_id')).toBe(RAMAN.id)
    expect(q.get('from')).toMatch(/-01-01$/)
    expect(screen.getByLabelText('Date range')).toHaveValue('ytd')
    expect(screen.getByLabelText('Dentist')).toHaveValue(RAMAN.id)

    await user.selectOptions(screen.getByLabelText('Paid by'), 'insurer')
    await waitFor(() => expect(calls.some((c) => c.path.includes('payer_type=insurer'))).toBe(true))
  })

  it('changes the grouping and asks again', async () => {
    const user = userEvent.setup()
    const { calls } = open('/admin/analytics/overview')
    await screen.findByRole('region', { name: 'Key figures' }, slow)
    await user.click(screen.getByRole('button', { name: 'week' }))
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.path.startsWith('/analytics/revenue/trend') && c.path.includes('granularity=week'),
        ),
      ).toBe(true),
    )
    expect(screen.getByRole('button', { name: 'week' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('asks for the same period a year earlier when that comparison is chosen', async () => {
    const user = userEvent.setup()
    const { calls } = open('/admin/analytics/overview')
    await screen.findByRole('region', { name: 'Key figures' }, slow)
    await user.selectOptions(screen.getByLabelText('Compare with'), 'year')
    await waitFor(() => {
      const summaries = calls.filter((c) => c.path.startsWith('/analytics/summary'))
      const years = summaries.map((c) => new URLSearchParams(c.path.split('?')[1]).get('from'))
      expect(new Set(years).size).toBeGreaterThan(1)
    })
    expect(await screen.findAllByText(/A year earlier:/)).not.toHaveLength(0)
  })

  it('accepts a custom range', async () => {
    const user = userEvent.setup()
    const { calls } = open('/admin/analytics/overview')
    await screen.findByRole('region', { name: 'Key figures' }, slow)
    await user.selectOptions(screen.getByLabelText('Date range'), 'custom')
    fireEvent.change(await screen.findByLabelText('From'), { target: { value: '2026-01-05' } })
    await waitFor(() => expect(calls.some((c) => c.path.includes('from=2026-01-05'))).toBe(true))
  })
})

describe('tabs', () => {
  it('lists every section and moves between them keeping the filters', async () => {
    const user = userEvent.setup()
    open('/admin/analytics/overview?range=qtd')
    const nav = await screen.findByRole('navigation', { name: 'Analytics sections' }, slow)
    expect(
      within(nav)
        .getAllByRole('link')
        .map((a) => a.textContent),
    ).toEqual([
      'Overview',
      'Revenue',
      'Appointments',
      'Patients',
      'Dentists and services',
      'Finance',
      'Assistant',
    ])
    await user.click(within(nav).getByRole('link', { name: 'Finance' }))
    expect(await screen.findByRole('region', { name: 'Receivables' }, slow)).toBeInTheDocument()
    expect(screen.getByLabelText('Date range')).toHaveValue('qtd')
  })

  it('revenue: compares two months and shows a waterfall that starts and ends on the months', async () => {
    open('/admin/analytics/revenue')
    const { option } = await drawn('What changed since last month')
    const total = option.series.find((s) => s.name === 'Total')
    expect(total?.data.filter((v) => v != null)).toHaveLength(2)
    expect(
      await screen.findByRole(
        'progressbar',
        { name: /Year to date collected against target/ },
        slow,
      ),
    ).toBeInTheDocument()
    expect(await screen.findByRole('table', { name: /Top ten services/ })).toBeInTheDocument()
  })

  it('appointments: sends a reminder to a patient the model flags', async () => {
    const user = userEvent.setup()
    const { calls } = (() => {
      const api = mockApi(
        analyticsApi('admin', {
          'POST /staff/appointments/30000000-0000-4000-8000-0000000000aa/remind': {
            status: 200,
            body: { message: 'The reminder email was sent.' },
          },
        }),
      )
      renderApp('/admin/analytics/appointments', { hasSession: true })
      return api
    })()
    await user.click(
      await screen.findByRole('button', { name: /Send reminder.*Jonas Weber/ }, slow),
    )
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/remind'))).toBe(true))
    expect(await screen.findByRole('button', { name: /Sent.*Jonas Weber/ })).toBeDisabled()
    const heat = await drawn('Busiest days and hours')
    expect((heat.option.series[0]?.data as number[][]).length).toBe(2)
  })

  it('patients: shows full names to an administrator', async () => {
    open('/admin/analytics/patients')
    expect(await screen.findByText('Jonas Weber', undefined, slow)).toBeInTheDocument()
    expect(screen.queryByText(/shown as initials/)).not.toBeInTheDocument()
    const growth = await drawn('Practice growth')
    expect(growth.option.series[0]?.data).toEqual([10, 30, 60])
  })

  it('dentists: ranks dentists and compares services', async () => {
    open('/admin/analytics/dentists')
    const board = await screen.findByRole('table', { name: /Dentists by billed revenue/ }, slow)
    expect(await within(board).findByText(RAMAN.full_name)).toBeInTheDocument()
    expect(within(board).getAllByRole('row')[1]).toHaveTextContent(RAMAN.full_name)
    const util = await drawn('Chair time used')
    expect(util.option.series[0]?.data).toEqual([80, 50])
  })

  it('finance: shows days to collect, receivables and open invoices', async () => {
    open('/admin/analytics/finance')
    const cards = await screen.findByRole('region', { name: 'Receivables' }, slow)
    expect(await within(cards).findByText('21.4 days')).toBeInTheDocument()
    expect(within(cards).getByText('$3,000')).toBeInTheDocument()
    const aging = await drawn('Who owes, and for how long')
    expect(aging.option.series[0]?.data).toEqual([1000, 800, 100, 0])
  })

  it('assistant: shows conversion, tokens against the limit and the questions to improve', async () => {
    open('/admin/analytics/chatbot')
    const cards = await screen.findByRole('region', { name: 'Assistant figures' }, slow)
    expect(await within(cards).findByText('62.5%')).toBeInTheDocument()
    expect(await screen.findByText('do you take [email] insurance')).toBeInTheDocument()
    const tokens = await drawn('Tokens used each day')
    expect(JSON.stringify(tokens.option)).toContain('100000')
  })

  it('exports the table behind the current tab', async () => {
    const user = userEvent.setup()
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    const { calls } = open('/admin/analytics/finance')
    await screen.findByRole('region', { name: 'Receivables' }, slow)
    await user.click(screen.getByRole('button', { name: /Export CSV/ }))
    await user.click(screen.getByRole('menuitem', { name: 'Collection rate' }))
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled())
    expect(calls.find((c) => c.path.startsWith('/analytics/export/csv'))?.path).toContain(
      'dataset=collection',
    )
  })
})

describe('access and accessibility', () => {
  it('keeps the page from anyone but an administrator', async () => {
    open('/admin/analytics', 'receptionist')
    expect(
      await screen.findByRole('heading', { name: /do not have access/i }, slow),
    ).toBeInTheDocument()
  })

  it('has no detectable accessibility problems on the overview and a table tab', async () => {
    mockApi(analyticsApi())
    const { container } = renderApp('/admin/analytics/overview', { hasSession: true })
    await screen.findByRole('region', { name: 'Key figures' }, slow)
    await drawn('Revenue over time')
    const rules = { rules: { 'color-contrast': { enabled: false } } }
    expect(await axe(container, rules)).toHaveNoViolations()
  })
})
