import { defineConfig } from '@playwright/test'

/**
 * End to end tests in a real browser (the installed Chrome). The server behind /api is a stand in
 * written in e2e/support, so the tests need no database and always see the same clinic.
 *
 *   e2e      journeys for each role, the booking wizard and the assistant, and an accessibility
 *            check of every page (npm run test:e2e)
 *   visual   pictures of key pages compared with kept ones (npm run test:visual)
 */
export default defineConfig({
  testDir: 'e2e',
  timeout: 45_000,
  fullyParallel: true,
  // Twelve browsers at once starve the dev server on a laptop and make tests time out.
  workers: 4,
  reporter: [['list']],
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.01, animations: 'disabled' } },
  use: {
    baseURL: 'http://localhost:5199',
    channel: 'chrome',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'e2e', testIgnore: /visual\.spec/ },
    { name: 'visual', testMatch: /visual\.spec/ },
  ],
  webServer: {
    command: 'npx vite --port 5199 --strictPort',
    url: 'http://localhost:5199',
    reuseExistingServer: false,
    timeout: 60_000,
  },
})
