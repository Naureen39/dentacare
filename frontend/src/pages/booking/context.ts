import * as React from 'react'

import type { Appointment, TimeChoice } from '@/lib/booking-api'

export type StepName = 'service' | 'dentist' | 'time' | 'details' | 'verify' | 'done'

export interface Details {
  patientType: 'new' | 'returning'
  firstName: string
  lastName: string
  email: string
  phone: string
  insuranceProviderId: string
  insuranceMemberId: string
  reason: string
  consent: boolean
  marketing: boolean
}

export interface Conflict {
  message: string
  alternatives: TimeChoice[]
}

export interface BookingState {
  serviceId?: string
  /** The dentist chosen, or null for "first available". */
  dentistId: string | null
  dentistName?: string
  /** A dentist named in the link (by full name), chosen when the dentist step loads. */
  preferredDentist?: string
  choice?: TimeChoice
  hold?: { token: string; expiresAt: number }
  details?: Details
  /** Which address the current code was sent to, and its id. */
  verification?: { id: string; email: string }
  conflict?: Conflict
  result?: Appointment
}

interface BookingApi {
  state: BookingState
  patch: (changes: Partial<BookingState>) => void
  /** Forget everything after choosing a different service or dentist. */
  clearTime: () => void
  isPatient: boolean
}

export const BookingContext = React.createContext<BookingApi | null>(null)

export function useBooking(): BookingApi {
  const context = React.useContext(BookingContext)
  if (!context) throw new Error('useBooking must be used inside the booking page')
  return context
}

export const stepPath = (step: StepName) => `/book/${step}`

/** The guided steps. Signed in patients skip the email check. */
export function stepsFor(isPatient: boolean): { name: StepName; label: string }[] {
  return [
    { name: 'service', label: 'Service' },
    { name: 'dentist', label: 'Dentist' },
    { name: 'time', label: 'Date and time' },
    { name: 'details', label: 'Details' },
    ...(isPatient ? [] : [{ name: 'verify' as const, label: 'Verify' }]),
    { name: 'done', label: 'Confirmed' },
  ]
}
