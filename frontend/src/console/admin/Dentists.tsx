import * as React from 'react'

import { Button } from '@/components/ui/button'
import { Badge, Skeleton } from '@/components/ui/display'
import { Field } from '@/components/ui/field'
import { Input, controlClasses } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/toggles'
import { useToast } from '@/components/ui/toast'
import {
  useAddTimeOff,
  useAdminDentists,
  useAdminServices,
  useDentistHours,
  useRemoveTimeOff,
  useSaveHours,
  useTimeOff,
  useUpdateDentist,
  type DentistAdmin,
  type ScheduleDay,
} from '@/console/api'
import { instantAt } from '@/console/time'
import { ApiError } from '@/lib/api-client'
import { FormAlert } from '@/lib/auth-forms'
import { cn } from '@/lib/utils'
import { longDay } from '@/pages/portal/format'

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const message = (error: unknown) =>
  error instanceof ApiError && error.status < 500
    ? error.message
    : 'That did not work. Please try again.'
const cut = (t: string | null | undefined) => (t ? t.slice(0, 5) : '')

interface Row {
  on: boolean
  start: string
  end: string
  breakStart: string
  breakEnd: string
}

function Hours({ id }: { id: string }) {
  const hours = useDentistHours(id)
  if (!hours.data) return <Skeleton className="h-64 w-full" />
  return <HoursForm id={id} days={hours.data} />
}

function HoursForm({ id, days: saved }: { id: string; days: ScheduleDay[] }) {
  const save = useSaveHours(id)
  const { toast } = useToast()
  const [rows, setRows] = React.useState<Row[]>(() =>
    DAYS.map((_, weekday) => {
      const d = saved.find((x) => x.weekday === weekday)
      return {
        on: Boolean(d),
        start: cut(d?.start_time) || '09:00',
        end: cut(d?.end_time) || '17:00',
        breakStart: cut(d?.break_start),
        breakEnd: cut(d?.break_end),
      }
    }),
  )
  const [problem, setProblem] = React.useState<string>()

  const set = (i: number, changes: Partial<Row>) =>
    setRows(rows.map((r, n) => (n === i ? { ...r, ...changes } : r)))

  return (
    <form
      noValidate
      aria-label="Weekly working hours"
      onSubmit={async (event) => {
        event.preventDefault()
        setProblem(undefined)
        const days: ScheduleDay[] = rows.flatMap((r, weekday) =>
          r.on
            ? [
                {
                  weekday,
                  start_time: `${r.start}:00`,
                  end_time: `${r.end}:00`,
                  break_start: r.breakStart && r.breakEnd ? `${r.breakStart}:00` : null,
                  break_end: r.breakStart && r.breakEnd ? `${r.breakEnd}:00` : null,
                },
              ]
            : [],
        )
        try {
          await save.mutateAsync(days)
          toast({ tone: 'success', title: 'Working hours saved.' })
        } catch (error) {
          setProblem(message(error))
        }
      }}
    >
      <FormAlert message={problem} />
      <ul className="grid gap-2">
        {rows.map((r, i) => (
          <li
            key={DAYS[i]}
            className="grid items-center gap-2 rounded-lg border bg-card p-3 sm:grid-cols-[130px_1fr]"
          >
            <div className="flex items-center gap-2">
              <Checkbox
                id={`day-${i}`}
                checked={r.on}
                onCheckedChange={(v) => set(i, { on: v === true })}
              />
              <label htmlFor={`day-${i}`} className="font-medium">
                {DAYS[i]}
              </label>
            </div>
            {r.on ? (
              <div className="flex flex-wrap items-end gap-3">
                <Field label="From">
                  {(c) => (
                    <Input
                      {...c}
                      type="time"
                      value={r.start}
                      onChange={(e) => set(i, { start: e.target.value })}
                      className="w-32"
                    />
                  )}
                </Field>
                <Field label="To">
                  {(c) => (
                    <Input
                      {...c}
                      type="time"
                      value={r.end}
                      onChange={(e) => set(i, { end: e.target.value })}
                      className="w-32"
                    />
                  )}
                </Field>
                <Field label="Break from">
                  {(c) => (
                    <Input
                      {...c}
                      type="time"
                      value={r.breakStart}
                      onChange={(e) => set(i, { breakStart: e.target.value })}
                      className="w-32"
                    />
                  )}
                </Field>
                <Field label="Break to">
                  {(c) => (
                    <Input
                      {...c}
                      type="time"
                      value={r.breakEnd}
                      onChange={(e) => set(i, { breakEnd: e.target.value })}
                      className="w-32"
                    />
                  )}
                </Field>
              </div>
            ) : (
              <span className="text-sm text-muted-foreground">Day off</span>
            )}
          </li>
        ))}
      </ul>
      <Button type="submit" className="mt-4" loading={save.isPending}>
        Save working hours
      </Button>
    </form>
  )
}

