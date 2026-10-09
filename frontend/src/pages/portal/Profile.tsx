import { zodResolver } from '@hookform/resolvers/zod'
import { Laptop } from 'lucide-react'
import * as React from 'react'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { Button } from '@/components/ui/button'
import { Badge, Card, Skeleton } from '@/components/ui/display'
import { Field } from '@/components/ui/field'
import { Input, controlClasses } from '@/components/ui/input'
import { PasswordInput } from '@/components/ui/password-input'
import { Switch } from '@/components/ui/toggles'
import { useToast } from '@/components/ui/toast'
import { useAuth } from '@/lib/auth'
import { authMessage, FormAlert } from '@/lib/auth-forms'
import { useInsuranceProviders, useProfile, useUpdateProfile } from '@/lib/booking-api'
import { codeField, passwordField, phoneField, requiredText } from '@/lib/forms'
import {
  changePassword,
  describeAgent,
  disableMfa,
  enableMfa,
  startMfaSetup,
  useRevokeSession,
  useSessions,
} from '@/lib/portal-api'
import { MIN_PASSWORD } from '@/pages/AccountPages'
import { clock, shortDay } from '@/pages/portal/format'

function Block({
  title,
  intro,
  children,
}: {
  title: string
  intro?: string
  children: React.ReactNode
}) {
  const id = React.useId()
  return (
    <Card className="p-6" role="region" aria-labelledby={id}>
      <h2 id={id} className="text-xl">
        {title}
      </h2>
      {intro && <p className="mt-1 text-sm text-muted-foreground">{intro}</p>}
      <div className="mt-4">{children}</div>
    </Card>
  )
}

// --- personal details and insurance --------------------------------------------------------------

const personal = z.object({
  first_name: requiredText('your first name', 100),
  last_name: requiredText('your last name', 100),
  phone: phoneField,
  date_of_birth: z.string(),
  address: z.string().trim().max(300, 'Please keep the address under 300 characters.'),
})
type Personal = z.infer<typeof personal>

function PersonalForm() {
  const profile = useProfile()
  const update = useUpdateProfile()
  const { toast } = useToast()
  const form = useForm<Personal>({
    resolver: zodResolver(personal),
    values: profile.data && {
      first_name: profile.data.first_name,
      last_name: profile.data.last_name,
      phone: profile.data.phone ?? '',
      date_of_birth: profile.data.date_of_birth ?? '',
      address: profile.data.address ?? '',
    },
  })
  const { errors } = form.formState
  if (profile.isLoading) return <Skeleton className="h-48 w-full" />
  return (
    <form
      noValidate
      aria-label="Personal details"
      className="grid gap-4"
      onSubmit={form.handleSubmit((v) =>
        update.mutate(
          {
            first_name: v.first_name,
            last_name: v.last_name,
            phone: v.phone || null,
            date_of_birth: v.date_of_birth || null,
            address: v.address || null,
          },
          { onSuccess: () => toast({ tone: 'success', title: 'Your details have been saved.' }) },
        ),
      )}
    >
      <FormAlert message={update.isError ? authMessage(update.error) : undefined} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="First name" required error={errors.first_name?.message}>
          {(c) => <Input {...c} autoComplete="given-name" {...form.register('first_name')} />}
        </Field>
        <Field label="Last name" required error={errors.last_name?.message}>
          {(c) => <Input {...c} autoComplete="family-name" {...form.register('last_name')} />}
        </Field>
        <Field label="Phone" error={errors.phone?.message}>
          {(c) => <Input {...c} type="tel" autoComplete="tel" {...form.register('phone')} />}
        </Field>
        <Field label="Date of birth">
          {(c) => (
            <Input {...c} type="date" autoComplete="bday" {...form.register('date_of_birth')} />
          )}
        </Field>
      </div>
      <Field label="Address" error={errors.address?.message}>
        {(c) => <Input {...c} autoComplete="street-address" {...form.register('address')} />}
      </Field>
      <div>
        <Button type="submit" loading={update.isPending}>
          Save details
        </Button>
      </div>
    </form>
  )
}

