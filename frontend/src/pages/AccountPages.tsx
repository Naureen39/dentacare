import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import * as React from 'react'
import { useForm } from 'react-hook-form'
import { Link, useSearchParams } from 'react-router-dom'
import { z } from 'zod'

import { AuthLayout } from '@/components/site/AuthLayout'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/toggles'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { PasswordInput } from '@/components/ui/password-input'
import { apiPost } from '@/lib/api-client'
import { emailField, phoneField, requiredText } from '@/lib/forms'
import { FormAlert, authMessage } from '@/lib/auth-forms'

export const MIN_PASSWORD = 12
const newPassword = z
  .string()
  .min(MIN_PASSWORD, `Use at least ${MIN_PASSWORD} characters.`)
  .max(128, 'Use at most 128 characters.')
const passwordHint = `At least ${MIN_PASSWORD} characters. A few unrelated words make a strong, memorable password.`

// --- Register ---------------------------------------------------------------------------------

const registerSchema = z.object({
  first_name: requiredText('your first name', 100),
  last_name: requiredText('your last name', 100),
  email: emailField,
  phone: phoneField,
  password: newPassword,
  marketing_consent: z.boolean(),
})

export function RegisterPage() {
  const form = useForm<z.infer<typeof registerSchema>>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      first_name: '',
      last_name: '',
      email: '',
      phone: '',
      password: '',
      marketing_consent: false,
    },
  })
  const mutation = useMutation({
    mutationFn: (values: z.infer<typeof registerSchema>) =>
      apiPost('/auth/register', { ...values, phone: values.phone || null }, { auth: false }),
  })
  const { errors } = form.formState
  if (mutation.isSuccess) {
    return (
      <AuthLayout title="Check your email" path="/register">
        <p role="status" className="mt-4">
          We sent a link to <strong>{form.getValues('email')}</strong>. Open it to confirm your
          address, then sign in.
        </p>
        <Button asChild className="mt-6">
          <Link to="/login">Go to sign in</Link>
        </Button>
      </AuthLayout>
    )
  }
  return (
    <AuthLayout
      title="Create an account"
      path="/register"
      subtitle="See your appointments and invoices, and book faster next time."
    >
      <FormAlert message={mutation.isError ? authMessage(mutation.error) : undefined} />
      <form
        noValidate
        onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
        className="mt-6 grid gap-5"
      >
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="First name" required error={errors.first_name?.message}>
            {(c) => <Input {...c} autoComplete="given-name" {...form.register('first_name')} />}
          </Field>
          <Field label="Last name" required error={errors.last_name?.message}>
            {(c) => <Input {...c} autoComplete="family-name" {...form.register('last_name')} />}
          </Field>
        </div>
        <Field label="Email address" required error={errors.email?.message}>
          {(c) => <Input {...c} type="email" autoComplete="email" {...form.register('email')} />}
        </Field>
        <Field label="Phone" hint="Optional." error={errors.phone?.message}>
          {(c) => <Input {...c} type="tel" autoComplete="tel" {...form.register('phone')} />}
        </Field>
        <Field label="Password" required hint={passwordHint} error={errors.password?.message}>
          {(c) => (
            <PasswordInput {...c} autoComplete="new-password" {...form.register('password')} />
          )}
        </Field>
        <div className="flex items-start gap-3">
          <Checkbox
            id="marketing"
            onCheckedChange={(v) => form.setValue('marketing_consent', v === true)}
            className="mt-0.5"
          />
          <label htmlFor="marketing" className="text-sm">
            Send me occasional news and oral health tips by email (optional)
          </label>
        </div>
        <p className="text-sm text-muted-foreground">
          By creating an account you agree to our <Link to="/terms">terms</Link> and{' '}
          <Link to="/privacy">privacy policy</Link>.
        </p>
        <Button type="submit" size="lg" loading={mutation.isPending} className="w-full">
          Create account
        </Button>
      </form>
      <p className="mt-6 text-sm text-muted-foreground">
        Already have an account? <Link to="/login">Sign in</Link>.
      </p>
    </AuthLayout>
  )
}

// --- Forgot and reset ---------------------------------------------------------------------------

const forgotSchema = z.object({ email: emailField })

