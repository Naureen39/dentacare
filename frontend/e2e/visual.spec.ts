import { expect, test, type Page } from '@playwright/test'

import { withFakeApi } from './support/fake-api'
import { signIn } from './support/sign-in'

/**
 * Visual regression: pictures of the pages that matter most, compared with the ones kept in
 * `visual.spec.ts-snapshots`. Everything that changes between runs is held still: the date is
 * fixed, motion is off, the map tiles (from the internet) are blocked and the data is the stand in
 * API's. Rendering differs between operating systems, so each system has its own pictures.
 *
 *   npm run test:visual             compare with the kept pictures
 *   npm run test:visual:update      replace them after a change that was meant
 */
const DAY = '2030-06-12'
test.use({ reducedMotion: 'reduce' })

async function steady(page: Page, role?: string) {
  const api = await withFakeApi(page)
  api.today = DAY
  await page.clock.setFixedTime(new Date(`${DAY}T14:00:00Z`))
  await page.route('**/*.tile.openstreetmap.org/**', (route) => route.abort())
  if (role) await signIn(page, `${role}@example.com`)
  return api
}

async function settle(page: Page) {
  await page.waitForLoadState('networkidle')
  await page.evaluate(() => document.fonts.ready)
  // Pages fade their sections in as they are scrolled to: show them all before taking the picture.
  await page.evaluate(async () => {
    for (let y = 0; y < document.body.scrollHeight; y += 600) {
      window.scrollTo(0, y)
      await new Promise((r) => setTimeout(r, 30))
    }
    window.scrollTo(0, 0)
  })
  await page.waitForTimeout(400)
}

const publicPages = [
  ['home', '/'],
  ['services', '/services'],
  ['service-detail', '/services/porcelain-crown'],
  ['dentists', '/dentists'],
  ['pricing', '/pricing'],
  ['faq', '/faq'],
  ['contact', '/contact'],
  ['login', '/login'],
  ['booking-service-step', '/book/service'],
] as const

for (const [name, path] of publicPages) {
  test(`${name}, desktop`, async ({ page }) => {
    await steady(page)
    await page.setViewportSize({ width: 1280, height: 900 })
    await page.goto(path)
    await settle(page)
    await expect(page).toHaveScreenshot(`${name}-desktop.png`, {
      fullPage: true,
      mask: [page.locator('.leaflet-container')],
    })
  })
}

for (const [name, path] of [publicPages[0], publicPages[1], publicPages[7], publicPages[8]]) {
  test(`${name}, phone`, async ({ page }) => {
    await steady(page)
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(path)
    await settle(page)
    await expect(page).toHaveScreenshot(`${name}-phone.png`, {
      fullPage: true,
      mask: [page.locator('.leaflet-container')],
    })
  })
}

test('the front desk schedule', async ({ page }) => {
  await steady(page, 'receptionist')
  await page.setViewportSize({ width: 1280, height: 900 })
  await page
    .getByRole('navigation', { name: 'Console' })
    .getByRole('link', { name: 'Schedule' })
    .click()
  await expect(page.getByRole('button', { name: /Jonas Weber/ }).first()).toBeVisible()
  await expect(page).toHaveScreenshot('console-schedule.png', { mask: [page.getByRole('status')] })
})

test('the analytics overview', async ({ page }) => {
  await steady(page, 'admin')
  await page.setViewportSize({ width: 1280, height: 900 })
  await expect(
    page.getByRole('figure', { name: 'Revenue over time' }).locator('canvas').first(),
  ).toBeVisible()
  await page.waitForTimeout(1200) // the charts finish drawing
  await expect(page).toHaveScreenshot('analytics-overview.png', {
    // The "refreshed" line shows the time of the last refresh, which the stand in API sets.
    mask: [page.getByText(/Figures last refreshed/)],
    maxDiffPixelRatio: 0.02,
  })
})
