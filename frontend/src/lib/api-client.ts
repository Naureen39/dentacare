import type { components } from './api-types'

export type ApiErrorBody = components['schemas']['ErrorResponse']
export type AuthenticatedResponse = components['schemas']['AuthenticatedResponse']

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown
  readonly requestId: string | null

  constructor(status: number, body: ApiErrorBody) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.details = body.details
    this.requestId = body.request_id ?? null
  }
}

const BASE_URL = '/api/v1'
const CSRF_COOKIE = 'csrf_token'
const CSRF_HEADER = 'X-CSRF-Token'

// --- the access token -------------------------------------------------------------------------
//
// The short lived access token lives only in this module's memory: never in local storage, never
// in a cookie JavaScript can write. A page reload loses it, and the long lived refresh token,
// which is an HttpOnly cookie the script cannot read, brings a new one.

let accessToken: string | null = null
const expiryListeners = new Set<() => void>()

export const tokenStore = {
  get: (): string | null => accessToken,
  set: (token: string | null): void => {
    accessToken = token
  },
}

/** Called when the session can no longer be renewed, so the interface can ask the user to sign in. */
export function onSessionExpired(listener: () => void): () => void {
  expiryListeners.add(listener)
  return () => expiryListeners.delete(listener)
}

function readCookie(name: string): string | null {
  const match = document.cookie.split('; ').find((part) => part.startsWith(`${name}=`))
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null
}

/**
 * Whether a session might exist. Signing in sets a readable CSRF cookie next to the HttpOnly
 * refresh cookie, so without it there is nothing to renew and the request is not worth making.
 */
export const mayHaveSession = (): boolean => readCookie(CSRF_COOKIE) !== null

async function toError(response: Response): Promise<ApiError> {
  const body = await response.json().catch((): ApiErrorBody => ({
    code: 'unknown_error',
    message: 'The server returned an unexpected response.',
  }))
  return new ApiError(response.status, body)
}

// --- renewing the session ----------------------------------------------------------------------

let refreshing: Promise<AuthenticatedResponse | null> | null = null

/**
 * Ask for a new access token using the refresh cookie. Calls made while one is already running
 * share its result: the server rotates refresh tokens, so two parallel renewals would make the
 * second one look like a stolen token. Returns null when there is no valid session.
 */
export function refreshSession(): Promise<AuthenticatedResponse | null> {
  refreshing ??= (async () => {
    try {
      const response = await fetch(`${BASE_URL}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers: { Accept: 'application/json', [CSRF_HEADER]: readCookie(CSRF_COOKIE) ?? '' },
      })
      if (!response.ok) {
        if (response.status >= 500) throw await toError(response)
        tokenStore.set(null)
        return null
      }
      const body = (await response.json()) as AuthenticatedResponse
      tokenStore.set(body.access_token)
      return body
    } finally {
      refreshing = null
    }
  })()
  return refreshing
}

// --- requests ---------------------------------------------------------------------------------------

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  headers?: Record<string, string>
  signal?: AbortSignal
  /** Send the access token and renew it on a 401. Turn off for sign in and similar calls. */
  auth?: boolean
  /** Read the body as a file (a PDF or calendar file) instead of JSON. */
  as?: 'json' | 'blob'
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, headers = {}, signal, auth = true, as = 'json' } = options

  const send = (): Promise<Response> => {
    const sent: Record<string, string> = { Accept: 'application/json', ...headers }
    if (body !== undefined) sent['Content-Type'] = 'application/json'
    const token = tokenStore.get()
    if (auth && token) sent.Authorization = `Bearer ${token}`
    if (method !== 'GET') {
      const csrf = readCookie(CSRF_COOKIE)
      if (csrf) sent[CSRF_HEADER] = csrf
    }
    return fetch(`${BASE_URL}${path}`, {
      method,
      credentials: 'include',
      headers: sent,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  }

  let response = await send()
  if (response.status === 401 && auth) {
    // The access token has probably expired. Renew it once and repeat the request once.
    const renewed = await refreshSession()
    if (renewed) {
      response = await send()
    } else {
      expiryListeners.forEach((listener) => listener())
    }
  }
  if (!response.ok) throw await toError(response)
  if (response.status === 204) return undefined as T
  if (as === 'blob') return (await response.blob()) as T
  return (await response.json()) as T
}

export const apiGet = <T>(
  path: string,
  init?: Omit<RequestOptions, 'method' | 'body'>,
): Promise<T> => apiFetch<T>(path, { ...init, method: 'GET' })
export const apiDelete = <T>(
  path: string,
  init?: Omit<RequestOptions, 'method' | 'body'>,
): Promise<T> => apiFetch<T>(path, { ...init, method: 'DELETE' })
export const apiPost = <T>(
  path: string,
  body?: unknown,
  init?: Omit<RequestOptions, 'method' | 'body'>,
): Promise<T> => apiFetch<T>(path, { ...init, method: 'POST', body })
export const apiPatch = <T>(
  path: string,
  body?: unknown,
  init?: Omit<RequestOptions, 'method' | 'body'>,
): Promise<T> => apiFetch<T>(path, { ...init, method: 'PATCH', body })

export type InfoResponse = components['schemas']['InfoResponse']

export const getInfo = (): Promise<InfoResponse> => apiGet<InfoResponse>('/info', { auth: false })
