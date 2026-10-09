import { ApiError } from '@/lib/api-client'

/** A message a person can act on, for any failure of a sign in or account request. */
export function authMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return 'Too many attempts. Please wait a few minutes and try again.'
    if (error.status === 401 || error.status === 400 || error.status === 422) return error.message
    return 'We could not complete that just now. Please try again.'
  }
  return 'We could not reach the service. Check your connection and try again.'
}

export function FormAlert({ message }: { message?: string }) {
  return (
    <div aria-live="polite">
      {message && (
        <p
          role="alert"
          className="mt-4 rounded-md bg-destructive-soft p-3 text-sm font-medium text-destructive"
        >
          {message}
        </p>
      )}
    </div>
  )
}
