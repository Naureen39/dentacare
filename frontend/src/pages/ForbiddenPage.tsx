import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'

export function ForbiddenPage() {
  return (
    <section className="mx-auto flex max-w-xl flex-col items-center gap-4 px-4 py-24 text-center">
      <p className="font-semibold text-destructive">Error 403</p>
      <h1 className="text-4xl font-bold">You do not have access to this page</h1>
      <p className="text-muted-foreground">
        Your account does not include this area. If you think it should, please ask a member of the
        team.
      </p>
      <Button asChild>
        <Link to="/">Return home</Link>
      </Button>
    </section>
  )
}
