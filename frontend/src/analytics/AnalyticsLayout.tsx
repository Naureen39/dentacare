import { Download, RefreshCw } from 'lucide-react'
import * as React from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { fetchCsv, useRefreshViews, useSummary } from '@/analytics/api'
import { tabs, type AnalyticsContext } from '@/analytics/context'
import { isStale } from '@/analytics/format'
import {
  presets,
  useFilters,
  type Compare,
  type Filters,
  type Granularity,
  type Payer,
  type Preset,
} from '@/analytics/filters'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/display'
import { controlClasses, Input } from '@/components/ui/input'
import { useToast } from '@/components/ui/toast'
import { useAllDentists, useAllServices } from '@/console/api'
import { saveFile } from '@/lib/download'
import { cn } from '@/lib/utils'
import { clock, longDay } from '@/pages/portal/format'

/** The tables each tab can export, as the server names them. */
const exports: Record<string, { dataset: string; label: string }[]> = {
  overview: [
    { dataset: 'summary', label: 'Key figures' },
    { dataset: 'revenue_trend', label: 'Revenue by period' },
    { dataset: 'forecast', label: 'Forecast' },
    { dataset: 'status_trend', label: 'Appointments by status' },
  ],
  revenue: [
    { dataset: 'revenue_trend', label: 'Revenue by period' },
    { dataset: 'by_service', label: 'Revenue by service' },
    { dataset: 'by_dentist', label: 'Revenue by dentist' },
    { dataset: 'by_payer', label: 'Payer mix' },
    { dataset: 'by_weekday', label: 'Revenue by weekday' },
    { dataset: 'service_trends', label: 'Services' },
  ],
  appointments: [
    { dataset: 'status_trend', label: 'Appointments by status' },
    { dataset: 'heatmap', label: 'Busy hours' },
    { dataset: 'lead_time', label: 'Booking lead time' },
    { dataset: 'channels', label: 'Booking channels' },
    { dataset: 'risk', label: 'No show risk' },
  ],
  patients: [
    { dataset: 'new_returning', label: 'New and returning' },
    { dataset: 'retention', label: 'Retention' },
    { dataset: 'demographics', label: 'Age and source' },
    { dataset: 'top_patients', label: 'Top patients' },
  ],
  dentists: [
    { dataset: 'leaderboard', label: 'Dentist leaderboard' },
    { dataset: 'dentist_services', label: 'Dentist by service' },
    { dataset: 'service_trends', label: 'Services' },
  ],
  finance: [
    { dataset: 'ar_aging', label: 'Receivables by age' },
    { dataset: 'collection', label: 'Collection rate' },
    { dataset: 'by_payer', label: 'Payer mix' },
  ],
  chatbot: [{ dataset: 'chatbot', label: 'Assistant summary' }],
}

const STALE_HOURS = 36

function Select<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (value: T) => void
}) {
  const id = React.useId()
  return (
    <div className="grid gap-1">
      <label htmlFor={id} className="text-xs font-medium text-muted-foreground">
        {label}
      </label>
      <select
        id={id}
        className={cn(controlClasses, 'h-10 w-full min-w-36')}
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  )
}

