import { Check, ExternalLink, ThumbsDown, ThumbsUp } from 'lucide-react'
import { Link } from 'react-router-dom'

import type { Choice, QuickReply } from '@/chat/api'
import { useDentistCards } from '@/chat/lookup'
import { internalPath, type Msg } from '@/chat/model'
import { Avatar } from '@/components/ui/display'
import { useLiveServices } from '@/lib/booking-api'
import { cn } from '@/lib/utils'

export type Pick = (choice: Choice) => void
const asChoice = (q: QuickReply): Choice => ({ kind: q.kind, value: q.value, label: q.label })

const chip =
  'inline-flex min-h-10 items-center rounded-full border border-primary bg-card px-4 py-1.5 text-sm font-semibold text-primary transition-colors hover:bg-secondary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50'
const solid =
  'inline-flex min-h-11 items-center justify-center rounded-full bg-primary px-5 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50'

/** Plain buttons for everything the assistant offers that has no card of its own. */
export function Chips({
  replies,
  onPick,
  disabled,
}: {
  replies: QuickReply[]
  onPick: Pick
  disabled: boolean
}) {
  if (replies.length === 0) return null
  return (
    <ul className="flex flex-wrap gap-2" aria-label="Suggested replies">
      {replies.map((q) => (
        <li key={`${q.kind}:${q.value}`}>
          <button
            type="button"
            className={chip}
            disabled={disabled}
            onClick={() => onPick(asChoice(q))}
          >
            {q.label}
          </button>
        </li>
      ))}
    </ul>
  )
}

/** Services as cards, with how long they take and what they start at. */
export function ServiceCards({
  replies,
  onPick,
  disabled,
}: {
  replies: QuickReply[]
  onPick: Pick
  disabled: boolean
}) {
  const live = useLiveServices()
  const byId = new Map((live.data ?? []).map((s) => [s.id, s]))
  return (
    <ul className="grid gap-2" aria-label="Services">
      {replies.map((q) => {
        const s = byId.get(q.value)
        return (
          <li key={q.value}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onPick(asChoice(q))}
              className="flex w-full items-center justify-between gap-3 rounded-xl border bg-card p-3 text-left hover:border-accent-strong focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50"
            >
              <span className="font-semibold text-primary">{q.label}</span>
              {s && (
                <span className="text-xs whitespace-nowrap text-muted-foreground">
                  {s.duration_min} min, from ${Number(s.base_price).toLocaleString('en-US')}
                </span>
              )}
            </button>
          </li>
        )
      })}
    </ul>
  )
}

/** Dentists as cards with their specialty. */
export function DentistCards({
  replies,
  onPick,
  disabled,
}: {
  replies: QuickReply[]
  onPick: Pick
  disabled: boolean
}) {
  const live = useDentistCards(true)
  const byId = new Map((live.data ?? []).map((d) => [d.id, d]))
  return (
    <ul className="grid gap-2" aria-label="Dentists">
      {replies.map((q) => {
        const d = byId.get(q.value)
        return (
          <li key={q.value}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onPick(asChoice(q))}
              className="flex w-full items-center gap-3 rounded-xl border bg-card p-3 text-left hover:border-accent-strong focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50"
            >
              <Avatar name={d?.full_name ?? q.label} size="sm" />
              <span>
                <span className="block font-semibold text-primary">{q.label}</span>
                {d && <span className="block text-xs text-muted-foreground">{d.specialty}</span>}
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

/** Open days or times as a group of choices, so the visitor picks with one tap. */
export function PickerCard({
  title,
  replies,
  onPick,
  disabled,
}: {
  title: string
  replies: QuickReply[]
  onPick: Pick
  disabled: boolean
}) {
  return (
    <fieldset className="rounded-xl border bg-card p-3">
      <legend className="px-1 text-sm font-semibold text-primary">{title}</legend>
      <ul className="flex flex-wrap gap-2">
        {replies.map((q) => (
          <li key={q.value}>
            <button
              type="button"
              className={chip}
              disabled={disabled}
              onClick={() => onPick(asChoice(q))}
            >
              {q.label}
            </button>
          </li>
        ))}
      </ul>
    </fieldset>
  )
}

/** The booking as the assistant understood it, with the button that books it. */
export function SummaryCard({
  text,
  confirm,
  onPick,
  disabled,
}: {
  text: string
  confirm: QuickReply
  onPick: Pick
  disabled: boolean
}) {
  return (
    <section
      aria-label="Booking summary"
      className="rounded-xl border-2 border-accent-strong bg-card p-4"
    >
      <h3 className="flex items-center gap-2 font-heading text-base font-bold text-primary">
        <Check className="size-4" aria-hidden="true" /> Check your booking
      </h3>
      <p className="mt-2 text-sm whitespace-pre-line">{text}</p>
      <button
        type="button"
        className={cn(solid, 'mt-3 w-full')}
        disabled={disabled}
        onClick={() => onPick(asChoice(confirm))}
      >
        {confirm.label} booking
      </button>
    </section>
  )
}

/** Links the assistant gives: pages on this site stay in the app, anything else opens a new tab. */
export function Links({ links, onNavigate }: { links: Msg['links']; onNavigate: () => void }) {
  if (links.length === 0) return null
  return (
    <ul className="mt-2 grid gap-1 text-sm" aria-label="Links">
      {links.map((l) => {
        const path = internalPath(l.url)
        return (
          <li key={l.url}>
            {path ? (
              <Link to={path} onClick={onNavigate} className="font-semibold underline">
                {l.label}
              </Link>
            ) : (
              <a
                href={l.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 font-semibold underline"
              >
                {l.label} <ExternalLink className="size-3" aria-hidden="true" />
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            )}
          </li>
        )
      })}
    </ul>
  )
}

/** Thumbs under a reply. The choice is kept by the server for the team to review. */
export function Rating({
  message,
  onRate,
}: {
  message: Msg
  onRate: (rating: 'up' | 'down') => void
}) {
  return (
    <div className="mt-1 flex items-center gap-1" role="group" aria-label="Was this helpful?">
      {(['up', 'down'] as const).map((r) => {
        const Icon = r === 'up' ? ThumbsUp : ThumbsDown
        return (
          <button
            key={r}
            type="button"
            aria-pressed={message.feedback === r}
            aria-label={r === 'up' ? 'Helpful' : 'Not helpful'}
            disabled={message.feedback !== null}
            onClick={() => onRate(r)}
            className={cn(
              'inline-flex size-8 items-center justify-center rounded-full text-muted-foreground hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring disabled:cursor-default',
              message.feedback === r && 'bg-secondary text-primary',
            )}
          >
            <Icon className="size-4" aria-hidden="true" />
          </button>
        )
      })}
    </div>
  )
}
