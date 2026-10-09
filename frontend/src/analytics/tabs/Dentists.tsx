import { useLeaderboard, useServiceTrends } from '@/analytics/api'
import { useAnalytics } from '@/analytics/context'
import { ChartCard } from '@/analytics/ChartCard'
import { money, percent } from '@/analytics/format'
import { dentistRadar, serviceScatter, utilizationBars } from '@/analytics/options'
import { DataTable, type Column } from '@/components/ui/data-table'

const empty = { columns: [], rows: [] }
type Row = NonNullable<ReturnType<typeof useLeaderboard>['data']>['rows'][number]

export function DentistsTab() {
  const { filters } = useAnalytics()
  const board = useLeaderboard(filters)
  const services = useServiceTrends(filters)
  const util = board.data ? utilizationBars(board.data) : null
  const radar = board.data ? dentistRadar(board.data) : null
  const scatter = services.data ? serviceScatter(services.data) : null

  const columns: Column<Row>[] = [
    { key: 'dentist', header: 'Dentist', sortValue: (r) => r.dentist, cell: (r) => r.dentist },
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
      key: 'per',
      header: 'Per visit',
      align: 'right',
      sortValue: (r) => r.revenue_per_visit ?? 0,
      cell: (r) => (r.revenue_per_visit == null ? 'No data' : money(r.revenue_per_visit)),
    },
    {
      key: 'util',
      header: 'Utilization',
      align: 'right',
      sortValue: (r) => r.utilization ?? 0,
      cell: (r) => percent(r.utilization),
    },
    {
      key: 'noshow',
      header: 'No show rate',
      align: 'right',
      sortValue: (r) => r.no_show_rate ?? 0,
      cell: (r) => percent(r.no_show_rate),
    },
  ]

  return (
    <div className="grid gap-6">
      <section aria-labelledby="board">
        <h2 id="board" className="mb-3 font-heading text-lg font-bold">
          Dentist leaderboard
        </h2>
        <DataTable
          caption="Dentists by billed revenue"
          columns={columns}
          rows={board.data?.rows ?? []}
          getRowId={(r) => r.dentist_id}
          loading={board.isLoading}
        />
      </section>
      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard
          title="Chair time used"
          description="Booked hours as a share of working hours."
          option={util?.option ?? null}
          table={util?.table ?? empty}
          loading={board.isLoading}
          error={board.isError}
        />
        <ChartCard
          title="Comparing dentists"
          description="Each measure scaled so the best of the five shown is 100."
          option={radar?.option ?? null}
          table={radar?.table ?? empty}
          loading={board.isLoading}
          error={board.isError}
        />
      </div>
      <ChartCard
        title="Which services earn the most"
        description="Visits against revenue per chair hour. Bigger circles billed more. Chair hours stand in for cost, which is not recorded."
        option={scatter?.option ?? null}
        table={scatter?.table ?? empty}
        loading={services.isLoading}
        error={services.isError}
        height={360}
      />
    </div>
  )
}
