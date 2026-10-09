import { useChatbot } from '@/analytics/api'
import { useAnalytics } from '@/analytics/context'
import { ChartCard } from '@/analytics/ChartCard'
import { integer, percent } from '@/analytics/format'
import { bookingFunnel, chatDaily, providerDonut, tokensVsLimit } from '@/analytics/options'
import { Card, Skeleton } from '@/components/ui/display'
import { StatCard } from '@/components/ui/metrics'
import { useLlmStatus } from '@/console/api'

const empty = { columns: [], rows: [] }

export function AssistantTab() {
  const { filters } = useAnalytics()
  const chat = useChatbot(filters)
  const llm = useLlmStatus()
  const d = chat.data
  const limits = Object.values(llm.data?.providers ?? {}).flatMap((p) => p.limits?.tpd ?? [])
  const dailyLimit = limits.length ? limits.reduce((a, b) => a + b, 0) : null
  const daily = d ? chatDaily(d) : null
  const funnel = d ? bookingFunnel(d) : null
  const providers = d ? providerDonut(d) : null
  const tokens = d ? tokensVsLimit(d, dailyLimit) : null

  return (
    <div className="grid gap-6">
      <section aria-label="Assistant figures" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {chat.isLoading ? (
          [1, 2, 3, 4].map((n) => <Skeleton key={n} className="h-32 w-full" />)
        ) : (
          <>
            <StatCard
              label="Conversations"
              value={d?.conversations ?? 0}
              format={integer}
              hint={`${integer(d?.turns ?? 0)} replies`}
            />
            <StatCard
              label="Answered without a model"
              value={(d?.zero_llm_share ?? 0) * 100}
              format={(v) => `${v.toFixed(1)}%`}
              hint="Replies from rules, saved answers or the knowledge base"
            />
            <StatCard
              label="Booking conversion"
              value={(d?.booking_conversion ?? 0) * 100}
              format={(v) => `${v.toFixed(1)}%`}
              hint={`${d?.booking_confirmed ?? 0} of ${d?.booking_started ?? 0} started`}
            />
            <StatCard
              label="Helpful replies"
              value={(d?.feedback_score ?? 0) * 100}
              format={(v) => (d?.feedback_score == null ? 'No votes' : `${v.toFixed(0)}%`)}
              hint={`${d?.feedback_up ?? 0} up, ${d?.feedback_down ?? 0} down`}
            />
          </>
        )}
      </section>
      <ChartCard
        title="Conversations each day"
        description="Bars are conversations; the line is the share of replies that needed no model."
        option={daily?.option ?? null}
        table={daily?.table ?? empty}
        loading={chat.isLoading}
        error={chat.isError}
      />
      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard
          title="Booking through the assistant"
          option={funnel?.option ?? null}
          table={funnel?.table ?? empty}
          loading={chat.isLoading}
          error={chat.isError}
        />
        <ChartCard
          title="Which provider answered"
          description={d ? `${d.failovers} times the second provider took over.` : undefined}
          option={providers?.option ?? null}
          table={providers?.table ?? empty}
          loading={chat.isLoading}
          error={chat.isError}
        />
      </div>
      <ChartCard
        title="Tokens used each day"
        description={
          dailyLimit
            ? `Against a combined daily limit of ${integer(dailyLimit)}.`
            : 'No daily limit is set.'
        }
        option={tokens?.option ?? null}
        table={tokens?.table ?? empty}
        loading={chat.isLoading}
        error={chat.isError}
      />
      <Card className="p-5" role="region" aria-label="Questions to improve">
        <h2 className="font-heading text-base font-bold">Questions the assistant struggled with</h2>
        <p className="text-sm text-muted-foreground">
          Replies that were handed to staff or marked not helpful. Add these answers to the
          knowledge base.
        </p>
        {chat.isLoading ? (
          <Skeleton className="mt-4 h-24 w-full" />
        ) : d?.unanswered.length ? (
          <ol className="mt-4 grid gap-2 text-sm">
            {d.unanswered.map((u) => (
              <li
                key={u.question}
                className="flex justify-between gap-3 rounded-md border px-3 py-2"
              >
                <span>{u.question}</span>
                <span className="text-muted-foreground">{u.count} times</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="mt-4 text-sm">Nothing flagged in this period.</p>
        )}
        <p className="mt-3 text-xs text-muted-foreground">
          Resolved without a person: {percent(d?.resolved_without_human)}.
        </p>
      </Card>
    </div>
  )
}
