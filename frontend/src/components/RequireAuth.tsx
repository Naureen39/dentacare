import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { Skeleton } from '@/components/ui/display'
import { useAuth, type Role } from '@/lib/auth'
import { ForbiddenPage } from '@/pages/ForbiddenPage'

/**
 * Guards a group of routes. Anonymous visitors are sent to the sign in page and come back to
 * where they were headed. Signed in users with the wrong role see a 403 page instead, so a
 * patient who types a staff address is told plainly rather than bounced around.
 *
 * This only decides what the interface shows. The server checks the role on every request.
 */
export function RequireAuth({ roles }: { roles?: Role[] }) {
  const { status, user } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return (
      <div className="container-page py-16" role="status" aria-label="Checking your session">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="mt-4 h-4 w-96 max-w-full" />
      </div>
    )
  }
  if (status === 'anonymous' || !user) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }
  if (roles && !roles.includes(user.role)) return <ForbiddenPage />
  return <Outlet />
}
