import * as DialogPrimitive from '@radix-ui/react-dialog'
import { Bot, Download, Send, Trash2, UserRound, X } from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'

import { buildTranscript, type Msg } from '@/chat/model'
import {
  Chips,
  DentistCards,
  Links,
  PickerCard,
  Rating,
  ServiceCards,
  SummaryCard,
  type Pick,
} from '@/chat/Parts'
import type { Chat } from '@/chat/useChat'
import { clinic } from '@/content/site'
import { saveFile } from '@/lib/download'
import { cn } from '@/lib/utils'

const hints: Record<
  string,
  { type: string; mode?: 'numeric' | 'email' | 'tel'; auto: string; label: string }
> = {
  name: { type: 'text', auto: 'name', label: 'Type your name' },
  email: { type: 'email', mode: 'email', auto: 'email', label: 'Type your email address' },
  phone: { type: 'tel', mode: 'tel', auto: 'tel', label: 'Type your phone number' },
  code: { type: 'text', mode: 'numeric', auto: 'one-time-code', label: 'Type the 6 digit code' },
  contact: { type: 'text', auto: 'off', label: 'Type your email address or phone number' },
}

/** The controls for the assistant's latest reply: cards for services, dentists, days, times. */
function Offer({ message, onPick, disabled }: { message: Msg; onPick: Pick; disabled: boolean }) {
  const q = message.quickReplies
  const of = (...kinds: string[]) => q.filter((r) => kinds.includes(r.kind))
  const rest = q.filter((r) => !['service', 'dentist', 'slot', 'date'].includes(r.kind))
  const confirm = q.find((r) => r.kind === 'confirm' && r.value === 'yes')
  if (message.picker === 'slot' && of('slot').length)
    return (
      <div className="grid gap-2">
        <PickerCard
          title="Choose a time"
          replies={of('slot')}
          onPick={onPick}
          disabled={disabled}
        />
        <Chips replies={rest} onPick={onPick} disabled={disabled} />
      </div>
    )
  if (message.picker === 'date' && of('date').length)
    return (
      <div className="grid gap-2">
        <PickerCard title="Choose a day" replies={of('date')} onPick={onPick} disabled={disabled} />
        <Chips replies={rest} onPick={onPick} disabled={disabled} />
      </div>
    )
  return (
    <div className="grid gap-2">
      {of('service').length > 0 && (
        <ServiceCards replies={of('service')} onPick={onPick} disabled={disabled} />
      )}
      {of('dentist').length > 0 && (
        <DentistCards replies={of('dentist')} onPick={onPick} disabled={disabled} />
      )}
      <Chips
        replies={confirm ? rest.filter((r) => r !== confirm) : rest}
        onPick={onPick}
        disabled={disabled}
      />
    </div>
  )
}

function Bubble({
  message,
  last,
  onRate,
  onNavigate,
  onPick,
  disabled,
}: {
  message: Msg
  last: boolean
  onRate: (id: string, rating: 'up' | 'down') => void
  onNavigate: () => void
  onPick: Pick
  disabled: boolean
}) {
  if (message.role === 'user')
    return (
      <li className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-4 py-2 text-sm whitespace-pre-line text-primary-foreground">
          <span className="sr-only">You said: </span>
          {message.text}
        </p>
      </li>
    )
  const confirm = last
    ? message.quickReplies.find((r) => r.kind === 'confirm' && r.value === 'yes')
    : undefined
  const rateable = !message.id.startsWith('local-') && !message.degraded
  return (
    <li className="flex flex-col items-start gap-1">
      <div className="max-w-[92%]">
        {confirm ? (
          <SummaryCard text={message.text} confirm={confirm} onPick={onPick} disabled={disabled} />
        ) : (
          <p className="rounded-2xl rounded-bl-sm bg-secondary px-4 py-2 text-sm whitespace-pre-line">
            <span className="sr-only">Assistant said: </span>
            {message.text}
          </p>
        )}
        <Links links={message.links} onNavigate={onNavigate} />
        {rateable && <Rating message={message} onRate={(r) => onRate(message.id, r)} />}
      </div>
    </li>
  )
}

