import { Bell } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Skeleton } from '@/components/ui/display'
import { EmptyState } from '@/components/ui/navigation'
import { useNotifications } from '@/lib/booking-api'
import { FormAlert } from '@/lib/auth-forms'
import { clock, longDay } from '@/pages/portal/format'

/** Reminders and messages the clinic has sent, newest first. */
export function NotificationsPage() {
  const notifications = useNotifications()
  return (
    <div>
      <h1 className="text-3xl">Notifications</h1>
      <p className="mt-2 text-muted-foreground">
        Reminders and messages we have sent to you by email.
      </p>
      <div className="mt-6">
        {notifications.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : notifications.isError ? (
          <FormAlert message="We could not load your notifications. Please try again." />
        ) : !notifications.data?.length ? (
          <EmptyState
            icon={<Bell className="size-6" aria-hidden="true" />}
            title="Nothing here yet"
            description="Confirmations and reminders appear here after we send them."
          />
        ) : (
          <ul className="grid gap-3">
            {notifications.data.map((item) => (
              <li key={item.id} className="rounded-xl border bg-card p-4">
                <p className="font-semibold">{item.title}</p>
                <p className="text-sm text-muted-foreground">
                  Sent {longDay(item.sent_at)} at {clock(item.sent_at)}
                </p>
                <Link to="/portal/appointments" className="mt-1 inline-block text-sm font-semibold">
                  View appointments
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
