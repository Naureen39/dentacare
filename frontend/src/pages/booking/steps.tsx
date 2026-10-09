import { useMutation } from '@tanstack/react-query'
import { Clock, Search, Sparkles, UserRound } from 'lucide-react'
import * as React from 'react'
import { Navigate, useNavigate } from 'react-router-dom'

import { TimePicker } from '@/components/booking/TimePicker'
import { Button } from '@/components/ui/button'
import { Avatar, Badge, Skeleton } from '@/components/ui/display'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { dentists as dentistContent } from '@/content/people'
import { groups, serviceByCode } from '@/content/services'
import {
  alternativesOf,
  holdSlot,
  isConflict,
  useAvailability,
  useLiveDentists,
  useLiveServices,
  type TimeChoice,
} from '@/lib/booking-api'
import { clinicToday, monthRange } from '@/lib/booking-time'
import { formatDate, startOfMonth, type DateString } from '@/lib/dates'
import { cn } from '@/lib/utils'
import { stepPath, useBooking } from '@/pages/booking/context'
import { PhoneFallback } from '@/pages/booking/state'

const money = (value: string | number) => `$${Number(value).toLocaleString('en-US')}`

const choiceClass = (selected: boolean) =>
  cn(
    'flex w-full flex-col gap-1 rounded-xl border bg-card p-4 text-left transition-colors hover:border-accent-strong focus-visible:outline-2 focus-visible:outline-ring',
    selected && 'border-primary bg-secondary ring-2 ring-primary',
  )

function Nav({
  back,
  next,
  nextLabel = 'Continue',
  disabled,
  onNext,
}: {
  back?: string
  next?: string
  nextLabel?: string
  disabled?: boolean
  onNext?: () => void
}) {
  const navigate = useNavigate()
  return (
    <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
      {back ? (
        <Button variant="secondary" onClick={() => void navigate(back)}>
          Back
        </Button>
      ) : (
        <span />
      )}
      <Button
        disabled={disabled}
        onClick={() => {
          onNext?.()
          if (next) void navigate(next)
        }}
      >
        {nextLabel}
      </Button>
    </div>
  )
}

// --- step 1 ----------------------------------------------------------------------------------

