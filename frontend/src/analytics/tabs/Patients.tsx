import { useDemographics, useNewVsReturning, useRetention, useTopPatients } from '@/analytics/api'
import { useAnalytics } from '@/analytics/context'
import { ChartCard } from '@/analytics/ChartCard'
import { money, percent } from '@/analytics/format'
import {
  cohortHeatmap,
  growthLine,
  newReturning,
  sliceBars,
  sourceDonut,
} from '@/analytics/options'
import { DataTable, type Column } from '@/components/ui/data-table'
import { longDay } from '@/pages/portal/format'

const empty = { columns: [], rows: [] }
type Top = NonNullable<ReturnType<typeof useTopPatients>['data']>['rows'][number]

export function PatientsTab() {
  const { filters } = useAnalytics()
  const flow = useNewVsReturning(filters)
  const retention = useRetention(filters)
  const people = useDemographics(filters)
  const top = useTopPatients(filters)
  const a = flow.data ? newReturning(flow.data) : null
  const g = flow.data ? growthLine(flow.data) : null
  const r = retention.data ? cohortHeatmap(retention.data) : null
  const age = people.data ? sliceBars(people.data) : null
  const source = people.data ? sourceDonut(people.data) : null
  const masked = top.data?.rows.some((p) => p.masked)

  const columns: Column<Top>[] = [
    { key: 'name', header: 'Patient', cell: (p) => p.name },
    {
      key: 'value',
      header: 'Billed in total',
      align: 'right',
      sortValue: (p) => Number(p.lifetime_value),
      cell: (p) => money(p.lifetime_value),
    },
    {
      key: 'visits',
      header: 'Visits',
      align: 'right',
      sortValue: (p) => p.visits,
      cell: (p) => p.visits,
    },
    {
      key: 'last',
      header: 'Last visit',
      sortValue: (p) => p.last_visit ?? '',
      cell: (p) => (p.last_visit ? longDay(`${p.last_visit}T12:00:00Z`) : ''),
    },
  ]

  return (
    <div className="grid gap-6">
      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard
          title="New and returning patients"
          description={
            flow.data
              ? `${flow.data.new_patients} new and ${flow.data.returning_patients} returning in this period.`
              : undefined
          }
          option={a?.option ?? null}
          table={a?.table ?? empty}
          loading={flow.isLoading}
          error={flow.isError}
        />
        <ChartCard
          title="Practice growth"
          description="New patients added so far in this period."
          option={g?.option ?? null}
          table={g?.table ?? empty}
          loading={flow.isLoading}
          error={flow.isError}
        />
      </div>
      <ChartCard
        title="Do patients come back?"
        description={
          retention.data?.six_month_retention != null
            ? `${percent(retention.data.six_month_retention)} of patients return within six months.`
            : 'Share of each first-visit month that came back, by months since.'
        }
        option={r?.option ?? null}
        table={r?.table ?? empty}
        loading={retention.isLoading}
        error={retention.isError}
        height={Math.max(260, (retention.data?.cohorts.length ?? 0) * 26 + 80)}
      />
      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard
          title="Patients by age"
          option={age?.option ?? null}
          table={age?.table ?? empty}
          loading={people.isLoading}
          error={people.isError}
        />
        <ChartCard
          title="Where patients came from"
          option={source?.option ?? null}
          table={source?.table ?? empty}
          loading={people.isLoading}
          error={people.isError}
        />
      </div>
      <section aria-labelledby="top-patients">
        <h2 id="top-patients" className="mb-1 font-heading text-lg font-bold">
          Patients who have billed the most
        </h2>
        {masked && (
          <p className="mb-3 text-sm text-muted-foreground">
            Names are shown as initials for your role.
          </p>
        )}
        <DataTable
          caption="Patients by lifetime billing"
          columns={columns}
          rows={top.data?.rows ?? []}
          getRowId={(p) => p.patient_id}
          loading={top.isLoading}
        />
      </section>
    </div>
  )
}
