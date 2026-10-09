import * as React from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input, controlClasses } from '@/components/ui/input'
import { useToast } from '@/components/ui/toast'
import {
  useAllDentists,
  useAllServices,
  useBookForPatient,
  useCreatePatient,
  usePatientSearch,
  type PatientSummary,
} from '@/console/api'
import { clinicToday, instantAt, parseHhmm } from '@/console/time'
import { ApiError } from '@/lib/api-client'
import { FormAlert } from '@/lib/auth-forms'
import { cn } from '@/lib/utils'

export interface NewAppointmentDefaults {
  date?: string
  time?: string
  dentistId?: string
}

/** Book a visit for a patient who rang or walked in, registering them first if they are new. */
export function NewAppointmentDialog({
  open,
  onOpenChange,
  defaults,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  defaults?: NewAppointmentDefaults
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        {open && <Body defaults={defaults} onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
}

function Body({ defaults, onDone }: { defaults?: NewAppointmentDefaults; onDone: () => void }) {
  const { toast } = useToast()
  const services = useAllServices()
  const dentists = useAllDentists()
  const book = useBookForPatient()
  const create = useCreatePatient()
  const [walkIn, setWalkIn] = React.useState(false)
  const [query, setQuery] = React.useState('')
  const [patient, setPatient] = React.useState<PatientSummary | null>(null)
  const [fresh, setFresh] = React.useState({ first_name: '', last_name: '', phone: '', email: '' })
  const [form, setForm] = React.useState({
    service: '',
    dentist: defaults?.dentistId ?? '',
    date: defaults?.date ?? clinicToday(),
    time: defaults?.time ?? '09:00',
    note: '',
  })
  const [problem, setProblem] = React.useState<string>()
  const found = usePatientSearch(query.trim(), query.trim().length >= 2 && !patient && !walkIn)

  const ready =
    form.service &&
    form.dentist &&
    form.date &&
    form.time &&
    (walkIn ? fresh.first_name.trim() && fresh.last_name.trim() : patient)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setProblem(undefined)
    try {
      let patientId = patient?.id
      if (walkIn) {
        const created = await create.mutateAsync(fresh)
        patientId = created.id
      }
      await book.mutateAsync({
        patientId: patientId ?? '',
        serviceId: form.service,
        dentistId: form.dentist,
        start: instantAt(form.date, parseHhmm(form.time)),
        note: form.note,
      })
      toast({ tone: 'success', title: 'The appointment was booked.' })
      onDone()
    } catch (error) {
      setProblem(
        error instanceof ApiError && error.status < 500
          ? error.message
          : 'We could not book that. Please try again.',
      )
    }
  }

  return (
    <form onSubmit={submit} noValidate className="grid gap-4" aria-label="New appointment">
      <DialogHeader>
        <DialogTitle>New appointment</DialogTitle>
        <DialogDescription>
          Staff bookings are not held to the online booking rules, but a time that is already taken
          is refused.
        </DialogDescription>
      </DialogHeader>
      <FormAlert message={problem} />

      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          variant={walkIn ? 'secondary' : 'primary'}
          onClick={() => setWalkIn(false)}
        >
          Existing patient
        </Button>
        <Button
          type="button"
          size="sm"
          variant={walkIn ? 'primary' : 'secondary'}
          onClick={() => setWalkIn(true)}
        >
          New patient
        </Button>
      </div>

      {walkIn ? (
        <div className="grid grid-cols-2 gap-3">
          <Field label="First name" required>
            {(c) => (
              <Input
                {...c}
                value={fresh.first_name}
                onChange={(e) => setFresh({ ...fresh, first_name: e.target.value })}
              />
            )}
          </Field>
          <Field label="Last name" required>
            {(c) => (
              <Input
                {...c}
                value={fresh.last_name}
                onChange={(e) => setFresh({ ...fresh, last_name: e.target.value })}
              />
            )}
          </Field>
          <Field label="Phone">
            {(c) => (
              <Input
                {...c}
                type="tel"
                value={fresh.phone}
                onChange={(e) => setFresh({ ...fresh, phone: e.target.value })}
              />
            )}
          </Field>
          <Field label="Email address">
            {(c) => (
              <Input
                {...c}
                type="email"
                value={fresh.email}
                onChange={(e) => setFresh({ ...fresh, email: e.target.value })}
              />
            )}
          </Field>
        </div>
      ) : patient ? (
        <div className="flex items-center justify-between rounded-lg border p-3 text-sm">
          <span>
            <strong>
              {patient.first_name} {patient.last_name}
            </strong>{' '}
            {patient.email}
          </span>
          <Button type="button" size="sm" variant="ghost" onClick={() => setPatient(null)}>
            Change
          </Button>
        </div>
      ) : (
        <div>
          <Field label="Find a patient" hint="Type at least two letters of the name.">
            {(c) => <Input {...c} value={query} onChange={(e) => setQuery(e.target.value)} />}
          </Field>
          {(found.data?.length ?? 0) > 0 && (
            <ul
              className="mt-2 max-h-40 overflow-y-auto rounded-lg border"
              aria-label="Matching patients"
            >
              {found.data?.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    className="flex w-full justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-secondary"
                    onClick={() => setPatient(p)}
                  >
                    <span className="font-medium">
                      {p.first_name} {p.last_name}
                    </span>
                    <span className="text-muted-foreground">{p.email}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Service" required>
          {(c) => (
            <select
              {...c}
              className={cn(controlClasses, 'h-11')}
              value={form.service}
              onChange={(e) => setForm({ ...form, service: e.target.value })}
            >
              <option value="">Choose a service</option>
              {services.data?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Dentist" required>
          {(c) => (
            <select
              {...c}
              className={cn(controlClasses, 'h-11')}
              value={form.dentist}
              onChange={(e) => setForm({ ...form, dentist: e.target.value })}
            >
              <option value="">Choose a dentist</option>
              {dentists.data?.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.full_name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Date" required>
          {(c) => (
            <Input
              {...c}
              type="date"
              value={form.date}
              onChange={(e) => setForm({ ...form, date: e.target.value })}
            />
          )}
        </Field>
        <Field label="Time" required>
          {(c) => (
            <Input
              {...c}
              type="time"
              step={900}
              value={form.time}
              onChange={(e) => setForm({ ...form, time: e.target.value })}
            />
          )}
        </Field>
      </div>
      <Field label="Note (optional)">
        {(c) => (
          <Input
            {...c}
            value={form.note}
            onChange={(e) => setForm({ ...form, note: e.target.value })}
          />
        )}
      </Field>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={!ready} loading={book.isPending || create.isPending}>
          Book appointment
        </Button>
      </div>
    </form>
  )
}
