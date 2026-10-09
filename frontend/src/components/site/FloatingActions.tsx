import { CalendarCheck, MessageCircle, Phone } from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { clinic } from '@/content/site'

/**
 * The chat button, bottom right on every page, and on phones a bar with Call and Book.
 * The assistant itself is added in the chat widget phase; until then the button opens a short
 * panel with the ways to reach the clinic, so the control is never a dead end.
 */
export function FloatingActions() {
  const [open, setOpen] = React.useState(false)
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed right-4 bottom-20 z-30 inline-flex size-14 items-center justify-center rounded-full bg-accent-strong text-white shadow-raised transition-transform hover:scale-105 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring motion-reduce:transition-none md:bottom-6"
        aria-label="Chat with our assistant"
        aria-haspopup="dialog"
      >
        <MessageCircle className="size-6" aria-hidden="true" />
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          side="bottom"
          className="mx-auto max-w-md sm:right-6 sm:bottom-6 sm:left-auto sm:rounded-xl"
        >
          <DialogTitle>Chat with our assistant</DialogTitle>
          <DialogDescription>
            The online assistant is coming soon. Until then we are glad to help directly.
          </DialogDescription>
          <div className="grid gap-3">
            <Button asChild>
              <a href={clinic.phoneHref}>Call {clinic.phone}</a>
            </Button>
            <Button asChild variant="secondary">
              <Link to="/contact" onClick={() => setOpen(false)}>
                Send us a message
              </Link>
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <nav
        aria-label="Quick actions"
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-2 gap-px border-t bg-border shadow-raised md:hidden"
      >
        <a
          href={clinic.phoneHref}
          className="flex h-14 items-center justify-center gap-2 bg-card font-semibold text-primary"
        >
          <Phone className="size-5" aria-hidden="true" />
          Call
        </a>
        <Link
          to="/book"
          className="flex h-14 items-center justify-center gap-2 bg-primary font-semibold text-primary-foreground"
        >
          <CalendarCheck className="size-5" aria-hidden="true" />
          Book
        </Link>
      </nav>
    </>
  )
}
