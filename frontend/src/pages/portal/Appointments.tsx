import { useMutation } from '@tanstack/react-query'
import { CalendarClock } from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'

import { TimePicker } from '@/components/booking/TimePicker'
import { clinicToday, monthRange } from '@/lib/booking-time'
import { Button } from '@/components/ui/button'
import { Card, Skeleton } from '@/components/ui/display'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Textarea } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/disclosure'
import { EmptyState } from '@/components/ui/navigation'
import { Checkbox } from '@/components/ui/toggles'
import { useToast } from '@/components/ui/toast'
import { ApiError } from '@/lib/api-client'
import {
  alternativesOf,
  holdSlot,
  isConflict,
  useAvailability,
  useCancelAppointment,
  useMyAppointments,
  useRescheduleAppointment,
  type Appointment,
  type TimeChoice,
} from '@/lib/booking-api'
import { startOfMonth, type DateString } from '@/lib/dates'
import { FormAlert } from '@/lib/auth-forms'
import { clock, hasPassed, isActive, longDay, shortDay } from '@/pages/portal/format'
import { StatusBadge } from '@/pages/portal/shared'

function Row({
  appointment,
  onReschedule,
  onCancel,
}: {
  appointment: Appointment
  onReschedule: (a: Appointment) => void
  onCancel: (a: Appointment) => void
}) {
  const manageable = isActive(appointment)
  return (
    <li>
      <Card className="flex flex-wrap items-center justify-between gap-4 p-4">
        <div>
          <p className="font-heading font-bold text-primary">{appointment.service_name}</p>
          <p className="text-sm">
            {longDay(appointment.start)} at {clock(appointment.start)}
          </p>
          <p className="text-sm text-muted-foreground">with {appointment.dentist_name}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={appointment.status} />
          {manageable && (
            <>
              <Button size="sm" variant="secondary" onClick={() => onReschedule(appointment)}>
                Reschedule <span className="sr-only">{appointment.service_name}</span>
              </Button>
              <Button size="sm" variant="ghost" onClick={() => onCancel(appointment)}>
                Cancel <span className="sr-only">{appointment.service_name}</span>
              </Button>
            </>
          )}
        </div>
      </Card>
    </li>
  )
}

function Policy({ appointment }: { appointment: Appointment }) {
  const late = hasPassed(appointment.free_cancellation_until)
  return late ? (
    <p className="rounded-md bg-warning-soft p-3 text-sm text-warning-strong">
      The free cancellation period ended on {shortDay(appointment.free_cancellation_until)} at{' '}
      {clock(appointment.free_cancellation_until)}. A change now is recorded as a late cancellation.
    </p>
  ) : (
    <p className="rounded-md bg-secondary p-3 text-sm">
      You can change or cancel for free until {shortDay(appointment.free_cancellation_until)} at{' '}
      {clock(appointment.free_cancellation_until)}. After that it is recorded as a late
      cancellation.
    </p>
  )
}

