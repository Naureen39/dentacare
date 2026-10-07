import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { RouterProvider } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createTestRouter } from '@/app/routes'

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={createTestRouter([path])} />
    </QueryClientProvider>,
  )
}

describe('application routes', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders the home page and reports API status', async () => {
    const payload = { name: 'Meridian Dental Care', version: '0.1.0', environment: 'test' }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 })),
    )
    renderAt('/')
    expect(
      await screen.findByRole('heading', { name: /exceptional dental care/i }),
    ).toBeInTheDocument()
    expect(await screen.findByText(/connected to meridian dental care/i)).toBeInTheDocument()
  })

  it('renders the not found page for unknown routes', async () => {
    renderAt('/does-not-exist')
    expect(await screen.findByRole('heading', { name: /page not found/i })).toBeInTheDocument()
  })

  it('shows the demo disclaimer and a skip link', async () => {
    renderAt('/does-not-exist')
    expect(await screen.findByText(/demo environment, fictional clinic/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /skip to main content/i })).toBeInTheDocument()
  })
})
