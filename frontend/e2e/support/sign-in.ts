import { expect, type Page } from '@playwright/test'

/** Sign in through the form, as a person would. The address decides the role in the stand in API. */
export async function signIn(page: Page, email: string): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Email address').fill(email)
  await page.locator('input[type=password]').fill('a-long-password-9')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).not.toHaveURL(/\/login/)
}
