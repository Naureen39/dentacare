import { ShieldCheck, ThumbsDown, ThumbsUp } from 'lucide-react'
import * as React from 'react'

import { Badge, Skeleton } from '@/components/ui/display'
import { controlClasses } from '@/components/ui/input'
import { EmptyState } from '@/components/ui/navigation'
import { useChatSessions, useTranscript } from '@/console/api'
import { FormAlert } from '@/lib/auth-forms'
import { cn } from '@/lib/utils'
import { clock, longDay } from '@/pages/portal/format'

function TranscriptView({ id }: { id: string }) {
  const transcript = useTranscript(id)
  if (transcript.isLoading) return <Skeleton className="h-64 w-full" />
  if (transcript.isError || !transcript.data)
    return <FormAlert message="We could not load this conversation." />
  const t = transcript.data
  return (
    <div>
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <ShieldCheck className="size-4" aria-hidden="true" />
        Emails, phone numbers, dates and names given in the conversation are hidden.
      </p>
      <ol className="mt-4 grid gap-3" aria-label="Messages">
        {t.messages.map((m) => (
          <li
            key={m.id}
            className={cn(
              'max-w-[85%] rounded-xl border p-3 text-sm',
              m.role === 'user' ? 'ml-auto bg-secondary' : 'bg-card',
            )}
          >
            <p className="text-xs font-semibold text-muted-foreground capitalize">
              {m.role} {clock(m.created_at)}
              {m.intent ? `, ${m.intent}` : ''}
              {m.route ? `, ${m.route}` : ''}
              {m.llm_calls > 0 ? `, ${m.llm_calls} model calls` : ''}
            </p>
            <p className="mt-1 whitespace-pre-line">{m.content}</p>
            {m.feedback === 1 && (
              <p className="mt-1 flex items-center gap-1 text-xs text-success-strong">
                <ThumbsUp className="size-3" aria-hidden="true" /> Marked helpful
              </p>
            )}
            {m.feedback === -1 && (
              <p className="mt-1 flex items-center gap-1 text-xs text-destructive">
                <ThumbsDown className="size-3" aria-hidden="true" /> Marked not helpful
              </p>
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}

export function ChatsPage() {
  const [feedback, setFeedback] = React.useState('any')
  const [open, setOpen] = React.useState<string | null>(null)
  const sessions = useChatSessions(feedback)
  return (
    <div>
      <h1 className="text-3xl">Chat review</h1>
      <div className="mt-4 flex items-center gap-3">
        <label htmlFor="feedback" className="text-sm font-medium">
          Show
        </label>
        <select
          id="feedback"
          className={cn(controlClasses, 'h-10 w-60')}
          value={feedback}
          onChange={(e) => {
            setFeedback(e.target.value)
            setOpen(null)
          }}
        >
          <option value="any">All conversations</option>
          <option value="negative">With a thumbs down</option>
          <option value="positive">With a thumbs up</option>
        </select>
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-[360px_1fr]">
        <div>
          {sessions.isLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : !sessions.data?.length ? (
            <EmptyState title="No conversations" description="Nothing matches this filter." />
          ) : (
            <ul className="grid gap-2" aria-label="Conversations">
              {sessions.data.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    aria-pressed={open === s.id}
                    onClick={() => setOpen(s.id)}
                    className={cn(
                      'w-full rounded-xl border bg-card p-3 text-left hover:border-accent-strong focus-visible:outline-2 focus-visible:outline-ring',
                      open === s.id && 'border-primary ring-2 ring-primary',
                    )}
                  >
                    <span className="block text-xs text-muted-foreground">
                      {longDay(s.created_at)} {clock(s.created_at)}, {s.messages} messages
                    </span>
                    <span className="mt-1 block truncate text-sm font-medium">
                      {s.first_message ?? 'No messages'}
                    </span>
                    <span className="mt-1 flex gap-2">
                      {s.thumbs_up > 0 && <Badge tone="success">{s.thumbs_up} up</Badge>}
                      {s.thumbs_down > 0 && <Badge tone="danger">{s.thumbs_down} down</Badge>}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          {open ? (
            <TranscriptView key={open} id={open} />
          ) : (
            <EmptyState title="Choose a conversation" description="Its messages appear here." />
          )}
        </div>
      </div>
    </div>
  )
}
