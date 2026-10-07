import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'

export function NotFoundPage() {
  return (
    <section className="mx-auto flex max-w-xl flex-col items-center gap-4 px-4 py-24 text-center">
      <p className="font-semibold text-accent">Error 404</p>
      <h1 className="text-4xl font-bold">Page not found</h1>
      <p className="text-muted-foreground">
        The page you requested does not exist or has been moved.
      </p>
      <Button asChild>
        <Link to="/">Return home</Link>
      </Button>
    </section>
  )
}
