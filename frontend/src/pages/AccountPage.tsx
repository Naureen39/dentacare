import { Card } from '@/components/ui/display'
import { Badge } from '@/components/ui/display'
import { useAuth } from '@/lib/auth'

/** A placeholder for the signed in area, so route guards have something real to protect. */
export default function AccountPage() {
  const { user } = useAuth()
  if (!user) return null
  return (
    <section className="container-page py-12">
      <h1 className="text-3xl">Your account</h1>
      <Card className="mt-6 max-w-lg p-6">
        <dl className="grid gap-3 text-sm">
          <div>
            <dt className="text-muted-foreground">Email address</dt>
            <dd className="font-medium">{user.email}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Role</dt>
            <dd className="capitalize">
              <Badge tone="brand">{user.role}</Badge>
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Two step verification</dt>
            <dd>{user.mfa_enabled ? 'On' : 'Off'}</dd>
          </div>
        </dl>
      </Card>
    </section>
  )
}