function InsuranceForm() {
  const profile = useProfile()
  const providers = useInsuranceProviders()
  const update = useUpdateProfile()
  const { toast } = useToast()
  const form = useForm<{ provider: string; member: string }>({
    values: profile.data && {
      provider: profile.data.insurance_provider_id ?? '',
      member: profile.data.insurance_member_id ?? '',
    },
  })
  if (profile.isLoading) return <Skeleton className="h-24 w-full" />
  return (
    <form
      noValidate
      aria-label="Insurance"
      className="grid gap-4"
      onSubmit={form.handleSubmit((v) =>
        update.mutate(
          {
            insurance_provider_id: v.provider || null,
            insurance_member_id: v.member.trim() || null,
          },
          { onSuccess: () => toast({ tone: 'success', title: 'Your insurance has been saved.' }) },
        ),
      )}
    >
      <FormAlert message={update.isError ? authMessage(update.error) : undefined} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Insurance provider">
          {(c) => (
            <select {...c} className={`${controlClasses} h-11`} {...form.register('provider')}>
              <option value="">No insurance, or not sure</option>
              {providers.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Member number">
          {(c) => <Input {...c} autoComplete="off" {...form.register('member')} />}
        </Field>
      </div>
      <div>
        <Button type="submit" loading={update.isPending}>
          Save insurance
        </Button>
      </div>
    </form>
  )
}

function Preferences() {
  const profile = useProfile()
  const update = useUpdateProfile()
  const { toast } = useToast()
  if (profile.isLoading || !profile.data) return <Skeleton className="h-16 w-full" />
  return (
    <div>
      <div className="flex items-start gap-3">
        <Switch
          id="marketing"
          checked={profile.data.marketing_consent}
          disabled={update.isPending}
          onCheckedChange={(checked) =>
            update.mutate(
              { marketing_consent: checked },
              {
                onSuccess: () =>
                  toast({ tone: 'success', title: 'Your preference has been saved.' }),
              },
            )
          }
        />
        <label htmlFor="marketing" className="text-sm">
          Send me news and oral health tips by email.
        </label>
      </div>
      <p className="mt-3 text-sm text-muted-foreground">
        Appointment confirmations and reminders are always sent, because they are part of your care.
      </p>
    </div>
  )
}

// --- password ----------------------------------------------------------------------------------------

const passwordSchema = z
  .object({
    current: passwordField,
    next: z.string().min(MIN_PASSWORD, `Use at least ${MIN_PASSWORD} characters.`).max(128),
    again: z.string(),
  })
  .refine((v) => v.next === v.again, {
    path: ['again'],
    message: 'The two passwords do not match.',
  })

function PasswordForm() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [failure, setFailure] = React.useState<string>()
  const form = useForm<z.infer<typeof passwordSchema>>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { current: '', next: '', again: '' },
  })
  const { errors, isSubmitting } = form.formState
  return (
    <form
      noValidate
      aria-label="Change password"
      className="grid max-w-md gap-4"
      onSubmit={form.handleSubmit(async (v) => {
        setFailure(undefined)
        try {
          await changePassword({ current: v.current, next: v.next })
          // Every session ends when the password changes, including this one.
          await auth.logout().catch(() => undefined)
          void navigate('/login', { replace: true })
        } catch (error) {
          setFailure(authMessage(error))
        }
      })}
    >
      <FormAlert message={failure} />
      <Field label="Current password" required error={errors.current?.message}>
        {(c) => (
          <PasswordInput {...c} autoComplete="current-password" {...form.register('current')} />
        )}
      </Field>
      <Field
        label="New password"
        required
        hint={`At least ${MIN_PASSWORD} characters. You will be signed out everywhere and asked to sign in again.`}
        error={errors.next?.message}
      >
        {(c) => <PasswordInput {...c} autoComplete="new-password" {...form.register('next')} />}
      </Field>
      <Field label="Repeat the new password" required error={errors.again?.message}>
        {(c) => <PasswordInput {...c} autoComplete="new-password" {...form.register('again')} />}
      </Field>
      <div>
        <Button type="submit" loading={isSubmitting}>
          Change password
        </Button>
      </div>
    </form>
  )
}

// --- two step verification ------------------------------------------------------------------------

function CodeForm({
  label,
  submit,
  onDone,
  withPassword = false,
}: {
  label: string
  submit: (values: { code: string; password: string }) => Promise<void>
  onDone?: () => void
  withPassword?: boolean
}) {
  const [failure, setFailure] = React.useState<string>()
  const form = useForm<{ code: string; password: string }>({
    resolver: zodResolver(
      z.object({ code: codeField, password: withPassword ? passwordField : z.string() }),
    ),
    defaultValues: { code: '', password: '' },
  })
  const { errors, isSubmitting } = form.formState
  return (
    <form
      noValidate
      aria-label={label}
      className="grid max-w-sm gap-4"
      onSubmit={form.handleSubmit(async (v) => {
        setFailure(undefined)
        try {
          await submit(v)
          onDone?.()
        } catch (error) {
          setFailure(authMessage(error))
        }
      })}
    >
      <FormAlert message={failure} />
      {withPassword && (
        <Field label="Your password" error={errors.password?.message}>
          {(c) => (
            <PasswordInput {...c} autoComplete="current-password" {...form.register('password')} />
          )}
        </Field>
      )}
      <Field label="6 digit code" error={errors.code?.message}>
        {(c) => (
          <Input
            {...c}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            {...form.register('code')}
          />
        )}
      </Field>
      <div>
        <Button type="submit" loading={isSubmitting}>
          {label}
        </Button>
      </div>
    </form>
  )
}

