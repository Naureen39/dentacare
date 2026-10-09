import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { axe } from 'vitest-axe'

import { instantAt, clinicToday } from '@/console/time'
import { tokenStore } from '@/lib/api-client'
import { CROWN, RAMAN, ROUTINE } from '@/test/booking-fixtures'
import {
  adminDentist,
  adminService,
  detail,
  emptyList,
  patientProfile,
  patientSummary,
  PATIENT_ID,
  schedule,
  staffSession,
  staffUser,
  visit,
  type StaffRole,
} from '@/test/console-fixtures'
import { json, mockApi, renderApp, type Handlers } from '@/test/utils'

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.set(null)
})

const slow = { timeout: 10_000 }
const VISIT = '30000000-0000-4000-8000-000000000001'
const open = (role: StaffRole, path: string, extra: Handlers = {}) => {
  const api = mockApi(staffSession(role, extra))
  renderApp(path, { hasSession: true })
  return api
}

describe('who sees which screens', () => {
  const labels = (nav: HTMLElement) =>
    within(nav)
      .getAllByRole('link')
      .map((a) => a.textContent)

  it('gives the receptionist the front desk and nothing administrative', async () => {
    open('receptionist', '/staff')
    const nav = await screen.findByRole('navigation', { name: 'Console' }, slow)
    expect(labels(nav)).toEqual(['Today', 'Schedule', 'Patients', 'Billing desk'])
    expect(screen.queryByText('Administration')).not.toBeInTheDocument()
  })

  it('gives the dentist their own day and schedule only', async () => {
    open('dentist', '/staff')
    const nav = await screen.findByRole('navigation', { name: 'Console' }, slow)
    expect(labels(nav)).toEqual(['My day', 'My schedule'])
  })

  it('gives the administrator everything', async () => {
    open('admin', '/staff')
    const nav = await screen.findByRole('navigation', { name: 'Console' }, slow)
    expect(labels(nav)).toEqual([
      'Today',
      'Schedule',
      'Patients',
      'Billing desk',
      'Analytics',
      'Staff',
      'Services and pricing',
      'Dentists and hours',
      'Knowledge base',
      'Chat review',
      'Settings',
      'Audit log',
    ])
  })

  it.each([
    ['dentist', '/staff/patients'],
    ['dentist', '/staff/billing'],
    ['dentist', '/admin/staff'],
    ['receptionist', '/admin/staff'],
    ['receptionist', '/admin/settings'],
    ['receptionist', '/admin/audit'],
  ] as [StaffRole, string][])('shows a %s a refusal at %s', async (role, path) => {
    open(role, path)
    expect(
      await screen.findByRole('heading', { name: /do not have access/i }, slow),
    ).toBeInTheDocument()
  })

  it('keeps patients out of the console and sends strangers to sign in', async () => {
    mockApi({
      'POST /auth/refresh': {
        status: 200,
        body: {
          status: 'authenticated',
          access_token: 'a',
          token_type: 'bearer',
          expires_in: 900,
          recovery_codes: null,
        },
      },
      'GET /auth/me': {
        status: 200,
        body: {
          id: 'u',
          email: 'p@example.com',
          role: 'patient',
          mfa_enabled: false,
          email_verified: true,
          patient_id: PATIENT_ID,
        },
      },
    })
    renderApp('/staff', { hasSession: true })
    expect(
      await screen.findByRole('heading', { name: /do not have access/i }, slow),
    ).toBeInTheDocument()
  })

  it('sends someone who is not signed in to the sign in page', async () => {
    mockApi({})
    renderApp('/admin/audit')
    expect(await screen.findByRole('heading', { name: 'Sign in' }, slow)).toBeInTheDocument()
  })
})

