import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { axe } from 'vitest-axe'

import { TooltipProvider } from '@/components/ui/display'
import { ToastProvider } from '@/components/ui/toast'
import StyleguidePage from '@/pages/StyleguidePage'

function renderPage() {
  return render(
    <MemoryRouter>
      <TooltipProvider>
        <ToastProvider>
          <StyleguidePage />
        </ToastProvider>
      </TooltipProvider>
    </MemoryRouter>,
  )
}

describe('style guide', () => {
  it('documents every component the design system promises', () => {
    renderPage()
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)
    expect(headings).toEqual([
      'Colour',
      'Typography',
      'Buttons',
      'Form controls',
      'Choices',
      'Dialog, drawer, tooltip and toast',
      'Loading and empty states',
      'Cards, badges, avatars and accordion',
      'Table and chart',
      'Stepper, pagination and breadcrumbs',
      'Date and time pickers',
      'Statistics and ratings',
    ])
    for (const name of [
      'Primary',
      'Accent',
      'Secondary',
      'Ghost',
      'Destructive',
      'Link',
      'Saving',
    ]) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument()
    }
    expect(screen.getByRole('table', { name: 'Recent visits' })).toBeInTheDocument()
    expect(screen.getByRole('grid', { name: /\d{4}$/ })).toBeInTheDocument()
    expect(screen.getAllByRole('figure')).toHaveLength(1)
  })

  it('has no accessibility violations that can be detected without a browser', async () => {
    const { container } = renderPage()
    const results = await axe(container, { rules: { 'color-contrast': { enabled: false } } })
    expect(results).toHaveNoViolations()
  })

  it('shows form validation messages in plain words', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByRole('button', { name: 'Check form' }))
    expect(await screen.findByText('Enter your name.')).toBeInTheDocument()
    expect(screen.getByText('Enter your email address.')).toBeInTheDocument()
    expect(screen.getByText('Please accept to continue.')).toBeInTheDocument()
    expect(screen.getByLabelText(/full name/i)).toHaveAttribute('aria-invalid', 'true')
  })

  it('opens a toast from a button', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByRole('button', { name: 'Success toast' }))
    expect(await screen.findByText('Appointment confirmed')).toBeVisible()
  })
})
