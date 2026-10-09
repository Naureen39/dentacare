import type { ComponentType } from 'react'
import {
  Navigate,
  createBrowserRouter,
  createMemoryRouter,
  type RouteObject,
} from 'react-router-dom'

import { RequireAuth } from '@/components/RequireAuth'
import { RootLayout } from '@/components/layout/RootLayout'
import { Skeleton } from '@/components/ui/display'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ServerErrorPage } from '@/pages/ServerErrorPage'

type Module = Record<string, unknown>

/**
 * A page loaded on demand, as its own chunk. The router waits for the chunk before it shows the
 * page, so a visitor never sees a half loaded screen, and a page that arrived already rendered is
 * matched by the browser's first render.
 */
const at = (
  path: string | undefined,
  load: () => Promise<Module>,
  key = 'default',
  children?: RouteObject[],
): RouteObject =>
  ({
    ...(path === undefined ? { index: true } : { path }),
    lazy: async () => ({ Component: (await load())[key] as ComponentType }),
    ...(children ? { children } : {}),
  }) as RouteObject

const services = () => import('@/pages/ServicePages')
const dentists = () => import('@/pages/DentistPages')
const info = () => import('@/pages/InfoPages')
const content = () => import('@/pages/ContentPages')
const accounts = () => import('@/pages/AccountPages')

// The condition is written out here, not imported, so the bundler can see it is false in a
// production build and leave the whole style guide out of the output.
const withStyleguideInBuild =
  import.meta.env.DEV || import.meta.env.VITE_ENABLE_STYLEGUIDE === 'true'

function PageLoading() {
  return (
    <div className="container-page min-h-screen py-16" role="status" aria-label="Loading page">
      <Skeleton className="h-8 w-64" />
      <Skeleton className="mt-4 h-4 w-96 max-w-full" />
    </div>
  )
}

