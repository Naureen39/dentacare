import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  apiFetch,
  apiGet,
  apiPost,
  onSessionExpired,
  refreshSession,
  tokenStore,
} from '@/lib/api-client'
import { json, mockApi, session } from '@/test/utils'

beforeEach(() => tokenStore.set(null))
afterEach(() => vi.unstubAllGlobals())

describe('requests', () => {
  it('sends the access token as a bearer token', async () => {
    tokenStore.set('abc')
    const { calls } = mockApi({ 'GET /thing': { status: 200, body: { ok: true } } })
    await expect(apiGet('/thing')).resolves.toEqual({ ok: true })
    expect(calls[0]?.headers.get('Authorization')).toBe('Bearer abc')
  })

  it('sends no token when asked not to, and none when there is none', async () => {
    tokenStore.set('abc')
    const { calls } = mockApi({ 'GET /open': { status: 200 }, 'GET /anon': { status: 200 } })
    await apiGet('/open', { auth: false })
    tokenStore.set(null)
    await apiGet('/anon')
    expect(calls[0]?.headers.has('Authorization')).toBe(false)
    expect(calls[1]?.headers.has('Authorization')).toBe(false)
  })

  it('echoes the CSRF cookie in a header on changes, not on reads', async () => {
    document.cookie = 'csrf_token=token-123; path=/'
    const { calls } = mockApi({ 'POST /save': { status: 200 }, 'GET /read': { status: 200 } })
    await apiPost('/save', { a: 1 })
    await apiGet('/read')
    expect(calls[0]?.headers.get('X-CSRF-Token')).toBe('token-123')
    expect(calls[0]?.headers.get('Content-Type')).toBe('application/json')
    expect(calls[0]?.body).toEqual({ a: 1 })
    expect(calls[1]?.headers.has('X-CSRF-Token')).toBe(false)
  })

  it('returns nothing for 204 and turns error bodies into ApiError', async () => {
    mockApi({
      'POST /logout': { status: 204 },
      'GET /missing': {
        status: 404,
        body: { code: 'not_found', message: 'Not found.', request_id: 'r1' },
      },
      'GET /broken': () => new Response('<html>oops</html>', { status: 502 }),
    })
    await expect(apiPost('/logout')).resolves.toBeUndefined()
    const missing = await apiGet('/missing').catch((e: unknown) => e)
    expect(missing).toBeInstanceOf(ApiError)
    expect(missing).toMatchObject({
      status: 404,
      code: 'not_found',
      requestId: 'r1',
      message: 'Not found.',
    })
    const broken = await apiGet('/broken').catch((e: unknown) => e)
    expect(broken).toMatchObject({ status: 502, code: 'unknown_error' })
  })
})

describe('keeping the session alive', () => {
  it('renews an expired token once and repeats the request', async () => {
    tokenStore.set('old')
    let first = true
    const { calls } = mockApi({
      'GET /private': () => {
        if (first) {
          first = false
          return json({ code: 'unauthorized', message: 'expired' }, 401)
        }
        return json({ secret: 1 })
      },
      'POST /auth/refresh': { status: 200, body: session('fresh') },
    })
    await expect(apiGet('/private')).resolves.toEqual({ secret: 1 })
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      'GET /private',
      'POST /auth/refresh',
      'GET /private',
    ])
    expect(calls[2]?.headers.get('Authorization')).toBe('Bearer fresh')
    expect(tokenStore.get()).toBe('fresh')
  })

  it('does not loop: a second 401 after renewing is returned as an error', async () => {
    tokenStore.set('old')
    const { calls } = mockApi({
      'GET /private': { status: 401, body: { code: 'unauthorized', message: 'no' } },
      'POST /auth/refresh': { status: 200, body: session('fresh') },
    })
    await expect(apiGet('/private')).rejects.toMatchObject({ status: 401 })
    expect(calls.filter((c) => c.path === '/auth/refresh')).toHaveLength(1)
    expect(calls.filter((c) => c.path === '/private')).toHaveLength(2)
  })

  it('shares one renewal between requests that expire together', async () => {
    tokenStore.set('old')
    let refreshes = 0
    mockApi({
      'GET /a': (init) =>
        (init?.headers as Record<string, string>).Authorization === 'Bearer old'
          ? json({}, 401)
          : json({ a: 1 }),
      'GET /b': (init) =>
        (init?.headers as Record<string, string>).Authorization === 'Bearer old'
          ? json({}, 401)
          : json({ b: 1 }),
      'GET /c': (init) =>
        (init?.headers as Record<string, string>).Authorization === 'Bearer old'
          ? json({}, 401)
          : json({ c: 1 }),
      'POST /auth/refresh': async () => {
        refreshes += 1
        await new Promise((r) => setTimeout(r, 10))
        return json(session('fresh'))
      },
    })
    const results = await Promise.all([apiGet('/a'), apiGet('/b'), apiGet('/c')])
    expect(results).toEqual([{ a: 1 }, { b: 1 }, { c: 1 }])
    expect(refreshes).toBe(1) // the server rotates refresh tokens, so parallel renewals would look like theft
  })

  it('tells the application when the session cannot be renewed', async () => {
    tokenStore.set('old')
    const expired = vi.fn()
    const stop = onSessionExpired(expired)
    mockApi({
      'GET /private': { status: 401, body: { code: 'unauthorized', message: 'no' } },
      'POST /auth/refresh': { status: 401, body: { code: 'unauthorized', message: 'no' } },
    })
    await expect(apiGet('/private')).rejects.toMatchObject({ status: 401 })
    expect(expired).toHaveBeenCalledTimes(1)
    expect(tokenStore.get()).toBeNull()
    stop()
  })

  it('does not try to renew calls that sign in', async () => {
    const { calls } = mockApi({
      'POST /auth/login': { status: 401, body: { code: 'invalid_credentials', message: 'Wrong.' } },
    })
    await expect(
      apiFetch('/auth/login', { method: 'POST', body: {}, auth: false }),
    ).rejects.toMatchObject({ code: 'invalid_credentials' })
    expect(calls).toHaveLength(1)
  })

  it('refreshSession sends the CSRF header, stores the token, and reports no session as null', async () => {
    document.cookie = 'csrf_token=c1; path=/'
    const { calls } = mockApi({ 'POST /auth/refresh': { status: 200, body: session('t1') } })
    expect((await refreshSession())?.access_token).toBe('t1')
    expect(calls[0]?.headers.get('X-CSRF-Token')).toBe('c1')
    expect(tokenStore.get()).toBe('t1')

    mockApi({
      'POST /auth/refresh': { status: 401, body: { code: 'unauthorized', message: 'no' } },
    })
    expect(await refreshSession()).toBeNull()
    expect(tokenStore.get()).toBeNull()
  })

  it('a server error while renewing is an error, not a sign out', async () => {
    mockApi({
      'POST /auth/refresh': { status: 503, body: { code: 'unavailable', message: 'Try later.' } },
    })
    await expect(refreshSession()).rejects.toMatchObject({ status: 503 })
  })

  it('keeps the access token out of storage', async () => {
    mockApi({ 'POST /auth/refresh': { status: 200, body: session('secret-token') } })
    await refreshSession()
    expect(JSON.stringify({ ...localStorage })).not.toContain('secret-token')
    expect(JSON.stringify({ ...sessionStorage })).not.toContain('secret-token')
    expect(document.cookie).not.toContain('secret-token')
  })
})
