import { expect, test, type Page } from '@playwright/test'

import { CODE, withFakeApi } from './support/fake-api'

/** Pick the service and "first available", then the first time shown, and stop at the details. */
async function chooseUpToDetails(page: Page) {
  await page.goto('/book')
  await page.getByRole('button', { name: /Routine Exam and Cleaning/ }).click()
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('button', { name: /First available/ }).click()
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('radio').first().click()
  await expect(page.getByText(/^Selected:/)).toBeVisible()
  await expect(page.getByRole('timer')).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: 'Your details' })).toBeVisible()
}

async function fillGuest(page: Page) {
  const form = page.getByRole('form', { name: 'Your details' })
  await form.getByLabel(/First name/).fill('Jonas')
  await form.getByLabel(/Last name/).fill('Weber')
  await form.getByLabel(/Email address/).fill('jonas@example.com')
  await form.getByRole('checkbox', { name: /privacy policy/i }).click()
  await form.getByRole('button', { name: 'Continue' }).click()
}

async function signIn(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Email address').fill('rachel@example.com')
  await page.locator('input[type=password]').fill('a-long-password-9')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText('Your next appointment')).toBeVisible()
}

test('a guest books an appointment with an email code', async ({ page }) => {
  const api = await withFakeApi(page)
  await chooseUpToDetails(page)
  await fillGuest(page)

  await expect(page.getByRole('heading', { name: 'Check your email' })).toBeVisible()
  await page.getByLabel('Verification code').fill(CODE)
  await page.getByRole('button', { name: 'Confirm booking' }).click()

  await expect(page.getByRole('heading', { name: 'Your appointment is booked' })).toBeVisible()
  await expect(page.locator('dd', { hasText: 'Routine Exam and Cleaning' })).toBeVisible()
  await expect(page.getByRole('button', { name: /add to calendar/i })).toBeVisible()
  expect(api.appointments).toHaveLength(2) // the one that was already there, and this one
  expect(api.codesRequested).toBe(1)
})

test('a wrong email code is explained and the right one then works', async ({ page }) => {
  const api = await withFakeApi(page)
  await chooseUpToDetails(page)
  await fillGuest(page)

  await page.getByLabel('Verification code').fill('000000')
  await page.getByRole('button', { name: 'Confirm booking' }).click()
  await expect(page.getByRole('alert')).toContainText('That code is not right')
  await expect(page.getByRole('heading', { name: 'Check your email' })).toBeVisible()
  expect(api.appointments).toHaveLength(1)

  await page.getByLabel('Verification code').fill(CODE)
  await page.getByRole('button', { name: 'Confirm booking' }).click()
  await expect(page.getByRole('heading', { name: 'Your appointment is booked' })).toBeVisible()
  expect(api.wrongCodes).toBe(1)
})

test('a time that was just taken leads to nearby alternatives', async ({ page }) => {
  const api = await withFakeApi(page)
  api.conflictOnNextHold = true
  await page.goto('/book')
  await page.getByRole('button', { name: /Routine Exam and Cleaning/ }).click()
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('button', { name: /First available/ }).click()
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('radio').first().click()

  const alert = page.getByRole('alert')
  await expect(alert).toContainText('not available')
  await expect(page.getByRole('button', { name: 'Continue' })).toBeDisabled()
  await alert.getByRole('button').first().click()

  await expect(page.getByText(/^Selected:/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Continue' })).toBeEnabled()
  expect(api.holds).toBe(2)
})

test('a patient who is signed in books without an email code', async ({ page }) => {
  const api = await withFakeApi(page)
  await signIn(page)
  await page.getByRole('main').getByRole('link', { name: 'Book an appointment' }).first().click()
  await page.getByRole('button', { name: /Routine Exam and Cleaning/ }).click()
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('button', { name: /First available/ }).click()
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('radio').first().click()
  await expect(page.getByText(/^Selected:/)).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()

  const form = page.getByRole('form', { name: 'Your details' })
  await expect(form.getByLabel(/First name/)).toHaveValue('Rachel')
  await form.getByRole('checkbox', { name: /privacy policy/i }).click()
  await form.getByRole('button', { name: 'Book appointment' }).click()

  await expect(page.getByRole('heading', { name: 'Your appointment is booked' })).toBeVisible()
  expect(api.codesRequested).toBe(0)
  expect(api.requests.some((r) => r.path === '/me/appointments' && r.method === 'POST')).toBe(true)
})

test('a patient reschedules an appointment', async ({ page }) => {
  const api = await withFakeApi(page)
  await signIn(page)
  await page.getByRole('link', { name: 'Appointments' }).click()
  await page.getByRole('button', { name: /Reschedule Routine Exam/ }).click()

  const dialog = page.getByRole('dialog', { name: 'Reschedule your appointment' })
  await expect(dialog.getByText(/free cancellation|free until/i)).toBeVisible()
  await dialog.getByRole('radio').nth(1).click()
  await dialog.getByRole('button', { name: 'Confirm new time' }).click()
  await expect(dialog).toBeHidden()

  expect(api.appointments.filter((a) => a.status === 'booked')).toHaveLength(1)
  expect(api.appointments.find((a) => a.rescheduled_from)).toBeTruthy()
  await expect(page.getByRole('button', { name: /Reschedule Routine Exam/ })).toHaveCount(1)
})

test('a patient cancels an appointment after reading the policy', async ({ page }) => {
  const api = await withFakeApi(page)
  await signIn(page)
  await page.getByRole('link', { name: 'Appointments' }).click()
  await page.getByRole('button', { name: /Cancel Routine Exam/ }).click()

  const dialog = page.getByRole('dialog', { name: 'Cancel this appointment?' })
  await expect(dialog.getByText(/free until/i)).toBeVisible()
  await dialog.getByRole('button', { name: 'Cancel appointment' }).click()
  await expect(dialog).toBeHidden()

  expect(api.appointments[0]?.status).toBe('cancelled')
  await expect(page.getByText('Cancelled', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /Cancel Routine Exam/ })).toHaveCount(0)
})
