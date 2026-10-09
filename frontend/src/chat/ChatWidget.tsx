import { MessageCircle, X } from 'lucide-react'
import * as React from 'react'
import { useLocation } from 'react-router-dom'

import { GREETED_KEY } from '@/chat/api'
import { useChat } from '@/chat/useChat'

const TEASER_DELAY_MS = 20_000
const loadPanel = () => import('@/chat/ChatPanel')
const ChatPanel = React.lazy(loadPanel)
/** Fetch the window's code as the visitor reaches for the button, so it opens at once. */
const preload = () => void loadPanel()

/** The chat button, an offer to help on the home page, and the conversation itself. */
export function ChatWidget() {
  const [open, setOpen] = React.useState(false)
  const [teaser, setTeaser] = React.useState(false)
  const [loaded, setLoaded] = React.useState(false)
  const chat = useChat(open)
  const input = React.useRef<HTMLInputElement>(null)
  const launcher = React.useRef<HTMLButtonElement>(null)
  const location = useLocation()
  const start = chat.start
  const home = location.pathname === '/'

  // On the home page, offer help once per visit after 20 seconds, if the chat was not opened.
  React.useEffect(() => {
    if (!home || open) return
    try {
      if (window.sessionStorage.getItem(GREETED_KEY)) return
    } catch {
      return
    }
    const timer = setTimeout(() => {
      try {
        window.sessionStorage.setItem(GREETED_KEY, '1')
      } catch {
        /* without storage the offer may repeat on a reload, which is harmless */
      }
      setTeaser(true)
    }, TEASER_DELAY_MS)
    return () => clearTimeout(timer)
  }, [home, open])

  const show = () => {
    setLoaded(true)
    setTeaser(false)
    chat.markSeen()
    setOpen(true)
    void start()
  }

  return (
    <>
      {teaser && !open && (
        <div
          role="status"
          className="fixed right-4 bottom-36 z-30 flex max-w-[16rem] items-start gap-2 rounded-xl border bg-card p-3 text-sm shadow-raised md:bottom-24"
        >
          <button
            type="button"
            onClick={show}
            className="text-left focus-visible:outline-2 focus-visible:outline-ring"
          >
            Hi, I am the Meridian Assistant. Can I help you book a visit or answer a question?
          </button>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => setTeaser(false)}
            className="rounded-full p-1 text-muted-foreground hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>
      )}
      <button
        ref={launcher}
        type="button"
        onClick={show}
        onPointerEnter={preload}
        onFocus={preload}
        className="fixed right-4 bottom-20 z-30 inline-flex size-14 items-center justify-center rounded-full bg-accent-strong text-white shadow-raised transition-transform hover:scale-105 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring motion-reduce:transition-none md:bottom-6"
        aria-label={`Chat with our assistant${chat.unseen || teaser ? ', new message' : ''}`}
        aria-haspopup="dialog"
      >
        <MessageCircle className="size-6" aria-hidden="true" />
        {(chat.unseen || teaser) && (
          <>
            <span
              className="absolute top-0 right-0 size-4 rounded-full border-2 border-white bg-destructive"
              aria-hidden="true"
            />
          </>
        )}
      </button>

      {loaded && (
        <React.Suspense fallback={null}>
          <ChatPanel
            chat={chat}
            open={open}
            onOpenChange={setOpen}
            input={input}
            launcher={launcher}
          />
        </React.Suspense>
      )}
    </>
  )
}
