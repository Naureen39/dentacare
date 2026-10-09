import * as React from 'react'

import { Button } from '@/components/ui/button'
import { Badge, Card, Skeleton } from '@/components/ui/display'
import { Field } from '@/components/ui/field'
import { Input, controlClasses } from '@/components/ui/input'
import { Switch } from '@/components/ui/toggles'
import { useToast } from '@/components/ui/toast'
import {
  useLlmChange,
  useLlmStatus,
  useSaveSettings,
  useSettings,
  type Settings,
} from '@/console/api'
import { ApiError } from '@/lib/api-client'
import { FormAlert } from '@/lib/auth-forms'
import { cn } from '@/lib/utils'

const message = (error: unknown) =>
  error instanceof ApiError && error.status < 500
    ? error.message
    : 'That did not work. Please try again.'

type Values = Record<string, string | number | boolean>
type Body = Parameters<ReturnType<typeof useSaveSettings>['mutateAsync']>[0]

function Block({
  title,
  intro,
  children,
}: {
  title: string
  intro?: string
  children: React.ReactNode
}) {
  const id = React.useId()
  return (
    <Card className="p-6" role="region" aria-labelledby={id}>
      <h2 id={id} className="text-xl">
        {title}
      </h2>
      {intro && <p className="mt-1 text-sm text-muted-foreground">{intro}</p>}
      <div className="mt-4">{children}</div>
    </Card>
  )
}

/** A form for one group of settings. Values are edited as text and checked by the server. */
function SettingsForm({
  title,
  intro,
  fields,
  initial,
  toBody,
}: {
  title: string
  intro?: string
  fields: { name: string; label: string; hint?: string; kind?: 'number' | 'switch' | 'list' }[]
  initial: Values
  toBody: (values: Values) => Body
}) {
  const save = useSaveSettings()
  const { toast } = useToast()
  const [values, setValues] = React.useState(initial)
  const [problem, setProblem] = React.useState<string>()
  return (
    <Block title={title} intro={intro}>
      <form
        noValidate
        aria-label={title}
        className="grid gap-4"
        onSubmit={async (event) => {
          event.preventDefault()
          setProblem(undefined)
          try {
            await save.mutateAsync(toBody(values))
            toast({ tone: 'success', title: `${title} saved.` })
          } catch (error) {
            setProblem(message(error))
          }
        }}
      >
        <FormAlert message={problem} />
        <div className="grid gap-4 sm:grid-cols-2">
          {fields.map((f) =>
            f.kind === 'switch' ? (
              <div key={f.name} className="flex items-center gap-3">
                <Switch
                  id={f.name}
                  checked={values[f.name] === true}
                  onCheckedChange={(v) => setValues({ ...values, [f.name]: v })}
                />
                <label htmlFor={f.name} className="text-sm">
                  {f.label}
                </label>
              </div>
            ) : (
              <Field key={f.name} label={f.label} hint={f.hint}>
                {(c) => (
                  <Input
                    {...c}
                    inputMode={f.kind === 'list' ? 'text' : 'decimal'}
                    value={String(values[f.name])}
                    onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
                  />
                )}
              </Field>
            ),
          )}
        </div>
        <div>
          <Button type="submit" loading={save.isPending}>
            Save
          </Button>
        </div>
      </form>
    </Block>
  )
}

const n = (v: unknown) => Number(v)

