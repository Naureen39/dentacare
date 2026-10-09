import { Printer } from 'lucide-react'
import * as React from 'react'
import { Link, useParams } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Badge, Skeleton } from '@/components/ui/display'
import { DataTable, type Column } from '@/components/ui/data-table'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input, controlClasses } from '@/components/ui/input'
import { useToast } from '@/components/ui/toast'
import {
  fetchInvoicePdf,
  useDeskInvoice,
  useInvoiceAction,
  useInvoiceList,
  type InvoiceRow,
} from '@/console/api'
import { ApiError } from '@/lib/api-client'
import { FormAlert } from '@/lib/auth-forms'
import { cn } from '@/lib/utils'
import { longDay, money } from '@/pages/portal/format'

const tone = {
  draft: 'neutral',
  issued: 'warning',
  partially_paid: 'warning',
  paid: 'success',
  void: 'danger',
} as const
const label = {
  draft: 'Draft',
  issued: 'Due',
  partially_paid: 'Part paid',
  paid: 'Paid',
  void: 'Void',
} as const

const reason = (error: unknown) =>
  error instanceof ApiError && error.status < 500
    ? error.message
    : 'That did not work. Please try again.'

export function BillingDeskPage() {
  const [filter, setFilter] = React.useState<'open' | 'all' | 'draft' | 'paid'>('open')
  const [q, setQ] = React.useState('')
  const list = useInvoiceList({
    openOnly: filter === 'open',
    status: filter === 'draft' || filter === 'paid' ? filter : undefined,
    q: q.trim() || undefined,
  })
  const columns: Column<InvoiceRow>[] = [
    {
      key: 'number',
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
      key: 'total',
      header: 'Total',
      align: 'right',
      sortValue: (i) => Number(i.total),
      cell: (i) => money(i.total),
    },
    {
      key: 'balance',
      header: 'Balance',
      align: 'right',
      sortValue: (i) => Number(i.balance),
      cell: (i) => money(i.balance),
    },
    {
      key: 'status',
      header: 'Status',
      cell: (i) => <Badge tone={tone[i.status]}>{label[i.status]}</Badge>,
    },
  ]
  return (
    <div>
      <h1 className="text-3xl">Billing desk</h1>
      <div className="mt-4 flex flex-wrap items-end gap-4">
        <Field label="Show">
          {(c) => (
            <select
              {...c}
              className={cn(controlClasses, 'h-11 w-48')}
              value={filter}
              onChange={(e) => setFilter(e.target.value as typeof filter)}
            >
              <option value="open">Open invoices</option>
              <option value="draft">Drafts to issue</option>
              <option value="paid">Paid</option>
              <option value="all">All</option>
            </select>
          )}
        </Field>
        <Field label="Search by patient name">
          {(c) => <Input {...c} type="search" value={q} onChange={(e) => setQ(e.target.value)} />}
        </Field>
      </div>
      <div className="mt-6">
        <DataTable
          caption="Invoices"
          columns={columns}
          rows={list.data ?? []}
          getRowId={(i) => i.id}
          loading={list.isLoading}
          emptyTitle="No invoices here"
          pageSize={15}
        />
      </div>
    </div>
  )
}

