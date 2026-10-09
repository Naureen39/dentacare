import { useOutletContext } from 'react-router-dom'

import type { Filters } from '@/analytics/filters'

export interface AnalyticsContext {
  filters: Filters
}

/** The filters chosen on the analytics page, for the tab being shown. */
export const useAnalytics = () => useOutletContext<AnalyticsContext>()

export const tabs = [
  { to: 'overview', label: 'Overview' },
  { to: 'revenue', label: 'Revenue' },
  { to: 'appointments', label: 'Appointments' },
  { to: 'patients', label: 'Patients' },
  { to: 'dentists', label: 'Dentists and services' },
  { to: 'finance', label: 'Finance' },
  { to: 'chatbot', label: 'Assistant' },
] as const
