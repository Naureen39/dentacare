import { CalendarDays, CreditCard, LayoutDashboard, Bell, UserRound } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'

import { Seo } from '@/components/site/Seo'
import { Badge } from '@/components/ui/display'
import { useAuth } from '@/lib/auth'
import type { Appointment } from '@/lib/booking-api'
import { cn } from '@/lib/utils'

type Status = Appointment['status']
const statuses: Record<
  Status,
  { label: string; tone: 'brand' | 'success' | 'neutral' | 'danger' | 'warning' }
> = {
  booked: { label: 'Booked', tone: 'brand' },
  confirmed: { label: 'Confirmed', tone: 'success' },
  checked_in: { label: 'Checked in', tone: 'warning' },
  completed: { label: 'Completed', tone: 'success' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
  no_show: { label: 'Missed', tone: 'danger' },
}

export function StatusBadge({ status }: { status: Status }) {
  const { label, tone } = statuses[status]
  return <Badge tone={tone}>{label}</Badge>
}

const links = [
  { to: '/portal', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/portal/appointments', label: 'Appointments', icon: CalendarDays },
  { to: '/portal/billing', label: 'Billing', icon: CreditCard },
  { to: '/portal/notifications', label: 'Notifications', icon: Bell },
  { to: '/portal/profile', label: 'Profile and security', icon: UserRound },
]

/** The signed in patient's area: a menu, then the page. */
export function PortalLayout() {
  const { user } = useAuth()
  return (
    <>
      <Seo
        title="Patient portal"
        description="Your appointments, invoices and details at Meridian Dental Care."
        path="/portal"
        noindex
      />
      <div className="bg-secondary">
        <div className="container-page py-8">
          <p className="text-sm text-muted-foreground">Patient portal</p>
          <p className="mt-1 font-heading text-2xl font-bold text-primary">{user?.email}</p>
        </div>
      </div>
      <div className="container-page grid gap-8 py-8 lg:grid-cols-[220px_1fr]">
        <nav aria-label="Patient portal">
          <ul className="flex gap-1 overflow-x-auto lg:flex-col">
            {links.map(({ to, label, icon: Icon, end }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={end}
                  className={({ isActive: active }) =>
                    cn(
                      'flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm font-medium whitespace-nowrap hover:bg-secondary',
                      active && 'bg-secondary font-semibold text-primary',
                    )
                  }
                >
                  <Icon className="size-4" aria-hidden="true" />
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0">
          <Outlet />
        </div>
      </div>
    </>
  )
}
