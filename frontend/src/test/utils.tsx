import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { HelmetProvider } from 'react-helmet-async'
import type { ReactElement } from 'react'
import { RouterProvider } from 'react-router-dom'
import { vi } from 'vitest'

import { createTestRouter } from '@/app/routes'
import { TooltipProvider } from '@/components/ui/display'
import { ToastProvider } from '@/components/ui/toast'
import { tokenStore } from '@/lib/api-client'
import { AuthProvider } from '@/lib/auth'

export type Handler = (init: RequestInit | undefined, url: string) => Response | Promise<Response>
export type Handlers = Record<string, Handler | { status: number; body?: unknown }>

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/**
 * Stand in for the API. Keys are `METHOD /path` (without the /api/v1 prefix). Every request is
 * recorded in `calls`; an unknown route fails the test loudly.
 */
export function mockApi(handlers: Handlers) {
  const calls: { method: string; path: string; headers: Headers; body: unknown }[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const path = url.replace(/^\/api\/v1/, '')
    const method = init?.method ?? 'GET'
    calls.push({
      method,
      path,
      headers: new Headers(init?.headers),
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    })
    const key = `${method} ${path}`
    // A key ending in * matches every path that starts the same way (query strings vary).
    const handler =
      handlers[key] ??
      Object.entries(handlers).find(([k]) => k.endsWith('*') && key.startsWith(k.slice(0, -1)))?.[1]
    // The public site asks for live prices and reviews and falls back to its own copy, so
    // those requests may go unanswered. Any other unexpected request is a mistake in the test.
    if (!handler && path.startsWith('/public/') && method === 'GET') {
      return json({ code: 'not_found', message: 'Not found.' }, 404)
    }
    if (!handler) throw new Error(`Unexpected request: ${method} ${path}`)
    if (typeof handler === 'function') return handler(init, url)
    if (handler.status === 204) return new Response(null, { status: 204 })
    return json(handler.body ?? {}, handler.status)
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}

export const me = (role: 'patient' | 'receptionist' | 'dentist' | 'admin' = 'patient') => ({
  id: '11111111-1111-4111-8111-111111111111',
  email: `${role}@example.com`,
  role,
  mfa_enabled: role === 'admin',
  email_verified: true,
  patient_id: role === 'patient' ? '22222222-2222-4222-8222-222222222222' : null,
})

export const session = (token = 'access-token-1') => ({
  status: 'authenticated',
  access_token: token,
  token_type: 'bearer',
  expires_in: 900,
  recovery_codes: null,
})

/** `hasSession` mimics a returning visitor, whose browser still holds the session cookie. */
export function renderApp(path: string, { hasSession = false } = {}) {
  tokenStore.set(null)
  document.cookie = hasSession
    ? 'csrf_token=test-csrf; path=/'
    : 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <HelmetProvider>
      <QueryClientProvider client={client}>
        <AuthProvider>
          <TooltipProvider>
            <ToastProvider>
              <RouterProvider router={createTestRouter([path])} />
            </ToastProvider>
          </TooltipProvider>
        </AuthProvider>
      </QueryClientProvider>
    </HelmetProvider>,
  )
}

/** Components that need the app's providers but no routing. */
export function renderUi(ui: ReactElement) {
  return render(
    <TooltipProvider>
      <ToastProvider>{ui}</ToastProvider>
    </TooltipProvider>,
  )
}
