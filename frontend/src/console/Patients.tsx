import { zodResolver } from '@hookform/resolvers/zod'
import * as React from 'react'
import { useForm } from 'react-hook-form'
import { Link, useParams } from 'react-router-dom'
import { z } from 'zod'

import { Button } from '@/components/ui/button'
import { Badge, Card, Skeleton } from '@/components/ui/display'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/disclosure'
import { DataTable, type Column } from '@/components/ui/data-table'
import { Field } from '@/components/ui/field'
import { Input, Textarea } from '@/components/ui/input'
import { useToast } from '@/components/ui/toast'
import {
  useAddNote,
  useDuplicates,
  usePatient,
  usePatientHistory,
  usePatientNotes,
  usePatientSearch,
  useUpdatePatient,
  type PatientSummary,
} from '@/console/api'
import { authMessage, FormAlert } from '@/lib/auth-forms'
import { emailField, phoneField, requiredText } from '@/lib/forms'
import { longDay, money } from '@/pages/portal/format'
import { StatusBadge } from '@/pages/portal/shared'

export function PatientsPage() {
  const [query, setQuery] = React.useState('')
  const search = usePatientSearch(query.trim(), true)
  const columns: Column<PatientSummary>[] = [
    {
      key: 'name',
      header: 'Name',
      sortValue: (p) => `${p.last_name} ${p.first_name}`,
      cell: (p) => (
        <Link to={`/staff/patients/${p.id}`} className="font-semibold">
          {p.last_name}, {p.first_name}
        </Link>
      ),
    },
    { key: 'email', header: 'Email', sortValue: (p) => p.email ?? '', cell: (p) => p.email ?? '' },
  ]
  return (
    <div>
      <h1 className="text-3xl">Patients</h1>
      <div className="mt-4 max-w-md">
        <Field label="Search by name" hint="Leave empty to see the first matches.">
          {(c) => (
            <Input
              {...c}
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              autoComplete="off"
            />
          )}
        </Field>
      </div>
      <div className="mt-6">
        <DataTable
          caption="Patients"
          columns={columns}
          rows={search.data ?? []}
          getRowId={(p) => p.id}
          loading={search.isLoading}
          emptyTitle="No patients found"
          emptyDescription="Try a different spelling, or the first letters of the name."
        />
      </div>
    </div>
  )
}

const schema = z.object({
  first_name: requiredText('a first name', 100),
  last_name: requiredText('a last name', 100),
  email: emailField.or(z.literal('')),
  phone: phoneField,
  address: z.string().trim().max(300),
})
type Values = z.infer<typeof schema>

function Details({ id }: { id: string }) {
  const patient = usePatient(id)
  const update = useUpdatePatient(id)
  const { toast } = useToast()
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    values: patient.data && {
      first_name: patient.data.first_name,
      last_name: patient.data.last_name,
      email: patient.data.email ?? '',
      phone: patient.data.phone ?? '',
      address: patient.data.address ?? '',
    },
  })
  const { errors } = form.formState
  if (patient.isLoading) return <Skeleton className="h-48 w-full" />
  return (
    <form
      noValidate
      aria-label="Patient details"
      className="grid gap-4"
      onSubmit={form.handleSubmit((v) =>
        update.mutate(
          {
            first_name: v.first_name,
            last_name: v.last_name,
            email: v.email || null,
            phone: v.phone || null,
            address: v.address || null,
          },
          { onSuccess: () => toast({ tone: 'success', title: 'Saved.' }) },
        ),
      )}
    >
      <FormAlert message={update.isError ? authMessage(update.error) : undefined} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="First name" required error={errors.first_name?.message}>
          {(c) => <Input {...c} {...form.register('first_name')} />}
        </Field>
        <Field label="Last name" required error={errors.last_name?.message}>
          {(c) => <Input {...c} {...form.register('last_name')} />}
        </Field>
        <Field label="Email address" error={errors.email?.message}>
          {(c) => <Input {...c} type="email" {...form.register('email')} />}
        </Field>
        <Field label="Phone" error={errors.phone?.message}>
          {(c) => <Input {...c} type="tel" {...form.register('phone')} />}
        </Field>
      </div>
      <Field label="Address" error={errors.address?.message}>
        {(c) => <Input {...c} {...form.register('address')} />}
      </Field>
      <div>
        <Button type="submit" loading={update.isPending}>
          Save details
        </Button>
      </div>
    </form>
  )
}

