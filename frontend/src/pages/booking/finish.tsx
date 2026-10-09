import { zodResolver } from '@hookform/resolvers/zod'
import { CalendarPlus, CheckCircle2, MailCheck, MapPin } from 'lucide-react'
import * as React from 'react'
import { Controller, useForm } from 'react-hook-form'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/display'
import { Field } from '@/components/ui/field'
import { Input, Textarea, controlClasses } from '@/components/ui/input'
import { Checkbox, RadioGroup, RadioGroupItem } from '@/components/ui/toggles'
import { serviceByCode } from '@/content/services'
import { clinic, directionsUrl, fullAddress } from '@/content/site'
import { ApiError } from '@/lib/api-client'
import {
  alternativesOf,
  bookAsGuest,
  bookAsPatient,
  isConflict,
  requestCode,
  useInsuranceProviders,
  useLiveServices,
  useProfile,
  useUpdateProfile,
  type BookingTarget,
} from '@/lib/booking-api'
import { dateInZone, formatDate, formatTime } from '@/lib/dates'
import { saveFile } from '@/lib/download'
import { codeField, emailField, phoneField, requiredText } from '@/lib/forms'
import { buildIcs } from '@/lib/ics'
import { FormAlert } from '@/lib/auth-forms'
import { stepPath, useBooking, type Details } from '@/pages/booking/context'

// --- step 4: details -----------------------------------------------------------------------------

const schema = z.object({
  patientType: z.enum(['new', 'returning']),
  firstName: requiredText('your first name', 100),
  lastName: requiredText('your last name', 100),
  email: emailField,
  phone: phoneField,
  insuranceProviderId: z.string(),
  insuranceMemberId: z.string().trim().max(60, 'The member number must be at most 60 characters.'),
  reason: z.string().trim().max(400, 'Please keep the note under 400 characters.'),
  consent: z.boolean().refine((value) => value, {
    message: 'Please accept the privacy policy and appointment reminders to book.',
  }),
  marketing: z.boolean(),
})

const emptyDetails: Details = {
  patientType: 'new',
  firstName: '',
  lastName: '',
  email: '',
  phone: '',
  insuranceProviderId: '',
  insuranceMemberId: '',
  reason: '',
  consent: false,
  marketing: false,
}

function target(state: ReturnType<typeof useBooking>['state'], details: Details): BookingTarget {
  const note = `${details.patientType === 'new' ? 'New patient.' : 'Returning patient.'} ${details.reason}`
  return {
    serviceId: state.serviceId ?? '',
    dentistId: state.choice?.dentistId ?? '',
    start: state.choice?.start ?? '',
    holdToken: state.hold?.token ?? '',
    reasonNote: note.trim().slice(0, 500),
  }
}