function Forms({ s }: { s: Settings }) {
  return (
    <>
      <SettingsForm
        title="Booking rules"
        intro="How online booking and cancellation behave. Changes apply to new bookings at once."
        fields={[
          { name: 'min_notice_hours', label: 'Minimum notice (hours)' },
          { name: 'max_horizon_days', label: 'Book up to (days ahead)' },
          { name: 'buffer_minutes', label: 'Gap between visits (minutes)' },
          { name: 'slot_grid_minutes', label: 'Start times every (minutes)' },
          { name: 'cancellation_free_hours', label: 'Free cancellation until (hours before)' },
          { name: 'same_day_enabled', label: 'Allow same day bookings online', kind: 'switch' },
        ]}
        initial={{ ...s.booking }}
        toBody={(v) => ({
          booking: {
            min_notice_hours: n(v.min_notice_hours),
            max_horizon_days: n(v.max_horizon_days),
            same_day_enabled: v.same_day_enabled === true,
            buffer_minutes: n(v.buffer_minutes),
            slot_grid_minutes: n(v.slot_grid_minutes),
            cancellation_free_hours: n(v.cancellation_free_hours),
          },
        })}
      />
      <SettingsForm
        title="Reminders"
        intro="When patients are reminded about a visit, and when we follow up."
        fields={[
          {
            name: 'hours_before',
            label: 'Reminders (hours before)',
            kind: 'list',
            hint: 'Up to four numbers, for example 48, 24.',
          },
          { name: 'followup_days', label: 'Thank you message (days after)' },
          { name: 'recall_months', label: 'Check-up reminder (months after)' },
        ]}
        initial={{ ...s.reminders, hours_before: s.reminders.hours_before.join(', ') }}
        toBody={(v) => ({
          reminders: {
            hours_before: String(v.hours_before).split(/[ ,]+/).filter(Boolean).map(Number),
            followup_days: n(v.followup_days),
            recall_months: n(v.recall_months),
          },
        })}
      />
      <SettingsForm
        title="Billing and targets"
        fields={[
          { name: 'tax_rate_percent', label: 'Tax rate (percent)' },
          {
            name: 'receptionist_max_discount_percent',
            label: 'Largest discount a receptionist may give (percent)',
          },
          {
            name: 'monthly_revenue_target',
            label: 'Monthly revenue target',
            hint: 'Used by the analytics progress bar.',
          },
        ]}
        initial={{ ...s.billing }}
        toBody={(v) => ({
          billing: {
            tax_rate_percent: String(v.tax_rate_percent),
            receptionist_max_discount_percent: String(v.receptionist_max_discount_percent),
            monthly_revenue_target: String(v.monthly_revenue_target),
          },
        })}
      />
      <SettingsForm
        title="Data retention"
        intro="How long chat conversations and guest details are kept."
        fields={[
          { name: 'chat_retention_days', label: 'Keep chat conversations (days)' },
          { name: 'guest_anonymize_months', label: 'Anonymise inactive guests after (months)' },
        ]}
        initial={{ ...s.retention }}
        toBody={(v) => ({
          retention: {
            chat_retention_days: n(v.chat_retention_days),
            guest_anonymize_months: n(v.guest_anonymize_months),
          },
        })}
      />
    </>
  )
}

