import type { ChatLink, QuickReply, Reply } from '@/chat/api'
import { clinic } from '@/content/site'
import type { components } from '@/lib/api-types'

type HistoryMessage = components['schemas']['ChatMessageOut']

export interface Msg {
  id: string
  role: 'user' | 'assistant'
  text: string
  quickReplies: QuickReply[]
  links: ChatLink[]
  inputHint: string | null
  picker: string | null
  step: string | null
  feedback: 'up' | 'down' | null
  degraded: boolean
  at: string
}

export const fromReply = (reply: Reply, at = new Date().toISOString()): Msg => ({
  id: reply.message_id,
  role: 'assistant',
  text: reply.text,
  quickReplies: reply.quick_replies,
  links: reply.links,
  inputHint: reply.input_hint,
  picker: reply.picker,
  step: reply.step,
  feedback: null,
  degraded: reply.degraded,
  at,
})

export const userMessage = (text: string, at = new Date().toISOString()): Msg => ({
  id: `local-${at}-${Math.random().toString(36).slice(2, 8)}`,
  role: 'user',
  text,
  quickReplies: [],
  links: [],
  inputHint: null,
  picker: null,
  step: null,
  feedback: null,
  degraded: false,
  at,
})

/** The conversation as the server kept it. Only the last reply still offers its buttons. */
export function fromHistory(messages: HistoryMessage[], step: string | null): Msg[] {
  const shown = messages.filter((m) => m.role !== 'system')
  return shown.map((m, i) => ({
    id: m.id,
    role: m.role === 'user' ? 'user' : 'assistant',
    text: m.content,
    quickReplies: m.quick_replies,
    links: m.links,
    inputHint: m.input_hint ?? null,
    picker: m.picker ?? null,
    step: i === shown.length - 1 ? step : null,
    feedback: m.feedback ?? null,
    degraded: false,
    at: m.created_at,
  }))
}

/** A plain text copy of the conversation for the visitor to keep. */
export function buildTranscript(messages: Msg[], savedAt = new Date()): string {
  const clock = (iso: string) =>
    new Intl.DateTimeFormat('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      timeZone: clinic.timeZone,
    }).format(new Date(iso))
  const lines = messages.map(
    (m) => `[${clock(m.at)}] ${m.role === 'user' ? 'You' : 'Assistant'}: ${m.text}`,
  )
  const when = new Intl.DateTimeFormat('en-US', {
    dateStyle: 'long',
    timeStyle: 'short',
    timeZone: clinic.timeZone,
  }).format(savedAt)
  return [`${clinic.name} chat transcript`, `Saved ${when}`, '', ...lines, ''].join('\n')
}

/** A path inside this site, from a link in a reply, or null for a link to somewhere else. */
export function internalPath(url: string, origin = window.location.origin): string | null {
  if (url.startsWith('/') && !url.startsWith('//')) return url
  try {
    const parsed = new URL(url)
    const own = [origin, clinic.siteUrl].map((o) => new URL(o).host)
    return own.includes(parsed.host) ? `${parsed.pathname}${parsed.search}${parsed.hash}` : null
  } catch {
    return null
  }
}

/** A short line telling the visitor what went wrong, in the assistant's own voice. */
export const trouble = (status: number | null): string =>
  status === 429
    ? 'You are sending messages quickly. Please wait a moment and try again.'
    : status === 409
      ? 'I am still answering your last message. Please wait a moment.'
      : `I could not complete that just now. You can try again, use the booking form, or call ${clinic.phone}.`
