import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiDelete, apiFetch, apiGet, apiPatch, apiPost } from '@/lib/api-client'
import type { components } from '@/lib/api-types'

type S = components['schemas']

export type Appointment = S['StaffAppointmentOut']
export type AppointmentDetail = S['AppointmentDetail']
export type Schedule = S['ScheduleResponse']
export type Patient = S['PatientProfile']
export type PatientSummary = S['PatientSummary']
export type StaffUser = S['StaffUserOut']
export type ServiceAdmin = S['ServiceAdminOut']
export type DentistAdmin = S['DentistAdminOut']
export type ScheduleDay = S['ScheduleDay']
export type TimeOff = S['TimeOffOut']
export type Intent = S['IntentExampleOut']
export type ChatRow = S['ChatSessionRow']
export type Transcript = S['Transcript']
export type Settings = S['SettingsOut']
export type Invoice = S['InvoiceOut']
export type InvoiceRow = S['InvoiceListItem']
export type AuditEntry = S['AuditLogEntry']
export type KbSummary = S['KbDocumentSummary']
export type KbDocument = S['KbDocumentOut']
export type Status = Appointment['status']

const key = (...parts: unknown[]) => ['console', ...parts]

// --- reading and changing, in small helpers --------------------------------------------------------

function useGet<T>(path: string, queryKey: unknown[], enabled = true) {
  return useQuery({
    queryKey: key(...queryKey),
    queryFn: () => apiGet<T>(path),
    enabled,
    retry: false,
  })
}

function useChange<TIn, TOut>(run: (input: TIn) => Promise<TOut>, invalidate: unknown[][] = []) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () =>
      Promise.all(invalidate.map((k) => client.invalidateQueries({ queryKey: key(...k) }))),
  })
}

// --- schedule and appointments -----------------------------------------------------------------------

export const useSchedule = (view: 'day' | 'week', on: string, dentistId?: string) =>
  useGet<Schedule>(
    `/staff/schedule?view=${view}&on=${on}${dentistId ? `&dentist_id=${dentistId}` : ''}`,
    ['schedule', view, on, dentistId ?? 'all'],
  )

export const useAppointment = (id: string | null) =>
  useGet<AppointmentDetail>(`/staff/appointments/${id}`, ['appointment', id], Boolean(id))

export const useChangeStatus = () =>
  useChange(
    (input: { id: string; status: Status; reason?: string }) =>
      apiPatch<Appointment>(`/staff/appointments/${input.id}/status`, {
        status: input.status,
        reason: input.reason || null,
      }),
    [['schedule'], ['appointment'], ['alerts']],
  )

export const useCompleteVisit = () =>
  useChange(
    (input: { id: string; serviceIds: string[]; note?: string }) =>
      apiPost<Appointment>(`/staff/appointments/${input.id}/complete`, {
        performed_service_ids: input.serviceIds,
        clinical_note: input.note ?? null,
      }),
    [['schedule'], ['appointment'], ['performance'], ['invoices']],
  )

export const useMoveAppointment = () =>
  useChange(
    (input: { id: string; start: string; dentistId?: string }) =>
      apiPatch<Appointment>(`/staff/appointments/${input.id}/reschedule`, {
        start: input.start,
        dentist_id: input.dentistId ?? null,
      }),
    [['schedule'], ['appointment'], ['alerts']],
  )

export const useSaveNote = () =>
  useChange(
    (input: { id: string; note: string }) =>
      apiFetch(`/staff/appointments/${input.id}/clinical-note`, {
        method: 'PUT',
        body: { note: input.note },
      }),
    [['appointment']],
  )

export const useBookForPatient = () =>
  useChange(
    (input: {
      patientId: string
      serviceId: string
      dentistId: string
      start: string
      note?: string
    }) =>
      apiPost<Appointment>('/staff/appointments', {
        patient_id: input.patientId,
        service_id: input.serviceId,
        dentist_id: input.dentistId,
        start: input.start,
        reason_note: input.note || null,
      }),
    [['schedule'], ['alerts']],
  )

export const useAlerts = (enabled: boolean) =>
  useGet<S['Alerts']>('/staff/alerts', ['alerts'], enabled)

export const usePerformance = (days: number, enabled: boolean) =>
  useGet<S['Performance']>(`/staff/me/performance?days=${days}`, ['performance', days], enabled)

// --- patients ----------------------------------------------------------------------------------------------

export const usePatientSearch = (q: string, enabled = true) =>
  useGet<PatientSummary[]>(`/patients?q=${encodeURIComponent(q)}`, ['patients', q], enabled)

export const usePatient = (id: string | undefined) =>
  useGet<Patient>(`/patients/${id}`, ['patient', id], Boolean(id))

export const usePatientHistory = (id: string | undefined) =>
  useGet<S['PatientHistory']>(`/patients/${id}/history`, ['patient', id, 'history'], Boolean(id))

export const usePatientNotes = (id: string | undefined) =>
  useGet<S['PatientNoteOut'][]>(`/patients/${id}/notes`, ['patient', id, 'notes'], Boolean(id))