function CancelDialog({
  appointment,
  onClose,
}: {
  appointment: Appointment | null
  onClose: () => void
}) {
  const cancel = useCancelAppointment()
  const { toast } = useToast()
  const [reason, setReason] = React.useState('')
  return (
    <Dialog open={appointment !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        {appointment && (
          <>
            <DialogHeader>
              <DialogTitle>Cancel this appointment?</DialogTitle>
              <DialogDescription>
                {appointment.service_name} on {longDay(appointment.start)} at{' '}
                {clock(appointment.start)} with {appointment.dentist_name}.
              </DialogDescription>
            </DialogHeader>
            <div className="mt-4 grid gap-4">
              <Policy appointment={appointment} />
              <Field label="Reason (optional)">
                {(c) => (
                  <Textarea
                    {...c}
                    rows={2}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                  />
                )}
              </Field>
              <FormAlert
                message={
                  cancel.isError
                    ? 'We could not cancel this appointment. Please try again.'
                    : undefined
                }
              />
            </div>
            <DialogFooter className="mt-6">
              <Button variant="secondary" onClick={onClose}>
                Keep appointment
              </Button>
              <Button
                variant="destructive"
                loading={cancel.isPending}
                onClick={() =>
                  cancel.mutate(
                    { id: appointment.id, reason },
                    {
                      onSuccess: () => {
                        toast({ tone: 'success', title: 'Your appointment has been cancelled.' })
                        setReason('')
                        onClose()
                      },
                    },
                  )
                }
              >
                Cancel appointment
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

function RescheduleBody({
  appointment,
  onClose,
}: {
  appointment: Appointment
  onClose: () => void
}) {
  const { toast } = useToast()
  const today = React.useMemo(() => clinicToday(), [])
  const [month, setMonth] = React.useState<DateString>(startOfMonth(today))
  const [anyDentist, setAnyDentist] = React.useState(false)
  const [chosen, setChosen] = React.useState<{ choice: TimeChoice; token: string } | null>(null)
  const [notice, setNotice] = React.useState<{
    message: string
    alternatives: TimeChoice[]
  } | null>(null)
  const times = useAvailability({
    serviceId: appointment.service_id,
    dentistId: anyDentist ? null : appointment.dentist_id,
    ...monthRange(month, today),
  })
  const reschedule = useRescheduleAppointment()
  const hold = useMutation({
    mutationFn: (choice: TimeChoice) =>
      holdSlot({
        serviceId: appointment.service_id,
        dentistId: choice.dentistId,
        start: choice.start,
      }),
    onSuccess: (held, choice) => {
      setChosen({ choice, token: held.hold_token })
      setNotice(null)
    },
    onError: (error) => {
      setChosen(null)
      setNotice({
        message: isConflict(error)
          ? error.message
          : 'We could not hold that time. Please try another.',
        alternatives: alternativesOf(error),
      })
      void times.refetch()
    },
  })
  const failure =
    reschedule.error && !isConflict(reschedule.error)
      ? reschedule.error instanceof ApiError && reschedule.error.status === 409
        ? reschedule.error.message
        : 'We could not change your appointment. Please try again.'
      : undefined

  return (
    <>
      <DialogHeader>
        <DialogTitle>Reschedule your appointment</DialogTitle>
        <DialogDescription>
          {appointment.service_name} with {appointment.dentist_name}, now on{' '}
          {longDay(appointment.start)} at {clock(appointment.start)}.
        </DialogDescription>
      </DialogHeader>
      <div className="mt-4 grid gap-4">
        <Policy appointment={appointment} />
        <div className="flex items-center gap-3">
          <Checkbox
            id="any-dentist"
            checked={anyDentist}
            onCheckedChange={(value) => {
              setAnyDentist(value === true)
              setChosen(null)
            }}
          />
          <label htmlFor="any-dentist" className="text-sm">
            Show times with other dentists too
          </label>
        </div>
        {notice && (
          <div role="alert" className="rounded-md border border-warning-strong bg-warning-soft p-3">
            <p className="font-semibold text-warning-strong">{notice.message}</p>
            {notice.alternatives.length > 0 && (
              <ul className="mt-2 flex flex-wrap gap-2">
                {notice.alternatives.slice(0, 5).map((choice) => (
                  <li key={choice.id}>
                    <Button size="sm" variant="secondary" onClick={() => hold.mutate(choice)}>
                      {shortDay(choice.start)}, {choice.label}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <TimePicker
          choices={times.data ?? []}
          loading={times.isLoading || times.isFetching}
          value={chosen?.choice.id}
          showDentist={anyDentist}
          onSelect={(choice) => hold.mutate(choice)}
          onMonthChange={setMonth}
        />
        <FormAlert message={failure} />
      </div>
      <DialogFooter className="mt-6">
        <Button variant="secondary" onClick={onClose}>
          Keep current time
        </Button>
        <Button
          disabled={!chosen}
          loading={reschedule.isPending}
          onClick={() =>
            chosen &&
            reschedule.mutate(
              {
                id: appointment.id,
                start: chosen.choice.start,
                dentistId: chosen.choice.dentistId,
                holdToken: chosen.token,
              },
              {
                onSuccess: () => {
                  toast({ tone: 'success', title: 'Your appointment has been moved.' })
                  onClose()
                },
                onError: (error) => {
                  if (isConflict(error)) {
                    setChosen(null)
                    setNotice({ message: error.message, alternatives: alternativesOf(error) })
                  }
                },
              },
            )
          }
        >
          Confirm new time
        </Button>
      </DialogFooter>
    </>
  )
}

function RescheduleDialog({
  appointment,
  onClose,
}: {
  appointment: Appointment | null
  onClose: () => void
}) {
  return (
    <Dialog open={appointment !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto">
        {appointment && (
          <RescheduleBody key={appointment.id} appointment={appointment} onClose={onClose} />
        )}
      </DialogContent>
    </Dialog>
  )
}

function List({
  when,
  onReschedule,
  onCancel,
}: {
  when: 'upcoming' | 'past'
  onReschedule: (a: Appointment) => void
  onCancel: (a: Appointment) => void
}) {
  const query = useMyAppointments(when)
  if (query.isLoading) return <Skeleton className="h-32 w-full" />
  if (query.isError)
    return <FormAlert message="We could not load your appointments. Please try again." />
  if (!query.data?.length)
    return (
      <EmptyState
        icon={<CalendarClock className="size-6" aria-hidden="true" />}
        title={when === 'upcoming' ? 'No upcoming appointments' : 'No past appointments'}
        description={when === 'upcoming' ? 'Book your next visit in two minutes.' : undefined}
        action={
          when === 'upcoming' ? (
            <Button asChild>
              <Link to="/book">Book an appointment</Link>
            </Button>
          ) : undefined
        }
      />
    )
  return (
    <ul className="grid gap-3">
      {query.data.map((appointment) => (
        <Row
          key={appointment.id}
          appointment={appointment}
          onReschedule={onReschedule}
          onCancel={onCancel}
        />
      ))}
    </ul>
  )
}

export function AppointmentsPage() {
  const [rescheduling, setRescheduling] = React.useState<Appointment | null>(null)
  const [cancelling, setCancelling] = React.useState<Appointment | null>(null)
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl">Appointments</h1>
        <Button asChild>
          <Link to="/book">Book an appointment</Link>
        </Button>
      </div>
      <Tabs defaultValue="upcoming" className="mt-6">
        <TabsList aria-label="Appointments">
          <TabsTrigger value="upcoming">Upcoming</TabsTrigger>
          <TabsTrigger value="past">Past</TabsTrigger>
        </TabsList>
        {(['upcoming', 'past'] as const).map((when) => (
          <TabsContent key={when} value={when} className="mt-4">
            <List when={when} onReschedule={setRescheduling} onCancel={setCancelling} />
          </TabsContent>
        ))}
      </Tabs>
      <RescheduleDialog appointment={rescheduling} onClose={() => setRescheduling(null)} />
      <CancelDialog appointment={cancelling} onClose={() => setCancelling(null)} />
    </div>
  )
}
