import * as React from 'react'

import {
  useChannels,
  useHeatmap,
  useLeadTime,
  useRisk,
  useSendReminder,
  useStatusTrend,
} from '@/analytics/api'
import { useAnalytics } from '@/analytics/context'
import { ChartCard } from '@/analytics/ChartCard'
import { channelDonut, heatmap, leadTimeBars, rateLines, statusFunnel } from '@/analytics/options'
import { Badge, Skeleton } from '@/components/ui/display'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast'
import { ApiError } from '@/lib/api-client'
import { clock, longDay } from '@/pages/portal/format'

const empty = { columns: [], rows: [] }
const tone = { high: 'danger', medium: 'warning', low: 'success' } as const

function RiskTable() {
  const { filters } = useAnalytics()
  const risk = useRisk(filters)
  const send = useSendReminder()
  const { toast } = useToast()
  const [sent, setSent] = React.useState<Set<string>>(new Set())

  if (risk.isLoading) return <Skeleton className="h-48 w-full" />
  if (risk.isError || !risk.data) return <p role="alert">We could not load the no show forecast.</p>
  const data = risk.data
  if (data.note) return <p className="rounded-md bg-secondary p-3 text-sm">{data.note}</p>
  return (
    <div className="overflow-x-auto rounded-xl border bg-card">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">
          Visits in the next seven days most likely to be missed
        </caption>
        <thead className="bg-muted text-xs uppercase">
          <tr>
            <th scope="col" className="p-3">
              When
            </th>
            <th scope="col" className="p-3">
              Patient
            </th>
            <th scope="col" className="p-3">
              Risk
            </th>
            <th scope="col" className="p-3">
              Main reasons
            </th>
            <th scope="col" className="p-3">
              <span className="sr-only">Action</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {data.rows.slice(0, 15).map((r) => (
            <tr key={r.appointment_id} className="border-t align-top">
              <td className="p-3 whitespace-nowrap">
                {longDay(r.start)}
                <span className="block text-muted-foreground">
                  {clock(r.start)} with {r.dentist_name}
                </span>
              </td>
              <th scope="row" className="p-3 font-normal">
                {r.patient_name}
                <span className="block text-muted-foreground">{r.service_name}</span>
              </th>
              <td className="p-3">
                <Badge tone={tone[r.level]}>
                  {Math.round(r.score * 100)}% {r.level}
                </Badge>
              </td>
              <td className="p-3">
                <ul className="grid gap-0.5">
                  {r.drivers.slice(0, 3).map((d) => (
                    <li key={d.feature}>{d.label}</li>
                  ))}
                </ul>
              </td>
              <td className="p-3 text-right">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={sent.has(r.appointment_id)}
                  loading={send.isPending && send.variables === r.appointment_id}
                  onClick={() =>
                    send.mutate(r.appointment_id, {
                      onSuccess: () => {
                        setSent(new Set(sent).add(r.appointment_id))
                        toast({ tone: 'success', title: `Reminder sent to ${r.patient_name}.` })
                      },
                      onError: (error) =>
                        toast({
                          tone: 'error',
                          title:
                            error instanceof ApiError
                              ? error.message
                              : 'The reminder was not sent.',
                        }),
                    })
                  }
                >
                  {sent.has(r.appointment_id) ? 'Sent' : 'Send reminder'}{' '}
                  <span className="sr-only">to {r.patient_name}</span>
                </Button>
              </td>
            </tr>
          ))}
          {data.rows.length === 0 && (
            <tr>
              <td colSpan={5} className="p-4 text-center text-muted-foreground">
                No visits in the next seven days.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {data.model_version && (
        <p className="border-t p-3 text-xs text-muted-foreground">
          Model {data.model_version}
          {data.model_auc ? `, AUC ${data.model_auc.toFixed(2)}` : ''}. Scores estimate the chance a
          visit is missed; they do not decide anything.
        </p>
      )}
    </div>
  )
}

export function AppointmentsTab() {
  const { filters } = useAnalytics()
  const heat = useHeatmap(filters)
  const status = useStatusTrend(filters)
  const lead = useLeadTime(filters)
  const channels = useChannels(filters)
  const h = heat.data ? heatmap(heat.data) : null
  const f = status.data ? statusFunnel(status.data) : null
  const l = lead.data ? leadTimeBars(lead.data) : null
  const r = status.data ? rateLines(status.data) : null
  const c = channels.data ? channelDonut(channels.data) : null
  return (
    <div className="grid gap-6">
      <ChartCard
        title="Busiest days and hours"
        description="Visits by weekday and hour. Hover for the no show rate."
        option={h?.option ?? null}
        table={h?.table ?? empty}
        loading={heat.isLoading}
        error={heat.isError}
        height={340}
      />
      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard
          title="From booking to visit"
          description="How many bookings were kept and completed."
          option={f?.option ?? null}
          table={f?.table ?? empty}
          loading={status.isLoading}
          error={status.isError}
        />
        <ChartCard
          title="How far ahead people book"
          description={
            lead.data?.average_days != null
              ? `Average ${lead.data.average_days} days, middle value ${lead.data.median_days} days.`
              : undefined
          }
          option={l?.option ?? null}
          table={l?.table ?? empty}
          loading={lead.isLoading}
          error={lead.isError}
        />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard
          title="Cancellations and no shows"
          option={r?.option ?? null}
          table={r?.table ?? empty}
          loading={status.isLoading}
          error={status.isError}
        />
        <ChartCard
          title="How visits are booked"
          option={c?.option ?? null}
          table={c?.table ?? empty}
          loading={channels.isLoading}
          error={channels.isError}
        />
      </div>
      <section aria-labelledby="risk">
        <h2 id="risk" className="mb-3 font-heading text-lg font-bold">
          Visits most likely to be missed
        </h2>
        <RiskTable />
      </section>
    </div>
  )
}
