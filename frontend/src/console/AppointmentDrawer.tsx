import * as React from 'react'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Badge, Skeleton } from '@/components/ui/display'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input, Textarea, controlClasses } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/toggles'
import { useToast } from '@/components/ui/toast'
import {
  useAllDentists,
  useAllServices,
  useAppointment,
  useChangeStatus,
  useCompleteVisit,
  useMoveAppointment,
  useSaveNote,
  type Status,
} from '@/console/api'
import { hhmm, instantAt, minutesOfDay, parseHhmm } from '@/console/time'
import { clinic } from '@/content/site'
import { ApiError } from '@/lib/api-client'
import { useAuth } from '@/lib/auth'
import { FormAlert } from '@/lib/auth-forms'
import { dateInZone } from '@/lib/dates'
import { clock, longDay } from '@/pages/portal/format'
import { StatusBadge } from '@/pages/portal/shared'

const NEXT: Record<Status, { status: Status; label: string }[]> = {
  booked: [
    { status: 'confirmed', label: 'Confirm' },
    { status: 'no_show', label: 'No show' },
    { status: 'cancelled', label: 'Cancel visit' },
  ],
  confirmed: [
    { status: 'checked_in', label: 'Check in' },
    { status: 'no_show', label: 'No show' },
    { status: 'cancelled', label: 'Cancel visit' },
  ],
  checked_in: [],
  completed: [],
  cancelled: [],
  no_show: [],
}

const message = (error: unknown) =>
  error instanceof ApiError && error.status < 500
    ? error.message
    : 'That did not work. Please try again.'