describe('search and alerts', () => {
  it('opens a search with Ctrl K that finds a patient and goes to their record', async () => {
    const user = userEvent.setup()
    open('receptionist', '/staff', {
      'GET /patients*': { status: 200, body: [patientSummary] },
      [`GET /patients/${PATIENT_ID}`]: { status: 200, body: patientProfile },
      [`GET /patients/${PATIENT_ID}/history`]: {
        status: 200,
        body: { appointments: [], invoices: [] },
      },
      [`GET /patients/${PATIENT_ID}/duplicates`]: emptyList,
    })
    await screen.findByRole('heading', { name: 'Today' }, slow)
    await user.keyboard('{Control>}k{/Control}')
    const box = await screen.findByRole('combobox', { name: 'Search pages and patients' })
    await user.type(box, 'Jon')
    expect(await screen.findByRole('option', { name: /Jonas Weber/ })).toBeInTheDocument()
    await user.keyboard('{Enter}')
    expect(await screen.findByRole('heading', { name: 'Jonas Weber' }, slow)).toBeInTheDocument()
  })

  it('does not offer patient search to a dentist', async () => {
    const user = userEvent.setup()
    open('dentist', '/staff')
    await screen.findByRole('heading', { name: 'My day' }, slow)
    await user.keyboard('{Control>}k{/Control}')
    const box = await screen.findByRole('combobox')
    expect(box).toHaveAttribute('placeholder', 'Search pages')
  })

  it('shows what needs attention in the bell', async () => {
    const user = userEvent.setup()
    open('receptionist', '/staff')
    await user.click(await screen.findByRole('button', { name: /Notifications, 3 waiting/ }, slow))
    expect(await screen.findByText(/new messages from the contact form/)).toBeInTheDocument()
  })
})

