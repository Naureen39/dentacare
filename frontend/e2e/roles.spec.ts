import { expect, test, type Page } from '@playwright/test'

import { withFakeApi } from './support/fake-api'
import { signIn } from './support/sign-in'

const refused = (page: Page) => page.getByRole('heading', { name: /do not have access/i })
const consoleMenu = (page: Page) => page.getByRole('navigation', { name: 'Console' })

test.describe('a visitor who has not signed in', () => {
  test('browses the public site but is sent to sign in from the console', async ({ page }) => {
    await withFakeApi(page)
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toContainText(/exceptional dental care/i)
    await page
      .getByRole('navigation', { name: 'Main' })
      .getByRole('link', { name: 'About' })
      .click()
    await expect(page).toHaveURL(/\/about/)

    for (const path of ['/staff', '/staff/schedule', '/admin/analytics', '/portal']) {
      await page.goto(path)
      await expect(page).toHaveURL(/\/login/)
    }
  })
})

test.describe('a patient', () => {
  test('reaches their own area and nothing that belongs to staff', async ({ page }) => {
    await withFakeApi(page)
    await signIn(page, 'rachel@example.com')
    await expect(page.getByText('Your next appointment')).toBeVisible()
    // Move inside the app, so the session held in memory is kept.
    for (const path of ['/staff', '/staff/patients', '/admin/staff', '/admin/analytics']) {
      await page.evaluate((to) => {
        window.history.pushState({}, '', to)
        window.dispatchEvent(new PopStateEvent('popstate'))
      }, path)
      await expect(refused(page)).toBeVisible()
    }
  })
})

test.describe('a receptionist', () => {
  test('works the front desk and is kept out of administration', async ({ page }) => {
    const api = await withFakeApi(page)
    await signIn(page, 'receptionist@example.com')
    await expect(page.getByRole('heading', { name: 'Today' })).toBeVisible()
    const menu = consoleMenu(page)
    for (const name of ['Today', 'Schedule', 'Patients', 'Billing desk'])
      await expect(menu.getByRole('link', { name })).toBeVisible()
    await expect(menu.getByRole('link', { name: 'Settings' })).toHaveCount(0)
    await expect(menu.getByRole('link', { name: 'Analytics' })).toHaveCount(0)

    // Confirm today's first visit from the list of arrivals.
    const arrivals = page.getByRole('region', { name: /Arrivals/ })
    await expect(arrivals).toContainText('Jonas Weber')
    await arrivals.getByRole('button', { name: 'Confirm' }).click()
    await expect.poll(() => api.statusChanges.at(-1)?.status).toBe('confirmed')

    // Open a visit on the schedule.
    await menu.getByRole('link', { name: 'Schedule' }).click()
    await page
      .getByRole('button', { name: /Jonas Weber/ })
      .first()
      .click()
    const drawer = page.getByRole('dialog')
    await expect(drawer.getByText('jonas@example.com')).toBeVisible()
    await expect(drawer.getByLabel('Clinical note')).toHaveCount(0)
    await page.keyboard.press('Escape')

    await menu.getByRole('link', { name: 'Patients' }).click()
    await expect(page.getByRole('link', { name: /Weber, Jonas/ })).toBeVisible()

    for (const path of ['/admin/staff', '/admin/settings', '/admin/audit', '/admin/analytics']) {
      await page.evaluate((to) => {
        window.history.pushState({}, '', to)
        window.dispatchEvent(new PopStateEvent('popstate'))
      }, path)
      await expect(refused(page)).toBeVisible()
    }
  })
})

test.describe('a dentist', () => {
  test('sees only their own day and keeps a private note', async ({ page }) => {
    const api = await withFakeApi(page)
    await signIn(page, 'dentist@example.com')
    await expect(page.getByRole('heading', { name: 'My day' })).toBeVisible()
    await expect(page.getByText('My numbers')).toBeVisible()
    const menu = consoleMenu(page)
    await expect(menu.getByRole('link')).toHaveText(['My day', 'My schedule'])

    await menu.getByRole('link', { name: 'My schedule' }).click()
    await page
      .getByRole('button', { name: /Jonas Weber/ })
      .first()
      .click()
    const note = page.getByRole('dialog').getByLabel('Clinical note')
    await expect(note).toHaveValue('Earlier note')
    await note.fill('Upper left molar, review in two weeks.')
    await page.getByRole('dialog').getByRole('button', { name: 'Save note' }).click()
    await expect.poll(() => api.notes.at(-1)).toBe('Upper left molar, review in two weeks.')
    await expect(page.getByRole('dialog').getByRole('button', { name: 'Confirm' })).toHaveCount(0)
    await page.keyboard.press('Escape')

    for (const path of ['/staff/patients', '/staff/billing', '/admin/staff']) {
      await page.evaluate((to) => {
        window.history.pushState({}, '', to)
        window.dispatchEvent(new PopStateEvent('popstate'))
      }, path)
      await expect(refused(page)).toBeVisible()
    }
  })
})

test.describe('an administrator', () => {
  test('reads the analytics and manages the practice', async ({ page }) => {
    await withFakeApi(page)
    await signIn(page, 'admin@example.com')
    await expect(page).toHaveURL(/\/admin\/analytics\/overview/)
    const cards = page.getByRole('region', { name: 'Key figures' })
    await expect(cards.getByText('Collected revenue')).toBeVisible()
    const revenue = page.getByRole('figure', { name: 'Revenue over time' })
    await expect(revenue.locator('canvas').first()).toBeVisible()

    await page
      .getByRole('navigation', { name: 'Analytics sections' })
      .getByRole('link', { name: 'Finance' })
      .click()
    await expect(page.getByRole('region', { name: 'Receivables' })).toBeVisible()

    const menu = consoleMenu(page)
    await menu.getByRole('link', { name: 'Staff', exact: true }).click()
    await expect(page.getByRole('table', { name: 'Staff accounts' })).toContainText(
      'receptionist@example.com',
    )
    await menu.getByRole('link', { name: 'Settings' }).click()
    await expect(page.getByRole('form', { name: 'Booking rules' })).toBeVisible()
    // Administrators also have the front desk screens.
    await menu.getByRole('link', { name: 'Billing desk' }).click()
    await expect(page.getByRole('heading', { name: 'Billing desk' })).toBeVisible()
  })
})
