import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { Filters } from '@/analytics/filters'
import { apiFetch, apiGet, apiPost } from '@/lib/api-client'
import type { components } from '@/lib/api-types'

type S = components['schemas']

export type Summary = S['Summary']
export type Kpi = S['Kpi']
export type RevenueTrend = S['RevenueTrend']
export type Breakdown = S['RevenueBreakdown']
export type ByPayer = S['ByPayer']
export type StatusTrend = S['StatusTrend']
export type Heatmap = S['Heatmap']
export type LeadTime = S['LeadTime']
export type NewVsReturning = S['NewVsReturning']
export type Retention = S['RetentionCohorts']
export type ArAging = S['ArAging']
export type Collection = S['CollectionRate']
export type Forecast = S['RevenueForecast']
export type Risk = S['UpcomingRisk']
export type Chatbot = S['ChatbotSummary']
export type Weekdays = S['WeekdayRevenue']
export type ServiceTrends = S['ServiceTrends']
export type DentistServices = S['DentistServiceMatrix']
export type Leaderboard = S['Leaderboard']
export type Demographics = S['Demographics']
export type TopPatients = S['TopPatients']
export type Channels = S['Channels']

/** The parts of the filters the server understands. */
export type Scope = Pick<Filters, 'from' | 'to' | 'granularity' | 'dentist' | 'service' | 'payer'>

export function query(scope: Scope, extra: Record<string, string> = {}): string {
  const q = new URLSearchParams({
    from: scope.from,
    to: scope.to,
    granularity: scope.granularity,
    ...extra,
  })
  if (scope.dentist) q.set('dentist_id', scope.dentist)
  if (scope.service) q.set('service_id', scope.service)
  if (scope.payer) q.set('payer_type', scope.payer)
  return q.toString()
}

/**
 * One figure from the analytics API. Earlier data stays on screen while a new filter loads, so
 * changing a filter never blanks the page, and answers are kept for five minutes.
 */
export function useFigure<T>(
  path: string,
  scope: Scope,
  extra?: Record<string, string>,
  enabled = true,
) {
  const q = query(scope, extra)
  return useQuery({
    queryKey: ['analytics', path, q],
    queryFn: () => apiGet<T>(`/analytics${path}?${q}`),
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
    retry: false,
    enabled,
  })
}

export const useSummary = (s: Scope, enabled = true) =>
  useFigure<Summary>('/summary', s, undefined, enabled)
export const useTrend = (s: Scope, enabled = true) =>
  useFigure<RevenueTrend>('/revenue/trend', s, undefined, enabled)
export const useByService = (s: Scope) => useFigure<Breakdown>('/revenue/by-service', s)
export const useByDentist = (s: Scope) => useFigure<Breakdown>('/revenue/by-dentist', s)
export const useByPayer = (s: Scope) => useFigure<ByPayer>('/revenue/by-payer', s)
export const useStatusTrend = (s: Scope) => useFigure<StatusTrend>('/appointments/status-trend', s)
export const useHeatmap = (s: Scope) => useFigure<Heatmap>('/appointments/heatmap', s)
export const useLeadTime = (s: Scope) => useFigure<LeadTime>('/appointments/lead-time', s)
export const useChannels = (s: Scope) => useFigure<Channels>('/appointments/channels', s)
export const useNewVsReturning = (s: Scope) =>
  useFigure<NewVsReturning>('/patients/new-vs-returning', s)
export const useRetention = (s: Scope) => useFigure<Retention>('/patients/retention-cohorts', s)
export const useDemographics = (s: Scope) => useFigure<Demographics>('/patients/demographics', s)
export const useTopPatients = (s: Scope) => useFigure<TopPatients>('/patients/top', s)
export const useArAging = (s: Scope) => useFigure<ArAging>('/finance/ar-aging', s)
export const useCollection = (s: Scope) => useFigure<Collection>('/finance/collection-rate', s)
export const useForecast = (s: Scope, enabled = true) =>
  useFigure<Forecast>('/forecast/revenue', s, undefined, enabled)
export const useRisk = (s: Scope) => useFigure<Risk>('/no-show/upcoming-risk', s)
export const useChatbot = (s: Scope) => useFigure<Chatbot>('/chatbot/summary', s)
export const useWeekdays = (s: Scope) => useFigure<Weekdays>('/revenue/by-weekday', s)
export const useServiceTrends = (s: Scope, enabled = true) =>
  useFigure<ServiceTrends>('/revenue/service-trends', s, undefined, enabled)
export const useDentistServices = (s: Scope) =>
  useFigure<DentistServices>('/revenue/dentist-services', s)
export const useLeaderboard = (s: Scope) => useFigure<Leaderboard>('/dentists/leaderboard', s)

/** Download a table as CSV. The server applies the same filters and permissions as the screen. */
export const fetchCsv = (dataset: string, scope: Scope) =>
  apiFetch<Blob>(`/analytics/export/csv?${query(scope, { dataset })}`, { as: 'blob' })

export function useRefreshViews() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => apiPost<S['RefreshResult']>('/analytics/refresh'),
    onSuccess: () => client.invalidateQueries({ queryKey: ['analytics'] }),
  })
}

export function useSendReminder() {
  return useMutation({
    mutationFn: (appointmentId: string) =>
      apiPost<{ message: string }>(`/staff/appointments/${appointmentId}/remind`),
  })
}
