import { z } from 'zod'

/** Messages are written for patients: plain, specific and polite. */
export const messages = {
  required: 'This field is required.',
  email: 'Enter an email address such as name@example.com.',
  phone: 'Enter a phone number with at least 7 digits.',
  code: 'Enter the 6 digit code.',
} as const

export const requiredText = (label: string, max = 200) =>
  z
    .string()
    .trim()
    .min(1, `Enter ${label}.`)
    .max(max, `${label[0]?.toUpperCase()}${label.slice(1)} must be at most ${max} characters.`)

export const emailField = z
  .string()
  .trim()
  .min(1, 'Enter your email address.')
  .email(messages.email)

export const phoneField = z
  .string()
  .trim()
  .refine((value) => value === '' || value.replace(/\D/g, '').length >= 7, messages.phone)

export const codeField = z
  .string()
  .trim()
  .regex(/^\d{6}$/, messages.code)

export const passwordField = z
  .string()
  .min(1, 'Enter your password.')
  .max(128, 'The password must be at most 128 characters.')

/** The first message for each field, in the shape the form components display. */
export function fieldErrors(error: z.ZodError): Record<string, string> {
  const out: Record<string, string> = {}
  for (const issue of error.issues) {
    const key = issue.path.join('.')
    if (!(key in out)) out[key] = issue.message
  }
  return out
}