function Panel({
  chat,
  onClose,
  input,
}: {
  chat: Chat
  onClose: () => void
  input: React.RefObject<HTMLInputElement>
}) {
  const [text, setText] = React.useState('')
  const [ending, setEnding] = React.useState(false)
  const log = React.useRef<HTMLDivElement>(null)
  const { messages, draft, busy } = chat
  const last = messages.at(-1)
  const hint = last?.role === 'assistant' && last.inputHint ? hints[last.inputHint] : undefined

  React.useEffect(() => {
    log.current?.scrollTo?.({ top: log.current.scrollHeight })
  }, [messages.length, draft])

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    const value = text.trim()
    if (!value || busy) return
    setText('')
    void chat.say(value)
  }

  return (
    <>
      <header className="flex items-center gap-3 border-b bg-primary px-4 py-3 text-primary-foreground">
        <span className="flex size-9 items-center justify-center rounded-full bg-white/15">
          <Bot className="size-5" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <DialogPrimitive.Title className="font-heading text-base font-bold">
            Meridian Assistant
          </DialogPrimitive.Title>
          <DialogPrimitive.Description className="text-xs text-primary-foreground/85">
            {chat.degraded
              ? 'Working in a limited way'
              : 'Online. Answers about visits, prices and booking.'}
          </DialogPrimitive.Description>
        </div>
        <button
          type="button"
          aria-label="Download transcript"
          disabled={messages.length === 0}
          onClick={() => saveFile(buildTranscript(messages), 'chat-transcript.txt')}
          className="inline-flex size-9 items-center justify-center rounded-full hover:bg-white/15 focus-visible:outline-2 focus-visible:outline-white disabled:opacity-40"
        >
          <Download className="size-4" aria-hidden="true" />
        </button>
        <button
          type="button"
          aria-label="End chat"
          aria-expanded={ending}
          onClick={() => setEnding((v) => !v)}
          className="inline-flex size-9 items-center justify-center rounded-full hover:bg-white/15 focus-visible:outline-2 focus-visible:outline-white"
        >
          <Trash2 className="size-4" aria-hidden="true" />
        </button>
        <DialogPrimitive.Close
          aria-label="Close chat"
          className="inline-flex size-9 items-center justify-center rounded-full hover:bg-white/15 focus-visible:outline-2 focus-visible:outline-white"
        >
          <X className="size-5" aria-hidden="true" />
        </DialogPrimitive.Close>
      </header>

      {ending && (
        <div role="alert" className="border-b bg-warning-soft px-4 py-3 text-sm">
          <p>End this chat? The conversation is deleted and cannot be brought back.</p>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              className="rounded-full bg-destructive px-4 py-1.5 font-semibold text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              onClick={async () => {
                await chat.end()
                setEnding(false)
                onClose()
              }}
            >
              Yes, end chat
            </button>
            <button
              type="button"
              className="rounded-full border px-4 py-1.5 font-semibold"
              onClick={() => setEnding(false)}
            >
              Keep chatting
            </button>
          </div>
        </div>
      )}

      {chat.degraded && (
        <div
          role="status"
          className="border-b bg-warning-soft px-4 py-2 text-sm text-warning-strong"
        >
          I may be slow or limited right now. You can{' '}
          <Link to="/book" onClick={onClose} className="font-semibold underline">
            book with the form
          </Link>{' '}
          or call{' '}
          <a href={clinic.phoneHref} className="font-semibold underline">
            {clinic.phone}
          </a>
          .
        </div>
      )}

      <div
        ref={log}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label="Conversation"
        className="flex-1 overflow-y-auto px-4 py-4"
      >
        <ol className="space-y-3">
          {!chat.ready && (
            <li role="status" className="text-sm text-muted-foreground">
              Starting the conversation
            </li>
          )}
          {messages.map((m, i) => (
            <Bubble
              key={m.id}
              message={m}
              last={i === messages.length - 1 && !busy}
              onRate={chat.rate}
              onNavigate={onClose}
              onPick={(c) => void chat.choose(c)}
              disabled={busy}
            />
          ))}
          {busy && (
            <li className="flex items-start">
              {draft ? (
                // The words are shown as they arrive but not read out piece by piece: the whole
                // reply is announced once, when it is complete.
                <p
                  aria-hidden="true"
                  className="max-w-[92%] rounded-2xl rounded-bl-sm bg-secondary px-4 py-2 text-sm whitespace-pre-line"
                >
                  {draft}
                </p>
              ) : (
                <p
                  className="flex gap-1 rounded-2xl rounded-bl-sm bg-secondary px-4 py-3"
                  role="status"
                >
                  <span className="sr-only">The assistant is typing</span>
                  {[0, 1, 2].map((n) => (
                    <span
                      key={n}
                      aria-hidden="true"
                      className="size-2 rounded-full bg-muted-foreground motion-safe:animate-pulse"
                      style={{ animationDelay: `${n * 150}ms` }}
                    />
                  ))}
                </p>
              )}
            </li>
          )}
        </ol>
      </div>

      {last?.role === 'assistant' && !busy && last.quickReplies.length > 0 && (
        <div className="max-h-[40%] overflow-y-auto border-t px-4 py-3">
          <Offer message={last} onPick={(c) => void chat.choose(c)} disabled={busy} />
        </div>
      )}

      <div className="border-t px-4 pt-3">
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            void chat.choose({ kind: 'action', value: 'handoff', label: 'Talk to a person' })
          }
          className="inline-flex items-center gap-1.5 text-sm font-semibold text-accent-strong underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50"
        >
          <UserRound className="size-4" aria-hidden="true" /> Talk to a person
        </button>
      </div>
      <form onSubmit={submit} className="flex gap-2 px-4 pt-2 pb-3" aria-label="Send a message">
        <input
          ref={input}
          type={hint?.type ?? 'text'}
          inputMode={hint?.mode}
          autoComplete={hint?.auto ?? 'off'}
          aria-label={hint?.label ?? 'Type your message'}
          placeholder={hint?.label ?? 'Type your message'}
          maxLength={500}
          value={text}
          disabled={busy}
          onChange={(e) => setText(e.target.value)}
          className="h-11 min-w-0 flex-1 rounded-full border border-input bg-card px-4 text-base focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={busy || !text.trim()}
          aria-label="Send"
          className="inline-flex size-11 items-center justify-center rounded-full bg-primary text-primary-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50"
        >
          <Send className="size-5" aria-hidden="true" />
        </button>
      </form>
      <p className="border-t px-4 py-2 text-center text-xs text-muted-foreground">
        Prefer a form?{' '}
        <Link to="/book" onClick={onClose} className="font-semibold underline">
          Open the booking page
        </Link>
        . The assistant gives general information, not medical advice.
      </p>
    </>
  )
}

/** The conversation window. It is loaded the first time the chat is opened. */
export default function ChatPanel({
  chat,
  open,
  onOpenChange,
  input,
  launcher,
}: {
  chat: Chat
  open: boolean
  onOpenChange: (open: boolean) => void
  input: React.RefObject<HTMLInputElement>
  launcher: React.RefObject<HTMLButtonElement>
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-primary/40 sm:bg-primary/10" />
        <DialogPrimitive.Content
          onOpenAutoFocus={(event) => {
            event.preventDefault()
            input.current?.focus()
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            launcher.current?.focus()
          }}
          className={cn(
            'fixed inset-0 z-50 flex flex-col bg-card focus:outline-none',
            'sm:inset-auto sm:right-6 sm:bottom-6 sm:h-[640px] sm:max-h-[calc(100dvh-3rem)] sm:w-[400px] sm:overflow-hidden sm:rounded-2xl sm:border sm:shadow-raised',
          )}
        >
          <Panel chat={chat} onClose={() => onOpenChange(false)} input={input} />
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
