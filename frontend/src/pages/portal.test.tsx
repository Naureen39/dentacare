import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { tokenStore } from '@/lib/api-client'
import { describeAgent } from '@/lib/portal-api'
import {
  appointment,
  patientProfile,
  publicCatalogue,
  RAMAN,
  signedInPatient,
} from '@/test/booking-fixtures'
import { json, mockApi, renderApp, type Handlers } from '@/test/utils'

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.set(null)
})

const slow = { timeout: 10_000 }
const INVOICE_ID = '50000000-0000-4000-8000-000000000001'

const invoiceItem = {
  id: INVOICE_ID,
  number: 7,
  display_number: 'INV-000007',
  patient_id: patientProfile.id,
  patient_name: 'Rachel Meyer',
  issued_at: '2030-04-02T15:00:00Z',
  status: 'issued',
  total: '120.00',
  paid: '70.00',
  balance: '50.00',
}
const invoice = {
  ...invoiceItem,
  appointment_id: '30000000-0000-4000-8000-000000000001',
  subtotal: '120.00',
  discount: '0.00',
  discount_reason: null,
  tax: '0.00',
  insurance_expected: '0.00',
  patient_responsibility: '120.00',
  void_reason: null,
  items: [
    {
      id: '60000000-0000-4000-8000-000000000001',
      service_id: null,
      description: 'Routine Exam and Cleaning',
      qty: 1,
      unit_price: '120.00',
      amount: '120.00',
    },
  ],
  payments: [
    {
      id: '70000000-0000-4000-8000-000000000001',
      amount: '70.00',
      method: 'card',
      payer_type: 'patient',
      paid_at: '2030-04-03T15:00:00Z',
      reference: null,
      card_last4: '4242',
      sandbox: true,
    },
  ],
}

const portal = (extra: Handlers = {}): Handlers => ({
  ...signedInPatient,
  ...publicCatalogue,
  'GET /me/appointments*': (_init, url) =>
    json(
      url.includes('when=upcoming')
        ? [appointment()]
        : [
            appointment({
              id: '30000000-0000-4000-8000-000000000009',
              status: 'completed',
              start: '2029-01-10T15:00:00Z',
              service_name: 'Deep Cleaning',
            }),
          ],
    ),
  'GET /me/invoices': { status: 200, body: [invoiceItem] },
  ...extra,
})

