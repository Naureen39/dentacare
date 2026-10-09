import type { Page, Route } from '@playwright/test'

/**
 * A small stand in for the clinic's API, kept in memory for one test. It answers the calls the
 * booking wizard and the patient portal make, and can be told to misbehave in the ways the tests
 * need: a time that is taken, and a wrong email code.
 */
const ROUTINE = {
  id: '00000000-0000-4000-8000-000000000002',
  code: 'SV02',
  name: 'Routine Exam and Cleaning',
  category: 'preventive',
  description: 'A checkup and professional cleaning.',
  duration_min: 45,
  base_price: '120.00',
}
const DENTISTS = [
  {
    id: '10000000-0000-4000-8000-000000000001',
    full_name: 'Dr. Priya Raman',
    specialty: 'general',
    bio: null,
    photo_url: null,
    color: '#0B2545',
  },
  {
    id: '10000000-0000-4000-8000-000000000002',
    full_name: 'Dr. Marcus Lindqvist',
    specialty: 'general',
    bio: null,
    photo_url: null,
    color: '#1F6F8B',
  },
]
const PATIENT = {
  id: '22222222-2222-4222-8222-222222222222',
  first_name: 'Rachel',
  last_name: 'Meyer',
  email: 'rachel@example.com',
  phone: '+1 555 0100',
  date_of_birth: null,
  address: null,
  insurance_provider_id: null,
  insurance_member_id: null,
  marketing_consent: false,
  source: 'web',
  created_at: '2029-01-01T00:00:00Z',
}

export const CODE = '123456'
const HOUR = 3_600_000

export interface Appointment {
  id: string
  status: 'booked' | 'cancelled'
  channel: 'web'
  start: string
  end: string
  service_id: string
  service_name: string
  dentist_id: string
  dentist_name: string
  reason_note: string | null
  late_cancel: boolean
  free_cancellation_until: string
  rescheduled_from: string | null
  created_at: string
}

export class FakeApi {
  /** The next hold request is refused as "just taken", with these other times offered. */
  conflictOnNextHold = false
  holds = 0
  codesRequested = 0
  wrongCodes = 0
  appointments: Appointment[] = []
  requests: { method: string; path: string; body: unknown }[] = []
  private counter = 1

  constructor() {
    // Something to reschedule and cancel: a visit a week from now.
    this.appointments.push(this.make(new Date(Date.now() + 7 * 24 * HOUR), DENTISTS[0]!))
  }

  private make(
    start: Date,
    dentist: (typeof DENTISTS)[number],
    from: string | null = null,
  ): Appointment {
    start.setUTCMinutes(0, 0, 0)
    return {
      id: `30000000-0000-4000-8000-${String(this.counter++).padStart(12, '0')}`,
      status: 'booked',
      channel: 'web',
      start: start.toISOString(),
      end: new Date(start.getTime() + 45 * 60_000).toISOString(),
      service_id: ROUTINE.id,
      service_name: ROUTINE.name,
      dentist_id: dentist.id,
      dentist_name: dentist.full_name,
      reason_note: null,
      late_cancel: false,
      free_cancellation_until: new Date(start.getTime() - 24 * HOUR).toISOString(),
      rescheduled_from: from,
      created_at: new Date().toISOString(),
    }
  }

  private slots(from: string, to: string, dentist: (typeof DENTISTS)[number]) {
    const days = []
    for (
      let day = new Date(`${from}T00:00:00Z`);
      day <= new Date(`${to}T00:00:00Z`);
      day = new Date(day.getTime() + 24 * HOUR)
    ) {
      const date = day.toISOString().slice(0, 10)
      days.push({
        date,
        // Only times that are still ahead, as the real clinic offers.
        slots: [14, 18, 22]
          .filter((h) => new Date(`${date}T${h}:00:00Z`).getTime() > Date.now() + HOUR)
          .map((h) => ({
            start: `${date}T${h}:00:00Z`,
            end: `${date}T${h}:45:00Z`,
            dentist_id: dentist.id,
            dentist_name: dentist.full_name,
          })),
      })
    }
    return days
  }

  private json(route: Route, body: unknown, status = 200) {
    return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  }

  private error(route: Route, status: number, code: string, message: string, details?: unknown) {
    return this.json(route, { code, message, details }, status)
  }

