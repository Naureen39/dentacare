import { ApiError, apiFetch, tokenStore, type ApiErrorBody } from '@/lib/api-client'
import type { components } from '@/lib/api-types'

type S = components['schemas']
export type Reply = S['ChatReplyOut']
export type QuickReply = S['QuickReplyOut']
export type ChatLink = S['LinkOut']
type CreateResponse = S['CreateSessionResponse']
type SessionOut = S['SessionOut']

export type Choice = { kind: string; value: string; label: string }
export type Outgoing = { text: string } | { choice: Choice }

export interface Stored {
  id: string
  token: string
}

const BASE = '/api/v1/chat'
const KEY = 'meridian-chat'
export const GREETED_KEY = 'meridian-chat-greeted'

// --- the conversation's secret, kept for this browser tab only ---------------------------------

export function readStored(): Stored | null {
  try {
    const raw = window.sessionStorage.getItem(KEY)
    const value = raw ? (JSON.parse(raw) as Partial<Stored>) : null
    return value?.id && value.token ? { id: value.id, token: value.token } : null
  } catch {
    return null
  }
}

export function writeStored(value: Stored | null): void {
  try {
    if (value) window.sessionStorage.setItem(KEY, JSON.stringify(value))
    else window.sessionStorage.removeItem(KEY)
  } catch {
    /* storage may be blocked; the conversation then lasts only until the page is closed */
  }
}

// --- calls ---------------------------------------------------------------------------------------

const tokenHeader = (token: string) => ({ 'X-Chat-Token': token })

export const createSession = () => apiFetch<CreateResponse>('/chat/sessions', { method: 'POST' })

export const loadSession = (stored: Stored) =>
  apiFetch<SessionOut>(`/chat/sessions/${stored.id}`, { headers: tokenHeader(stored.token) })

export const sendFeedback = (stored: Stored, messageId: string, rating: 'up' | 'down') =>
  apiFetch<void>(`/chat/sessions/${stored.id}/feedback`, {
    method: 'POST',
    headers: tokenHeader(stored.token),
    body: { message_id: messageId, rating },
  })

export const endSession = (stored: Stored) =>
  apiFetch<void>(`/chat/sessions/${stored.id}`, {
    method: 'DELETE',
    headers: tokenHeader(stored.token),
  })

// --- sending a message and reading the reply as it arrives -------------------------------------------

export interface StreamHandlers {
  /** Called with each piece of the reply text as it arrives. */
  onText: (piece: string) => void
}

/** One server sent event: its name and the JSON in its data line. */
export function parseEvents(chunk: string): { event: string; data: unknown }[] {
  return chunk
    .split('\n\n')
    .map((block) => {
      const lines = block.split('\n')
      const event = lines
        .find((l) => l.startsWith('event:'))
        ?.slice(6)
        .trim()
      const data = lines
        .find((l) => l.startsWith('data:'))
        ?.slice(5)
        .trim()
      return event && data ? { event, data: JSON.parse(data) as unknown } : null
    })
    .filter((e): e is { event: string; data: unknown } => e !== null)
}

/**
 * Send what the visitor typed or clicked. The reply is asked for as a stream, so its text can be
 * shown as it arrives; the final event carries the whole reply with its buttons.
 */
export async function sendMessage(
  stored: Stored,
  outgoing: Outgoing,
  handlers: StreamHandlers,
): Promise<Reply> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
    ...tokenHeader(stored.token),
  }
  const access = tokenStore.get()
  if (access) headers.Authorization = `Bearer ${access}`
  const response = await fetch(`${BASE}/sessions/${stored.id}/messages`, {
    method: 'POST',
    headers,
    body: JSON.stringify(outgoing),
    credentials: 'include',
  })
  if (!response.ok) {
    const body = (await response
      .json()
      .catch(() => ({ code: 'unknown_error', message: '' }))) as ApiErrorBody
    throw new ApiError(response.status, body)
  }
  if (!response.body) return (await response.json()) as Reply

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let final: Reply | null = null
  for (;;) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const cut = buffer.lastIndexOf('\n\n')
    if (cut >= 0 || done) {
      const ready = done ? buffer : buffer.slice(0, cut + 2)
      buffer = done ? '' : buffer.slice(cut + 2)
      for (const { event, data } of parseEvents(ready)) {
        if (event === 'delta') handlers.onText((data as { text: string }).text)
        if (event === 'done') final = data as Reply
      }
    }
    if (done) break
  }
  if (!final) throw new Error('The reply ended early.')
  return final
}
