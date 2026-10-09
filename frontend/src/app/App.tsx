import { RouterProvider, type createBrowserRouter } from 'react-router-dom'

import { Providers } from '@/app/Providers'

export function App({ router }: { router: ReturnType<typeof createBrowserRouter> }) {
  return (
    <Providers>
      <RouterProvider router={router} />
    </Providers>
  )
}