export function DetailsStep() {
  const { state, patch, isPatient } = useBooking()
  const navigate = useNavigate()
  const profile = useProfile(isPatient)
  const providers = useInsuranceProviders()
  const updateProfile = useUpdateProfile()
  const [failure, setFailure] = React.useState<string>()
  const form = useForm<Details>({
    resolver: zodResolver(schema),
    defaultValues: state.details ?? emptyDetails,
  })
  const { errors, isSubmitting } = form.formState

  // A signed in patient's details come from their record.
  const loaded = profile.data
  const reset = form.reset
  React.useEffect(() => {
    if (!loaded || state.details) return
    reset({
      ...emptyDetails,
      patientType: 'returning',
      firstName: loaded.first_name,
      lastName: loaded.last_name,
      email: loaded.email ?? '',
      phone: loaded.phone ?? '',
      insuranceProviderId: loaded.insurance_provider_id ?? '',
      insuranceMemberId: loaded.insurance_member_id ?? '',
    })
  }, [loaded, state.details, reset])

  // Once booked, the page is already on its way to the confirmation: do not step back.
  if (state.result) return null
  if (!state.hold || !state.choice) return <Navigate to={stepPath('time')} replace />

  const submit = form.handleSubmit(async (details) => {
    setFailure(undefined)
    patch({ details })
    if (!isPatient) {
      void navigate(stepPath('verify'))
      return
    }
    try {
      const insuranceChanged =
        details.insuranceProviderId !== (loaded?.insurance_provider_id ?? '') ||
        details.insuranceMemberId !== (loaded?.insurance_member_id ?? '')
      if (insuranceChanged) {
        await updateProfile.mutateAsync({
          insurance_provider_id: details.insuranceProviderId || null,
          insurance_member_id: details.insuranceMemberId || null,
        })
      }
      const appointment = await bookAsPatient(target(state, details))
      patch({ result: appointment, hold: undefined, conflict: undefined })
      void navigate(stepPath('done'))
    } catch (error) {
      if (isConflict(error)) {
        patch({
          hold: undefined,
          choice: undefined,
          conflict: {
            message: (error as ApiError).message,
            alternatives: alternativesOf(error),
          },
        })
        void navigate(stepPath('time'))
        return
      }
      setFailure(
        error instanceof ApiError && error.status === 429
          ? 'There have been many booking attempts. Please wait a little, or call us.'
          : `We could not complete your booking. Please try again or call ${clinic.phone}.`,
      )
    }
  })

  return (
    <form noValidate onSubmit={submit} className="grid gap-6" aria-label="Your details">
      <h2 className="text-2xl">Your details</h2>
      <FormAlert message={failure} />

      <Controller
        control={form.control}
        name="patientType"
        render={({ field }) => (
          <fieldset>
            <legend className="mb-2 text-sm font-medium">Are you new to our practice?</legend>
            <RadioGroup
              className="grid-flow-col justify-start gap-6"
              value={field.value}
              onValueChange={field.onChange}
            >
              {(['new', 'returning'] as const).map((value) => (
                <div key={value} className="flex items-center gap-2">
                  <RadioGroupItem value={value} id={`type-${value}`} />
                  <label htmlFor={`type-${value}`} className="text-sm">
                    {value === 'new' ? 'I am a new patient' : 'I have visited before'}
                  </label>
                </div>
              ))}
            </RadioGroup>
          </fieldset>
        )}
      />

      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="First name" required error={errors.firstName?.message}>
          {(c) => <Input {...c} autoComplete="given-name" {...form.register('firstName')} />}
        </Field>
        <Field label="Last name" required error={errors.lastName?.message}>
          {(c) => <Input {...c} autoComplete="family-name" {...form.register('lastName')} />}
        </Field>
        <Field
          label="Email address"
          required
          error={errors.email?.message}
          hint={
            isPatient ? 'This is the address on your account.' : 'We send your confirmation here.'
          }
        >
          {(c) => (
            <Input
              {...c}
              type="email"
              autoComplete="email"
              readOnly={isPatient}
              {...form.register('email')}
            />
          )}
        </Field>
        <Field
          label="Phone"
          error={errors.phone?.message}
          hint="Optional. For urgent changes only."
        >
          {(c) => <Input {...c} type="tel" autoComplete="tel" {...form.register('phone')} />}
        </Field>
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="Insurance provider (optional)">
          {(c) => (
            <select
              {...c}
              className={`${controlClasses} h-11`}
              {...form.register('insuranceProviderId')}
            >
              <option value="">No insurance, or not sure</option>
              {providers.data?.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Member number (optional)" error={errors.insuranceMemberId?.message}>
          {(c) => <Input {...c} autoComplete="off" {...form.register('insuranceMemberId')} />}
        </Field>
      </div>

      <Field
        label="Reason for your visit (optional)"
        hint="Anything the dentist should know, such as pain or a broken tooth."
        error={errors.reason?.message}
      >
        {(c) => <Textarea {...c} rows={3} {...form.register('reason')} />}
      </Field>

      <div className="grid gap-3">
        <Controller
          control={form.control}
          name="consent"
          render={({ field }) => (
            <div className="flex items-start gap-3">
              <Checkbox
                id="consent"
                checked={field.value}
                onCheckedChange={(checked) => field.onChange(checked === true)}
                aria-invalid={errors.consent ? true : undefined}
                aria-describedby={errors.consent ? 'consent-error' : undefined}
                className="mt-0.5"
              />
              <label htmlFor="consent" className="text-sm">
                I have read the <Link to="/privacy">privacy policy</Link> and agree to receive
                appointment confirmations and reminders by email.
              </label>
            </div>
          )}
        />
        {errors.consent && (
          <p id="consent-error" role="alert" className="text-sm font-medium text-destructive">
            {errors.consent.message}
          </p>
        )}
        <Controller
          control={form.control}
          name="marketing"
          render={({ field }) => (
            <div className="flex items-start gap-3">
              <Checkbox
                id="marketing"
                checked={field.value}
                onCheckedChange={(checked) => field.onChange(checked === true)}
                className="mt-0.5"
              />
              <label htmlFor="marketing" className="text-sm">
                Send me occasional news and oral health tips (optional).
              </label>
            </div>
          )}
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button type="button" variant="secondary" onClick={() => void navigate(stepPath('time'))}>
          Back
        </Button>
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Please wait' : isPatient ? 'Book appointment' : 'Continue'}
        </Button>
      </div>
    </form>
  )
}

// --- step 5: verify (guests) ----------------------------------------------------------------------

const codeSchema = z.object({ code: codeField })

export function VerifyStep() {
  const { state, patch, isPatient } = useBooking()
  const navigate = useNavigate()
  const [error, setError] = React.useState<string>()
  const [sending, setSending] = React.useState(false)
  const [locked, setLocked] = React.useState(false)
  const asked = React.useRef<string | null>(null)
  const form = useForm<{ code: string }>({
    resolver: zodResolver(codeSchema),
    defaultValues: { code: '' },
  })
  const details = state.details
  const email = details?.email.trim().toLowerCase()
  const firstName = details?.firstName

  const send = React.useCallback(
    async (address: string, name: string) => {
      setSending(true)
      setError(undefined)
      setLocked(false)
      try {
        const sent = await requestCode({ email: address, firstName: name })
        patch({ verification: { id: sent.verification_id, email: address } })
        form.reset({ code: '' })
      } catch (cause) {
        setError(
          cause instanceof ApiError && cause.status === 429
            ? 'We have sent several codes to this address. Please wait a little before asking again.'
            : 'We could not send a code just now. Please try again.',
        )
      } finally {
        setSending(false)
      }
    },
    [patch, form],
  )

  React.useEffect(() => {
    if (!email || !firstName || state.verification?.email === email || asked.current === email)
      return
    asked.current = email
    void send(email, firstName)
  }, [email, firstName, state.verification?.email, send])

  if (state.result) return null
  if (isPatient) return <Navigate to={stepPath('details')} replace />
  if (!details || !state.hold || !state.choice) return <Navigate to={stepPath('details')} replace />

  const submit = form.handleSubmit(async ({ code }) => {
    if (!state.verification) return
    setError(undefined)
    try {
      const appointment = await bookAsGuest(target(state, details), {
        verificationId: state.verification.id,
        otp: code,
        firstName: details.firstName,
        lastName: details.lastName,
        email: details.email.trim().toLowerCase(),
        phone: details.phone.trim() || null,
        marketing: details.marketing,
        insuranceProviderId: details.insuranceProviderId || null,
        insuranceMemberId: details.insuranceMemberId.trim() || null,
      })
      patch({ result: appointment, hold: undefined, conflict: undefined })
      void navigate(stepPath('done'))
    } catch (cause) {
      if (isConflict(cause)) {
        patch({
          hold: undefined,
          choice: undefined,
          conflict: { message: (cause as ApiError).message, alternatives: alternativesOf(cause) },
        })
        void navigate(stepPath('time'))
        return
      }
      if (cause instanceof ApiError && cause.code === 'otp_locked') {
        setLocked(true)
        setError('Too many wrong codes. Please ask for a new code.')
      } else if (cause instanceof ApiError && cause.code === 'otp_invalid') {
        setError('That code is not right, or it has expired. Check the email and try again.')
      } else {
        setError(`We could not complete your booking. Please try again or call ${clinic.phone}.`)
      }
    }
  })

  return (
    <form
      noValidate
      onSubmit={submit}
      className="mx-auto grid max-w-md gap-5"
      aria-label="Verify your email"
    >
      <h2 className="text-2xl">Check your email</h2>
      <p className="text-muted-foreground">
        We sent a 6 digit code to <strong className="text-foreground">{details.email}</strong>. It
        confirms the address is yours. The code works for ten minutes.
      </p>
      <FormAlert message={error} />
      <Field label="Verification code" error={form.formState.errors.code?.message}>
        {(c) => (
          <Input
            {...c}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            className="text-center text-2xl tracking-[0.4em]"
            disabled={!state.verification || sending}
            {...form.register('code')}
          />
        )}
      </Field>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button
          type="button"
          variant="secondary"
          onClick={() => void navigate(stepPath('details'))}
        >
          Back
        </Button>
        <Button
          type="button"
          variant="secondary"
          disabled={sending}
          onClick={() => void send(details.email.trim().toLowerCase(), details.firstName)}
        >
          {locked ? 'Send a new code' : 'Resend code'}
        </Button>
        <Button type="submit" disabled={!state.verification || sending || locked}>
          Confirm booking
        </Button>
      </div>
    </form>
  )
}

// --- step 6: confirmation ---------------------------------------------------------------------------

const TIPS: Record<string, string[]> = {
  preventive: [
    'Brush and floss as usual before you come.',
    'Bring a list of any medicines you take.',
  ],
  restorative: [
    'Eat something light beforehand if you will have numbing.',
    'Tell us about any allergies before treatment starts.',
  ],
  cosmetic: [
    'Bring photos of a smile you like, if you have one.',
    'Tell us if your teeth are sensitive to cold or heat.',
  ],
  'surgical-orthodontic': [
    'Arrange for someone to take you home if you will be sedated.',
    'Follow any eating instructions we send before the visit.',
  ],
}

export function ConfirmedStep() {
  const { state, isPatient } = useBooking()
  const services = useLiveServices()
  const appointment = state.result
  if (!appointment) return <Navigate to="/book" replace />

  const day = dateInZone(appointment.start, clinic.timeZone)
  const time = formatTime(appointment.start, clinic.timeZone)
  const code = services.data?.find((s) => s.id === appointment.service_id)?.code
  const group = (code && serviceByCode(code)?.group) || 'preventive'
  const email = state.details?.email

  return (
    <div className="mx-auto max-w-2xl">
      <div className="flex items-center gap-3 text-success-strong">
        <CheckCircle2 className="size-8" aria-hidden="true" />
        <h2 className="text-3xl">Your appointment is booked</h2>
      </div>
      <Card variant="elevated" className="mt-6 p-6">
        <dl className="grid gap-4 sm:grid-cols-2">
          <div>
            <dt className="text-sm text-muted-foreground">Service</dt>
            <dd className="font-semibold">{appointment.service_name}</dd>
          </div>
          <div>
            <dt className="text-sm text-muted-foreground">Dentist</dt>
            <dd className="font-semibold">{appointment.dentist_name}</dd>
          </div>
          <div>
            <dt className="text-sm text-muted-foreground">Date</dt>
            <dd className="font-semibold">{formatDate(day)}</dd>
          </div>
          <div>
            <dt className="text-sm text-muted-foreground">Time</dt>
            <dd className="font-semibold">{time}</dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="text-sm text-muted-foreground">Where</dt>
            <dd className="font-semibold">
              {clinic.name}, {fullAddress}
            </dd>
          </div>
        </dl>
        <p className="mt-4 flex items-start gap-2 text-sm text-muted-foreground" role="status">
          <MailCheck className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <span>
            A confirmation email {email ? `has been sent to ${email}` : 'has been sent'}. You can
            cancel for free until{' '}
            {formatDate(dateInZone(appointment.free_cancellation_until, clinic.timeZone), {
              month: 'long',
              day: 'numeric',
            })}{' '}
            at {formatTime(appointment.free_cancellation_until, clinic.timeZone)}.
          </span>
        </p>
        <div className="mt-5 flex flex-wrap gap-3">
          <Button
            variant="secondary"
            onClick={() =>
              saveFile(
                buildIcs({
                  id: appointment.id,
                  start: appointment.start,
                  end: appointment.end,
                  service: appointment.service_name,
                  dentist: appointment.dentist_name,
                }),
                'appointment.ics',
                'text/calendar',
              )
            }
          >
            <CalendarPlus aria-hidden="true" /> Add to calendar
          </Button>
          <Button asChild variant="secondary">
            <a href={directionsUrl} target="_blank" rel="noreferrer">
              <MapPin aria-hidden="true" /> Directions
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          </Button>
        </div>
      </Card>

      <h3 className="mt-8 text-xl">How to prepare</h3>
      <ul className="mt-3 list-disc space-y-1 pl-5">
        <li>Arrive ten minutes early. Parking is free behind the building.</li>
        <li>Bring photo identification and your insurance card, if you have one.</li>
        {(TIPS[group] ?? []).map((tip) => (
          <li key={tip}>{tip}</li>
        ))}
      </ul>

      <div className="mt-8 rounded-xl bg-secondary p-5">
        {isPatient ? (
          <p>
            You can see, change or cancel this visit in your{' '}
            <Link to="/portal/appointments">patient portal</Link>.
          </p>
        ) : (
          <p>
            Want to manage your visits, see invoices and book faster next time?{' '}
            <Link to="/register">Create a free account</Link> with the same email address.
          </p>
        )}
      </div>
    </div>
  )
}