function Assistant() {
  const status = useLlmStatus()
  const change = useLlmChange()
  const { toast } = useToast()
  const [problem, setProblem] = React.useState<string>()
  const [limits, setLimits] = React.useState<Record<string, Record<string, string>>>({})
  if (status.isLoading) return <Skeleton className="h-40 w-full" />
  if (status.isError || !status.data)
    return <FormAlert message="The assistant gateway is not available right now." />
  const data = status.data
  const run = async (task: () => Promise<unknown>, done: string) => {
    setProblem(undefined)
    try {
      await task()
      toast({ tone: 'success', title: done })
    } catch (error) {
      setProblem(message(error))
    }
  }
  return (
    <div className="grid gap-6">
      <FormAlert message={problem} />
      <div className="flex flex-wrap items-end gap-4">
        <Field
          label="Try first"
          hint="The other provider is the fallback when this one fails or is near its limit."
        >
          {(c) => (
            <select
              {...c}
              className={cn(controlClasses, 'h-11 w-48')}
              value={data.primary}
              onChange={(e) =>
                run(
                  () => change.mutateAsync({ primary: e.target.value }),
                  'Provider order changed.',
                )
              }
            >
              {Object.keys(data.providers).map((p) => (
                <option key={p} value={p} className="capitalize">
                  {p}
                </option>
              ))}
            </select>
          )}
        </Field>
        <p className="text-sm text-muted-foreground">
          Switches to the other provider at {Math.round(data.failover_threshold * 100)}% of a limit.
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {Object.entries(data.providers).map(([name, p]) => (
          <Card key={name} className="p-4">
            <h3 className="flex items-center justify-between text-lg capitalize">
              {name}
              <Badge tone={p.configured ? 'success' : 'neutral'}>
                {p.configured ? 'Configured' : 'Not set up'}
              </Badge>
            </h3>
            {p.configured && (
              <>
                <p className="text-sm text-muted-foreground">
                  {p.model}, {Math.round((p.utilization ?? 0) * 100)}% of the busiest limit used
                  {p.breaker?.state && p.breaker.state !== 'closed'
                    ? `, circuit ${p.breaker.state}`
                    : ''}
                </p>
                <form
                  noValidate
                  aria-label={`${name} limits`}
                  className="mt-3 grid grid-cols-2 gap-3"
                  onSubmit={(event) => {
                    event.preventDefault()
                    const draft = limits[name] ?? {}
                    const values = Object.fromEntries(
                      (['rpm', 'rpd', 'tpm', 'tpd'] as const).map((k) => {
                        const text = draft[k] ?? String(p.limits?.[k] ?? '')
                        return [k, text.trim() === '' ? null : Number(text)]
                      }),
                    )
                    void run(
                      () => change.mutateAsync({ limits: { provider: name, values } }),
                      `${name} limits saved.`,
                    )
                  }}
                >
                  {(['rpm', 'rpd', 'tpm', 'tpd'] as const).map((k) => (
                    <Field
                      key={k}
                      label={`${{ rpm: 'Requests a minute', rpd: 'Requests a day', tpm: 'Tokens a minute', tpd: 'Tokens a day' }[k]}`}
                      hint={`Used: ${p.usage?.[k] ?? 0}. Empty means no limit.`}
                    >
                      {(c) => (
                        <Input
                          {...c}
                          inputMode="numeric"
                          value={limits[name]?.[k] ?? String(p.limits?.[k] ?? '')}
                          onChange={(e) =>
                            setLimits({
                              ...limits,
                              [name]: { ...limits[name], [k]: e.target.value },
                            })
                          }
                        />
                      )}
                    </Field>
                  ))}
                  <div className="col-span-2">
                    <Button type="submit" size="sm" variant="secondary">
                      Save limits <span className="sr-only">for {name}</span>
                    </Button>
                  </div>
                </form>
              </>
            )}
          </Card>
        ))}
      </div>
    </div>
  )
}

export function SettingsPage() {
  const settings = useSettings()
  if (settings.isLoading) return <Skeleton className="h-96 w-full" />
  if (settings.isError || !settings.data)
    return <FormAlert message="We could not load the settings." />
  const s = settings.data
  return (
    <div className="grid gap-6">
      <h1 className="text-3xl">Settings</h1>
      <Block
        title="Clinic details"
        intro="Set in the server configuration. They appear on invoices, emails and the assistant's answers."
      >
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          {(
            [
              ['Name', s.clinic.name],
              ['Address', s.clinic.address],
              ['Phone', s.clinic.phone],
              ['Email', s.clinic.email],
              ['Time zone', s.clinic.timezone],
            ] as const
          ).map(([term, value]) => (
            <div key={term}>
              <dt className="text-muted-foreground">{term}</dt>
              <dd className="font-medium">{value}</dd>
            </div>
          ))}
        </dl>
      </Block>
      <Forms s={s} />
      <Block
        title="Assistant providers"
        intro="Which language model answers first, and the limits we keep it under."
      >
        <Assistant />
      </Block>
    </div>
  )
}