  async handle(route: Route) {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace('/api/v1', '')
    const method = request.method()
    const body = request.postData() ? JSON.parse(request.postData() ?? 'null') : undefined
    this.requests.push({ method, path, body })
    const key = `${method} ${path}`

    switch (key) {
      case 'GET /public/services':
        return this.json(route, [ROUTINE])
      case 'POST /chat/sessions':
        return this.json(
          route,
          {
            session_id: 'chat-1',
            session_token: 'chat-secret',
            greeting: this.say('Hello, I am the Meridian Assistant. How can I help?', {
              quick_replies: [
                { label: 'Book an appointment', kind: 'action', value: 'start_booking' },
                { label: 'Opening hours', kind: 'action', value: 'hours' },
              ],
            }),
          },
          201,
        )
      case 'GET /public/dentists':
        return this.json(route, DENTISTS)
      case 'GET /public/insurance-providers':
        return this.json(route, [])
      case 'GET /public/availability': {
        const dentist =
          DENTISTS.find((d) => d.id === url.searchParams.get('dentist_id')) ?? DENTISTS[0]!
        return this.json(
          route,
          this.slots(url.searchParams.get('from') ?? '', url.searchParams.get('to') ?? '', dentist),
        )
      }
      case 'POST /public/hold': {
        this.holds += 1
        if (this.conflictOnNextHold) {
          this.conflictOnNextHold = false
          const near = new Date(body.start)
          near.setUTCHours(near.getUTCHours() + 1)
          return this.error(route, 409, 'slot_unavailable', 'This time is not available.', {
            alternatives: [
              {
                start: near.toISOString(),
                end: new Date(near.getTime() + 45 * 60_000).toISOString(),
                dentist_id: body.dentist_id,
                dentist_name: DENTISTS.find((d) => d.id === body.dentist_id)?.full_name ?? '',
              },
            ],
          })
        }
        return this.json(
          route,
          {
            hold_token: `hold-${this.holds}`.padEnd(24, 'x'),
            expires_in: 300,
            start: body.start,
            end: body.start,
            dentist_id: body.dentist_id,
          },
          201,
        )
      }
      case 'POST /public/appointments/verification':
        this.codesRequested += 1
        return this.json(
          route,
          {
            verification_id: '40000000-0000-4000-8000-000000000001',
            expires_in: 600,
            message: 'Sent.',
          },
          202,
        )
      case 'POST /public/appointments': {
        if (body.otp !== CODE) {
          this.wrongCodes += 1
          return this.error(route, 400, 'otp_invalid', 'Invalid code.')
        }
        return this.book(route, body)
      }
      case 'POST /auth/login':
        return this.json(route, {
          status: 'authenticated',
          access_token: 'token-1',
          token_type: 'bearer',
          expires_in: 900,
          recovery_codes: null,
        })
      case 'POST /auth/refresh':
        return this.error(route, 401, 'unauthorized', 'No session.')
      case 'GET /auth/me':
        return this.json(route, {
          id: '11111111-1111-4111-8111-111111111111',
          email: PATIENT.email,
          role: 'patient',
          mfa_enabled: false,
          email_verified: true,
          patient_id: PATIENT.id,
        })
      case 'GET /me':
        return this.json(route, PATIENT)
      case 'GET /me/appointments': {
        const when = url.searchParams.get('when')
        const list = this.appointments.filter((a) =>
          when === 'past'
            ? new Date(a.start) < new Date()
            : when === 'upcoming'
              ? new Date(a.start) >= new Date()
              : true,
        )
        return this.json(
          route,
          list.sort((a, b) => a.start.localeCompare(b.start)),
        )
      }
      case 'GET /me/invoices':
      case 'GET /me/notifications':
        return this.json(route, [])
      case 'POST /me/appointments':
        return this.book(route, body)
    }

    if (method === 'POST' && path === '/chat/sessions/chat-1/messages')
      return this.chat(route, body.choice)

    const reschedule = path.match(/^\/me\/appointments\/([\w-]+)\/reschedule$/)
    if (method === 'POST' && reschedule) {
      const old = this.appointments.find((a) => a.id === reschedule[1])
      if (!old) return this.error(route, 404, 'not_found', 'Appointment not found.')
      old.status = 'cancelled'
      const dentist = DENTISTS.find((d) => d.id === body.dentist_id) ?? DENTISTS[0]!
      const fresh = this.make(new Date(body.start), dentist, old.id)
      this.appointments.push(fresh)
      return this.json(route, fresh, 201)
    }
    const cancel = path.match(/^\/me\/appointments\/([\w-]+)\/cancel$/)
    if (method === 'POST' && cancel) {
      const found = this.appointments.find((a) => a.id === cancel[1])
      if (!found) return this.error(route, 404, 'not_found', 'Appointment not found.')
      found.status = 'cancelled'
      return this.json(route, found)
    }
    return this.error(route, 404, 'not_found', `Unexpected request: ${key}`)
  }