export const useDuplicates = (id: string | undefined) =>
  useGet<S['DuplicateCandidate'][]>(
    `/patients/${id}/duplicates`,
    ['patient', id, 'duplicates'],
    Boolean(id),
  )

export const useAddNote = (id: string) =>
  useChange(
    (body: string) => apiPost<S['PatientNoteOut']>(`/patients/${id}/notes`, { body }),
    [['patient', id, 'notes']],
  )

export const useUpdatePatient = (id: string) =>
  useChange(
    (changes: Partial<S['StaffPatientUpdate']>) => apiPatch<Patient>(`/patients/${id}`, changes),
    [['patient', id], ['patients']],
  )

export const useCreatePatient = () =>
  useChange(
    (input: { first_name: string; last_name: string; email?: string; phone?: string }) =>
      apiPost<Patient>('/patients', {
        first_name: input.first_name,
        last_name: input.last_name,
        email: input.email || null,
        phone: input.phone || null,
        source: 'walk_in',
      }),
    [['patients']],
  )

// --- billing desk -------------------------------------------------------------------------------------------

export const useInvoiceList = (params: { status?: string; openOnly?: boolean; q?: string }) => {
  const query = new URLSearchParams({ limit: '100' })
  if (params.status) query.set('status', params.status)
  if (params.openOnly) query.set('open_only', 'true')
  if (params.q) query.set('q', params.q)
  return useGet<InvoiceRow[]>(`/billing/invoices?${query}`, ['invoices', query.toString()])
}

export const useDeskInvoice = (id: string | undefined) =>
  useGet<Invoice>(`/billing/invoices/${id}`, ['invoice', id], Boolean(id))

export const useInvoiceAction = (id: string) =>
  useChange(
    (input: { action: 'issue' | 'void' | 'pay'; body?: unknown }) =>
      apiPost<Invoice>(
        `/billing/invoices/${id}/${input.action === 'pay' ? 'payments' : input.action}`,
        input.body,
      ),
    [['invoice', id], ['invoices']],
  )

export const fetchInvoicePdf = (id: string) =>
  apiFetch<Blob>(`/billing/invoices/${id}/pdf`, { as: 'blob' })

// --- administration ----------------------------------------------------------------------------------------

export const useStaffUsers = () => useGet<StaffUser[]>('/admin/users', ['users'])

export const useCreateStaff = () =>
  useChange(
    (input: { email: string; role: string; full_name?: string; specialty?: string }) =>
      apiPost<StaffUser>('/admin/users', input),
    [['users'], ['dentists']],
  )

export const useUpdateStaff = () =>
  useChange(
    (input: { id: string; is_active: boolean }) =>
      apiPatch<StaffUser>(`/admin/users/${input.id}`, { is_active: input.is_active }),
    [['users']],
  )

export const useChangeRole = () =>
  useChange(
    (input: { id: string; role: string }) =>
      apiPatch(`/admin/users/${input.id}/role`, { role: input.role }),
    [['users']],
  )

export const useResetMfa = () =>
  useChange((id: string) => apiPost(`/admin/users/${id}/reset-mfa`), [['users']])

export const useAdminServices = () => useGet<ServiceAdmin[]>('/admin/services', ['services'])

export const useServiceChange = () =>
  useChange(
    (input: { path: string; method: 'POST' | 'PATCH' | 'DELETE'; body?: unknown }) =>
      apiFetch<ServiceAdmin | undefined>(`/admin/services${input.path}`, {
        method: input.method,
        body: input.body,
      }),
    [['services']],
  )

export const useAdminDentists = () => useGet<DentistAdmin[]>('/admin/dentists', ['dentists'])

export const useUpdateDentist = () =>
  useChange(
    (input: { id: string; changes: Partial<S['DentistUpdate']> }) =>
      apiPatch<DentistAdmin>(`/admin/dentists/${input.id}`, input.changes),
    [['dentists']],
  )

export const useDentistHours = (id: string | undefined) =>
  useGet<ScheduleDay[]>(`/admin/dentists/${id}/schedule`, ['hours', id], Boolean(id))

export const useSaveHours = (id: string) =>
  useChange(
    (days: ScheduleDay[]) =>
      apiFetch<ScheduleDay[]>(`/admin/dentists/${id}/schedule`, { method: 'PUT', body: { days } }),
    [['hours', id]],
  )

export const useTimeOff = (id: string | undefined) =>
  useGet<TimeOff[]>(`/admin/dentists/${id}/time-off`, ['time-off', id], Boolean(id))

export const useAddTimeOff = (id: string) =>
  useChange(
    (input: { starts_at: string; ends_at: string; reason: string; note?: string }) =>
      apiPost<S['TimeOffCreated']>(`/admin/dentists/${id}/time-off`, input),
    [['time-off', id]],
  )

export const useRemoveTimeOff = (id: string) =>
  useChange((timeOffId: string) => apiDelete(`/admin/time-off/${timeOffId}`), [['time-off', id]])

