import { instantAt, clinicToday } from '@/console/time'
import { RAMAN, LINDQVIST, ROUTINE, CROWN, publicCatalogue } from '@/test/booking-fixtures'
import { json, me, session, type Handlers } from '@/test/utils'

export type StaffRole = 'receptionist' | 'dentist' | 'admin'

export const PATIENT_ID = '22222222-2222-4222-8222-222222222222'

export const visit = (overrides: Record<string, unknown> = {}) => ({
  id: '30000000-0000-4000-8000-000000000001',
  status: 'booked',
  channel: 'web',
  start: instantAt(clinicToday(), 10 * 60),
  end: instantAt(clinicToday(), 10 * 60 + 45),
  service_id: ROUTINE.id,
  service_name: ROUTINE.name,
  dentist_id: RAMAN.id,
  dentist_name: RAMAN.full_name,
  reason_note: 'Sore tooth',
  late_cancel: false,
  free_cancellation_until: instantAt(clinicToday(), 0),
  rescheduled_from: null,
  created_at: '2030-05-01T10:00:00Z',
  patient_id: PATIENT_ID,
  patient_name: 'Jonas Weber',
  ...overrides,
})

export const detail = (overrides: Record<string, unknown> = {}) => ({
  ...visit(),
  patient_email: 'jonas@example.com',
  patient_phone: '+1 555 0100',
  clinical_note: null,
  recent_visits: [],
  ...overrides,
})

export const schedule = (appointments: unknown[]) => ({
  view: 'day',
  start: clinicToday(),
  end: clinicToday(),
  appointments,
})

/** The calls every console page makes, for a member of staff with this role. */
export function staffSession(role: StaffRole, extra: Handlers = {}): Handlers {
  return {
    'POST /auth/refresh': { status: 200, body: session() },
    'GET /auth/me': { status: 200, body: me(role) },
    'GET /staff/alerts': { status: 200, body: { unconfirmed_soon: 2, new_inquiries: 1 } },
    'GET /staff/schedule*': { status: 200, body: schedule([visit()]) },
    'GET /staff/me/performance*': {
      status: 200,
      body: { days: 30, visits: 12, revenue: '4200.00', no_shows: 1, no_show_rate: 0.0769 },
    },
    ...publicCatalogue,
    'GET /public/dentists': { status: 200, body: [RAMAN, LINDQVIST] },
    ...extra,
  }
}

export const patientSummary = {
  id: PATIENT_ID,
  first_name: 'Jonas',
  last_name: 'Weber',
  email: 'jonas@example.com',
}

export const patientProfile = {
  ...patientSummary,
  phone: '+1 555 0100',
  date_of_birth: null,
  address: null,
  insurance_provider_id: null,
  insurance_member_id: null,
  marketing_consent: false,
  source: 'web',
  created_at: '2029-01-01T00:00:00Z',
}

export const staffUser = (over: Record<string, unknown> = {}) => ({
  id: '40000000-0000-4000-8000-000000000001',
  email: 'desk@example.com',
  role: 'receptionist',
  is_active: true,
  mfa_enabled: true,
  last_login_at: null,
  dentist_id: null,
  dentist_name: null,
  ...over,
})

export const adminService = {
  id: ROUTINE.id,
  code: ROUTINE.code,
  name: ROUTINE.name,
  category: 'preventive',
  description: null,
  duration_min: 45,
  base_price: '120.00',
  is_active: true,
  display_order: 1,
  price_changes: [],
}

export const adminDentist = {
  id: RAMAN.id,
  full_name: RAMAN.full_name,
  specialty: 'general',
  color: '#0B2545',
  is_active: true,
  user_id: null,
  service_ids: [ROUTINE.id, CROWN.id],
}

export const emptyList = { status: 200, body: [] }
export const okJson =
  (body: unknown = {}) =>
  () =>
    json(body)
