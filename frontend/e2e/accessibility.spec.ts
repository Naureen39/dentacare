import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

import { sitemapPaths } from '../vite-plugins/seo'
import { withFakeApi } from './support/fake-api'
import { signIn } from './support/sign-in'

const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice']

/** No map tiles from the internet: they make the page slow and the result unrepeatable. */
async function quiet(page: Page) {
  await page.route('**/*.tile.openstreetmap.org/**', (route) => route.abort())
}

async function audit(page: Page) {
  await page.waitForLoadState('networkidle')
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze()
  const summary = results.violations.map(
    (v) =>
      `${v.id}: ${v.nodes
        .map((n) => n.target.join(' '))
        .slice(0, 3)
        .join(' | ')}`,
  )
  expect(summary, 'accessibility violations').toEqual([])
}

const publicPages = [...sitemapPaths(), '/login', '/register', '/forgot-password', '/book/service']

test.describe('every public page, on a desktop', () => {
  for (const path of publicPages) {
    test(path, async ({ page }) => {
      await withFakeApi(page)
      await quiet(page)
      await page.goto(path)
      await audit(page)
    })
  }
})

test.describe('the pages people use most, on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true })
  for (const path of ['/', '/services', '/contact', '/book/service', '/login', '/faq']) {
    test(path, async ({ page }) => {
      await withFakeApi(page)
      await quiet(page)
      await page.goto(path)
      await audit(page)
    })
  }
})

test.describe('the signed in areas', () => {
  const areas: [string, string, string][] = [
    ['patient', 'rachel@example.com', '/portal'],
    ['patient', 'rachel@example.com', '/portal/appointments'],
    ['patient', 'rachel@example.com', '/portal/profile'],
    ['receptionist', 'receptionist@example.com', '/staff'],
    ['receptionist', 'receptionist@example.com', '/staff/schedule'],
    ['receptionist', 'receptionist@example.com', '/staff/patients'],
    ['dentist', 'dentist@example.com', '/staff'],
    ['admin', 'admin@example.com', '/admin/analytics/overview'],
    ['admin', 'admin@example.com', '/admin/analytics/finance'],
    ['admin', 'admin@example.com', '/admin/settings'],
    ['admin', 'admin@example.com', '/admin/staff'],
  ]
  for (const [role, email, path] of areas) {
    test(`${role}: ${path}`, async ({ page }) => {
      await withFakeApi(page)
      await signIn(page, email)
      // Move inside the app so the session held in memory is kept.
      await page.evaluate((to) => {
        window.history.pushState({}, '', to)
        window.dispatchEvent(new PopStateEvent('popstate'))
      }, path)
      await page.locator('main').first().waitFor()
      await audit(page)
    })
  }
})