export const useKbDocuments = () => useGet<KbSummary[]>('/admin/kb/documents', ['kb'])

export const useKbDocument = (slug: string | null) =>
  useGet<KbDocument>(`/admin/kb/documents/${slug}`, ['kb', slug], Boolean(slug))

export const useKbSave = () =>
  useChange(
    (input: { slug: string; title: string; category: string; body: string; isNew: boolean }) =>
      input.isNew
        ? apiPost<KbDocument>('/admin/kb/documents', {
            slug: input.slug,
            title: input.title,
            category: input.category,
            body: input.body,
            reembed: true,
          })
        : apiFetch<KbDocument>(`/admin/kb/documents/${input.slug}`, {
            method: 'PUT',
            body: { title: input.title, category: input.category, body: input.body, reembed: true },
          }),
    [['kb']],
  )

export const useReembed = () =>
  useChange((slug: string) => apiPost<KbDocument>(`/admin/kb/documents/${slug}/reembed`), [['kb']])

export const useKbSearch = (q: string) =>
  useGet<S['SearchHitOut'][]>(
    `/admin/kb/search?q=${encodeURIComponent(q)}`,
    ['kb-search', q],
    q.trim().length > 2,
  )

export const useIntents = () => useGet<Intent[]>('/admin/kb/intents', ['intents'])

export const useIntentChange = () =>
  useChange(
    (input: { add?: { intent: string; text: string }; remove?: string }) =>
      input.add
        ? apiPost<Intent>('/admin/kb/intents', input.add)
        : apiDelete(`/admin/kb/intents/${input.remove}`),
    [['intents']],
  )

export const useChatSessions = (feedback: string) =>
  useGet<ChatRow[]>(`/admin/chat/sessions?feedback=${feedback}&limit=50`, ['chats', feedback])

export const useTranscript = (id: string | null) =>
  useGet<Transcript>(`/admin/chat/sessions/${id}`, ['chat', id], Boolean(id))

export const useSettings = () => useGet<Settings>('/admin/settings', ['settings'])

export const useSaveSettings = () =>
  useChange(
    (body: Partial<Pick<Settings, 'booking' | 'reminders' | 'billing' | 'retention'>>) =>
      apiFetch<Settings>('/admin/settings', { method: 'PUT', body }),
    [['settings']],
  )

export interface LlmStatus {
  primary: string
  order: string[]
  failover_threshold: number
  providers: Record<
    string,
    {
      configured: boolean
      model?: string
      cooldown_seconds?: number
      limits?: Record<'rpm' | 'rpd' | 'tpm' | 'tpd', number | null>
      usage?: Record<'rpm' | 'rpd' | 'tpm' | 'tpd', number>
      utilization?: number
      busiest_limit?: string | null
      breaker?: { state?: string }
    }
  >
}

export const useLlmStatus = () => useGet<LlmStatus>('/admin/llm/status', ['llm'])

export const useLlmChange = () =>
  useChange(
    (input: {
      primary?: string
      limits?: { provider: string; values: Record<string, number | null> }
    }) =>
      input.primary
        ? apiFetch('/admin/llm/primary', { method: 'PUT', body: { provider: input.primary } })
        : apiFetch(`/admin/llm/limits/${input.limits?.provider}`, {
            method: 'PUT',
            body: input.limits?.values,
          }),
    [['llm']],
  )

export interface AuditFilters {
  action?: string
  since?: string
  until?: string
  offset: number
}

const auditQuery = (f: Omit<AuditFilters, 'offset'>) => {
  const q = new URLSearchParams()
  if (f.action) q.set('action', f.action)
  if (f.since) q.set('since', new Date(`${f.since}T00:00:00`).toISOString())
  if (f.until) q.set('until', new Date(`${f.until}T23:59:59`).toISOString())
  return q
}

export const PAGE = 25

export const useAuditLogs = (f: AuditFilters) => {
  const q = auditQuery(f)
  q.set('limit', String(PAGE))
  q.set('offset', String(f.offset))
  return useGet<AuditEntry[]>(`/admin/audit-logs?${q}`, ['audit', q.toString()])
}

export const fetchAuditCsv = (f: Omit<AuditFilters, 'offset'>) =>
  apiFetch<Blob>(`/admin/audit-logs/export.csv?${auditQuery(f)}`, { as: 'blob' })

// --- the catalogue, for pickers ----------------------------------------------------------------------------

export const useAllDentists = () =>
  useQuery({
    queryKey: ['public', 'all-dentists'],
    queryFn: () => apiGet<S['DentistOut'][]>('/public/dentists', { auth: false }),
    staleTime: 5 * 60_000,
    retry: false,
  })

export const useAllServices = () =>
  useQuery({
    queryKey: ['public', 'live-services'],
    queryFn: () => apiGet<S['ServiceOut'][]>('/public/services', { auth: false }),
    staleTime: 5 * 60_000,
    retry: false,
  })