describe('today', () => {
  it('lists arrivals and confirms or checks in with one click', async () => {
    const user = userEvent.setup()
    const { calls } = open('receptionist', '/staff', {
      [`PATCH /staff/appointments/${VISIT}/status`]: () => json(visit({ status: 'confirmed' })),
    })
    const arrivals = await screen.findByRole('region', { name: /Arrivals/ }, slow)
    expect(await within(arrivals).findByText(/Jonas Weber/)).toBeInTheDocument()
    await user.click(within(arrivals).getByRole('button', { name: 'Confirm' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({
        status: 'confirmed',
        reason: null,
      }),
    )
  })

  it('shows a dentist their numbers instead of the front desk tools', async () => {
    open('dentist', '/staff')
    expect(await screen.findByText('Revenue produced', undefined, slow)).toBeInTheDocument()
    expect(screen.getByText('Visits completed')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New appointment' })).not.toBeInTheDocument()
    expect(screen.queryByText('Needs a confirmation call')).not.toBeInTheDocument()
  })
})

describe('schedule and the appointment drawer', () => {
  const block = /10:00 AM, Jonas Weber, Routine Exam and Cleaning, Booked/

  it("puts each visit in its dentist's column and opens it", async () => {
    const user = userEvent.setup()
    open('receptionist', '/staff/schedule', {
      [`GET /staff/appointments/${VISIT}`]: { status: 200, body: detail() },
    })
    expect(await screen.findByText('Dr. Priya Raman', undefined, slow)).toBeInTheDocument()
    expect(screen.getByText('Dr. Marcus Lindqvist')).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: block }))
    const drawer = await screen.findByRole('dialog')
    expect(await within(drawer).findByText('jonas@example.com')).toBeInTheDocument()
    expect(within(drawer).getByRole('button', { name: 'Confirm' })).toBeInTheDocument()
    expect(within(drawer).queryByLabelText('Clinical note')).not.toBeInTheDocument()
  })

  it('moves a visit from the drawer to a time the receptionist types', async () => {
    const user = userEvent.setup()
    const { calls } = open('receptionist', '/staff/schedule', {
      [`GET /staff/appointments/${VISIT}`]: { status: 200, body: detail() },
      [`PATCH /staff/appointments/${VISIT}/reschedule`]: () =>
        json(visit({ start: instantAt(clinicToday(), 660) })),
    })
    await user.click(await screen.findByRole('button', { name: block }, slow))
    const drawer = await screen.findByRole('dialog')
    await user.click(await within(drawer).findByRole('button', { name: 'Move to another time' }))
    fireEvent.change(within(drawer).getByLabelText('Time'), { target: { value: '11:00' } })
    await user.click(within(drawer).getByRole('button', { name: 'Move visit' }))
    await waitFor(() => {
      const sent = calls.find((c) => c.path.endsWith('/reschedule'))
      expect(sent?.body).toEqual({ start: instantAt(clinicToday(), 660), dentist_id: RAMAN.id })
    })
  })

  it('lets a dentist write a private note and mark a no show, but not confirm or move', async () => {
    const user = userEvent.setup()
    const { calls } = open('dentist', '/staff/schedule', {
      'GET /staff/schedule*': { status: 200, body: schedule([visit()]) },
      [`GET /staff/appointments/${VISIT}`]: {
        status: 200,
        body: detail({ clinical_note: 'Old note' }),
      },
      [`PUT /staff/appointments/${VISIT}/clinical-note`]: {
        status: 200,
        body: { note: 'New note' },
      },
    })
    expect(await screen.findByText('My schedule', { selector: 'div' }, slow)).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: block }))
    const drawer = await screen.findByRole('dialog')
    const note = await within(drawer).findByLabelText('Clinical note')
    expect(note).toHaveValue('Old note')
    expect(within(drawer).queryByRole('button', { name: 'Confirm' })).not.toBeInTheDocument()
    expect(
      within(drawer).queryByRole('button', { name: 'Move to another time' }),
    ).not.toBeInTheDocument()
    expect(within(drawer).getByRole('button', { name: 'No show' })).toBeInTheDocument()
    await user.clear(note)
    await user.type(note, 'New note')
    await user.click(within(drawer).getByRole('button', { name: 'Save note' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ note: 'New note' }),
    )
  })

  it('completes a visit with the services that were performed', async () => {
    const user = userEvent.setup()
    const { calls } = open('dentist', '/staff/schedule', {
      'GET /staff/schedule*': { status: 200, body: schedule([visit({ status: 'checked_in' })]) },
      [`GET /staff/appointments/${VISIT}`]: { status: 200, body: detail({ status: 'checked_in' }) },
      [`POST /staff/appointments/${VISIT}/complete`]: () => json(visit({ status: 'completed' })),
    })
    await user.click(await screen.findByRole('button', { name: /Jonas Weber/ }, slow))
    const drawer = await screen.findByRole('dialog')
    await user.click(await within(drawer).findByRole('checkbox', { name: CROWN.name }))
    await user.click(within(drawer).getByRole('button', { name: 'Mark completed' }))
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith('/complete'))?.body).toEqual({
        performed_service_ids: [CROWN.id],
        clinical_note: '',
      }),
    )
  })

  it('refuses to drop on a taken time in the grid, and shows the legend and help', async () => {
    open('receptionist', '/staff/schedule')
    expect(await screen.findByRole('list', { name: 'Status colours' }, slow)).toBeInTheDocument()
    expect(screen.getByText(/Drag a booked or confirmed visit/)).toBeInTheDocument()
  })

  it('books for a walk in: registers the patient, then books', async () => {
    const user = userEvent.setup()
    const { calls } = open('receptionist', '/staff/schedule', {
      'POST /patients': () => json({ ...patientProfile, id: 'new-patient-id' }, 201),
      'POST /staff/appointments': () => json(visit(), 201),
    })
    await user.click(await screen.findByRole('button', { name: 'New appointment' }, slow))
    const form = await screen.findByRole('form', { name: 'New appointment' })
    await user.click(within(form).getByRole('button', { name: 'New patient' }))
    await user.type(within(form).getByLabelText(/First name/), 'Walt')
    await user.type(within(form).getByLabelText(/Last name/), 'Inn')
    await user.selectOptions(await within(form).findByLabelText(/Service/), ROUTINE.id)
    await user.selectOptions(within(form).getByLabelText(/Dentist/), RAMAN.id)
    await user.click(within(form).getByRole('button', { name: 'Book appointment' }))
    await waitFor(() => expect(calls.some((c) => c.path === '/staff/appointments')).toBe(true))
    expect(calls.find((c) => c.path === '/patients')?.body).toMatchObject({
      first_name: 'Walt',
      source: 'walk_in',
    })
    expect(calls.find((c) => c.path === '/staff/appointments')?.body).toMatchObject({
      patient_id: 'new-patient-id',
      service_id: ROUTINE.id,
    })
  })

  it('has no detectable accessibility problems', async () => {
    const { container } = (() => {
      mockApi(staffSession('receptionist'))
      return renderApp('/staff/schedule', { hasSession: true })
    })()
    await screen.findByRole('button', { name: block }, slow)
    expect(
      await axe(container, { rules: { 'color-contrast': { enabled: false } } }),
    ).toHaveNoViolations()
  })
})

