import * as React from 'react'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'

const KEY = 'meridian-cookie-notice'

function seen(): boolean {
  try {
    return window.localStorage.getItem(KEY) === 'seen'
  } catch {
    return false
  }
}

/** The site sets only the cookies it needs to work (your session), so this is a notice, not a choice. */
export function CookieNotice() {
  // Decided in the browser only: the page is rendered ahead of time, where nothing is stored.
  const unseen = React.useSyncExternalStore(
    () => () => {},
    () => !seen(),
    () => false,
  )
  const [dismissed, setDismissed] = React.useState(false)
  if (!unseen || dismissed) return null
  return (
    <section
      aria-label="Cookie notice"
      className="fixed inset-x-3 bottom-[4.5rem] z-40 mx-auto max-w-2xl rounded-xl border bg-card p-4 shadow-raised md:bottom-4"
    >
      <p className="text-sm">
        We use only the cookies the site needs to work, such as keeping you signed in. We do not use
        advertising or tracking cookies. <Link to="/privacy">Read our privacy policy</Link>.
      </p>
      <Button
        size="sm"
        className="mt-3"
        onClick={() => {
          try {
            window.localStorage.setItem(KEY, 'seen')
          } catch {
            /* storage may be blocked; the notice then simply shows again next time */
          }
          setDismissed(true)
        }}
      >
        Got it
      </Button>
    </section>
  )
}
