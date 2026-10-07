import type { components } from './api-types'

export type ApiErrorBody = components['schemas']['ErrorResponse']

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

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    method: 'GET',
    credentials: 'include',
    headers: { Accept: 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch((): ApiErrorBody => ({
      code: 'unknown_error',
      message: 'The server returned an unexpected response.',
    }))
    throw new ApiError(response.status, body)
  }
  return (await response.json()) as T
}

export type InfoResponse = components['schemas']['InfoResponse']

export const getInfo = (): Promise<InfoResponse> => apiGet<InfoResponse>('/info')
