import { CalendarCheck, Phone } from 'lucide-react'
import { Link } from 'react-router-dom'

import { ChatWidget } from '@/chat/ChatWidget'
import { clinic } from '@/content/site'

/**
 * The assistant, bottom right on every page, and on phones a bar with Call and Book.
 */
export function FloatingActions() {
  return (
    <>
      <ChatWidget />

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