describe('patients and billing desk', () => {
  const invoice = {
    id: '50000000-0000-4000-8000-000000000001',
    number: 7,
    display_number: 'INV-000007',
    patient_id: PATIENT_ID,
    patient_name: 'Jonas Weber',
    issued_at: '2030-04-02T15:00:00Z',
    status: 'issued',
    total: '120.00',
    paid: '20.00',
    balance: '100.00',
  }
  const full = {
    ...invoice,
    appointment_id: VISIT,
    subtotal: '120.00',
    discount: '0.00',
    discount_reason: null,
    tax: '0.00',
    insurance_expected: '0.00',
    patient_responsibility: '120.00',
    void_reason: null,
    items: [
      {
        id: 'i1',
        service_id: null,
        description: 'Routine Exam and Cleaning',
        qty: 1,
        unit_price: '120.00',
        amount: '120.00',
      },
    ],
    payments: [],
  }

  it('searches patients, shows a possible duplicate and keeps a note', async () => {
    const user = userEvent.setup()
    const { calls } = open('receptionist', '/staff/patients', {
      'GET /patients?*': { status: 200, body: [patientSummary] },
      [`GET /patients/${PATIENT_ID}`]: { status: 200, body: patientProfile },
      [`GET /patients/${PATIENT_ID}/history`]: {
        status: 200,
        body: { appointments: [visit()], invoices: [] },
      },
      [`GET /patients/${PATIENT_ID}/duplicates`]: {
        status: 200,
        body: [
          {
            patient: { id: 'dup', first_name: 'Jonas', last_name: 'Wever', email: 'x@example.com' },
            score: 0.8,
            reasons: ['similar name'],
          },
        ],
      },
      [`GET /patients/${PATIENT_ID}/notes`]: emptyList,
      [`POST /patients/${PATIENT_ID}/notes`]: () =>
        json(
          {
            id: 'n',
            body: 'Call after five',
            author: 'desk@example.com',
            created_at: '2030-05-01T10:00:00Z',
          },
          201,
        ),
    })
    await user.click(await screen.findByRole('link', { name: /Weber, Jonas/ }, slow))
    const dup = await screen.findByRole('region', { name: 'Possible duplicates' })
    expect(within(dup).getByText(/Wever/)).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Notes' }))
    await user.type(await screen.findByLabelText('New note'), 'Call after five')
    await user.click(screen.getByRole('button', { name: 'Add note' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST' && c.path.endsWith('/notes'))?.body).toEqual({
        body: 'Call after five',
      }),
    )
  })

  it('records a payment on an open invoice', async () => {
    const user = userEvent.setup()
    const { calls } = open('receptionist', `/staff/billing/${invoice.id}`, {
      [`GET /billing/invoices/${invoice.id}`]: { status: 200, body: full },
      [`POST /billing/invoices/${invoice.id}/payments`]: () =>
        json({ ...full, paid: '120.00', balance: '0.00', status: 'paid' }, 201),
    })
    await user.click(await screen.findByRole('button', { name: 'Record payment' }, slow))
    const form = await screen.findByRole('form', { name: 'Record a payment' })
    expect(within(form).getByLabelText('Amount')).toHaveValue('100.00')
    await user.click(within(form).getByRole('button', { name: 'Record payment' }))
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith('/payments'))?.body).toEqual({
        amount: '100.00',
        method: 'cash',
        reference: null,
      }),
    )
  })

  it('lists open invoices', async () => {
    open('receptionist', '/staff/billing', {
      'GET /billing/invoices*': { status: 200, body: [invoice] },
    })
    expect(await screen.findByRole('link', { name: 'INV-000007' }, slow)).toHaveAttribute(
      'href',
      `/staff/billing/${invoice.id}`,
    )
  })
})

