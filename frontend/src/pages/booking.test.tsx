import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { axe } from 'vitest-axe'

import { tokenStore } from '@/lib/api-client'
import { alternativesOf, periodOf, toChoice } from '@/lib/booking-api'
import { ApiError } from '@/lib/api-client'
import { buildIcs } from '@/lib/ics'
import {
  appointment,
  CROWN,
  patientProfile,
  publicCatalogue,
  RAMAN,
  ROUTINE,
  signedInPatient,
} from '@/test/booking-fixtures'
import { json, mockApi, renderApp, type Handlers } from '@/test/utils'

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.set(null)
})

const VERIFICATION = {
  verification_id: '40000000-0000-4000-8000-000000000001',
  expires_in: 600,
  message: 'Sent.',
}
const slow = { timeout: 10_000 }

/** Choose the service, the dentist and the first time, and stop on the details step. */
async function toDetails(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /Routine Exam and Cleaning/ }, slow))
  await user.click(screen.getByRole('button', { name: 'Continue' }))
  await user.click(await screen.findByRole('button', { name: /First available/ }))
  await user.click(screen.getByRole('button', { name: 'Continue' }))
  const times = await screen.findAllByRole('radio', undefined, slow)
  await user.click(times[0] as HTMLElement)
  await screen.findByText(/^Selected:/)
  await user.click(screen.getByRole('button', { name: 'Continue' }))
  await screen.findByRole('heading', { name: 'Your details' })
}

/** The details form. The page footer has an email field of its own, so queries stay inside. */
const detailsForm = () => within(screen.getByRole('form', { name: 'Your details' }))

async function fillGuest(user: ReturnType<typeof userEvent.setup>) {
  const form = detailsForm()
  await user.type(form.getByLabelText(/First name/), 'Jonas')
  await user.type(form.getByLabelText(/Last name/), 'Weber')
  await user.type(form.getByLabelText(/Email address/), 'jonas@example.com')
  await user.click(form.getByRole('checkbox', { name: /privacy policy/i }))
  await user.click(form.getByRole('button', { name: 'Continue' }))
}

const guestHandlers = (extra: Handlers = {}): Handlers => ({
  ...publicCatalogue,
  'POST /public/appointments/verification': { status: 202, body: VERIFICATION },
  'POST /public/appointments': () => json(appointment(), 201),
  ...extra,
})

describe('helpers', () => {
  it('groups times by the clinic day, not the visitor day', () => {
    expect(periodOf('2030-05-14T14:00:00Z')).toBe('morning') // 10:00 in New York
    expect(periodOf('2030-05-14T18:00:00Z')).toBe('afternoon')
    expect(periodOf('2030-05-14T22:30:00Z')).toBe('evening')
    const choice = toChoice({
      start: '2030-05-14T14:00:00Z',
      end: '2030-05-14T14:45:00Z',
      dentist_id: RAMAN.id,
      dentist_name: RAMAN.full_name,
    })
    expect(choice).toMatchObject({ date: '2030-05-14', label: '10:00 AM', period: 'morning' })
  })

  it('reads the alternatives the server offers after a conflict', () => {
    const slot = {
      start: '2030-05-14T15:00:00Z',
      end: '2030-05-14T15:45:00Z',
      dentist_id: RAMAN.id,
      dentist_name: 'Dr. Priya Raman',
    }
    const error = new ApiError(409, {
      code: 'slot_unavailable',
      message: 'Taken.',
      details: { alternatives: [slot] },
    })
    expect(alternativesOf(error).map((c) => c.label)).toEqual(['11:00 AM'])
    expect(alternativesOf(new Error('x'))).toEqual([])
  })

  it('builds a calendar file with escaped text and an end after the start', () => {
    const text = buildIcs({
      id: 'abc',
      start: '2030-05-14T14:00:00Z',
      end: '2030-05-14T14:45:00Z',
      service: 'Crown, porcelain',
      dentist: 'Dr. Raman',
    })
    expect(text).toContain('BEGIN:VCALENDAR\r\n')
    expect(text).toContain('DTSTART:20300514T140000Z')
    expect(text).toContain('DTEND:20300514T144500Z')
    expect(text).toContain('SUMMARY:Crown\\, porcelain at Meridian Dental Care')
    expect(text.endsWith('END:VCALENDAR\r\n')).toBe(true)
  })
})

