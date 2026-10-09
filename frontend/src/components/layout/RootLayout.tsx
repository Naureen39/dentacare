import * as React from 'react'
import { Outlet, useLocation } from 'react-router-dom'

import { CookieNotice } from '@/components/site/CookieNotice'
import { FloatingActions } from '@/components/site/FloatingActions'
import { Footer } from '@/components/site/Footer'
import { Header, TopBar } from '@/components/site/Header'

export const skipLinkClass =
  'sr-only z-50 rounded-md bg-primary px-4 py-2 text-primary-foreground focus:not-sr-only focus:absolute focus:top-2 focus:left-2'

export function RootLayout() {
  const location = useLocation()
  const main = React.useRef<HTMLElement>(null)

  // After moving to another page, send focus to the content so keyboard and screen reader users
  // start at the top of the new page rather than wherever the old link was. A link to a heading
  // on the same page (an anchor) keeps its own behaviour.
  const first = React.useRef(true)
  React.useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    if (location.hash) {
      document.getElementById(location.hash.slice(1))?.scrollIntoView()
      return
    }
    main.current?.focus({ preventScroll: true })
    window.scrollTo({ top: 0 })
  }, [location.pathname, location.hash])

  return (
    <div className="flex min-h-screen flex-col pb-14 md:pb-0">
      <a href="#main-content" className={skipLinkClass}>
        Skip to main content
      </a>
      <TopBar />
      <Header />
      <main id="main-content" ref={main} tabIndex={-1} className="flex-1 focus:outline-none">
        <Outlet />
      </main>
      <Footer />
      <FloatingActions />
      <CookieNotice />
    </div>
  )
}