function TwoStep() {
  const { user, reloadUser } = useAuth()
  const [step, setStep] = React.useState<
    | { name: 'idle' }
    | { name: 'setup'; secret: string }
    | { name: 'codes'; codes: string[] }
    | { name: 'disable' }
  >({ name: 'idle' })
  const [failure, setFailure] = React.useState<string>()
  const { toast } = useToast()
  if (!user) return null

  return (
    <div>
      <p className="flex items-center gap-2">
        Two step verification is{' '}
        <Badge tone={user.mfa_enabled ? 'success' : 'neutral'}>
          {user.mfa_enabled ? 'On' : 'Off'}
        </Badge>
      </p>
      <FormAlert message={failure} />
      {step.name === 'idle' && !user.mfa_enabled && (
        <Button
          className="mt-4"
          variant="secondary"
          onClick={async () => {
            setFailure(undefined)
            try {
              const setup = await startMfaSetup()
              setStep({ name: 'setup', secret: setup.secret })
            } catch (error) {
              setFailure(authMessage(error))
            }
          }}
        >
          Set up two step verification
        </Button>
      )}
      {step.name === 'idle' && user.mfa_enabled && (
        <Button className="mt-4" variant="secondary" onClick={() => setStep({ name: 'disable' })}>
          Turn off
        </Button>
      )}
      {step.name === 'setup' && (
        <div className="mt-4 grid gap-4">
          <p className="text-sm text-muted-foreground">
            Add this key to an authenticator app on your phone, then enter the code it shows.
          </p>
          <p className="rounded-md bg-muted p-3 font-mono text-sm break-all" aria-label="Setup key">
            {step.secret}
          </p>
          <CodeForm
            label="Turn on"
            submit={async ({ code }) => {
              const result = await enableMfa(code)
              await reloadUser()
              setStep(
                result.recovery_codes?.length
                  ? { name: 'codes', codes: result.recovery_codes }
                  : { name: 'idle' },
              )
            }}
          />
        </div>
      )}
      {step.name === 'codes' && (
        <div className="mt-4">
          <h3 className="text-lg">Save your recovery codes</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Each code works once if you lose your phone. They are shown only now.
          </p>
          <ul className="mt-3 grid max-w-sm grid-cols-2 gap-2 rounded-md bg-muted p-3 font-mono text-sm">
            {step.codes.map((code) => (
              <li key={code}>{code}</li>
            ))}
          </ul>
          <Button className="mt-4" onClick={() => setStep({ name: 'idle' })}>
            I have saved them
          </Button>
        </div>
      )}
      {step.name === 'disable' && (
        <div className="mt-4">
          <CodeForm
            label="Turn off"
            withPassword
            submit={async ({ code, password }) => {
              await disableMfa({ password, code })
              await reloadUser()
              toast({ tone: 'success', title: 'Two step verification is off.' })
            }}
            onDone={() => setStep({ name: 'idle' })}
          />
          <Button className="mt-3" variant="ghost" onClick={() => setStep({ name: 'idle' })}>
            Keep it on
          </Button>
        </div>
      )}
    </div>
  )
}

// --- sessions -----------------------------------------------------------------------------------------

function Sessions() {
  const sessions = useSessions()
  const revoke = useRevokeSession()
  if (sessions.isLoading) return <Skeleton className="h-24 w-full" />
  if (sessions.isError)
    return <FormAlert message="We could not load your sessions. Please try again." />
  return (
    <>
      <FormAlert
        message={
          revoke.isError ? 'We could not sign that device out. Please try again.' : undefined
        }
      />
      <ul className="grid gap-3">
        {sessions.data?.map((session) => (
          <li
            key={session.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3"
          >
            <div className="flex items-center gap-3">
              <Laptop className="size-5 text-muted-foreground" aria-hidden="true" />
              <div>
                <p className="font-semibold">
                  {describeAgent(session.user_agent)}{' '}
                  {session.current && <Badge tone="brand">This device</Badge>}
                </p>
                <p className="text-sm text-muted-foreground">
                  Active {shortDay(session.last_active)} at {clock(session.last_active)}
                  {session.ip ? `, address ${session.ip}` : ''}
                </p>
              </div>
            </div>
            {!session.current && (
              <Button
                size="sm"
                variant="secondary"
                loading={revoke.isPending && revoke.variables === session.id}
                onClick={() => revoke.mutate(session.id)}
              >
                Sign out <span className="sr-only">{describeAgent(session.user_agent)}</span>
              </Button>
            )}
          </li>
        ))}
      </ul>
    </>
  )
}

export function ProfilePage() {
  return (
    <div className="grid gap-6">
      <h1 className="text-3xl">Profile and security</h1>
      <Block title="Personal details">
        <PersonalForm />
      </Block>
      <Block title="Insurance" intro="Optional. It helps us prepare your estimate.">
        <InsuranceForm />
      </Block>
      <Block title="Communication preferences">
        <Preferences />
      </Block>
      <Block title="Password">
        <PasswordForm />
      </Block>
      <Block
        title="Two step verification"
        intro="A code from your phone, as well as your password, when you sign in."
      >
        <TwoStep />
      </Block>
      <Block title="Where you are signed in" intro="Sign out any device you do not recognise.">
        <Sessions />
      </Block>
    </div>
  )
}