function Notes({ id }: { id: string }) {
  const notes = usePatientNotes(id)
  const add = useAddNote(id)
  const [body, setBody] = React.useState('')
  return (
    <div className="grid gap-4">
      <form
        aria-label="Add a note"
        className="grid gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          if (body.trim()) add.mutate(body.trim(), { onSuccess: () => setBody('') })
        }}
      >
        <Field
          label="New note"
          hint="For the front desk: a callback request, a payment arrangement. Stored encrypted."
        >
          {(c) => (
            <Textarea {...c} rows={3} value={body} onChange={(e) => setBody(e.target.value)} />
          )}
        </Field>
        <div>
          <Button type="submit" size="sm" loading={add.isPending} disabled={!body.trim()}>
            Add note
          </Button>
        </div>
      </form>
      <ul className="grid gap-2">
        {notes.data?.map((n) => (
          <li key={n.id} className="rounded-lg border bg-card p-3 text-sm">
            <p>{n.body}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {n.author} on {longDay(n.created_at)}
            </p>
          </li>
        ))}
        {notes.data?.length === 0 && (
          <li className="text-sm text-muted-foreground">No notes yet.</li>
        )}
      </ul>
    </div>
  )
}

export function PatientProfilePage() {
  const { id } = useParams()
  const patient = usePatient(id)
  const history = usePatientHistory(id)
  const duplicates = useDuplicates(id)
  if (!id) return null
  if (patient.isError)
    return (
      <div>
        <FormAlert message="We could not find that patient." />
        <Link to="/staff/patients" className="font-semibold">
          Back to patients
        </Link>
      </div>
    )
  return (
    <div className="grid gap-6">
      <div>
        <Link to="/staff/patients" className="text-sm font-semibold">
          Back to patients
        </Link>
        <h1 className="mt-2 text-3xl">
          {patient.data ? `${patient.data.first_name} ${patient.data.last_name}` : 'Patient'}
        </h1>
      </div>

      {(duplicates.data?.length ?? 0) > 0 && (
        <Card
          className="border-warning-strong bg-warning-soft p-4"
          role="region"
          aria-label="Possible duplicates"
        >
          <h2 className="text-lg">Possible duplicate records</h2>
          <p className="text-sm">
            These records look like the same person. Check them before booking.
          </p>
          <ul className="mt-2 grid gap-1 text-sm">
            {duplicates.data?.map((d) => (
              <li key={d.patient.id}>
                <Link to={`/staff/patients/${d.patient.id}`} className="font-semibold">
                  {d.patient.first_name} {d.patient.last_name}
                </Link>{' '}
                {d.patient.email} <Badge tone="warning">{d.reasons.join(', ')}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Tabs defaultValue="details">
        <TabsList aria-label="Patient record">
          <TabsTrigger value="details">Details</TabsTrigger>
          <TabsTrigger value="visits">Visits</TabsTrigger>
          <TabsTrigger value="invoices">Invoices</TabsTrigger>
          <TabsTrigger value="notes">Notes</TabsTrigger>
        </TabsList>
        <TabsContent value="details" className="mt-4">
          <Details id={id} />
        </TabsContent>
        <TabsContent value="visits" className="mt-4">
          {history.isLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : (
            <ul className="grid gap-2">
              {history.data?.appointments.map((a) => (
                <li
                  key={a.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-card p-3 text-sm"
                >
                  <span>
                    <strong>{a.service_name}</strong> with {a.dentist_name}, {longDay(a.start)}
                  </span>
                  <StatusBadge status={a.status} />
                </li>
              ))}
              {history.data?.appointments.length === 0 && (
                <li className="text-sm text-muted-foreground">No visits yet.</li>
              )}
            </ul>
          )}
        </TabsContent>
        <TabsContent value="invoices" className="mt-4">
          <ul className="grid gap-2">
            {history.data?.invoices.map((i) => (
              <li
                key={i.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-card p-3 text-sm"
              >
                <Link to={`/staff/billing/${i.id}`} className="font-semibold">
                  {i.display_number}
                </Link>
                <span>
                  {longDay(i.issued_at)}, total {money(i.total)}, balance {money(i.balance)}
                </span>
              </li>
            ))}
            {history.data?.invoices.length === 0 && (
              <li className="text-sm text-muted-foreground">No invoices yet.</li>
            )}
          </ul>
        </TabsContent>
        <TabsContent value="notes" className="mt-4">
          <Notes id={id} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
