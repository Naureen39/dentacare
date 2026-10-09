import { zodResolver } from '@hookform/resolvers/zod'
import * as React from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { z } from 'zod'

import { AuthLayout } from '@/components/site/AuthLayout'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { PasswordInput } from '@/components/ui/password-input'
import { apiPost, tokenStore, type AuthenticatedResponse } from '@/lib/api-client'
import { homeFor, useAuth } from '@/lib/auth'
import { FormAlert, authMessage } from '@/lib/auth-forms'
import { codeField, emailField, passwordField } from '@/lib/forms'

const credentials = z.object({ email: emailField, password: passwordField })
const codeForm = z.object({ code: codeField })

type Step =
  | { name: 'credentials' }
  | { name: 'mfa'; mfaToken: string }
  | { name: 'enrol'; mfaToken: string; secret: string }
  | { name: 'recovery'; codes: string[] }

export default function LoginPage() {
  const auth = useAuth()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from
  const [step, setStep] = React.useState<Step>({ name: 'credentials' })
  const [formError, setFormError] = React.useState<string>()

  if (auth.status === 'authenticated' && auth.user && step.name !== 'recovery') {
    return <Navigate to={from ?? homeFor(auth.user.role)} replace />
  }

  return (
    <AuthLayout
      title="Sign in"
      path="/login"
      subtitle="Patients and clinic staff sign in here. Booking an appointment does not need an account."
    >
      <FormAlert message={formError} />
      {step.name === 'credentials' && (
        <CredentialsForm
          onSubmit={async (values) => {
            setFormError(undefined)
            try {
              const outcome = await auth.login(values.email, values.password)
              if (outcome.status === 'mfa_required')
                setStep({ name: 'mfa', mfaToken: outcome.mfaToken })
              if (outcome.status === 'mfa_setup_required') {
                const body = await apiPost<{ secret: string }>('/auth/mfa/setup', undefined, {
                  auth: false,
                  headers: { Authorization: `Bearer ${outcome.mfaToken}` },
                })
                setStep({ name: 'enrol', mfaToken: outcome.mfaToken, secret: body.secret })
              }
            } catch (error) {
              setFormError(authMessage(error))
            }
          }}
        />
      )}
      {step.name === 'mfa' && (
        <CodeForm
          title="Enter your verification code"
          help="Open your authenticator app and enter the 6 digit code."
          submitLabel="Verify"
          onSubmit={async (code) => {
            setFormError(undefined)
            try {
              // Signing in changes the user, and the redirect at the top of this page follows.
              await auth.verifyMfa({ mfaToken: step.mfaToken, code })
            } catch (error) {
              setFormError(authMessage(error))
            }
          }}
        />
      )}
      {step.name === 'enrol' && (
        <div>
          <h2 className="mt-6 text-xl font-bold">Set up two step verification</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Your role requires a verification code at every sign in. Add this key to an
            authenticator app, then enter the code it shows.
          </p>
          <p
            className="mt-3 rounded-md bg-muted p-3 font-mono text-sm break-all"
            aria-label="Setup key"
          >
            {step.secret}
          </p>
          <CodeForm
            title=""
            submitLabel="Turn on and sign in"
            onSubmit={async (code) => {
              setFormError(undefined)
              try {
                const result = await apiPost<AuthenticatedResponse>(
                  '/auth/mfa/enable',
                  { code },
                  { auth: false, headers: { Authorization: `Bearer ${step.mfaToken}` } },
                )
                tokenStore.set(result.access_token)
                setStep({ name: 'recovery', codes: result.recovery_codes ?? [] })
              } catch (error) {
                setFormError(authMessage(error))
              }
            }}
          />
        </div>
      )}
      {step.name === 'recovery' && (
        <div>
          <h2 className="mt-6 text-xl font-bold">Save your recovery codes</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Each code works once if you lose your phone. They are shown only now. Store them
            somewhere safe.
          </p>
          <ul className="mt-3 grid grid-cols-2 gap-2 rounded-md bg-muted p-3 font-mono text-sm">
            {step.codes.map((code) => (
              <li key={code}>{code}</li>
            ))}
          </ul>
          <Button className="mt-6 w-full" onClick={() => window.location.assign(from ?? '/')}>
            I have saved them
          </Button>
        </div>
      )}
      {step.name === 'credentials' && (
        <p className="mt-6 text-sm text-muted-foreground">
          New here? <Link to="/register">Create an account</Link>. Forgot your password?{' '}
          <Link to="/forgot-password">Reset it</Link>.
        </p>
      )}
    </AuthLayout>
  )
}

function CredentialsForm({
  onSubmit,
}: {
  onSubmit: (values: z.infer<typeof credentials>) => Promise<void>
}) {
  const form = useForm<z.infer<typeof credentials>>({
    resolver: zodResolver(credentials),
    defaultValues: { email: '', password: '' },
  })
  const { errors, isSubmitting } = form.formState
  return (
    <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="mt-6 flex flex-col gap-5">
      <Field label="Email address" error={errors.email?.message} required>
        {(control) => (
          <Input {...control} type="email" autoComplete="email" {...form.register('email')} />
        )}
      </Field>
      <Field label="Password" error={errors.password?.message} required>
        {(control) => (
          <PasswordInput
            {...control}
            autoComplete="current-password"
            {...form.register('password')}
          />
        )}
      </Field>
      <Button type="submit" size="lg" loading={isSubmitting} className="w-full">
        Sign in
      </Button>
    </form>
  )
}

function CodeForm({
  title,
  help,
  submitLabel,
  onSubmit,
}: {
  title: string
  help?: string
  submitLabel: string
  onSubmit: (code: string) => Promise<void>
}) {
  const form = useForm<z.infer<typeof codeForm>>({
    resolver: zodResolver(codeForm),
    defaultValues: { code: '' },
  })
  const { errors, isSubmitting } = form.formState
  return (
    <form
      onSubmit={form.handleSubmit((values) => onSubmit(values.code))}
      noValidate
      className="mt-6 flex flex-col gap-5"
    >
      {title && <h2 className="text-xl font-bold">{title}</h2>}
      <Field label="Verification code" hint={help} error={errors.code?.message} required>
        {(control) => (
          <Input
            {...control}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            {...form.register('code')}
          />
        )}
      </Field>
      <Button type="submit" size="lg" loading={isSubmitting} className="w-full">
        {submitLabel}
      </Button>
    </form>
  )
}