describe('booking wizard as a guest', () => {
  it('books through all steps and shows the confirmation', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi(guestHandlers())
    renderApp('/book')
    await toDetails(user)
    // The hold countdown is visible once a time is chosen.
    expect(screen.getByRole('timer')).toHaveTextContent(/^[45]:\d\d$/)
    await fillGuest(user)

    expect(await screen.findByRole('heading', { name: 'Check your email' })).toBeInTheDocument()
    const verify = calls.find((c) => c.path === '/public/appointments/verification')
    expect(verify?.body).toEqual({ email: 'jonas@example.com', first_name: 'Jonas' })

    await user.type(await screen.findByLabelText('Verification code'), '123456')
    await user.click(screen.getByRole('button', { name: 'Confirm booking' }))

    expect(
      await screen.findByRole('heading', { name: 'Your appointment is booked' }),
    ).toBeInTheDocument()
    const booked = calls.find((c) => c.method === 'POST' && c.path === '/public/appointments')
    expect(booked?.body).toMatchObject({
      service_id: ROUTINE.id,
      dentist_id: RAMAN.id,
      otp: '123456',
      consent: true,
      email: 'jonas@example.com',
      hold_token: 'h'.repeat(24),
    })
    expect(screen.getByRole('button', { name: /add to calendar/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /create a free account/i })).toHaveAttribute(
      'href',
      '/register',
    )
  })

  it('keeps the entries when going back', async () => {
    const user = userEvent.setup()
    mockApi(guestHandlers())
    renderApp('/book')
    await toDetails(user)
    await user.click(screen.getByRole('button', { name: 'Back' }))
    // The chosen time is still selected on the previous step.
    expect(await screen.findByText(/^Selected:/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Back' }))
    expect(await screen.findByRole('button', { name: /First available/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('says what is wrong when the code is not right and lets the guest try again', async () => {
    const user = userEvent.setup()
    let attempts = 0
    mockApi(
      guestHandlers({
        'POST /public/appointments': () =>
          ++attempts === 1
            ? json({ code: 'otp_invalid', message: 'Invalid code.' }, 400)
            : json(appointment(), 201),
      }),
    )
    renderApp('/book')
    await toDetails(user)
    await fillGuest(user)
    const code = await screen.findByLabelText('Verification code')
    await user.type(code, '000000')
    await user.click(screen.getByRole('button', { name: 'Confirm booking' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/code is not right/i)
    expect(screen.getByRole('heading', { name: 'Check your email' })).toBeInTheDocument()

    await user.clear(code)
    await user.type(code, '123456')
    await user.click(screen.getByRole('button', { name: 'Confirm booking' }))
    expect(
      await screen.findByRole('heading', { name: 'Your appointment is booked' }),
    ).toBeInTheDocument()
  })

  it('asks for a new code when too many wrong ones were entered', async () => {
    const user = userEvent.setup()
    mockApi(
      guestHandlers({
        'POST /public/appointments': () => json({ code: 'otp_locked', message: 'Locked.' }, 400),
      }),
    )
    renderApp('/book')
    await toDetails(user)
    await fillGuest(user)
    await user.type(await screen.findByLabelText('Verification code'), '111111')
    await user.click(screen.getByRole('button', { name: 'Confirm booking' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/too many wrong codes/i)
    expect(screen.getByRole('button', { name: 'Confirm booking' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Send a new code' })).toBeEnabled()
  })

  it('offers the nearest other times when the chosen time was just taken', async () => {
    const user = userEvent.setup()
    let holds = 0
    const alternative = {
      start: '2030-05-14T15:00:00Z',
      end: '2030-05-14T15:45:00Z',
      dentist_id: RAMAN.id,
      dentist_name: RAMAN.full_name,
    }
    const { calls } = mockApi(
      guestHandlers({
        'POST /public/hold': () =>
          ++holds === 1
            ? json(
                {
                  code: 'slot_unavailable',
                  message: 'This time is not available.',
                  details: { alternatives: [alternative] },
                },
                409,
              )
            : json(
                {
                  hold_token: 'h'.repeat(24),
                  expires_in: 300,
                  start: alternative.start,
                  end: alternative.end,
                  dentist_id: RAMAN.id,
                },
                201,
              ),
      }),
    )
    renderApp('/book')
    await user.click(await screen.findByRole('button', { name: /Routine Exam and Cleaning/ }, slow))
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await user.click(await screen.findByRole('button', { name: /First available/ }))
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await user.click((await screen.findAllByRole('radio', undefined, slow))[0] as HTMLElement)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/not available/i)
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
    await user.click(within(alert).getByRole('button', { name: /11:00 AM/ }))

    expect(await screen.findByText(/^Selected:/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled()
    expect(calls.filter((c) => c.path === '/public/hold')).toHaveLength(2)
  })

  it('requires the privacy consent before going on', async () => {
    const user = userEvent.setup()
    mockApi(guestHandlers())
    renderApp('/book')
    await toDetails(user)
    const form = detailsForm()
    await user.type(form.getByLabelText(/First name/), 'Jonas')
    await user.type(form.getByLabelText(/Last name/), 'Weber')
    await user.type(form.getByLabelText(/Email address/), 'jonas@example.com')
    await user.click(form.getByRole('button', { name: 'Continue' }))
    expect(
      await screen.findByText(/accept the privacy policy and appointment reminders/i),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Your details' })).toBeInTheDocument()
  })

  it('starts from the service and dentist named in a link', async () => {
    mockApi(guestHandlers())
    renderApp('/book?service=SV05&dentist=priya-raman')
    expect(
      await screen.findByRole('heading', { name: 'Who would you like to see?' }, slow),
    ).toBeInTheDocument()
    const raman = await screen.findByRole('button', { name: /Dr. Priya Raman/ })
    await waitFor(() => expect(raman).toHaveAttribute('aria-pressed', 'true'))
    expect(CROWN.code).toBe('SV05')
  })

  it('suggests a routine exam when the guest is not sure, and can search', async () => {
    const user = userEvent.setup()
    mockApi(guestHandlers())
    renderApp('/book/service')
    await user.click(await screen.findByRole('button', { name: /i am not sure/i }, slow))
    expect(screen.getByRole('button', { name: /Routine Exam and Cleaning/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await user.type(screen.getByLabelText('Search services'), 'crown')
    expect(screen.queryByRole('button', { name: /Routine Exam/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Porcelain Crown/ })).toBeInTheDocument()
  })

  it('offers the phone when the services cannot be loaded', async () => {
    mockApi({
      'GET /public/services': { status: 500, body: { code: 'server_error', message: 'x' } },
    })
    renderApp('/book/service')
    expect(
      await screen.findByText(/could not load our services/i, undefined, slow),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /call \(555\) 010-0199/i })).toBeInTheDocument()
  })

  it('returns to the start when the confirmation page is opened without a booking', async () => {
    mockApi(guestHandlers())
    renderApp('/book/done')
    expect(
      await screen.findByRole('heading', { name: 'What would you like to book?' }, slow),
    ).toBeInTheDocument()
  })
})

describe('accessibility', () => {
  it('has no detectable problems on the service, time and details steps', async () => {
    const user = userEvent.setup()
    mockApi(guestHandlers())
    const { container } = renderApp('/book')
    await screen.findByRole('button', { name: /Routine Exam and Cleaning/ }, slow)
    const rules = { rules: { 'color-contrast': { enabled: false } } }
    expect(await axe(container, rules)).toHaveNoViolations()
    await user.click(screen.getByRole('button', { name: /Routine Exam and Cleaning/ }))
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await user.click(await screen.findByRole('button', { name: /First available/ }))
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await user.click((await screen.findAllByRole('radio', undefined, slow))[0] as HTMLElement)
    await screen.findByText(/^Selected:/)
    expect(await axe(container, rules)).toHaveNoViolations()
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await screen.findByRole('heading', { name: 'Your details' })
    expect(await axe(container, rules)).toHaveNoViolations()
  })
})

describe('booking wizard as a signed in patient', () => {
  it('prefills the details, skips the email check and books straight away', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi({
      ...signedInPatient,
      ...publicCatalogue,
      'POST /me/appointments': () => json(appointment(), 201),
    })
    renderApp('/book', { hasSession: true })
    // Five steps: there is no "Verify" step for a patient.
    await toDetails(user)
    expect(screen.queryByText('Verify')).not.toBeInTheDocument()
    const form = detailsForm()
    await waitFor(() => expect(form.getByLabelText(/First name/)).toHaveValue('Rachel'))
    expect(form.getByLabelText(/Email address/)).toHaveValue('patient@example.com')
    expect(form.getByLabelText(/Email address/)).toHaveAttribute('readonly')
    await user.click(form.getByRole('checkbox', { name: /privacy policy/i }))
    await user.click(form.getByRole('button', { name: 'Book appointment' }))

    expect(
      await screen.findByRole('heading', { name: 'Your appointment is booked' }),
    ).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/public/appointments/verification')).toBe(false)
    const booked = calls.find((c) => c.method === 'POST' && c.path === '/me/appointments')
    expect(booked?.body).toMatchObject({ service_id: ROUTINE.id, hold_token: 'h'.repeat(24) })
    expect(booked?.headers.get('Authorization')).toBe('Bearer access-token-1')
    expect(screen.getByRole('link', { name: /patient portal/i })).toHaveAttribute(
      'href',
      '/portal/appointments',
    )
    expect(patientProfile.first_name).toBe('Rachel')
  })
})