  /** A reply in the shape the assistant sends. */
  private say(text: string, extra: Record<string, unknown> = {}) {
    return {
      message_id: `00000000-0000-4000-8000-${String(this.counter++).padStart(12, '0')}`,
      text,
      route: 'rule',
      intent: null,
      quick_replies: [],
      links: [],
      input_hint: null,
      picker: null,
      degraded: false,
      flow: null,
      step: null,
      ...extra,
    }
  }

  /** The booking conversation, one step per button: service, day, time, confirm. */
  private chat(route: Route, choice: { kind: string; value: string } | undefined) {
    const slot = new Date(Date.now() + 24 * HOUR)
    slot.setUTCMinutes(0, 0, 0)
    const day = slot.toISOString().slice(0, 10)
    const key = `${choice?.kind}:${choice?.value}`
    const dentist = DENTISTS[0]!
    let reply = this.say('I can help with booking, hours and prices.')
    if (key === 'action:start_booking')
      reply = this.say('What would you like to book?', {
        flow: 'book',
        step: 'service',
        quick_replies: [{ label: ROUTINE.name, kind: 'service', value: ROUTINE.id }],
      })
    else if (choice?.kind === 'service')
      reply = this.say('Which day suits you?', {
        flow: 'book',
        step: 'day',
        picker: 'date',
        quick_replies: [{ label: 'Tomorrow (3 open)', kind: 'date', value: day }],
      })
    else if (choice?.kind === 'date')
      reply = this.say('Here are some available times. Pick one.', {
        flow: 'book',
        step: 'time',
        picker: 'slot',
        quick_replies: [
          { label: '10:00 AM', kind: 'slot', value: `${slot.toISOString()}|${dentist.id}` },
        ],
      })
    else if (choice?.kind === 'slot')
      reply = this.say(`${ROUTINE.name} with ${dentist.full_name} tomorrow at 10:00 AM.`, {
        flow: 'book',
        step: 'confirm',
        quick_replies: [
          { label: 'Confirm', kind: 'confirm', value: 'yes' },
          { label: 'Change time', kind: 'action', value: 'change_time' },
        ],
      })
    else if (key === 'confirm:yes') {
      this.appointments.push(this.make(slot, dentist))
      reply = this.say('Your appointment is booked. A confirmation email is on its way.', {
        links: [{ label: 'Manage my appointments', url: '/portal/appointments' }],
      })
    } else if (key === 'action:hours')
      reply = this.say('We are open Monday to Friday, 8 AM to 6 PM.')
    const events = [
      `event: meta\ndata: ${JSON.stringify({ message_id: reply.message_id, route: 'rule' })}\n\n`,
      `event: delta\ndata: ${JSON.stringify({ text: reply.text })}\n\n`,
      `event: done\ndata: ${JSON.stringify(reply)}\n\n`,
    ]
    return route.fulfill({ status: 200, contentType: 'text/event-stream', body: events.join('') })
  }

  private book(route: Route, body: { start: string; dentist_id: string }) {
    const dentist = DENTISTS.find((d) => d.id === body.dentist_id) ?? DENTISTS[0]!
    const made = this.make(new Date(body.start), dentist)
    this.appointments.push(made)
    return this.json(route, made, 201)
  }
}

/** Put a fresh fake API behind the page and keep the cookie notice out of the way. */
export async function withFakeApi(page: Page): Promise<FakeApi> {
  const api = new FakeApi()
  await page.addInitScript(() => {
    try {
      localStorage.setItem('meridian-cookie-notice', 'seen')
    } catch {
      /* storage may be unavailable */
    }
  })
  await page.route('**/api/v1/**', (route) => api.handle(route))
  return api
}
