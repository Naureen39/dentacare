import * as React from 'react'

import { Button } from '@/components/ui/button'
import { Badge, Skeleton } from '@/components/ui/display'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input, Textarea } from '@/components/ui/input'
import { useToast } from '@/components/ui/toast'
import { useAdminServices, useServiceChange, type ServiceAdmin } from '@/console/api'
import { clinicToday } from '@/console/time'
import { ApiError } from '@/lib/api-client'
import { FormAlert } from '@/lib/auth-forms'
import { dateInZone, formatDate } from '@/lib/dates'
import { money } from '@/pages/portal/format'

const message = (error: unknown) =>
  error instanceof ApiError && error.status < 500
    ? error.message
    : 'That did not work. Please try again.'

type Mode =
  | { kind: 'new' }
  | { kind: 'edit'; service: ServiceAdmin }
  | { kind: 'price'; service: ServiceAdmin }

function ServiceDialog({ mode, onClose }: { mode: Mode; onClose: () => void }) {
  const change = useServiceChange()
  const { toast } = useToast()
  const [form, setForm] = React.useState(() => {
    const s = mode.kind === 'new' ? null : mode.service
    return {
      code: '',
      name: mode.kind === 'edit' ? (s?.name ?? '') : '',
      category: mode.kind === 'edit' ? (s?.category ?? 'preventive') : 'preventive',
      description: mode.kind === 'edit' ? (s?.description ?? '') : '',
      duration_min: mode.kind === 'edit' ? String(s?.duration_min ?? 30) : '30',
      base_price: '0.00',
      price: mode.kind === 'price' ? (s?.base_price ?? '') : '',
      effective_from: clinicToday(),
    }
  })
  const [problem, setProblem] = React.useState<string>()

  const title =
    mode.kind === 'new' ? 'New service' : mode.kind === 'edit' ? 'Edit service' : 'Change the price'

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setProblem(undefined)
    try {
      if (mode.kind === 'new') {
        await change.mutateAsync({
          path: '',
          method: 'POST',
          body: {
            code: form.code,
            name: form.name,
            category: form.category,
            description: form.description || null,
            duration_min: Number(form.duration_min),
            base_price: form.base_price,
          },
        })
      } else if (mode.kind === 'edit') {
        await change.mutateAsync({
          path: `/${mode.service.id}`,
          method: 'PATCH',
          body: {
            name: form.name,
            category: form.category,
            description: form.description || null,
            duration_min: Number(form.duration_min),
          },
        })
      } else {
        await change.mutateAsync({
          path: `/${mode.service.id}/price-changes`,
          method: 'POST',
          body: { price: form.price, effective_from: form.effective_from },
        })
      }
      toast({ tone: 'success', title: 'Saved.' })
      onClose()
    } catch (error) {
      setProblem(message(error))
    }
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {mode.kind === 'price' && (
            <DialogDescription>
              {mode.service.name}. A date of today or earlier takes effect at once. A later date
              waits for that day. Invoices already issued keep their price.
            </DialogDescription>
          )}
        </DialogHeader>
        <form noValidate aria-label={title} className="grid gap-4" onSubmit={submit}>
          <FormAlert message={problem} />
          {mode.kind === 'price' ? (
            <>
              <Field label="New price" required>
                {(c) => (
                  <Input
                    {...c}
                    inputMode="decimal"
                    value={form.price}
                    onChange={(e) => setForm({ ...form, price: e.target.value })}
                  />
                )}
              </Field>
              <Field label="Effective from" required>
                {(c) => (
                  <Input
                    {...c}
                    type="date"
                    value={form.effective_from}
                    onChange={(e) => setForm({ ...form, effective_from: e.target.value })}
                  />
                )}
              </Field>
            </>
          ) : (
            <>
              {mode.kind === 'new' && (
                <Field label="Code" required hint="Capital letters and digits, for example SV15.">
                  {(c) => (
                    <Input
                      {...c}
                      value={form.code}
                      onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })}
                    />
                  )}
                </Field>
              )}
              <Field label="Name" required>
                {(c) => (
                  <Input
                    {...c}
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                  />
                )}
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Category" required>
                  {(c) => (
                    <Input
                      {...c}
                      value={form.category}
                      onChange={(e) => setForm({ ...form, category: e.target.value })}
                    />
                  )}
                </Field>
                <Field label="Minutes" required>
                  {(c) => (
                    <Input
                      {...c}
                      inputMode="numeric"
                      value={form.duration_min}
                      onChange={(e) => setForm({ ...form, duration_min: e.target.value })}
                    />
                  )}
                </Field>
              </div>
              {mode.kind === 'new' && (
                <Field label="Starting price" required>
                  {(c) => (
                    <Input
                      {...c}
                      inputMode="decimal"
                      value={form.base_price}
                      onChange={(e) => setForm({ ...form, base_price: e.target.value })}
                    />
                  )}
                </Field>
              )}
              <Field label="Description">
                {(c) => (
                  <Textarea
                    {...c}
                    rows={3}
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                  />
                )}
              </Field>
            </>
          )}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={change.isPending}>
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function ServicesPage() {
  const services = useAdminServices()
  const change = useServiceChange()
  const { toast } = useToast()
  const [mode, setMode] = React.useState<Mode | null>(null)
  const [problem, setProblem] = React.useState<string>()

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
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl">Services and pricing</h1>
        <Button onClick={() => setMode({ kind: 'new' })}>New service</Button>
      </div>
      <FormAlert message={problem} />
      {services.isLoading ? (
        <Skeleton className="mt-6 h-64 w-full" />
      ) : (
        <ul className="mt-6 grid gap-3">
          {services.data?.map((s) => {
            const waiting = s.price_changes.filter((c) => !c.applied_at)
            return (
              <li key={s.id} className="rounded-xl border bg-card p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-heading font-bold text-primary">
                      {s.name}{' '}
                      <span className="text-sm font-normal text-muted-foreground">{s.code}</span>
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {s.category}, {s.duration_min} minutes
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-lg font-bold">{money(s.base_price)}</p>
                    {!s.is_active && <Badge tone="neutral">Hidden</Badge>}
                  </div>
                </div>
                {waiting.length > 0 && (
                  <ul
                    className="mt-2 grid gap-1 text-sm"
                    aria-label={`Waiting price changes for ${s.name}`}
                  >
                    {waiting.map((c) => (
                      <li key={c.id} className="flex items-center gap-2">
                        <Badge tone="warning">Scheduled</Badge>
                        {money(c.price)} from {formatDate(c.effective_from)}
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            run(
                              () =>
                                change.mutateAsync({
                                  path: `/${s.id}/price-changes/${c.id}`,
                                  method: 'DELETE',
                                }),
                              'Price change withdrawn.',
                            )
                          }
                        >
                          Withdraw <span className="sr-only">price change for {s.name}</span>
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => setMode({ kind: 'price', service: s })}
                  >
                    Change price <span className="sr-only">of {s.name}</span>
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => setMode({ kind: 'edit', service: s })}
                  >
                    Edit <span className="sr-only">{s.name}</span>
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      run(
                        () =>
                          change.mutateAsync({
                            path: `/${s.id}`,
                            method: 'PATCH',
                            body: { is_active: !s.is_active },
                          }),
                        s.is_active ? 'Hidden from booking.' : 'Shown for booking.',
                      )
                    }
                  >
                    {s.is_active ? 'Hide' : 'Show'} <span className="sr-only">{s.name}</span>
                  </Button>
                </div>
                {s.price_changes.some((c) => c.applied_at) && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Last changed{' '}
                    {formatDate(
                      dateInZone(
                        s.price_changes.find((c) => c.applied_at)?.applied_at ?? '',
                        'UTC',
                      ),
                      { month: 'long', day: 'numeric', year: 'numeric' },
                    )}
                    .
                  </p>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {mode && <ServiceDialog mode={mode} onClose={() => setMode(null)} />}
    </div>
  )
}
