import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'

export function ServerErrorPage() {
  return (
    <section className="mx-auto flex max-w-xl flex-col items-center gap-4 px-4 py-24 text-center">
      <p className="font-semibold text-destructive">Error 500</p>
      <h1 className="text-4xl font-bold">We could not load this page</h1>
      <p className="text-muted-foreground">Please try again in a moment.</p>
      <Button asChild>
        <Link to="/">Return home</Link>
      </Button>
    </section>
  )
}
