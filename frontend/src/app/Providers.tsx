import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { HelmetProvider, type HelmetServerState } from 'react-helmet-async'

import { ErrorBoundary } from '@/components/ErrorBoundary'
import { TooltipProvider } from '@/components/ui/display'
import { ToastProvider } from '@/components/ui/toast'
import { ApiError } from '@/lib/api-client'
import { AuthProvider } from '@/lib/auth'

/** Retry once for failures that may pass (network, server); never for a refusal by the server. */
const retry = (count: number, error: unknown) =>
  count < 1 && !(error instanceof ApiError && error.status < 500)

export type HelmetContext = { helmet?: HelmetServerState }

/**
 * Everything the application needs around its pages. The same tree is used in the browser and
 * when pages are rendered ahead of time at build, where `helmetContext` collects the page's
 * title and meta tags.
 */
export function Providers({
  children,
  helmetContext,
}: {
  children: ReactNode
  helmetContext?: HelmetContext
}) {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry, staleTime: 30_000 } } }),
  )
  return (
    <ErrorBoundary>
      <HelmetProvider context={helmetContext}>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <TooltipProvider delayDuration={200}>
              <ToastProvider>{children}</ToastProvider>
            </TooltipProvider>
          </AuthProvider>
        </QueryClientProvider>
      </HelmetProvider>
    </ErrorBoundary>
  )
}
