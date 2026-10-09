import { json, me, session, type Handlers } from '@/test/utils'

export const ROUTINE = {
  id: '00000000-0000-4000-8000-000000000002',
  code: 'SV02',
  name: 'Routine Exam and Cleaning',
  category: 'preventive',
  description: 'A checkup and professional cleaning.',
  duration_min: 45,
  base_price: '120.00',
}
export const CROWN = {
  id: '00000000-0000-4000-8000-000000000005',
  code: 'SV05',
  name: 'Porcelain Crown',
  category: 'restorative',
  description: 'A custom crown.',
  duration_min: 90,
  base_price: '1150.00',
}
export const RAMAN = {
  id: '10000000-0000-4000-8000-000000000001',
  full_name: 'Dr. Priya Raman',
  specialty: 'general',
  bio: null,
  photo_url: null,
  color: '#0B2545',
}
export const LINDQVIST = {
  ...RAMAN,
  id: '10000000-0000-4000-8000-000000000002',
  full_name: 'Dr. Marcus Lindqvist',
}

const TOKEN = 'h'.repeat(24)

/** Slots on every day asked for, at 14:00, 18:00 and 22:00 UTC (morning, afternoon, evening). */
export function availabilityFor(url: string, dentist = RAMAN) {
  const query = new URL(url, 'http://localhost').searchParams
  const from = new Date(`${query.get('from')}T00:00:00Z`)
  const to = new Date(`${query.get('to')}T00:00:00Z`)
  const days = []
  for (let day = from; day <= to; day = new Date(day.getTime() + 86_400_000)) {
    const date = day.toISOString().slice(0, 10)
    days.push({
      date,
      slots: [14, 18, 22].map((hour) => ({
        start: `${date}T${hour}:00:00Z`,
        end: `${date}T${hour}:45:00Z`,
        dentist_id: dentist.id,
        dentist_name: dentist.full_name,
      })),
    })
  }
  return days
}

export const held = (init: RequestInit | undefined) => {
  const body = JSON.parse(String(init?.body)) as { start: string; dentist_id: string }
  return json(
    {
      hold_token: TOKEN,
      expires_in: 300,
      start: body.start,
      end: body.start,
      dentist_id: body.dentist_id,
    },
    201,
  )
}

export const appointment = (overrides: Record<string, unknown> = {}) => ({
  id: '30000000-0000-4000-8000-000000000001',
  status: 'booked',
  channel: 'web',
  start: '2030-05-14T14:00:00Z',
  end: '2030-05-14T14:45:00Z',
  service_id: ROUTINE.id,
  service_name: ROUTINE.name,
  dentist_id: RAMAN.id,
  dentist_name: RAMAN.full_name,
  reason_note: null,
  late_cancel: false,
  free_cancellation_until: '2030-05-13T14:00:00Z',
  rescheduled_from: null,
  created_at: '2030-05-01T10:00:00Z',
  ...overrides,
})

export const publicCatalogue: Handlers = {
  'GET /public/services': { status: 200, body: [ROUTINE, CROWN] },
  'GET /public/dentists*': { status: 200, body: [RAMAN, LINDQVIST] },
  'GET /public/insurance-providers': {
    status: 200,
    body: [
      { id: '20000000-0000-4000-8000-000000000001', name: 'Alpine Mutual', plan_types: ['PPO'] },
    ],
  },
  'GET /public/availability*': (_init, url) => json(availabilityFor(url)),
  'POST /public/hold': held,
}

export const patientProfile = {
  id: me('patient').patient_id,
  first_name: 'Rachel',
  last_name: 'Meyer',
  email: 'patient@example.com',
  phone: '+1 555 0100',
  date_of_birth: '1990-04-02',
  address: null,
  insurance_provider_id: null,
  insurance_member_id: null,
  marketing_consent: false,
  source: 'web',
  created_at: '2029-01-01T00:00:00Z',
}

export const signedInPatient: Handlers = {
  'POST /auth/refresh': { status: 200, body: session() },
  'GET /auth/me': { status: 200, body: me('patient') },
  'GET /me': { status: 200, body: patientProfile },
}