export function ServiceStep() {
  const { state, patch, clearTime } = useBooking()
  const services = useLiveServices()
  const [query, setQuery] = React.useState('')

  if (services.isLoading) return <Skeleton className="h-64 w-full" />
  if (services.isError || !services.data)
    return <PhoneFallback>We could not load our services just now.</PhoneFallback>

  const choose = (id: string) => {
    if (state.serviceId === id) return
    clearTime()
    patch({ serviceId: id, dentistId: null, dentistName: undefined })
  }
  const needle = query.trim().toLowerCase()
  const shown = services.data.filter(
    (s) => !needle || `${s.name} ${s.description ?? ''}`.toLowerCase().includes(needle),
  )
  const routine = services.data.find((s) => s.code === 'SV02')

  return (
    <div>
      <h2 className="text-2xl">What would you like to book?</h2>
      <div className="mt-4 grid gap-4 md:grid-cols-[1fr_auto] md:items-end">
        <Field label="Search services">
          {(control) => (
            <div className="relative">
              <Search
                className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                {...control}
                type="search"
                className="pl-9"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="For example cleaning, crown or whitening"
              />
            </div>
          )}
        </Field>
        {routine && (
          <Button variant="secondary" onClick={() => choose(routine.id)}>
            <Sparkles aria-hidden="true" /> I am not sure
          </Button>
        )}
      </div>
      {routine && state.serviceId === routine.id && (
        <p className="mt-3 rounded-md bg-secondary p-3 text-sm" role="status">
          Not sure what you need? A Routine Exam and Cleaning is the right start for most people.
          Your dentist will talk through anything else at the visit.
        </p>
      )}
      <ul className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Services">
        {shown.map((service) => {
          const content = serviceByCode(service.code)
          const selected = state.serviceId === service.id
          return (
            <li key={service.id}>
              <button
                type="button"
                aria-pressed={selected}
                onClick={() => choose(service.id)}
                className={choiceClass(selected)}
              >
                <span className="font-heading font-bold text-primary">{service.name}</span>
                {content && (
                  <span className="text-xs text-muted-foreground">
                    {groups[content.group].title}
                  </span>
                )}
                <span className="mt-1 flex items-center gap-3 text-sm text-muted-foreground">
                  <span className="inline-flex items-center gap-1">
                    <Clock className="size-3.5" aria-hidden="true" />
                    {service.duration_min} minutes
                  </span>
                  <span>From {money(service.base_price)}</span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      {shown.length === 0 && (
        <p className="mt-6 text-muted-foreground" role="status">
          No service matches that search.
        </p>
      )}
      <Nav next={stepPath('dentist')} disabled={!state.serviceId} />
    </div>
  )
}

// --- step 2 ----------------------------------------------------------------------------------

export function DentistStep() {
  const { state, patch, clearTime } = useBooking()
  const live = useLiveDentists(state.serviceId)
  const dentists = live.data
  const { preferredDentist } = state
  // A dentist named in the link ("Book with Dr. Raman") is chosen once, when the list is here.
  React.useEffect(() => {
    if (!preferredDentist || !dentists) return
    const match = dentists.find((d) => d.full_name === preferredDentist)
    patch({
      preferredDentist: undefined,
      ...(match ? { dentistId: match.id, dentistName: match.full_name } : {}),
    })
  }, [preferredDentist, dentists, patch])
  if (!state.serviceId) return <Navigate to={stepPath('service')} replace />
  if (live.isLoading) return <Skeleton className="h-64 w-full" />
  if (live.isError || !live.data)
    return <PhoneFallback>We could not load our dentists just now.</PhoneFallback>

  const choose = (id: string | null, name?: string) => {
    if (state.dentistId === id) return
    clearTime()
    patch({ dentistId: id, dentistName: name })
  }
  return (
    <div>
      <h2 className="text-2xl">Who would you like to see?</h2>
      <ul className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Dentists">
        <li>
          <button
            type="button"
            aria-pressed={state.dentistId === null}
            onClick={() => choose(null)}
            className={choiceClass(state.dentistId === null)}
          >
            <span className="flex items-center gap-3">
              <span className="flex size-10 items-center justify-center rounded-full bg-secondary text-accent-strong">
                <UserRound className="size-5" aria-hidden="true" />
              </span>
              <span className="font-heading font-bold text-primary">First available</span>
              <Badge tone="brand">Quickest</Badge>
            </span>
            <span className="text-sm text-muted-foreground">
              We show every open time and match you with the dentist who is free.
            </span>
          </button>
        </li>
        {live.data.map((dentist) => {
          const content = dentistContent.find((d) => d.name === dentist.full_name)
          const selected = state.dentistId === dentist.id
          return (
            <li key={dentist.id}>
              <button
                type="button"
                aria-pressed={selected}
                onClick={() => choose(dentist.id, dentist.full_name)}
                className={choiceClass(selected)}
              >
                <span className="flex items-center gap-3">
                  <Avatar name={dentist.full_name} />
                  <span>
                    <span className="block font-heading font-bold text-primary">
                      {dentist.full_name}
                    </span>
                    <span className="block text-sm text-muted-foreground">
                      {content?.specialty ?? dentist.specialty}
                    </span>
                  </span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      <Nav back={stepPath('service')} next={stepPath('time')} />
    </div>
  )
}

// --- step 3 ----------------------------------------------------------------------------------

export function TimeStep() {
  const { state, patch } = useBooking()
  const today = React.useMemo(() => clinicToday(), [])
  const [month, setMonth] = React.useState<DateString>(startOfMonth(state.choice?.date ?? today))
  const range = monthRange(month, today)
  const times = useAvailability({
    serviceId: state.serviceId,
    dentistId: state.dentistId,
    ...range,
  })

  const hold = useMutation({
    mutationFn: (choice: TimeChoice) =>
      holdSlot({
        serviceId: state.serviceId ?? '',
        dentistId: choice.dentistId,
        start: choice.start,
      }),
    onSuccess: (held, choice) =>
      patch({
        choice,
        hold: { token: held.hold_token, expiresAt: Date.now() + held.expires_in * 1000 },
        conflict: undefined,
      }),
    onError: (error) => {
      patch({
        choice: undefined,
        hold: undefined,
        conflict: isConflict(error)
          ? { message: error.message, alternatives: alternativesOf(error) }
          : { message: 'We could not hold that time. Please try another.', alternatives: [] },
      })
      void times.refetch()
    },
  })

  if (!state.serviceId) return <Navigate to={stepPath('service')} replace />
  const conflict = state.conflict
  const found = state.choice

  return (
    <div>
      <h2 className="text-2xl">Pick a date and time</h2>
      {conflict && (
        <div
          className="mt-4 rounded-xl border border-warning-strong bg-warning-soft p-4"
          role="alert"
        >
          <p className="font-semibold text-warning-strong">{conflict.message}</p>
          {conflict.alternatives.length > 0 && (
            <>
              <p className="mt-2 text-sm">These times are close to the one you chose:</p>
              <ul className="mt-2 flex flex-wrap gap-2">
                {conflict.alternatives.slice(0, 6).map((choice) => (
                  <li key={choice.id}>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => hold.mutate(choice)}
                      disabled={hold.isPending}
                    >
                      {formatDate(choice.date, {
                        weekday: 'short',
                        month: 'short',
                        day: 'numeric',
                      })}
                      , {choice.label} with {choice.dentistName}
                    </Button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
      <div className="mt-6">
        {times.isError ? (
          <PhoneFallback>We could not load the available times just now.</PhoneFallback>
        ) : (
          <TimePicker
            choices={times.data ?? []}
            loading={times.isLoading || times.isFetching}
            value={found?.id}
            showDentist={state.dentistId === null}
            onSelect={(choice) => hold.mutate(choice)}
            onMonthChange={setMonth}
          />
        )}
      </div>
      {found && state.hold && (
        <p className="mt-6 rounded-md bg-secondary p-3 text-sm" role="status">
          Selected: {formatDate(found.date)} at {found.label} with {found.dentistName}.
        </p>
      )}
      <Nav
        back={stepPath('dentist')}
        next={stepPath('details')}
        disabled={!state.hold || hold.isPending}
      />
    </div>
  )
}