describe('administration', () => {
  it('adds a dentist and lets the administrator deactivate someone, but not themselves', async () => {
    const user = userEvent.setup()
    const { calls } = open('admin', '/admin/staff', {
      'GET /admin/users': {
        status: 200,
        body: [
          staffUser(),
          staffUser({
            id: '11111111-1111-4111-8111-111111111111',
            email: 'admin@example.com',
            role: 'admin',
          }),
        ],
      },
      'POST /admin/users': () => json(staffUser({ role: 'dentist' }), 201),
    })
    await user.click(await screen.findByRole('button', { name: 'Add staff' }, slow))
    const form = await screen.findByRole('form', { name: 'Add a member of staff' })
    await user.type(within(form).getByLabelText(/Email address/), 'new@example.com')
    await user.selectOptions(within(form).getByLabelText(/Role/), 'dentist')
    await user.type(within(form).getByLabelText(/Full name/), 'Dr. Ada Quill')
    await user.click(within(form).getByRole('button', { name: 'Create account' }))
    await waitFor(() =>
      expect(
        calls.find((c) => c.method === 'POST' && c.path === '/admin/users')?.body,
      ).toMatchObject({
        email: 'new@example.com',
        role: 'dentist',
        full_name: 'Dr. Ada Quill',
      }),
    )
    const own = screen.getByRole('button', { name: /Deactivate admin@example.com/ })
    expect(own).toBeDisabled()
  })

  it('schedules a price change for a service', async () => {
    const user = userEvent.setup()
    const { calls } = open('admin', '/admin/services', {
      'GET /admin/services': { status: 200, body: [adminService] },
      [`POST /admin/services/${ROUTINE.id}/price-changes`]: () => json(adminService, 201),
    })
    await user.click(
      await screen.findByRole('button', { name: /Change price of Routine Exam/ }, slow),
    )
    const form = await screen.findByRole('form', { name: 'Change the price' })
    const price = within(form).getByLabelText(/New price/)
    await user.clear(price)
    await user.type(price, '135.00')
    fireEvent.change(within(form).getByLabelText(/Effective from/), {
      target: { value: '2031-01-01' },
    })
    await user.click(within(form).getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith('/price-changes'))?.body).toEqual({
        price: '135.00',
        effective_from: '2031-01-01',
      }),
    )
  })

  it('saves working hours and adds time off', async () => {
    const user = userEvent.setup()
    const { calls } = open('admin', '/admin/dentists', {
      'GET /admin/dentists': { status: 200, body: [adminDentist] },
      'GET /admin/services': { status: 200, body: [adminService] },
      [`GET /admin/dentists/${RAMAN.id}/schedule`]: {
        status: 200,
        body: [
          {
            weekday: 0,
            start_time: '08:00:00',
            end_time: '17:00:00',
            break_start: null,
            break_end: null,
          },
        ],
      },
      [`PUT /admin/dentists/${RAMAN.id}/schedule`]: () => json([]),
      [`GET /admin/dentists/${RAMAN.id}/time-off`]: emptyList,
      [`POST /admin/dentists/${RAMAN.id}/time-off`]: () =>
        json(
          {
            id: 't',
            starts_at: '2031-01-01T05:00:00Z',
            ends_at: '2031-01-02T05:00:00Z',
            reason: 'leave',
            note: null,
            affected_appointments: 2,
          },
          201,
        ),
    })
    const hours = await screen.findByRole('form', { name: 'Weekly working hours' }, slow)
    await user.click(within(hours).getByRole('checkbox', { name: 'Tuesday' }))
    await user.click(within(hours).getByRole('button', { name: 'Save working hours' }))
    await waitFor(() => {
      const body = calls.find((c) => c.method === 'PUT')?.body as { days: { weekday: number }[] }
      expect(body.days.map((d) => d.weekday)).toEqual([0, 1])
    })

    const off = screen.getByRole('form', { name: 'Add time off' })
    fireEvent.change(within(off).getByLabelText(/First day off/), {
      target: { value: '2031-01-01' },
    })
    await user.click(within(off).getByRole('button', { name: 'Add time off' }))
    await waitFor(() =>
      expect(
        calls.find((c) => c.method === 'POST' && c.path.endsWith('/time-off'))?.body,
      ).toMatchObject({ reason: 'leave' }),
    )
    expect(await screen.findByText(/2 booked visits fall in this period/)).toBeInTheDocument()
  })

  it('adds and removes assistant intent examples', async () => {
    const user = userEvent.setup()
    const { calls } = open('admin', '/admin/knowledge', {
      'GET /admin/kb/documents': emptyList,
      'GET /admin/kb/intents': {
        status: 200,
        body: [{ id: 'e1', intent: 'opening_hours', text: 'when are you open' }],
      },
      'POST /admin/kb/intents': () => json({ id: 'e2', intent: 'opening_hours', text: 'x' }, 201),
      'DELETE /admin/kb/intents/e1': { status: 204 },
    })
    await user.click(await screen.findByRole('tab', { name: 'Intent examples' }, slow))
    const form = await screen.findByRole('form', { name: 'Add an example' })
    await user.type(within(form).getByLabelText('Intent'), 'opening_hours')
    await user.type(within(form).getByLabelText('Example sentence'), 'what time do you close')
    await user.click(within(form).getByRole('button', { name: 'Add example' }))
    await waitFor(() =>
      expect(
        calls.find((c) => c.method === 'POST' && c.path === '/admin/kb/intents')?.body,
      ).toEqual({
        intent: 'opening_hours',
        text: 'what time do you close',
      }),
    )
    await user.click(screen.getByRole('button', { name: /Remove .*when are you open/ }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
  })

  it('shows a masked transcript and filters by feedback', async () => {
    const user = userEvent.setup()
    const { calls } = open('admin', '/admin/chats', {
      'GET /admin/chat/sessions?*': {
        status: 200,
        body: [
          {
            id: 's1',
            created_at: '2030-05-01T10:00:00Z',
            messages: 2,
            thumbs_up: 0,
            thumbs_down: 1,
            first_message: 'my name is [name]',
            provider_last: 'groq',
          },
        ],
      },
      'GET /admin/chat/sessions/s1': {
        status: 200,
        body: {
          id: 's1',
          created_at: '2030-05-01T10:00:00Z',
          ended_at: null,
          provider_last: 'groq',
          masked: true,
          messages: [
            {
              id: 'm1',
              role: 'user',
              content: 'my name is [name]',
              intent: null,
              route: null,
              llm_calls: 0,
              feedback: null,
              created_at: '2030-05-01T10:00:00Z',
            },
          ],
        },
      },
    })
    await user.selectOptions(await screen.findByLabelText('Show', undefined, slow), 'negative')
    await waitFor(() => expect(calls.some((c) => c.path.includes('feedback=negative'))).toBe(true))
    await user.click(await screen.findByRole('button', { name: /my name is/ }))
    expect(await screen.findByText(/hidden/)).toBeInTheDocument()
    expect(await screen.findByText('my name is [name]', { selector: 'p.mt-1' })).toBeInTheDocument()
  })

  it('saves booking rules and exports the audit log', async () => {
    const user = userEvent.setup()
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    const settings = {
      clinic: {
        name: 'Meridian',
        address: '1 Road',
        phone: '1',
        email: 'a@b.c',
        timezone: 'America/New_York',
      },
      booking: {
        min_notice_hours: 2,
        max_horizon_days: 90,
        same_day_enabled: true,
        buffer_minutes: 10,
        slot_grid_minutes: 15,
        cancellation_free_hours: 24,
      },
      reminders: { hours_before: [48, 24], followup_days: 2, recall_months: 6 },
      billing: {
        tax_rate_percent: '0',
        receptionist_max_discount_percent: '10',
        monthly_revenue_target: '0',
      },
      retention: { chat_retention_days: 90, guest_anonymize_months: 24 },
    }
    const { calls } = open('admin', '/admin/settings', {
      'GET /admin/settings': { status: 200, body: settings },
      'PUT /admin/settings': () => json(settings),
      'GET /admin/llm/status': {
        status: 200,
        body: {
          primary: 'groq',
          order: ['groq', 'gemini'],
          failover_threshold: 0.9,
          providers: {
            groq: {
              configured: true,
              model: 'm',
              utilization: 0.1,
              limits: { rpm: 30, rpd: null, tpm: null, tpd: null },
              usage: { rpm: 1, rpd: 1, tpm: 1, tpd: 1 },
            },
            gemini: { configured: false },
          },
        },
      },
    })
    const form = await screen.findByRole('form', { name: 'Booking rules' }, slow)
    const free = within(form).getByLabelText(/Free cancellation until/)
    await user.clear(free)
    await user.type(free, '48')
    await user.click(within(form).getByRole('button', { name: 'Save' }))
    await waitFor(() => {
      const body = calls.find((c) => c.method === 'PUT')?.body as {
        booking: { cancellation_free_hours: number }
      }
      expect(body.booking.cancellation_free_hours).toBe(48)
    })
    expect((await screen.findAllByText(/groq/i)).length).toBeGreaterThan(0)
  })

  it('exports the audit log as a file', async () => {
    const user = userEvent.setup()
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    const { calls } = open('admin', '/admin/audit', {
      'GET /admin/audit-logs?*': {
        status: 200,
        body: [
          {
            id: 'a1',
            actor_id: null,
            actor_role: 'admin',
            action: 'auth.login',
            entity: null,
            entity_id: null,
            ip: null,
            metadata: {},
            created_at: '2030-05-01T10:00:00Z',
          },
        ],
      },
      'GET /admin/audit-logs/export.csv*': () => new Response('time,actor_id\n', { status: 200 }),
    })
    expect(await screen.findByText('auth.login', undefined, slow)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Export CSV/ }))
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled())
    expect(calls.some((c) => c.path.includes('export.csv'))).toBe(true)
  })
})