function Controls({
  filters,
  update,
}: {
  filters: Filters
  update: (c: Partial<Filters>) => void
}) {
  const dentists = useAllDentists()
  const services = useAllServices()
  return (
    <form
      aria-label="Filters"
      className="grid gap-3 rounded-xl border bg-card p-4 sm:grid-cols-2 lg:grid-cols-4"
      onSubmit={(e) => e.preventDefault()}
    >
      <Select<Preset>
        label="Date range"
        value={filters.preset}
        options={presets}
        onChange={(preset) =>
          update(preset === 'custom' ? { preset, from: filters.from, to: filters.to } : { preset })
        }
      />
      {filters.preset === 'custom' && (
        <>
          <div className="grid gap-1">
            <label htmlFor="from" className="text-xs font-medium text-muted-foreground">
              From
            </label>
            <Input
              id="from"
              type="date"
              className="h-10"
              value={filters.from}
              max={filters.to}
              onChange={(e) => e.target.value && update({ from: e.target.value })}
            />
          </div>
          <div className="grid gap-1">
            <label htmlFor="to" className="text-xs font-medium text-muted-foreground">
              To
            </label>
            <Input
              id="to"
              type="date"
              className="h-10"
              value={filters.to}
              min={filters.from}
              onChange={(e) => e.target.value && update({ to: e.target.value })}
            />
          </div>
        </>
      )}
      <div className="grid gap-1">
        <span id="grain" className="text-xs font-medium text-muted-foreground">
          Group by
        </span>
        <div role="group" aria-labelledby="grain" className="inline-flex rounded-full bg-muted p-1">
          {(['day', 'week', 'month', 'quarter'] as Granularity[]).map((g) => (
            <Button
              key={g}
              type="button"
              size="sm"
              className="h-8 flex-1 px-3 capitalize"
              variant={filters.granularity === g ? 'primary' : 'ghost'}
              aria-pressed={filters.granularity === g}
              onClick={() => update({ granularity: g })}
            >
              {g}
            </Button>
          ))}
        </div>
      </div>
      <Select<Compare>
        label="Compare with"
        value={filters.compare}
        options={[
          { value: 'previous', label: 'Previous period' },
          { value: 'year', label: 'Same period last year' },
          { value: 'none', label: 'No comparison' },
        ]}
        onChange={(compare) => update({ compare })}
      />
      <Select
        label="Dentist"
        value={filters.dentist}
        options={[
          { value: '', label: 'All dentists' },
          ...(dentists.data ?? []).map((d) => ({ value: d.id, label: d.full_name })),
        ]}
        onChange={(dentist) => update({ dentist })}
      />
      <Select
        label="Service"
        value={filters.service}
        options={[
          { value: '', label: 'All services' },
          ...(services.data ?? []).map((s) => ({ value: s.id, label: s.name })),
        ]}
        onChange={(service) => update({ service })}
      />
      <Select<Payer>
        label="Paid by"
        value={filters.payer}
        options={[
          { value: '', label: 'Patients and insurers' },
          { value: 'patient', label: 'Patients' },
          { value: 'insurer', label: 'Insurers' },
        ]}
        onChange={(payer) => update({ payer })}
      />
    </form>
  )
}

/** Analytics: filters that live in the address, tabs for each area, and the page for the tab. */
export function AnalyticsLayout() {
  const [filters, update] = useFilters()
  const location = useLocation()
  const { toast } = useToast()
  const summary = useSummary(filters)
  const refresh = useRefreshViews()
  const tab = location.pathname.split('/')[3] ?? 'overview'
  const asOf = summary.data?.meta.data_as_of
  const stale = asOf ? isStale(asOf, STALE_HOURS) : false
  const [menu, setMenu] = React.useState(false)

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-3xl">Analytics</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            {asOf ? (
              <span>
                Figures last refreshed {longDay(asOf)} at {clock(asOf)}.
              </span>
            ) : (
              <span>Figures are refreshed every night.</span>
            )}
            {stale && <Badge tone="warning">Out of date</Badge>}
            {summary.data?.meta.cached && <Badge tone="neutral">From the last five minutes</Badge>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            loading={refresh.isPending}
            onClick={() =>
              refresh.mutate(undefined, {
                onSuccess: () => toast({ tone: 'success', title: 'Figures refreshed.' }),
                onError: () =>
                  toast({ tone: 'error', title: 'Refreshing failed. Please try again.' }),
              })
            }
          >
            <RefreshCw aria-hidden="true" /> Refresh figures
          </Button>
          <div className="relative">
            <Button
              size="sm"
              variant="secondary"
              aria-expanded={menu}
              aria-haspopup="menu"
              onClick={() => setMenu((v) => !v)}
            >
              <Download aria-hidden="true" /> Export CSV
            </Button>
            {menu && (
              <ul
                role="menu"
                aria-label="Export a table"
                className="absolute right-0 z-20 mt-2 w-60 rounded-xl border bg-card p-2 shadow-raised"
              >
                {(exports[tab] ?? []).map((e) => (
                  <li key={e.dataset} role="none">
                    <button
                      type="button"
                      role="menuitem"
                      className="w-full rounded-md px-3 py-2 text-left text-sm hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring"
                      onClick={async () => {
                        setMenu(false)
                        try {
                          saveFile(
                            await fetchCsv(e.dataset, filters),
                            `${e.dataset}-${filters.from}-${filters.to}.csv`,
                            'text/csv',
                          )
                        } catch {
                          toast({ tone: 'error', title: 'The export failed. Please try again.' })
                        }
                      }}
                    >
                      {e.label}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>

      <Controls filters={filters} update={update} />

      <nav aria-label="Analytics sections">
        <ul className="flex flex-wrap gap-1 border-b">
          {tabs.map((t) => (
            <li key={t.to}>
              <NavLink
                to={{ pathname: `/admin/analytics/${t.to}`, search: location.search }}
                className={({ isActive }) =>
                  cn(
                    'inline-flex min-h-11 items-center border-b-2 border-transparent px-4 text-sm font-medium hover:text-primary',
                    isActive && 'border-primary font-semibold text-primary',
                  )
                }
              >
                {t.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <Outlet context={{ filters } satisfies AnalyticsContext} />
    </div>
  )
}
