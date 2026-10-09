import { expect, test } from '@playwright/test'

import { withFakeApi } from './support/fake-api'

test('a patient books a visit through the assistant with buttons only, in under eight interactions', async ({
  page,
}) => {
  const api = await withFakeApi(page)
  await page.goto('/login')
  await page.getByLabel('Email address').fill('rachel@example.com')
  await page.locator('input[type=password]').fill('a-long-password-9')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText('Your next appointment')).toBeVisible()

  // Everything from here is one tap each. Nothing is typed.
  let interactions = 0
  const tap = async (target: ReturnType<typeof page.getByRole>) => {
    interactions += 1
    await target.click()
  }

  await tap(page.getByRole('button', { name: /Chat with our assistant/ }))
  const chat = page.getByRole('dialog', { name: 'Meridian Assistant' })
  await expect(chat.getByText(/How can I help/)).toBeVisible()
  await tap(chat.getByRole('button', { name: 'Book an appointment' }))
  await tap(chat.getByRole('button', { name: /Routine Exam and Cleaning/ }))
  await tap(chat.getByRole('button', { name: /Tomorrow/ }))
  await tap(chat.getByRole('button', { name: '10:00 AM' }))
  const summary = chat.getByRole('region', { name: 'Booking summary' })
  await expect(summary).toContainText('Routine Exam and Cleaning')
  await tap(summary.getByRole('button', { name: 'Confirm booking' }))

  await expect(chat.getByText(/Your appointment is booked/)).toBeVisible()
  expect(interactions).toBeLessThan(8)
  expect(api.appointments.filter((a) => a.status === 'booked')).toHaveLength(2)
  // The link in the reply opens a page of the site and puts the chat away.
  await chat.getByRole('link', { name: 'Manage my appointments' }).click()
  await expect(page).toHaveURL(/\/portal\/appointments/)
  await expect(chat).toBeHidden()
})

test('the chat works from the keyboard and keeps the conversation after leaving the page', async ({
  page,
}) => {
  await withFakeApi(page)
  await page.goto('/pricing')
  await page.getByRole('button', { name: /Chat with our assistant/ }).focus()
  await page.keyboard.press('Enter')
  const chat = page.getByRole('dialog', { name: 'Meridian Assistant' })
  await expect(chat.getByRole('textbox', { name: 'Type your message' })).toBeFocused()
  await expect(chat.getByText(/How can I help/)).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(chat).toBeHidden()
  await expect(page.getByRole('button', { name: /Chat with our assistant/ })).toBeFocused()

  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'About' }).click()
  await expect(page).toHaveURL(/\/about/)
  await page.getByRole('button', { name: /Chat with our assistant/ }).click()
  await expect(chat.getByText(/How can I help/)).toBeVisible()
})
