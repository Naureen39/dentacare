import { zodResolver } from '@hookform/resolvers/zod'
import { Download, Receipt } from 'lucide-react'
import * as React from 'react'
import { useForm } from 'react-hook-form'
import { Link, useParams } from 'react-router-dom'
import { z } from 'zod'

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
import { Input } from '@/components/ui/input'
import { EmptyState } from '@/components/ui/navigation'
import { useToast } from '@/components/ui/toast'
import { ApiError } from '@/lib/api-client'
import { FormAlert } from '@/lib/auth-forms'
import { saveFile } from '@/lib/download'
import {
  downloadInvoice,
  useInvoice,
  useInvoices,
  usePayInvoice,
  type Invoice,
} from '@/lib/portal-api'
import { longDay, money } from '@/pages/portal/format'

const statusTone = {
  issued: 'warning',
  partially_paid: 'warning',
  paid: 'success',
  void: 'neutral',
  draft: 'neutral',
} as const
const statusLabel = {
  issued: 'Due',
  partially_paid: 'Part paid',
  paid: 'Paid',
  void: 'Void',
  draft: 'Draft',
} as const

// --- the list --------------------------------------------------------------------------------------

export function BillingPage() {
  const invoices = useInvoices()
  return (
    <div>
      <h1 className="text-3xl">Billing</h1>
      <div className="mt-6">
        {invoices.isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : invoices.isError ? (
          <FormAlert message="We could not load your invoices. Please try again." />
        ) : !invoices.data?.length ? (
          <EmptyState
            icon={<Receipt className="size-6" aria-hidden="true" />}
            title="No invoices yet"
            description="After a visit, your invoice appears here."
          />
        ) : (
          <div className="overflow-x-auto rounded-xl border bg-card">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Your invoices</caption>
              <thead className="bg-muted text-xs uppercase">
                <tr>
                  <th scope="col" className="p-3">
                    Invoice
                  </th>
                  <th scope="col" className="p-3">
                    Date
                  </th>
                  <th scope="col" className="p-3 text-right">
                    Total
                  </th>
                  <th scope="col" className="p-3 text-right">
                    Balance
                  </th>
                  <th scope="col" className="p-3">
                    Status
                  </th>
                  <th scope="col" className="p-3">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {invoices.data.map((invoice) => (
                  <tr key={invoice.id} className="border-t">
                    <th scope="row" className="p-3 font-semibold">
                      {invoice.display_number}
                    </th>
                    <td className="p-3">{longDay(invoice.issued_at)}</td>
                    <td className="p-3 text-right">{money(invoice.total)}</td>
                    <td className="p-3 text-right">{money(invoice.balance)}</td>
                    <td className="p-3">
                      <Badge tone={statusTone[invoice.status]}>{statusLabel[invoice.status]}</Badge>
                    </td>
                    <td className="p-3 text-right">
                      <Link to={`/portal/billing/${invoice.id}`} className="font-semibold">
                        View <span className="sr-only">invoice {invoice.display_number}</span>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// --- paying --------------------------------------------------------------------------------------------

const payment = z.object({
  amount: z.string().refine((v) => Number(v) > 0, 'Enter an amount greater than zero.'),
  number: z
    .string()
    .transform((v) => v.replace(/[ -]/g, ''))
    .pipe(z.string().regex(/^\d{12,19}$/, 'Enter the card number, digits only.')),
  expMonth: z.coerce
    .number()
    .int()
    .min(1, 'Enter a month from 1 to 12.')
    .max(12, 'Enter a month from 1 to 12.'),
  expYear: z.coerce.number().int().min(0, 'Enter the year.').max(2100, 'Enter the year.'),
  cvv: z.string().regex(/^\d{3,4}$/, 'Enter the 3 or 4 digit security code.'),
  cardholder: z.string().trim().max(100),
})
type PaymentForm = z.input<typeof payment>

function PayDialog({
  invoice,
  open,
  onClose,
}: {
  invoice: Invoice
  open: boolean
  onClose: () => void
}) {
  const { toast } = useToast()
  const pay = usePayInvoice(invoice.id)
  const form = useForm<PaymentForm, unknown, z.output<typeof payment>>({
    resolver: zodResolver(payment),
    defaultValues: {
      amount: Number(invoice.balance).toFixed(2),
      number: '',
      expMonth: '',
      expYear: '',
      cvv: '',
      cardholder: '',
    },
  })
  const { errors } = form.formState
  const balance = Number(invoice.balance)
  const failure = pay.error
    ? pay.error instanceof ApiError && pay.error.status < 500
      ? pay.error.message
      : 'We could not take the payment just now. Please try again.'
    : undefined

  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Pay invoice {invoice.display_number}</DialogTitle>
          <DialogDescription>
            This is a demonstration. No real money moves. Use 4242 4242 4242 4242 for an approved
            payment, or 4000 0000 0000 0002 to see a declined one.
          </DialogDescription>
        </DialogHeader>
        <form
          noValidate
          className="mt-4 grid gap-4"
          aria-label="Card payment"
          onSubmit={form.handleSubmit((values) => {
            if (Number(values.amount) > balance) {
              form.setError('amount', { message: `The most you can pay is ${money(balance)}.` })
              return
            }
            pay.mutate(
              {
                amount: Number(values.amount).toFixed(2),
                card: {
                  number: values.number,
                  expMonth: values.expMonth,
                  expYear: values.expYear < 100 ? 2000 + values.expYear : values.expYear,
                  cvv: values.cvv,
                  cardholder: values.cardholder,
                },
              },
              {
                onSuccess: () => {
                  toast({ tone: 'success', title: 'Payment received. Thank you.' })
                  form.reset()
                  onClose()
                },
              },
            )
          })}
        >
          <FormAlert message={failure} />
          <Field
            label="Amount to pay"
            error={errors.amount?.message}
            hint={`Balance ${money(balance)}`}
          >
            {(c) => <Input {...c} inputMode="decimal" {...form.register('amount')} />}
          </Field>
          <Field label="Card number" error={errors.number?.message}>
            {(c) => (
              <Input
                {...c}
                inputMode="numeric"
                autoComplete="cc-number"
                {...form.register('number')}
              />
            )}
          </Field>
          <div className="grid grid-cols-3 gap-3">
            <Field label="Month" error={errors.expMonth?.message}>
              {(c) => (
                <Input
                  {...c}
                  inputMode="numeric"
                  autoComplete="cc-exp-month"
                  placeholder="MM"
                  {...form.register('expMonth')}
                />
              )}
            </Field>
            <Field label="Year" error={errors.expYear?.message}>
              {(c) => (
                <Input
                  {...c}
                  inputMode="numeric"
                  autoComplete="cc-exp-year"
                  placeholder="YY"
                  {...form.register('expYear')}
                />
              )}
            </Field>
            <Field label="Security code" error={errors.cvv?.message}>
              {(c) => (
                <Input {...c} inputMode="numeric" autoComplete="cc-csc" {...form.register('cvv')} />
              )}
            </Field>
          </div>
          <Field label="Name on card (optional)" error={errors.cardholder?.message}>
            {(c) => <Input {...c} autoComplete="cc-name" {...form.register('cardholder')} />}
          </Field>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={pay.isPending}>
              Pay now
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// --- one invoice ----------------------------------------------------------------------------------------

export function InvoicePage() {
  const { id } = useParams()
  const invoice = useInvoice(id)
  const [paying, setPaying] = React.useState(false)
  const [downloading, setDownloading] = React.useState(false)
  const [problem, setProblem] = React.useState<string>()

  if (invoice.isLoading) return <Skeleton className="h-64 w-full" />
  if (invoice.isError || !invoice.data)
    return (
      <div>
        <FormAlert message="We could not find that invoice." />
        <Link to="/portal/billing" className="mt-4 inline-block font-semibold">
          Back to billing
        </Link>
      </div>
    )
  const data = invoice.data
  const owing = Number(data.balance) > 0 && data.status !== 'void' && data.status !== 'paid'

  return (
    <div>
      <Link to="/portal/billing" className="text-sm font-semibold">
        Back to billing
      </Link>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl">Invoice {data.display_number}</h1>
        <Badge tone={statusTone[data.status]}>{statusLabel[data.status]}</Badge>
      </div>
      <p className="text-muted-foreground">Issued {longDay(data.issued_at)}</p>

      <div className="mt-6 overflow-x-auto rounded-xl border bg-card">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Items on this invoice</caption>
          <thead className="bg-muted text-xs uppercase">
            <tr>
              <th scope="col" className="p-3">
                Item
              </th>
              <th scope="col" className="p-3 text-right">
                Qty
              </th>
              <th scope="col" className="p-3 text-right">
                Price
              </th>
              <th scope="col" className="p-3 text-right">
                Amount
              </th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((item) => (
              <tr key={item.id} className="border-t">
                <th scope="row" className="p-3 font-normal">
                  {item.description}
                </th>
                <td className="p-3 text-right">{item.qty}</td>
                <td className="p-3 text-right">{money(item.unit_price)}</td>
                <td className="p-3 text-right">{money(item.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <dl className="mt-4 ml-auto grid max-w-xs grid-cols-2 gap-x-6 gap-y-1 text-sm">
        <dt>Subtotal</dt>
        <dd className="text-right">{money(data.subtotal)}</dd>
        {Number(data.discount) > 0 && (
          <>
            <dt>Discount</dt>
            <dd className="text-right">-{money(data.discount)}</dd>
          </>
        )}
        {Number(data.tax) > 0 && (
          <>
            <dt>Tax</dt>
            <dd className="text-right">{money(data.tax)}</dd>
          </>
        )}
        <dt className="font-semibold">Total</dt>
        <dd className="text-right font-semibold">{money(data.total)}</dd>
        {Number(data.insurance_expected) > 0 && (
          <>
            <dt>Expected from insurance</dt>
            <dd className="text-right">{money(data.insurance_expected)}</dd>
          </>
        )}
        <dt>Paid</dt>
        <dd className="text-right">{money(data.paid)}</dd>
        <dt className="font-semibold">Balance</dt>
        <dd className="text-right font-semibold">{money(data.balance)}</dd>
      </dl>

      <FormAlert message={problem} />
      <div className="mt-6 flex flex-wrap gap-3">
        <Button
          variant="secondary"
          loading={downloading}
          onClick={async () => {
            setDownloading(true)
            setProblem(undefined)
            try {
              saveFile(await downloadInvoice(data.id), `invoice-${data.display_number}.pdf`)
            } catch {
              setProblem('We could not download the invoice. Please try again.')
            } finally {
              setDownloading(false)
            }
          }}
        >
          <Download aria-hidden="true" /> Download PDF
        </Button>
        {owing && <Button onClick={() => setPaying(true)}>Pay now</Button>}
      </div>

      <section className="mt-10" aria-labelledby="payments">
        <h2 id="payments" className="text-xl">
          Payment history
        </h2>
        {data.payments.length === 0 ? (
          <p className="mt-2 text-muted-foreground">No payments yet.</p>
        ) : (
          <ul className="mt-3 grid gap-2">
            {data.payments.map((p) => (
              <li
                key={p.id}
                className="flex flex-wrap justify-between gap-2 rounded-lg border bg-card p-3 text-sm"
              >
                <span>
                  {longDay(p.paid_at)}
                  {p.card_last4 ? `, card ending ${p.card_last4}` : ''}
                  {p.sandbox ? ' (demonstration)' : ''}
                </span>
                <span className="font-semibold">{money(p.amount)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <PayDialog invoice={data} open={paying} onClose={() => setPaying(false)} />
    </div>
  )
}