/** Everything about one visit, and what staff can do with it. */
export function AppointmentDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  return (
    <Dialog open={id !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent side="right" className="max-w-lg">
        {id && <DrawerBody key={id} id={id} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  )
}

function DrawerBody({ id, onClose }: { id: string; onClose: () => void }) {
  const { user } = useAuth()
  const { toast } = useToast()
  const detail = useAppointment(id)
  const change = useChangeStatus()
  const complete = useCompleteVisit()
  const move = useMoveAppointment()
  const saveNote = useSaveNote()
  const services = useAllServices()
  const dentists = useAllDentists()
  const [reason, setReason] = React.useState('')
  const [picked, setPicked] = React.useState<string[]>([])
  const [note, setNote] = React.useState<string | null>(null)
  const [moving, setMoving] = React.useState(false)
  const [target, setTarget] = React.useState({ date: '', time: '', dentist: '' })
  const [problem, setProblem] = React.useState<string>()

  if (detail.isLoading) return <Skeleton className="h-64 w-full" />
  if (detail.isError || !detail.data) return <FormAlert message="We could not load this visit." />
  const a = detail.data
  const role = user?.role
  const dentist = role === 'dentist'
  const frontDesk = role === 'admin' || role === 'receptionist'
  const actions = NEXT[a.status].filter((n) => !dentist || n.status === 'no_show')
  const canComplete = a.status === 'checked_in' && (dentist || frontDesk)
  const canMove = frontDesk && (a.status === 'booked' || a.status === 'confirmed')
  const noteText = note ?? a.clinical_note ?? ''
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
    <>
      <DialogHeader>
        <DialogTitle>{a.patient_name}</DialogTitle>
        <DialogDescription>
          {a.service_name} with {a.dentist_name}
        </DialogDescription>
      </DialogHeader>
      <div className="flex items-center gap-3">
        <StatusBadge status={a.status} />
        <span className="text-sm">
          {longDay(a.start)}, {clock(a.start)} to {clock(a.end)}
        </span>
      </div>
      <FormAlert message={problem} />

      <dl className="grid gap-2 text-sm">
        {a.patient_email && (
          <div>
            <dt className="text-muted-foreground">Email</dt>
            <dd>{a.patient_email}</dd>
          </div>
        )}
        {a.patient_phone && (
          <div>
            <dt className="text-muted-foreground">Phone</dt>
            <dd>
              <a href={`tel:${a.patient_phone}`}>{a.patient_phone}</a>
            </dd>
          </div>
        )}
        {a.reason_note && (
          <div>
            <dt className="text-muted-foreground">Reason for the visit</dt>
            <dd>{a.reason_note}</dd>
          </div>
        )}
      </dl>
      {frontDesk && (
        <Link to={`/staff/patients/${a.patient_id}`} className="text-sm font-semibold">
          Open patient record
        </Link>
      )}

      {actions.length > 0 && (
        <section aria-label="Change status" className="grid gap-3">
          {actions.some((n) => n.status === 'cancelled') && (
            <Field label="Reason, if cancelling">
              {(c) => <Input {...c} value={reason} onChange={(e) => setReason(e.target.value)} />}
            </Field>
          )}
          <div className="flex flex-wrap gap-2">
            {actions.map((n) => (
              <Button
                key={n.status}
                size="sm"
                variant={
                  n.status === 'cancelled' || n.status === 'no_show' ? 'secondary' : 'primary'
                }
                loading={change.isPending && change.variables?.status === n.status}
                onClick={() =>
                  run(
                    () => change.mutateAsync({ id, status: n.status, reason }),
                    `Marked as ${n.label.toLowerCase()}.`,
                  )
                }
              >
                {n.label}
              </Button>
            ))}
          </div>
        </section>
      )}

      {canComplete && (
        <section aria-label="Complete the visit" className="grid gap-3 rounded-xl border p-4">
          <h3 className="font-heading font-bold text-primary">Complete the visit</h3>
          <fieldset>
            <legend className="mb-2 text-sm font-medium">Other services performed</legend>
            <ul className="grid max-h-40 gap-1 overflow-y-auto">
              {(services.data ?? [])
                .filter((s) => s.id !== a.service_id)
                .map((s) => (
                  <li key={s.id} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      id={`perf-${s.id}`}
                      checked={picked.includes(s.id)}
                      onCheckedChange={(checked) =>
                        setPicked((list) =>
                          checked === true ? [...list, s.id] : list.filter((x) => x !== s.id),
                        )
                      }
                    />
                    <label htmlFor={`perf-${s.id}`}>{s.name}</label>
                  </li>
                ))}
            </ul>
          </fieldset>
          <Button
            loading={complete.isPending}
            onClick={() =>
              run(
                () =>
                  complete.mutateAsync({
                    id,
                    serviceIds: picked,
                    note: dentist ? noteText : undefined,
                  }),
                'Visit completed. A draft invoice was prepared.',
              )
            }
          >
            Mark completed
          </Button>
        </section>
      )}

      {dentist && (
        <section aria-label="Private note" className="grid gap-2">
          <Field label="Clinical note" hint="Private. Stored encrypted. Only you can read it.">
            {(c) => (
              <Textarea
                {...c}
                rows={5}
                value={noteText}
                onChange={(e) => setNote(e.target.value)}
              />
            )}
          </Field>
          <div>
            <Button
              size="sm"
              variant="secondary"
              loading={saveNote.isPending}
              onClick={() => run(() => saveNote.mutateAsync({ id, note: noteText }), 'Note saved.')}
            >
              Save note
            </Button>
          </div>
        </section>
      )}

      {canMove && (
        <section aria-label="Move the visit" className="grid gap-3">
          {!moving ? (
            <div>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  setTarget({
                    date: dateInZone(a.start, clinic.timeZone),
                    time: hhmm(minutesOfDay(a.start)),
                    dentist: a.dentist_id,
                  })
                  setMoving(true)
                }}
              >
                Move to another time
              </Button>
            </div>
          ) : (
            <div className="grid gap-3 rounded-xl border p-4">
              <h3 className="font-heading font-bold text-primary">Move the visit</h3>
              <Field label="Dentist">
                {(c) => (
                  <select
                    {...c}
                    className={`${controlClasses} h-11`}
                    value={target.dentist}
                    onChange={(e) => setTarget({ ...target, dentist: e.target.value })}
                  >
                    {dentists.data?.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.full_name}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Date">
                  {(c) => (
                    <Input
                      {...c}
                      type="date"
                      value={target.date}
                      onChange={(e) => setTarget({ ...target, date: e.target.value })}
                    />
                  )}
                </Field>
                <Field label="Time">
                  {(c) => (
                    <Input
                      {...c}
                      type="time"
                      step={900}
                      value={target.time}
                      onChange={(e) => setTarget({ ...target, time: e.target.value })}
                    />
                  )}
                </Field>
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  loading={move.isPending}
                  onClick={() =>
                    run(async () => {
                      await move.mutateAsync({
                        id,
                        start: instantAt(target.date, parseHhmm(target.time)),
                        dentistId: target.dentist,
                      })
                      onClose()
                    }, 'The visit was moved.')
                  }
                >
                  Move visit
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setMoving(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </section>
      )}

      {a.recent_visits.length > 0 && (
        <section aria-label="Recent visits">
          <h3 className="font-heading font-bold text-primary">Recent visits</h3>
          <ul className="mt-2 grid gap-1 text-sm">
            {a.recent_visits.map((v) => (
              <li key={v.id} className="flex justify-between gap-2">
                <span>{v.service_name}</span>
                <span className="text-muted-foreground">{longDay(v.start)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <Badge tone="neutral" className="self-start">
        {a.channel}
      </Badge>
    </>
  )
}
