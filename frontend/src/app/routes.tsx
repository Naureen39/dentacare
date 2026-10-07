import { lazy, Suspense } from 'react'
import { createBrowserRouter, createMemoryRouter, type RouteObject } from 'react-router-dom'

import { RootLayout } from '@/components/layout/RootLayout'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ServerErrorPage } from '@/pages/ServerErrorPage'

const HomePage = lazy(() => import('@/pages/HomePage'))

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <RootLayout />,
    errorElement: <ServerErrorPage />,
    children: [
      {
        index: true,
        element: (
          <Suspense fallback={<p className="p-8 text-muted-foreground">Loading...</p>}>
            <HomePage />
          </Suspense>
        ),
      },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]

export const createAppRouter = () => createBrowserRouter(routes)
export const createTestRouter = (initialEntries: string[]) =>
  createMemoryRouter(routes, { initialEntries })