/** The route table. The style guide is included only when asked for (see lib/features). */
export const buildRoutes = (withStyleguide: boolean): RouteObject[] => [
  {
    path: '/',
    element: <RootLayout />,
    errorElement: <ServerErrorPage />,
    HydrateFallback: PageLoading,
    children: [
      at(undefined, () => import('@/pages/HomePage')),
      at('services', services, 'ServicesPage'),
      at('services/:slug', services, 'ServiceDetailPage'),
      at('dentists', dentists, 'DentistsPage'),
      at('dentists/:slug', dentists, 'DentistProfilePage'),
      at('about', info, 'AboutPage'),
      at('new-patients', info, 'NewPatientsPage'),
      at('insurance-and-payment', info, 'InsurancePage'),
      at('pricing', info, 'PricingPage'),
      at('faq', info, 'FaqPage'),
      at('reviews', info, 'ReviewsPage'),
      at('contact', () => import('@/pages/ContactPage')),
      at('resources', content, 'ResourcesPage'),
      at('resources/:slug', content, 'ArticlePage'),
      at('book', () => import('@/pages/booking/state'), 'BookLayout', [
        at(undefined, () => import('@/pages/booking/state'), 'BookStart'),
        at('service', () => import('@/pages/booking/steps'), 'ServiceStep'),
        at('dentist', () => import('@/pages/booking/steps'), 'DentistStep'),
        at('time', () => import('@/pages/booking/steps'), 'TimeStep'),
        at('details', () => import('@/pages/booking/finish'), 'DetailsStep'),
        at('verify', () => import('@/pages/booking/finish'), 'VerifyStep'),
        at('done', () => import('@/pages/booking/finish'), 'ConfirmedStep'),
      ]),
      at('privacy', content, 'PrivacyPage'),
      at('terms', content, 'TermsPage'),
      at('accessibility', content, 'AccessibilityPage'),
      at('notice-of-privacy-practices', content, 'NoticePage'),
      ...(withStyleguide && withStyleguideInBuild
        ? [at('styleguide', () => import('@/pages/StyleguidePage'))]
        : []),
      {
        // The patient's own area.
        element: <RequireAuth roles={['patient']} />,
        children: [
          at('portal', () => import('@/pages/portal/shared'), 'PortalLayout', [
            at(undefined, () => import('@/pages/portal/Overview'), 'OverviewPage'),
            at('appointments', () => import('@/pages/portal/Appointments'), 'AppointmentsPage'),
            at('billing', () => import('@/pages/portal/Billing'), 'BillingPage'),
            at('billing/:id', () => import('@/pages/portal/Billing'), 'InvoicePage'),
            at('notifications', () => import('@/pages/portal/Notifications'), 'NotificationsPage'),
            at('profile', () => import('@/pages/portal/Profile'), 'ProfilePage'),
          ]),
        ],
      },
      {
        // Any signed in user. Role specific areas add their own guard with the roles allowed.
        element: <RequireAuth />,
        children: [at('account', () => import('@/pages/AccountPage'))],
      },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
  // The staff and admin console. It has its own layout, without the public site around it.
  {
    element: <RequireAuth roles={['admin', 'receptionist', 'dentist']} />,
    children: [
      {
        lazy: async () => ({
          Component: (await import('@/console/ConsoleLayout')).ConsoleLayout as ComponentType,
        }),
        children: [
          {
            path: 'staff',
            children: [
              at(undefined, () => import('@/console/Today'), 'TodayPage'),
              at('schedule', () => import('@/console/Schedule'), 'SchedulePage'),
              {
                element: <RequireAuth roles={['admin', 'receptionist']} />,
                children: [
                  at('patients', () => import('@/console/Patients'), 'PatientsPage'),
                  at('patients/:id', () => import('@/console/Patients'), 'PatientProfilePage'),
                  at('billing', () => import('@/console/BillingDesk'), 'BillingDeskPage'),
                  at('billing/:id', () => import('@/console/BillingDesk'), 'DeskInvoicePage'),
                ],
              },
            ],
          },
          {
            path: 'admin',
            element: <RequireAuth roles={['admin']} />,
            children: [
              { index: true, element: <Navigate to="analytics" replace /> },
              at('analytics', () => import('@/analytics/AnalyticsLayout'), 'AnalyticsLayout', [
                { index: true, element: <Navigate to="overview" replace /> },
                at('overview', () => import('@/analytics/tabs/Overview'), 'OverviewTab'),
                at('revenue', () => import('@/analytics/tabs/Revenue'), 'RevenueTab'),
                at(
                  'appointments',
                  () => import('@/analytics/tabs/Appointments'),
                  'AppointmentsTab',
                ),
                at('patients', () => import('@/analytics/tabs/Patients'), 'PatientsTab'),
                at('dentists', () => import('@/analytics/tabs/Dentists'), 'DentistsTab'),
                at('finance', () => import('@/analytics/tabs/Finance'), 'FinanceTab'),
                at('chatbot', () => import('@/analytics/tabs/Assistant'), 'AssistantTab'),
              ]),
              at('staff', () => import('@/console/admin/Staff'), 'StaffPage'),
              at('services', () => import('@/console/admin/Services'), 'ServicesPage'),
              at('dentists', () => import('@/console/admin/Dentists'), 'DentistsPage'),
              at('knowledge', () => import('@/console/admin/Knowledge'), 'KnowledgePage'),
              at('chats', () => import('@/console/admin/Chats'), 'ChatsPage'),
              at('settings', () => import('@/console/admin/Settings'), 'SettingsPage'),
              at('audit', () => import('@/console/admin/Audit'), 'AuditPage'),
            ],
          },
        ],
      },
    ],
  },
  // Sign in and registration have their own split layout, without the site header and footer.
  { ...at('/login', () => import('@/pages/LoginPage')), errorElement: <ServerErrorPage /> },
  at('/register', accounts, 'RegisterPage'),
  at('/forgot-password', accounts, 'ForgotPasswordPage'),
  at('/reset-password', accounts, 'ResetPasswordPage'),
  at('/verify-email', accounts, 'VerifyEmailPage'),
]

export const routes = buildRoutes(true)

/** Pass `hydrationData` so pages that arrive already rendered are attached to, not re-fetched. */
export const createAppRouter = () => createBrowserRouter(routes, { hydrationData: {} })
export const createTestRouter = (initialEntries: string[]) =>
  createMemoryRouter(routes, { initialEntries })