function TimeOffPanel({ id }: { id: string }) {
  const off = useTimeOff(id)
  const add = useAddTimeOff(id)
  const remove = useRemoveTimeOff(id)
  const { toast } = useToast()
  const [form, setForm] = React.useState({ from: '', to: '', reason: 'leave', note: '' })
  const [problem, setProblem] = React.useState<string>()
  return (
    <div className="grid gap-4">
      <form
        noValidate
        aria-label="Add time off"
        className="grid gap-3 sm:grid-cols-4"
        onSubmit={async (event) => {
          event.preventDefault()
          setProblem(undefined)
          try {
            const created = await add.mutateAsync({
              starts_at: instantAt(form.from, 0),
              ends_at: instantAt(form.to, 24 * 60),
              reason: form.reason,
              note: form.note || undefined,
            })
            toast({
              tone: created.affected_appointments ? 'warning' : 'success',
              title: created.affected_appointments
                ? `Saved. ${created.affected_appointments} booked visits fall in this period and need to be moved.`
                : 'Time off saved.',
            })
            setForm({ from: '', to: '', reason: 'leave', note: '' })
          } catch (error) {
            setProblem(message(error))
          }
        }}
      >
        <div className="sm:col-span-4">
          <FormAlert message={problem} />
        </div>
        <Field label="First day off" required>
          {(c) => (
            <Input
              {...c}
              type="date"
              value={form.from}
              onChange={(e) =>
                setForm({ ...form, from: e.target.value, to: form.to || e.target.value })
              }
            />
          )}
        </Field>
        <Field label="Last day off" required>
          {(c) => (
            <Input
              {...c}
              type="date"
              value={form.to}
              onChange={(e) => setForm({ ...form, to: e.target.value })}
            />
          )}
        </Field>
        <Field label="Reason">
          {(c) => (
            <select
              {...c}
              className={cn(controlClasses, 'h-11')}
              value={form.reason}
              onChange={(e) => setForm({ ...form, reason: e.target.value })}
            >
              <option value="leave">Leave</option>
              <option value="holiday">Holiday</option>
              <option value="training">Training</option>
            </select>
          )}
        </Field>
        <div className="flex items-end">
          <Button type="submit" disabled={!form.from || !form.to} loading={add.isPending}>
            Add time off
          </Button>
        </div>
      </form>
      <ul className="grid gap-2">
        {off.data?.map((t) => (
          <li
            key={t.id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-card p-3 text-sm"
          >
            <span>
              {longDay(t.starts_at)} to{' '}
              {longDay(new Date(new Date(t.ends_at).getTime() - 60_000).toISOString())}{' '}
              <Badge tone="brand" className="capitalize">
                {t.reason}
              </Badge>
            </span>
            <Button size="sm" variant="ghost" onClick={() => remove.mutate(t.id)}>
              Remove <span className="sr-only">this time off</span>
            </Button>
          </li>
        ))}
        {off.data?.length === 0 && (
          <li className="text-sm text-muted-foreground">No time off planned.</li>
        )}
      </ul>
    </div>
  )
}

function Services({ dentist }: { dentist: DentistAdmin }) {
  const services = useAdminServices()
  const update = useUpdateDentist()
  const { toast } = useToast()
  const picked = new Set(dentist.service_ids)
  return (
    <fieldset>
      <legend className="mb-2 text-sm font-medium">Services this dentist offers</legend>
      <ul className="grid gap-1 sm:grid-cols-2">
        {services.data?.map((s) => (
          <li key={s.id} className="flex items-center gap-2 text-sm">
            <Checkbox
              id={`svc-${s.id}`}
              checked={picked.has(s.id)}
              onCheckedChange={(v) => {
                const next = new Set(picked)
                if (v === true) next.add(s.id)
                else next.delete(s.id)
                update.mutate(
                  { id: dentist.id, changes: { service_ids: [...next] } },
                  { onSuccess: () => toast({ tone: 'success', title: 'Services updated.' }) },
                )
              }}
            />
            <label htmlFor={`svc-${s.id}`}>{s.name}</label>
          </li>
        ))}
      </ul>
    </fieldset>
  )
}

export function DentistsPage() {
  const dentists = useAdminDentists()
  const update = useUpdateDentist()
  const [selected, setSelected] = React.useState<string>('')
  const current = dentists.data?.find((d) => d.id === selected) ?? dentists.data?.[0]

  if (dentists.isLoading) return <Skeleton className="h-64 w-full" />
  return (
    <div>
      <h1 className="text-3xl">Dentists and hours</h1>
      <div className="mt-4 flex flex-wrap items-end gap-4">
        <Field label="Dentist">
          {(c) => (
            <select
              {...c}
              className={cn(controlClasses, 'h-11 w-64')}
              value={current?.id ?? ''}
              onChange={(e) => setSelected(e.target.value)}
            >
              {dentists.data?.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.full_name}
                  {d.is_active ? '' : ' (inactive)'}
                </option>
              ))}
            </select>
          )}
        </Field>
        {current && (
          <Button
            variant="secondary"
            onClick={() =>
              update.mutate({ id: current.id, changes: { is_active: !current.is_active } })
            }
          >
            {current.is_active ? 'Stop offering bookings' : 'Offer bookings again'}
          </Button>
        )}
      </div>
      {current && (
        <div className="mt-8 grid gap-10" key={current.id}>
          <section aria-labelledby="hours">
            <h2 id="hours" className="mb-3 text-xl">
              Weekly working hours
            </h2>
            <Hours id={current.id} />
          </section>
          <section aria-labelledby="off">
            <h2 id="off" className="mb-3 text-xl">
              Time off
            </h2>
            <TimeOffPanel id={current.id} />
          </section>
          <section aria-labelledby="offered">
            <h2 id="offered" className="mb-3 text-xl">
              Services
            </h2>
            <Services dentist={current} />
          </section>
        </div>
      )}
    </div>
  )
}