export function ForgotPasswordPage() {
  const form = useForm<z.infer<typeof forgotSchema>>({
    resolver: zodResolver(forgotSchema),
    defaultValues: { email: '' },
  })
  const mutation = useMutation({
    mutationFn: (values: z.infer<typeof forgotSchema>) =>
      apiPost('/auth/forgot', values, { auth: false }),
  })
  const { errors } = form.formState
  return (
    <AuthLayout
      title="Reset your password"
      path="/forgot-password"
      subtitle="Enter your email address and we will send you a link."
    >
      {mutation.isSuccess ? (
        <p role="status" className="mt-6 rounded-md bg-success-soft p-4 text-success-strong">
          If an account exists for that address, a reset link is on its way. It works for a short
          time only.
        </p>
      ) : (
        <>
          <FormAlert message={mutation.isError ? authMessage(mutation.error) : undefined} />
          <form
            noValidate
            onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
            className="mt-6 grid gap-5"
          >
            <Field label="Email address" required error={errors.email?.message}>
              {(c) => (
                <Input {...c} type="email" autoComplete="email" {...form.register('email')} />
              )}
            </Field>
            <Button type="submit" size="lg" loading={mutation.isPending} className="w-full">
              Send reset link
            </Button>
          </form>
        </>
      )}
      <p className="mt-6 text-sm">
        <Link to="/login">Back to sign in</Link>
      </p>
    </AuthLayout>
  )
}

const resetSchema = z.object({ password: newPassword })

export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const form = useForm<z.infer<typeof resetSchema>>({
    resolver: zodResolver(resetSchema),
    defaultValues: { password: '' },
  })
  const mutation = useMutation({
    mutationFn: (values: z.infer<typeof resetSchema>) =>
      apiPost('/auth/reset', { token, new_password: values.password }, { auth: false }),
  })
  const { errors } = form.formState
  if (token.length < 20) {
    return (
      <AuthLayout title="This link is not valid" path="/reset-password">
        <p className="mt-4">
          The link is missing or incomplete. <Link to="/forgot-password">Ask for a new one</Link>.
        </p>
      </AuthLayout>
    )
  }
  return (
    <AuthLayout title="Choose a new password" path="/reset-password">
      {mutation.isSuccess ? (
        <>
          <p role="status" className="mt-6 rounded-md bg-success-soft p-4 text-success-strong">
            Your password has been changed.
          </p>
          <Button asChild className="mt-6">
            <Link to="/login">Sign in</Link>
          </Button>
        </>
      ) : (
        <>
          <FormAlert message={mutation.isError ? authMessage(mutation.error) : undefined} />
          <form
            noValidate
            onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
            className="mt-6 grid gap-5"
          >
            <Field
              label="New password"
              required
              hint={passwordHint}
              error={errors.password?.message}
            >
              {(c) => (
                <PasswordInput {...c} autoComplete="new-password" {...form.register('password')} />
              )}
            </Field>
            <Button type="submit" size="lg" loading={mutation.isPending} className="w-full">
              Change password
            </Button>
          </form>
        </>
      )}
    </AuthLayout>
  )
}

// --- Verify email --------------------------------------------------------------------------------

export function VerifyEmailPage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const mutation = useMutation({
    mutationFn: () => apiPost('/auth/verify-email', { token }, { auth: false }),
  })
  const started = React.useRef(false)
  React.useEffect(() => {
    if (token.length >= 20 && !started.current) {
      started.current = true
      mutation.mutate()
    }
  }, [token, mutation])
  return (
    <AuthLayout title="Confirm your email" path="/verify-email">
      <div role="status" className="mt-6">
        {token.length < 20 && (
          <p>The link is missing or incomplete. Please use the link from your email.</p>
        )}
        {token.length >= 20 && mutation.isPending && <p>Confirming your address</p>}
        {mutation.isSuccess && (
          <p className="rounded-md bg-success-soft p-4 text-success-strong">
            Thank you. Your email address is confirmed.
          </p>
        )}
      </div>
      <FormAlert message={mutation.isError ? authMessage(mutation.error) : undefined} />
      {mutation.isSuccess && (
        <Button asChild className="mt-6">
          <Link to="/login">Sign in</Link>
        </Button>
      )}
    </AuthLayout>
  )
}
