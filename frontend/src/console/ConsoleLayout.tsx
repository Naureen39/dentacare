import * as Popover from '@radix-ui/react-popover'
import { Bell, ExternalLink, LogOut, Menu, Search } from 'lucide-react'
import * as React from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { Seo } from '@/components/site/Seo'
import { Button } from '@/components/ui/button'
import { Avatar } from '@/components/ui/display'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { useAlerts } from '@/console/api'
import { CommandPalette } from '@/console/CommandPalette'
import { labelFor, sectionsFor } from '@/console/nav'
import { clinic } from '@/content/site'
import { useAuth } from '@/lib/auth'
import { cn } from '@/lib/utils'

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const { user } = useAuth()
  if (!user) return null
  return (
    <nav aria-label="Console" className="grid gap-6">
      {sectionsFor(user.role).map((section) => (
        <div key={section.title}>
          <p className="px-3 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            {section.title}
          </p>
          <ul className="mt-2 grid gap-1">
            {section.items.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    cn(
                      'flex min-h-10 items-center gap-2 rounded-lg px-3 text-sm font-medium hover:bg-secondary',
                      isActive && 'bg-secondary font-semibold text-primary',
                    )
                  }
                >
                  <item.icon className="size-4" aria-hidden="true" />
                  {labelFor(item, user.role)}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  )
}

function Alerts() {
  const { user } = useAuth()
  const front = user?.role === 'admin' || user?.role === 'receptionist'
  const alerts = useAlerts(front)
  if (!front) return null
  const total = (alerts.data?.unconfirmed_soon ?? 0) + (alerts.data?.new_inquiries ?? 0)
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Notifications, ${total} waiting`}>
          <span className="relative">
            <Bell className="size-5" aria-hidden="true" />
            {total > 0 && (
              <span className="absolute -top-2 -right-2 flex size-4 items-center justify-center rounded-full bg-destructive text-[10px] font-bold text-white">
                {total}
              </span>
            )}
          </span>
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={8}
          className="z-50 w-72 rounded-xl border bg-card p-4 shadow-raised"
        >
          <p className="font-heading font-bold text-primary">Needs attention</p>
          <ul className="mt-3 grid gap-2 text-sm">
            <li>
              <Link to="/staff" className="font-semibold">
                {alerts.data?.unconfirmed_soon ?? 0} visits
              </Link>{' '}
              in the next 48 hours are not confirmed.
            </li>
            <li>
              <strong>{alerts.data?.new_inquiries ?? 0}</strong> new messages from the contact form.
            </li>
          </ul>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

function ProfileMenu() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  if (!user) return null
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          aria-label="Account menu"
          className="rounded-full focus-visible:outline-2 focus-visible:outline-ring"
        >
          <Avatar name={user.email} />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={8}
          className="z-50 w-64 rounded-xl border bg-card p-4 shadow-raised"
        >
          <p className="truncate font-semibold">{user.email}</p>
          <p className="text-sm text-muted-foreground capitalize">{user.role}</p>
          <div className="mt-4 grid gap-2">
            <Button asChild variant="secondary" size="sm">
              <Link to="/">
                <ExternalLink aria-hidden="true" /> View public site
              </Link>
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={async () => {
                await logout()
                void navigate('/login')
              }}
            >
              <LogOut aria-hidden="true" /> Sign out
            </Button>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

/** The staff and admin console: a menu for the role, a search, alerts and the page. */
export function ConsoleLayout() {
  const { user } = useAuth()
  const location = useLocation()
  const [menu, setMenu] = React.useState(false)
  const [palette, setPalette] = React.useState(false)
  const main = React.useRef<HTMLElement>(null)
  const first = React.useRef(true)

  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPalette((open) => !open)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  React.useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    main.current?.focus({ preventScroll: true })
  }, [location.pathname])

  if (!user) return null
  return (
    <div className="flex min-h-screen bg-muted/40">
      <Seo title="Console" description="Clinic console." path="/staff" noindex />
      <a
        href="#console-main"
        className="sr-only z-50 rounded-md bg-primary px-4 py-2 text-primary-foreground focus:not-sr-only focus:absolute focus:top-2 focus:left-2"
      >
        Skip to main content
      </a>
      <aside className="hidden w-60 shrink-0 border-r bg-card p-4 lg:block">
        <Link to="/staff" className="mb-6 block px-3 font-heading text-lg font-bold text-primary">
          {clinic.name}
        </Link>
        <NavList />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-card px-4">
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            aria-label="Open menu"
            onClick={() => setMenu(true)}
          >
            <Menu className="size-5" aria-hidden="true" />
          </Button>
          <button
            type="button"
            onClick={() => setPalette(true)}
            className="flex h-9 max-w-md flex-1 items-center gap-2 rounded-full border bg-background px-3 text-left text-sm text-muted-foreground hover:border-accent-strong"
          >
            <Search className="size-4" aria-hidden="true" />
            <span className="flex-1 truncate">Search pages and patients</span>
            <kbd className="hidden rounded border px-1.5 text-xs sm:block">Ctrl K</kbd>
          </button>
          <div className="ml-auto flex items-center gap-1">
            <Alerts />
            <ProfileMenu />
          </div>
        </header>
        <main
          id="console-main"
          ref={main}
          tabIndex={-1}
          className="flex-1 p-4 focus:outline-none md:p-8"
        >
          <Outlet />
        </main>
      </div>

      <Dialog open={menu} onOpenChange={setMenu}>
        <DialogContent side="left" className="w-72">
          <DialogTitle>Menu</DialogTitle>
          <DialogDescription className="sr-only">Pages of the console</DialogDescription>
          <div className="mt-4">
            <NavList onNavigate={() => setMenu(false)} />
          </div>
        </DialogContent>
      </Dialog>
      <CommandPalette open={palette} onOpenChange={setPalette} role={user.role} />
    </div>
  )
}
