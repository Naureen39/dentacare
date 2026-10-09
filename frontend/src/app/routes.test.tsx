import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createMemoryRouter, RouterProvider } from 'react-router-dom'

import { buildRoutes } from '@/app/routes'
import { RequireAuth } from '@/components/RequireAuth'
import { tokenStore } from '@/lib/api-client'
import { AuthProvider, type Role } from '@/lib/auth'
import { json, me, mockApi, renderApp, session } from '@/test/utils'

const anonymous = {
  'POST /auth/refresh': { status: 401, body: { code: 'unauthorized', message: 'No session.' } },
}
const signedIn = (role: Parameters<typeof me>[0] = 'patient') => ({
  'POST /auth/refresh': { status: 200, body: session() },
  'GET /auth/me': { status: 200, body: me(role) },
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.set(null)
})

describe('public pages', () => {
  it('renders the home page', async () => {
    mockApi(anonymous)
    renderApp('/')
    expect(
      await screen.findByRole('heading', { level: 1, name: /exceptional dental care/i }),
    ).toBeInTheDocument()
  })

  it('renders the not found page for unknown routes', async () => {
    mockApi(anonymous)
    renderApp('/does-not-exist')
    expect(await screen.findByRole('heading', { name: /page not found/i })).toBeInTheDocument()
  })

  it('shows the demo disclaimer, a skip link and a labelled main navigation', async () => {
    mockApi(anonymous)
    renderApp('/does-not-exist')
    expect(await screen.findByText(/demo environment, fictional clinic/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /skip to main content/i })).toHaveAttribute(
      'href',
      '#main-content',
    )
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument()
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main-content')
  })

  it('shows a sign in button to visitors and no account link', async () => {
    mockApi(anonymous)
    renderApp('/does-not-exist')
    expect((await screen.findAllByRole('link', { name: /patient login/i })).length).toBeGreaterThan(
      0,
    )
    expect(screen.queryByRole('link', { name: /^account$/i })).not.toBeInTheDocument()
  })
})

describe('the style guide route', () => {
  it('is available while developing', async () => {
    mockApi(anonymous)
    renderApp('/styleguide')
    expect(
      await screen.findByRole('heading', { level: 1, name: /style guide/i }, { timeout: 10_000 }),
    ).toBeInTheDocument()
  })

  it('is not part of a production build', () => {
    const table = buildRoutes(false)
    const paths = table[0]?.children?.map((child) => child.path)
    expect(paths).not.toContain('styleguide')
    expect(paths).toContain('services')
    expect(table.map((route) => route.path)).toContain('/login')
  })

  it('can be switched on for auditing', () => {
    expect(buildRoutes(true)[0]?.children?.map((child) => child.path)).toContain('styleguide')
  })
})

describe('route guards', () => {
  it('does not ask the server to renew a session a first time visitor cannot have', async () => {
    const { calls } = mockApi({})
    renderApp('/does-not-exist')
    expect((await screen.findAllByRole('link', { name: /patient login/i })).length).toBeGreaterThan(
      0,
    )
    expect(calls).toHaveLength(0)
  })

  it('sends an anonymous visitor to sign in and brings them back afterwards', async () => {
    const user = userEvent.setup()
    let signedInNow = false
    mockApi({
      'POST /auth/refresh': () => json({ code: 'unauthorized', message: 'No session.' }, 401),
      'POST /auth/login': () => {
        signedInNow = true
        return json(session('after-login'))
      },
      'GET /auth/me': () =>
        signedInNow ? json(me('patient')) : json({ code: 'unauthorized', message: '' }, 401),
    })
    renderApp('/account')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/email address/i), 'patient@example.com')
    await user.type(screen.getByLabelText(/^password/i, { selector: 'input' }), 'a-long-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('heading', { name: 'Your account' })).toBeInTheDocument()
    expect(screen.getByText('patient@example.com')).toBeInTheDocument()
  })

  it('signs a returning visitor in again without showing the form', async () => {
    mockApi(signedIn('patient'))
    renderApp('/account', { hasSession: true })
    expect(await screen.findByRole('heading', { name: 'Your account' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Sign in' })).not.toBeInTheDocument()
  })

  it('shows a loading state while it checks the session', async () => {
    let release: (value: Response) => void = () => {}
    mockApi({ 'POST /auth/refresh': () => new Promise<Response>((resolve) => (release = resolve)) })
    renderApp('/account', { hasSession: true })
    expect(
      await screen.findByRole('status', { name: /checking your session/i }),
    ).toBeInTheDocument()
    release(json({ code: 'unauthorized', message: '' }, 401))
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('treats an unreachable server as signed out rather than crashing', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network down')))
    renderApp('/account', { hasSession: true })
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('signs out and returns to the public view', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi({ ...signedIn('patient'), 'POST /auth/logout': { status: 204 } })
    renderApp('/account', { hasSession: true })
    await user.click(await screen.findByRole('button', { name: /sign out/i }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/auth/logout')).toBe(true)
    expect(tokenStore.get()).toBeNull()
  })

  it('moves focus to the content after navigating', async () => {
    const user = userEvent.setup()
    mockApi({
      ...anonymous,
      'GET /info': {
        status: 200,
        body: { name: 'Meridian Dental Care', version: '1', environment: 'test' },
      },
    })
    renderApp('/')
    await screen.findByRole('heading', { name: /exceptional dental care/i })
    await user.click(screen.getByRole('link', { name: /style guide/i }))
    await screen.findByRole('heading', { level: 1, name: /style guide/i }, { timeout: 10_000 })
    await waitFor(() => expect(screen.getByRole('main')).toHaveFocus())
  })
})

describe('role checks', () => {
  function renderGuarded(role: Parameters<typeof me>[0], allowed: Role[]) {
    document.cookie = 'csrf_token=test-csrf; path=/'
    mockApi(signedIn(role))
    const router = createMemoryRouter(
      [
        {
          element: <RequireAuth roles={allowed} />,
          children: [{ path: '/staff', element: <h1>Staff area</h1> }],
        },
      ],
      { initialEntries: ['/staff'] },
    )
    render(
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>,
    )
  }

  it('lets an allowed role in', async () => {
    renderGuarded('receptionist', ['receptionist', 'admin'])
    expect(await screen.findByRole('heading', { name: 'Staff area' })).toBeInTheDocument()
  })

  it('shows a 403 page to a signed in user with the wrong role', async () => {
    renderGuarded('patient', ['receptionist', 'admin'])
    const heading = await screen.findByRole('heading', { name: /do not have access/i })
    expect(
      within(heading.closest('section') as HTMLElement).getByText('Error 403'),
    ).toBeInTheDocument()
    expect(screen.queryByText('Staff area')).not.toBeInTheDocument()
  })
})
