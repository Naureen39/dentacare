import { Clock } from 'lucide-react'
import * as React from 'react'
import { Navigate, Outlet, useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { PageHeader, Section } from '@/components/site/parts'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/display'
import { Stepper } from '@/components/ui/navigation'
import { clinic } from '@/content/site'
import { dentists as dentistContent } from '@/content/people'
import { useAuth } from '@/lib/auth'
import {
  BookingContext,
  stepPath,
  stepsFor,
  useBooking,
  type BookingState,
  type StepName,
} from '@/pages/booking/context'
import { useLiveServices } from '@/lib/booking-api'

/** Counts down the five minutes the server keeps a chosen time for this visitor. */
export function HoldTimer({ expiresAt, onExpire }: { expiresAt: number; onExpire: () => void }) {
  const [now, setNow] = React.useState(() => Date.now())
  const expire = React.useRef(onExpire)
  React.useEffect(() => {
    expire.current = onExpire
  })
  React.useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  const left = Math.max(0, Math.ceil((expiresAt - now) / 1000))
  React.useEffect(() => {
    if (left === 0) expire.current()
  }, [left])
  const minutes = Math.floor(left / 60)
  const seconds = String(left % 60).padStart(2, '0')
  const low = left <= 60
  return (
    <div
      className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${low ? 'border-warning-strong bg-warning-soft text-warning-strong' : 'bg-secondary'}`}
    >
      <Clock className="size-4" aria-hidden="true" />
      <span>
        We are holding this time for you:{' '}
        <span role="timer" className="font-semibold tabular-nums">
          {minutes}:{seconds}
        </span>
      </span>
      {/* Read out only when it matters, not every second. */}
      <span className="sr-only" role="status">
        {left === 60 ? 'One minute left to finish booking.' : ''}
      </span>
    </div>
  )
}

/** Holds the choices across steps, so going back never loses them, and draws the progress. */
export function BookLayout() {
  const auth = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const isPatient = auth.status === 'authenticated' && auth.user?.role === 'patient'
  const [state, setState] = React.useState<BookingState>({ dentistId: null })
  const patch = React.useCallback(
    (changes: Partial<BookingState>) => setState((current) => ({ ...current, ...changes })),
    [],
  )
  const clearTime = React.useCallback(
    () =>
      setState((current) => ({
        ...current,
        choice: undefined,
        hold: undefined,
        conflict: undefined,
        verification: undefined,
      })),
    [],
  )
  const api = React.useMemo(
    () => ({ state, patch, clearTime, isPatient }),
    [state, patch, clearTime, isPatient],
  )

  const steps = stepsFor(isPatient)
  const current = location.pathname.split('/')[2] as StepName | undefined
  const index = Math.max(
    0,
    steps.findIndex((s) => s.name === current),
  )
  const timed = current === 'time' || current === 'details' || current === 'verify'

  return (
    <BookingContext.Provider value={api}>
      <PageHeader
        crumbs={[{ label: 'Book an appointment' }]}
        title="Book an appointment"
        intro="Choose a service, a dentist and a time. It takes about two minutes."
        seo={{
          title: 'Book an appointment',
          description: 'Book a dental appointment online at Meridian Dental Care.',
          path: '/book',
          noindex: true,
        }}
      />
      <Section>
        {auth.status === 'loading' ? (
          <div role="status" aria-label="Loading">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="mt-6 h-64 w-full" />
          </div>
        ) : (
          <>
            {current !== 'done' && (
              <Stepper steps={steps.map((s) => s.label)} current={index} className="mb-8" />
            )}
            {timed && state.hold && (
              <div className="mb-6">
                <HoldTimer
                  expiresAt={state.hold.expiresAt}
                  onExpire={() => {
                    patch({
                      hold: undefined,
                      choice: undefined,
                      conflict: {
                        message:
                          'We could only hold that time for five minutes. Please choose a time again.',
                        alternatives: [],
                      },
                    })
                    void navigate(stepPath('time'))
                  }}
                />
              </div>
            )}
            <Outlet />
          </>
        )}
      </Section>
    </BookingContext.Provider>
  )
}

/** `/book` itself: reads a service and dentist from the link, then goes to the first open step. */
export function BookStart() {
  const [params] = useSearchParams()
  const { state, patch } = useBooking()
  const services = useLiveServices()
  const code = params.get('service')
  const service = services.data?.find((s) => s.code === code)
  const named = dentistContent.find((d) => d.slug === params.get('dentist'))?.name

  React.useEffect(() => {
    if (named && state.preferredDentist !== named) patch({ preferredDentist: named })
    if (service && state.serviceId !== service.id) patch({ serviceId: service.id, dentistId: null })
  }, [service, named, state.serviceId, state.preferredDentist, patch])

  if (code && services.isLoading) {
    return (
      <div role="status" aria-label="Loading">
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  if (service && state.serviceId !== service.id) return null
  return <Navigate to={stepPath(service ? 'dentist' : 'service')} replace />
}

/** The phone number, for when the online service cannot be reached. */
export function PhoneFallback({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border bg-card p-6" role="alert">
      <p className="font-semibold">{children}</p>
      <p className="mt-2 text-sm text-muted-foreground">
        You can still book by phone. Call us on {clinic.phone} and we will find a time.
      </p>
      <Button asChild className="mt-4">
        <a href={clinic.phoneHref}>Call {clinic.phone}</a>
      </Button>
    </div>
  )
}
