import { useQuery } from '@tanstack/react-query'

import { getInfo } from '@/lib/api-client'

export default function HomePage() {
  const { data, isError, isPending } = useQuery({ queryKey: ['info'], queryFn: getInfo })

  return (
    <section className="mx-auto max-w-[1240px] px-4 py-14">
      <h1 className="text-4xl font-bold">Exceptional dental care for every stage of life</h1>
      <p className="mt-4 max-w-2xl text-lg text-muted-foreground">
        The public website is built in a later phase. This page confirms the application shell and
        the API connection.
      </p>
      <p className="mt-6 text-sm" role="status">
        {isPending && 'Checking service status...'}
        {isError && 'The service is currently unavailable.'}
        {data && `Connected to ${data.name} (${data.environment}).`}
      </p>
    </section>
  )
}
