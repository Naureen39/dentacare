import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { clinic } from '@/content/site'
import { ApiError, apiGet, apiPatch, apiPost } from '@/lib/api-client'
import type { components } from '@/lib/api-types'
import { dateInZone, formatTime, type DateString } from '@/lib/dates'

type Schemas = components['schemas']
export type LiveService = Schemas['ServiceOut']
export type LiveDentist = Schemas['DentistOut']
export type Slot = Schemas['SlotOut']
export type Hold = Schemas['HoldResponse']
export type Appointment = Schemas['AppointmentOut']
export type InsuranceProvider = Schemas['InsuranceProviderOut']
export type PatientProfile = Schemas['PatientProfile']

const stable = { staleTime: 5 * 60_000, retry: false } as const

export const useLiveServices = () =>
  useQuery({
    queryKey: ['public', 'live-services'],
    queryFn: () => apiGet<LiveService[]>('/public/services', { auth: false }),
    ...stable,
  })

export const useLiveDentists = (serviceId: string | undefined) =>
  useQuery({
    queryKey: ['public', 'dentists', serviceId],
    queryFn: () =>
      apiGet<LiveDentist[]>(`/public/dentists?service_id=${serviceId}`, { auth: false }),
    enabled: Boolean(serviceId),
    ...stable,
  })

export const useInsuranceProviders = () =>
  useQuery({
    queryKey: ['public', 'insurance-providers'],
    queryFn: () => apiGet<InsuranceProvider[]>('/public/insurance-providers', { auth: false }),
    ...stable,
  })

// --- times -------------------------------------------------------------------------------------

/** One choosable time: a start, and the dentist who would see the patient then. */
export interface TimeChoice {
  id: string
  start: string
  end: string
  dentistId: string
  dentistName: string
  date: DateString
  /** The time of day as read in the clinic, such as "9:30 AM". */
  label: string
  period: 'morning' | 'afternoon' | 'evening'
}

export const periodOf = (iso: string): TimeChoice['period'] => {
  const hour = Number(
    new Intl.DateTimeFormat('en-US', {
      hour: 'numeric',
      hour12: false,
      timeZone: clinic.timeZone,
    }).format(new Date(iso)),
  )
  return hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening'
}

export function toChoice(slot: Slot): TimeChoice {
  return {
    id: `${slot.start}|${slot.dentist_id}`,
    start: slot.start,
    end: slot.end,
    dentistId: slot.dentist_id,
    dentistName: slot.dentist_name,
    date: dateInZone(slot.start, clinic.timeZone),
    label: formatTime(slot.start, clinic.timeZone),
    period: periodOf(slot.start),
  }
}

/**
 * Openings between two dates, one choice per start time. When no dentist was chosen, several
 * dentists may be free at the same minute: the first one listed is offered.
 */
export function useAvailability(input: {
  serviceId: string | undefined
  dentistId: string | null
  from: DateString
  to: DateString
}) {
  const { serviceId, dentistId, from, to } = input
  return useQuery({
    queryKey: ['public', 'availability', serviceId, dentistId, from, to],
    queryFn: async (): Promise<TimeChoice[]> => {
      const query = new URLSearchParams({ service_id: serviceId ?? '', from, to })
      if (dentistId) query.set('dentist_id', dentistId)
      const days = await apiGet<Schemas['DayAvailabilityOut'][]>(`/public/availability?${query}`, {
        auth: false,
      })
      const seen = new Set<string>()
      return days
        .flatMap((day) => day.slots)
        .filter((slot) => !seen.has(slot.start) && Boolean(seen.add(slot.start)))
        .map(toChoice)
    },
    enabled: Boolean(serviceId),
    staleTime: 30_000,
    retry: false,
  })
}

/** Other times the server offers when a time was taken. */
export function alternativesOf(error: unknown): TimeChoice[] {
  if (!(error instanceof ApiError)) return []
  const details = error.details as { alternatives?: Slot[] } | null | undefined
  return (details?.alternatives ?? []).map(toChoice)
}

export const isConflict = (error: unknown) =>
  error instanceof ApiError &&
  ['slot_unavailable', 'slot_held', 'hold_expired'].includes(error.code)

// --- booking ---------------------------------------------------------------------------------------

export const holdSlot = (input: { serviceId: string; dentistId: string; start: string }) =>
  apiPost<Hold>(
    '/public/hold',
    { service_id: input.serviceId, dentist_id: input.dentistId, start: input.start },
    { auth: false },
  )

export const requestCode = (input: { email: string; firstName: string }) =>
  apiPost<{ verification_id: string; expires_in: number; message: string }>(
    '/public/appointments/verification',
    { email: input.email, first_name: input.firstName },
    { auth: false },
  )

export interface BookingTarget {
  serviceId: string
  dentistId: string
  start: string
  holdToken: string
  reasonNote: string | null
}

export const bookAsGuest = (
  target: BookingTarget,
  guest: {
    verificationId: string
    otp: string
    firstName: string
    lastName: string
    email: string
    phone: string | null
    marketing: boolean
    insuranceProviderId: string | null
    insuranceMemberId: string | null
  },
) =>
  apiPost<Appointment>(
    '/public/appointments',
    {
      service_id: target.serviceId,
      dentist_id: target.dentistId,
      start: target.start,
      hold_token: target.holdToken,
      reason_note: target.reasonNote,
      verification_id: guest.verificationId,
      otp: guest.otp,
      first_name: guest.firstName,
      last_name: guest.lastName,
      email: guest.email,
      phone: guest.phone,
      consent: true,
      marketing_consent: guest.marketing,
      insurance_provider_id: guest.insuranceProviderId,
      insurance_member_id: guest.insuranceMemberId,
    },
    { auth: false },
  )

export const bookAsPatient = (target: BookingTarget) =>
  apiPost<Appointment>('/me/appointments', {
    service_id: target.serviceId,
    dentist_id: target.dentistId,
    start: target.start,
    hold_token: target.holdToken,
    reason_note: target.reasonNote,
  })

// --- the patient's own data ------------------------------------------------------------------

export const useProfile = (enabled = true) =>
  useQuery({
    queryKey: ['me', 'profile'],
    queryFn: () => apiGet<PatientProfile>('/me'),
    enabled,
    retry: false,
  })

export function useUpdateProfile() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (changes: Partial<Schemas['PatientUpdate']>) =>
      apiPatch<PatientProfile>('/me', changes),
    onSuccess: (profile) => client.setQueryData(['me', 'profile'], profile),
  })
}

export const useMyAppointments = (when: 'upcoming' | 'past' | 'all' = 'all') =>
  useQuery({
    queryKey: ['me', 'appointments', when],
    queryFn: () => apiGet<Appointment[]>(`/me/appointments?when=${when}`),
    retry: false,
  })

export function useCancelAppointment() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { id: string; reason?: string }) =>
      apiPost<Appointment>(`/me/appointments/${input.id}/cancel`, {
        reason: input.reason || null,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['me'] }),
  })
}

export function useRescheduleAppointment() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { id: string; start: string; dentistId: string; holdToken: string }) =>
      apiPost<Appointment>(`/me/appointments/${input.id}/reschedule`, {
        start: input.start,
        dentist_id: input.dentistId,
        hold_token: input.holdToken,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['me'] }),
  })
}

export const useNotifications = () =>
  useQuery({
    queryKey: ['me', 'notifications'],
    queryFn: () => apiGet<Schemas['NotificationOut'][]>('/me/notifications'),
    retry: false,
  })
