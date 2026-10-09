import * as React from 'react'

import {
  createSession,
  endSession,
  loadSession,
  readStored,
  sendFeedback,
  sendMessage,
  writeStored,
  type Choice,
  type Stored,
} from '@/chat/api'
import { fromHistory, fromReply, trouble, userMessage, type Msg } from '@/chat/model'
import { ApiError } from '@/lib/api-client'

export interface Chat {
  messages: Msg[]
  /** The reply being written, shown while its text arrives. */
  draft: string | null
  busy: boolean
  ready: boolean
  /** The assistant could not answer in full: show the other ways to book. */
  degraded: boolean
  /** A reply arrived that the visitor has not seen, because the panel was closed. */
  unseen: boolean
  start: () => Promise<void>
  say: (text: string) => Promise<void>
  choose: (choice: Choice) => Promise<void>
  rate: (messageId: string, rating: 'up' | 'down') => void
  end: () => Promise<void>
  markSeen: () => void
}

/**
 * One conversation with the assistant. The secret that opens it is kept in the tab's session
 * storage, so a reload carries on where it was and closing the tab forgets it.
 */
export function useChat(open: boolean): Chat {
  const stored = React.useRef<Stored | null>(null)
  const starting = React.useRef<Promise<void> | null>(null)
  const openRef = React.useRef(open)
  const [messages, setMessages] = React.useState<Msg[]>([])
  const [draft, setDraft] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [degraded, setDegraded] = React.useState(false)
  const [unseen, setUnseen] = React.useState(false)

  React.useEffect(() => {
    openRef.current = open
  }, [open])

  const create = React.useCallback(async () => {
    const created = await createSession()
    stored.current = { id: created.session_id, token: created.session_token }
    writeStored(stored.current)
    setMessages([fromReply(created.greeting)])
    setDegraded(created.greeting.degraded)
  }, [])

  const start = React.useCallback(() => {
    starting.current ??= (async () => {
      try {
        stored.current = readStored()
        if (stored.current) {
          try {
            const history = await loadSession(stored.current)
            const step = history.step ?? null
            const restored = fromHistory(history.messages, step)
            if (restored.length) {
              setMessages(restored)
              return
            }
          } catch (error) {
            if (!(error instanceof ApiError) || error.status !== 404) throw error
            writeStored(null)
            stored.current = null
          }
        }
        await create()
      } catch {
        setDegraded(true)
        setMessages([
          { ...userMessage(''), role: 'assistant', text: trouble(null), degraded: true },
        ])
        starting.current = null // try again the next time the panel opens
      }
    })()
    return starting.current
  }, [create])

  const deliver = React.useCallback(
    async (outgoing: { text: string } | { choice: Choice }, shown: string) => {
      if (busy) return
      setMessages((m) => [...m, userMessage(shown)])
      setBusy(true)
      setDraft('')
      try {
        if (!stored.current) await create()
        const current = stored.current as Stored
        const reply = await sendMessage(current, outgoing, {
          onText: (piece) => setDraft((d) => (d ?? '') + piece),
        })
        setMessages((m) => [...m, fromReply(reply)])
        setDegraded(reply.degraded)
        if (!openRef.current) setUnseen(true)
      } catch (error) {
        const status = error instanceof ApiError ? error.status : null
        if (status === 404) {
          // The conversation no longer exists (it was ended or expired): begin a fresh one.
          writeStored(null)
          stored.current = null
          starting.current = null
        }
        setDegraded(status !== 429 && status !== 409)
        setMessages((m) => [
          ...m,
          { ...userMessage(''), role: 'assistant', text: trouble(status), degraded: true },
        ])
      } finally {
        setDraft(null)
        setBusy(false)
      }
    },
    [busy, create],
  )

  const say = React.useCallback((text: string) => deliver({ text }, text), [deliver])
  const choose = React.useCallback(
    (choice: Choice) => deliver({ choice }, choice.label || choice.value),
    [deliver],
  )

  const rate = React.useCallback((messageId: string, rating: 'up' | 'down') => {
    const current = stored.current
    if (!current) return
    setMessages((all) => all.map((m) => (m.id === messageId ? { ...m, feedback: rating } : m)))
    void sendFeedback(current, messageId, rating).catch(() =>
      setMessages((all) => all.map((m) => (m.id === messageId ? { ...m, feedback: null } : m))),
    )
  }, [])

  const end = React.useCallback(async () => {
    const current = stored.current
    if (current) await endSession(current).catch(() => undefined)
    writeStored(null)
    stored.current = null
    starting.current = null
    setMessages([])
    setDegraded(false)
  }, [])

  return {
    messages,
    draft,
    busy,
    ready: messages.length > 0,
    degraded,
    unseen,
    start,
    say,
    choose,
    rate,
    end,
    markSeen: () => setUnseen(false),
  }
}