function PayDialog({
  id,
  balance,
  open,
  onClose,
}: {
  id: string
  balance: number
  open: boolean
  onClose: () => void
}) {
  const act = useInvoiceAction(id)
  const { toast } = useToast()
  const [amount, setAmount] = React.useState(balance.toFixed(2))
  const [method, setMethod] = React.useState('cash')
  const [ref, setRef] = React.useState('')
  const [problem, setProblem] = React.useState<string>()
  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Record a payment</DialogTitle>
          <DialogDescription>Balance {money(balance)}.</DialogDescription>
        </DialogHeader>
        <form
          noValidate
          aria-label="Record a payment"
          className="grid gap-4"
          onSubmit={async (event) => {
            event.preventDefault()
            setProblem(undefined)
            try {
              await act.mutateAsync({
                action: 'pay',
                body: { amount, method, reference: ref || null },
              })
              toast({ tone: 'success', title: 'Payment recorded.' })
              onClose()
            } catch (error) {
              setProblem(reason(error))
            }
          }}
        >
          <FormAlert message={problem} />
          <Field label="Amount">
            {(c) => (
              <Input
                {...c}
                inputMode="decimal"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
            )}
          </Field>
          <Field label="Method">
            {(c) => (
              <select
                {...c}
                className={cn(controlClasses, 'h-11')}
                value={method}
                onChange={(e) => setMethod(e.target.value)}
              >
                <option value="cash">Cash</option>
                <option value="bank_transfer">Bank transfer</option>
                <option value="insurance">Insurance payment</option>
              </select>
            )}
          </Field>
          <Field label="Reference (optional)">
            {(c) => <Input {...c} value={ref} onChange={(e) => setRef(e.target.value)} />}
          </Field>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={act.isPending}>
              Record payment
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function DeskInvoicePage() {
  const { id = '' } = useParams()
  const invoice = useDeskInvoice(id)
  const act = useInvoiceAction(id)
  const { toast } = useToast()
  const [paying, setPaying] = React.useState(false)
  const [voiding, setVoiding] = React.useState(false)
  const [why, setWhy] = React.useState('')
  const [problem, setProblem] = React.useState<string>()

  if (invoice.isLoading) return <Skeleton className="h-64 w-full" />
  if (invoice.isError || !invoice.data)
    return (
      <div>
        <FormAlert message="We could not find that invoice." />
        <Link to="/staff/billing" className="font-semibold">
          Back to billing
        </Link>
      </div>
    )
  const d = invoice.data
  const balance = Number(d.balance)
  const run = async (task: () => Promise<unknown>, done: string) => {
    setProblem(undefined)
    try {
      await task()
      toast({ tone: 'success', title: done })
    } catch (error) {
      setProblem(reason(error))
    }
  }
  const print = async () => {
    const blob = await fetchInvoicePdf(id)
    const url = URL.createObjectURL(blob)
    const win = window.open(url, '_blank')
    win?.addEventListener('load', () => win.print())
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }

  return (
    <div>
      <Link to="/staff/billing" className="text-sm font-semibold">
        Back to billing
      </Link>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl">Invoice {d.display_number}</h1>
        <Badge tone={tone[d.status]}>{label[d.status]}</Badge>
      </div>
      <p className="text-muted-foreground">
        {d.patient_name}, issued {longDay(d.issued_at)}
      </p>
      <FormAlert message={problem} />

      <div className="mt-6 overflow-x-auto rounded-xl border bg-card">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Items</caption>
          <thead className="bg-muted text-xs uppercase">
            <tr>
              <th scope="col" className="p-3">
                Item
              </th>
              <th scope="col" className="p-3 text-right">
                Qty
              </th>
              <th scope="col" className="p-3 text-right">
                Amount
              </th>
            </tr>
          </thead>
          <tbody>
            {d.items.map((item) => (
              <tr key={item.id} className="border-t">
                <th scope="row" className="p-3 font-normal">
                  {item.description}
                </th>
                <td className="p-3 text-right">{item.qty}</td>
                <td className="p-3 text-right">{money(item.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="mt-4 ml-auto grid max-w-xs grid-cols-2 gap-x-6 gap-y-1 text-sm">
        <dt>Subtotal</dt>
        <dd className="text-right">{money(d.subtotal)}</dd>
        {Number(d.discount) > 0 && (
          <>
            <dt>Discount</dt>
            <dd className="text-right">-{money(d.discount)}</dd>
          </>
        )}
        <dt className="font-semibold">Total</dt>
        <dd className="text-right font-semibold">{money(d.total)}</dd>
        <dt>Paid</dt>
        <dd className="text-right">{money(d.paid)}</dd>
        <dt className="font-semibold">Balance</dt>
        <dd className="text-right font-semibold">{money(d.balance)}</dd>
      </dl>

      <div className="mt-6 flex flex-wrap gap-3">
        {d.status === 'draft' && (
          <Button
            loading={act.isPending}
            onClick={() => run(() => act.mutateAsync({ action: 'issue' }), 'Invoice issued.')}
          >
            Issue invoice
          </Button>
        )}
        {(d.status === 'issued' || d.status === 'partially_paid') && balance > 0 && (
          <Button onClick={() => setPaying(true)}>Record payment</Button>
        )}
        {d.status !== 'draft' && d.status !== 'void' && (
          <Button variant="secondary" onClick={() => run(print, 'Opened for printing.')}>
            <Printer aria-hidden="true" /> Print
          </Button>
        )}
        {d.status !== 'void' && d.status !== 'paid' && (
          <Button variant="ghost" onClick={() => setVoiding(true)}>
            Void invoice
          </Button>
        )}
      </div>

      <section className="mt-8" aria-labelledby="payments">
        <h2 id="payments" className="text-xl">
          Payments
        </h2>
        <ul className="mt-3 grid gap-2">
          {d.payments.map((p) => (
            <li
              key={p.id}
              className="flex flex-wrap justify-between gap-2 rounded-lg border bg-card p-3 text-sm"
            >
              <span>
                {longDay(p.paid_at)}, {p.method.replace('_', ' ')}
                {p.card_last4 ? ` ending ${p.card_last4}` : ''}
                {p.reference ? `, ${p.reference}` : ''}
              </span>
              <strong>{money(p.amount)}</strong>
            </li>
          ))}
          {d.payments.length === 0 && (
            <li className="text-sm text-muted-foreground">No payments yet.</li>
          )}
        </ul>
      </section>

      <PayDialog id={id} balance={balance} open={paying} onClose={() => setPaying(false)} />
      <Dialog open={voiding} onOpenChange={setVoiding}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Void this invoice?</DialogTitle>
            <DialogDescription>
              The invoice stays on record, marked void. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <Field label="Reason" required>
            {(c) => <Input {...c} value={why} onChange={(e) => setWhy(e.target.value)} />}
          </Field>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setVoiding(false)}>
              Keep invoice
            </Button>
            <Button
              variant="destructive"
              disabled={why.trim().length < 3}
              loading={act.isPending}
              onClick={() =>
                run(async () => {
                  await act.mutateAsync({ action: 'void', body: { reason: why } })
                  setVoiding(false)
                }, 'Invoice voided.')
              }
            >
              Void invoice
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
