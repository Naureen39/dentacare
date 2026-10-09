import { defineConfig } from '@playwright/test'

/**
 * End to end tests of the booking wizard and the patient portal. The browser is real (the
 * installed Chrome); the server behind /api is a small stand in written in e2e/support, so the
 * tests need no database and always see the same clinic.
 */
export default defineConfig({
  testDir: 'e2e',
  timeout: 45_000,
  fullyParallel: true,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5199',
    channel: 'chrome',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npx vite --port 5199 --strictPort',
    url: 'http://localhost:5199',
    reuseExistingServer: false,
    timeout: 60_000,
  },
})