describe('patient portal', () => {
  it('shows the next visit, the balance and a prompt for visits long ago', async () => {
    mockApi(portal())
    renderApp('/portal', { hasSession: true })
    expect(await screen.findByText('Your next appointment', undefined, slow)).toBeInTheDocument()
    expect(await screen.findByText(/Routine Exam and Cleaning/)).toBeInTheDocument()
    expect(await screen.findByText('$50.00')).toBeInTheDocument()
    expect(screen.getByText('Deep Cleaning')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Book an appointment' })).toHaveAttribute(
      'href',
      '/book',
    )
    expect(screen.getByRole('navigation', { name: 'Patient portal' })).toBeInTheDocument()
  })

  it('is closed to staff accounts', async () => {
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
          email: 'r@example.com',
          role: 'receptionist',
          mfa_enabled: true,
          email_verified: true,
          patient_id: null,
        },
      },
    })
    renderApp('/portal', { hasSession: true })
    expect(
      await screen.findByRole('heading', { name: /do not have access/i }, slow),
    ).toBeInTheDocument()
  })

  it('cancels an appointment after showing the policy', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi(
      portal({
        'POST /me/appointments/30000000-0000-4000-8000-000000000001/cancel': () =>
          json(appointment({ status: 'cancelled' })),
      }),
    )
    renderApp('/portal/appointments', { hasSession: true })
    await user.click(await screen.findByRole('button', { name: /Cancel Routine Exam/ }, slow))
    const dialog = await screen.findByRole('dialog', { name: 'Cancel this appointment?' })
    expect(within(dialog).getByText(/free until/i)).toBeInTheDocument()
    await user.type(within(dialog).getByLabelText(/Reason/), 'Travelling')
    await user.click(within(dialog).getByRole('button', { name: 'Cancel appointment' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    const sent = calls.find((c) => c.path.endsWith('/cancel'))
    expect(sent?.body).toEqual({ reason: 'Travelling' })
  })

  it('reschedules to a new time with a held slot', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi(
      portal({
        'POST /me/appointments/30000000-0000-4000-8000-000000000001/reschedule': () =>
          json(appointment({ start: '2030-06-01T14:00:00Z' }), 201),
      }),
    )
    renderApp('/portal/appointments', { hasSession: true })
    await user.click(await screen.findByRole('button', { name: /Reschedule Routine Exam/ }, slow))
    const dialog = await screen.findByRole('dialog', { name: 'Reschedule your appointment' })
    const confirm = within(dialog).getByRole('button', { name: 'Confirm new time' })
    expect(confirm).toBeDisabled()
    await user.click(
      (await within(dialog).findAllByRole('radio', undefined, slow))[0] as HTMLElement,
    )
    await waitFor(() => expect(confirm).toBeEnabled())
    await user.click(confirm)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    const sent = calls.find((c) => c.path.endsWith('/reschedule'))
    expect(sent?.body).toMatchObject({ dentist_id: RAMAN.id, hold_token: 'h'.repeat(24) })
  })

  it('lists invoices and shows one with its payments', async () => {
    const user = userEvent.setup()
    mockApi(portal({ [`GET /me/invoices/${INVOICE_ID}`]: { status: 200, body: invoice } }))
    renderApp('/portal/billing', { hasSession: true })
    await user.click(await screen.findByRole('link', { name: /View invoice INV-000007/ }, slow))
    expect(await screen.findByRole('heading', { name: 'Invoice INV-000007' })).toBeInTheDocument()
    expect(screen.getByText(/card ending 4242/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Pay now' })).toBeInTheDocument()
  })

  it('pays an invoice with a sandbox card and reports a declined card', async () => {
    const user = userEvent.setup()
    let attempt = 0
    const { calls } = mockApi(
      portal({
        [`GET /me/invoices/${INVOICE_ID}`]: { status: 200, body: invoice },
        [`POST /me/invoices/${INVOICE_ID}/pay`]: () =>
          ++attempt === 1
            ? json({ code: 'payment_declined', message: 'The card was declined.' }, 402)
            : json({ ...invoice, status: 'paid', balance: '0.00' }, 201),
      }),
    )
    renderApp(`/portal/billing/${INVOICE_ID}`, { hasSession: true })
    await user.click(await screen.findByRole('button', { name: 'Pay now' }, slow))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Card number'), '4000 0000 0000 0002')
    await user.type(within(dialog).getByLabelText('Month'), '12')
    await user.type(within(dialog).getByLabelText('Year'), '40')
    await user.type(within(dialog).getByLabelText('Security code'), '123')
    await user.click(within(dialog).getByRole('button', { name: 'Pay now' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The card was declined.')

    await user.click(within(dialog).getByRole('button', { name: 'Pay now' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    const sent = calls.filter((c) => c.path.endsWith('/pay')).at(-1)
    expect(sent?.body).toMatchObject({
      amount: '50.00',
      card: { card_number: '4000000000000002', exp_month: 12, exp_year: 2040, cvv: '123' },
    })
  })

  it('downloads an invoice as a PDF', async () => {
    const user = userEvent.setup()
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    mockApi(
      portal({
        [`GET /me/invoices/${INVOICE_ID}`]: { status: 200, body: invoice },
        [`GET /me/invoices/${INVOICE_ID}/pdf`]: () => new Response('%PDF-1.4', { status: 200 }),
      }),
    )
    renderApp(`/portal/billing/${INVOICE_ID}`, { hasSession: true })
    await user.click(await screen.findByRole('button', { name: /Download PDF/ }, slow))
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled())
  })

  it('lists the reminders that were sent', async () => {
    mockApi(
      portal({
        'GET /me/notifications': {
          status: 200,
          body: [
            {
              id: '80000000-0000-4000-8000-000000000001',
              kind: '24h',
              title: 'Appointment reminder',
              sent_at: '2030-05-13T14:00:00Z',
              appointment_id: '30000000-0000-4000-8000-000000000001',
            },
          ],
        },
      }),
    )
    renderApp('/portal/notifications', { hasSession: true })
    expect(await screen.findByText('Appointment reminder', undefined, slow)).toBeInTheDocument()
  })
})

describe('profile and security', () => {
  const sessions = [
    {
      id: '90000000-0000-4000-8000-000000000001',
      user_agent: 'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36',
      ip: '10.0.0.2',
      last_active: '2030-05-01T10:00:00Z',
      expires_at: '2030-05-08T10:00:00Z',
      current: true,
    },
    {
      id: '90000000-0000-4000-8000-000000000002',
      user_agent: 'Mozilla/5.0 (iPhone) Safari/604.1',
      ip: null,
      last_active: '2030-04-28T10:00:00Z',
      expires_at: '2030-05-05T10:00:00Z',
      current: false,
    },
  ]
  const profile = (extra: Handlers = {}): Handlers =>
    portal({ 'GET /auth/sessions': { status: 200, body: sessions }, ...extra })

  it('describes browsers in plain words', () => {
    expect(describeAgent(sessions[0]?.user_agent ?? null)).toBe('Chrome on Windows')
    expect(describeAgent(sessions[1]?.user_agent ?? null)).toBe('Safari on iOS')
    expect(describeAgent(null)).toBe('Unknown device')
  })

  it('saves personal details and communication preferences', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi(
      profile({
        'PATCH /me': (init) => json({ ...patientProfile, ...JSON.parse(String(init?.body)) }),
      }),
    )
    renderApp('/portal/profile', { hasSession: true })
    const first = await screen.findByLabelText(/First name/, undefined, slow)
    await waitFor(() => expect(first).toHaveValue('Rachel'))
    await user.clear(first)
    await user.type(first, 'Rae')
    await user.click(screen.getByRole('button', { name: 'Save details' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({ first_name: 'Rae' }),
    )
    await user.click(screen.getByRole('switch', { name: /news and oral health tips/i }))
    await waitFor(() =>
      expect(calls.filter((c) => c.method === 'PATCH').at(-1)?.body).toEqual({
        marketing_consent: true,
      }),
    )
  })

  it('shows signed in devices and signs another one out', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi(
      profile({ 'DELETE /auth/sessions/90000000-0000-4000-8000-000000000002': { status: 204 } }),
    )
    renderApp('/portal/profile', { hasSession: true })
    expect(await screen.findByText('Chrome on Windows', undefined, slow)).toBeInTheDocument()
    expect(screen.getByText('This device')).toBeInTheDocument()
    // The current device cannot be signed out from here, only the other one.
    const devices = within(screen.getByRole('region', { name: 'Where you are signed in' }))
    expect(devices.getAllByRole('button')).toHaveLength(1)
    await user.click(devices.getByRole('button', { name: /Sign out Safari on iOS/ }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
  })

  it('checks that the two new passwords match before sending anything', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi(profile())
    renderApp('/portal/profile', { hasSession: true })
    const form = await screen.findByRole('form', { name: 'Change password' }, slow)
    await user.type(within(form).getByLabelText(/Current password/), 'old-password-123')
    await user.type(within(form).getByLabelText(/^New password/), 'a-new-long-password-9')
    await user.type(
      within(form).getByLabelText(/Repeat the new password/),
      'something-else-entirely',
    )
    await user.click(within(form).getByRole('button', { name: 'Change password' }))
    expect(await within(form).findByText(/do not match/i)).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/auth/password')).toBe(false)
  })

  it('turns on two step verification with the code from an app', async () => {
    const user = userEvent.setup()
    let enabled = false
    const { calls } = mockApi(
      profile({
        'GET /auth/me': () =>
          json({
            id: 'u',
            email: 'patient@example.com',
            role: 'patient',
            mfa_enabled: enabled,
            email_verified: true,
            patient_id: patientProfile.id,
          }),
        'POST /auth/mfa/setup': {
          status: 200,
          body: { secret: 'JBSWY3DPEHPK3PXP', otpauth_uri: 'otpauth://x' },
        },
        'POST /auth/mfa/enable': () => {
          enabled = true
          return json({ recovery_codes: ['aaaa-bbbb', 'cccc-dddd'] })
        },
      }),
    )
    renderApp('/portal/profile', { hasSession: true })
    await user.click(
      await screen.findByRole('button', { name: 'Set up two step verification' }, slow),
    )
    expect(await screen.findByLabelText('Setup key')).toHaveTextContent('JBSWY3DPEHPK3PXP')
    await user.type(screen.getByLabelText('6 digit code'), '123456')
    await user.click(screen.getByRole('button', { name: 'Turn on' }))
    expect(await screen.findByText('aaaa-bbbb')).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/auth/mfa/enable')?.body).toEqual({ code: '123456' })
  })
})
