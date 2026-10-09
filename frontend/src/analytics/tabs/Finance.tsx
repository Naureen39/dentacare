import { Link } from 'react-router-dom'

import { useArAging, useCollection, useTrend } from '@/analytics/api'
import { useAnalytics } from '@/analytics/context'
import { ChartCard } from '@/analytics/ChartCard'
import { money, percent } from '@/analytics/format'
import { agingBars, collectionLine, paymentsByPayer } from '@/analytics/options'
import { DataTable, type Column } from '@/components/ui/data-table'
import { StatCard } from '@/components/ui/metrics'
import { useInvoiceList, type InvoiceRow } from '@/console/api'
import { longDay } from '@/pages/portal/format'

const empty = { columns: [], rows: [] }

export function FinanceTab() {
  const { filters } = useAnalytics()
  const aging = useArAging(filters)
  const collection = useCollection(filters)
  const patient = useTrend({ ...filters, payer: 'patient' })
  const insurer = useTrend({ ...filters, payer: 'insurer' })
  const open = useInvoiceList({ openOnly: true })
  const a = aging.data ? agingBars(aging.data) : null
  const c = collection.data ? collectionLine(collection.data) : null
  const p = patient.data && insurer.data ? paymentsByPayer(patient.data, insurer.data) : null

  const columns: Column<InvoiceRow>[] = [
    {
      key: 'n',
      header: 'Invoice',
      sortValue: (i) => i.number,
      cell: (i) => (
        <Link to={`/staff/billing/${i.id}`} className="font-semibold">
          {i.display_number}
        </Link>
      ),
    },
    {
      key: 'patient',
      header: 'Patient',
      sortValue: (i) => i.patient_name,
      cell: (i) => i.patient_name,
    },
    {
      key: 'date',
      header: 'Issued',
      sortValue: (i) => i.issued_at,
      cell: (i) => longDay(i.issued_at),
    },
    {
      key: 'balance',
      header: 'Balance',
      align: 'right',
      sortValue: (i) => Number(i.balance),
      cell: (i) => money(i.balance),
    },
  ]

  return (
    <div className="grid gap-6">
      <section aria-label="Receivables" className="grid gap-4 sm:grid-cols-3">
        <StatCard
          label="Owed to the practice"
          value={Number(aging.data?.total_outstanding ?? 0)}
          format={money}
          hint={aging.data ? `As of ${longDay(`${aging.data.as_of}T12:00:00Z`)}` : undefined}
        />
        <StatCard
          label="Owed for over 90 days"
          value={(aging.data?.over_90_share ?? 0) * 100}
          format={(v) => `${v.toFixed(1)}%`}
          lowerIsBetter
        />
        <StatCard
          label="Days to get paid"
          value={collection.data?.average_days_to_collect ?? 0}
          format={(v) =>
            collection.data?.average_days_to_collect == null ? 'No data' : `${v.toFixed(1)} days`
          }
          hint={`Collection rate ${percent(collection.data?.overall_rate)}`}
          lowerIsBetter
        />
      </section>
      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard
          title="Who owes, and for how long"
          option={a?.option ?? null}
          table={a?.table ?? empty}
          loading={aging.isLoading}
          error={aging.isError}
        />
        <ChartCard
          title="How much of what was billed has been collected"
          option={c?.option ?? null}
          table={c?.table ?? empty}
          loading={collection.isLoading}
          error={collection.isError}
        />
      </div>
      <ChartCard
        title="Money received"
        description="Payments from patients and from insurers."
        option={p?.option ?? null}
        table={p?.table ?? empty}
        loading={patient.isLoading || insurer.isLoading}
        error={patient.isError || insurer.isError}
      />
      <section aria-labelledby="open">
        <h2 id="open" className="mb-3 font-heading text-lg font-bold">
          Open invoices
        </h2>
        <DataTable
          caption="Invoices that are not fully paid"
          columns={columns}
          rows={open.data ?? []}
          getRowId={(i) => i.id}
          loading={open.isLoading}
        />
      </section>
    </div>
  )
}
