import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiDelete, apiFetch, apiGet, apiPost } from '@/lib/api-client'
import type { components } from '@/lib/api-types'

type Schemas = components['schemas']
export type InvoiceItem = Schemas['InvoiceListItem']
export type Invoice = Schemas['InvoiceOut']
export type SessionInfo = Schemas['SessionInfo']

export const useInvoices = () =>
  useQuery({
    queryKey: ['me', 'invoices'],
    queryFn: () => apiGet<InvoiceItem[]>('/me/invoices'),
    retry: false,
  })

export const useInvoice = (id: string | undefined) =>
  useQuery({
    queryKey: ['me', 'invoices', id],
    queryFn: () => apiGet<Invoice>(`/me/invoices/${id}`),
    enabled: Boolean(id),
    retry: false,
  })

export const downloadInvoice = (id: string) =>
  apiFetch<Blob>(`/me/invoices/${id}/pdf`, { as: 'blob' })

export interface CardInput {
  number: string
  expMonth: number
  expYear: number
  cvv: string
  cardholder: string
}

/** Sandbox payment: the card details are sent once and never kept. */
export function usePayInvoice(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { card: CardInput; amount?: string }) =>
      apiPost<Invoice>(`/me/invoices/${id}/pay`, {
        amount: input.amount ?? null,
        card: {
          card_number: input.card.number,
          exp_month: input.card.expMonth,
          exp_year: input.card.expYear,
          cvv: input.card.cvv,
          cardholder: input.card.cardholder || null,
        },
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['me', 'invoices'] }),
  })
}

// --- account security -----------------------------------------------------------------------

export const useSessions = () =>
  useQuery({
    queryKey: ['me', 'sessions'],
    queryFn: () => apiGet<SessionInfo[]>('/auth/sessions'),
    retry: false,
  })

export function useRevokeSession() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/auth/sessions/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ['me', 'sessions'] }),
  })
}

export const changePassword = (input: { current: string; next: string }) =>
  apiPost<{ message: string }>('/auth/password', {
    current_password: input.current,
    new_password: input.next,
  })

export const startMfaSetup = () =>
  apiPost<{ secret: string; otpauth_uri: string }>('/auth/mfa/setup')

export const enableMfa = (code: string) =>
  apiPost<{ recovery_codes?: string[] | null }>('/auth/mfa/enable', { code })

export const disableMfa = (input: { password: string; code: string }) =>
  apiPost<{ message: string }>('/auth/mfa/disable', input)

/** A readable name for a browser, from its user agent text. */
export function describeAgent(agent: string | null): string {
  if (!agent) return 'Unknown device'
  const browser = /Edg\//.test(agent)
    ? 'Edge'
    : /Chrome\//.test(agent)
      ? 'Chrome'
      : /Firefox\//.test(agent)
        ? 'Firefox'
        : /Safari\//.test(agent)
          ? 'Safari'
          : 'Browser'
  const system = /Windows/.test(agent)
    ? 'Windows'
    : /Android/.test(agent)
      ? 'Android'
      : /iPhone|iPad/.test(agent)
        ? 'iOS'
        : /Mac OS/.test(agent)
          ? 'macOS'
          : /Linux/.test(agent)
            ? 'Linux'
            : ''
  return system ? `${browser} on ${system}` : browser
}
