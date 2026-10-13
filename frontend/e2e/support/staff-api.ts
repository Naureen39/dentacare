import type { Route } from '@playwright/test'

import type { FakeApi } from './fake-api'
import { DENTISTS, ROUTINE } from './fake-api'

/**
 * The staff, administration and analytics side of the stand in API: fixed answers, shaped like the
 * real ones, so the console can be driven in a browser. The business rules live in the backend
 * tests; these only let the screens be exercised for each role.
 */
const PATIENT_ID = '22222222-2222-4222-8222-222222222222'
const VISIT_IDS = ['30000000-0000-4000-8000-0000000000a1', '30000000-0000-4000-8000-0000000000a2']

/** The clinic's calendar date for an instant, as YYYY-MM-DD. */
export const clinicDay = (at = new Date()): string =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(at)

function visit(api: FakeApi, index: number) {
  const day = api.today
  const hour = index === 0 ? 14 : 16 // 10:00 and 12:00 in New York in summer
  const status =
    api.statusChanges.findLast((c) => c.id === VISIT_IDS[index])?.status ??
    (index === 0 ? 'booked' : 'confirmed')
  return {
    id: VISIT_IDS[index],
    status,
    channel: 'web',
    start: `${day}T${hour}:00:00Z`,
    end: `${day}T${hour}:45:00Z`,
    service_id: ROUTINE.id,
    service_name: ROUTINE.name,
    dentist_id: DENTISTS[index]!.id,
    dentist_name: DENTISTS[index]!.full_name,
    reason_note: 'Sore tooth',
    late_cancel: false,
    free_cancellation_until: `${day}T00:00:00Z`,
    rescheduled_from: null,
    created_at: `${day}T00:00:00Z`,
    patient_id: PATIENT_ID,
    patient_name: index === 0 ? 'Jonas Weber' : 'Amelia Hartwell',
  }
}

const meta = (asOf: string) => ({
  date_from: '2025-07-01',
  date_to: '2026-06-30',
  granularity: 'month',
  data_as_of: asOf,
  cached: false,
})

const kpi = (key: string, label: string, unit: string, value: number, previous: number) => ({
  key,
  label,
  unit,
  value,
  previous,
  change_percent:
    unit === 'percent' ? (value - previous) * 100 : ((value - previous) / previous) * 100,
  change_kind: unit === 'percent' ? 'points' : 'relative',
  higher_is_better: key !== 'no_show_rate',
  sparkline: [1, 2, 3].map((n) => ({ period: `2026-0${n}-01`, value: value * (0.8 + n / 10) })),
})

export async function handleStaff(
  api: FakeApi,
  route: Route,
  method: string,
  path: string,
  url: URL,
  body: Record<string, unknown> | undefined,
): Promise<boolean> {
  const ok = (data: unknown, status = 200) => api.json(route, data, status)
  const key = `${method} ${path}`
  const asOf = `${api.today}T05:00:00Z`
  const month = (n: number) => `2026-0${n}-01`

  // --- front desk and dentist ------------------------------------------------------------------
  const detail = path.match(/^\/staff\/appointments\/([\w-]+)$/)
  const statusChange = path.match(/^\/staff\/appointments\/([\w-]+)\/status$/)
  if (method === 'GET' && detail) {
    const index = VISIT_IDS.indexOf(detail[1] ?? '')
    await ok({
      ...visit(api, Math.max(index, 0)),
      patient_email: 'jonas@example.com',
      patient_phone: '+1 555 0100',
      clinical_note: api.role === 'dentist' ? 'Earlier note' : null,
      recent_visits: [],
    })
    return true
  }
  if (method === 'PUT' && /^\/staff\/appointments\/[\w-]+\/clinical-note$/.test(path)) {
    api.notes.push(String(body?.note))
    await ok({ note: body?.note })
    return true
  }
  if (method === 'PATCH' && statusChange) {
    api.statusChanges.push({ id: statusChange[1] ?? '', status: String(body?.status) })
    await ok(visit(api, Math.max(VISIT_IDS.indexOf(statusChange[1] ?? ''), 0)))
    return true
  }

  switch (key) {
    case 'GET /staff/alerts':
      await ok({ unconfirmed_soon: 1, new_inquiries: 2 })
      return true
    case 'GET /staff/schedule':
      await ok({
        view: 'day',
        start: api.today,
        end: api.today,
        appointments: (api.role === 'dentist' ? [0] : [0, 1]).map((i) => visit(api, i)),
      })
      return true
    case 'GET /staff/me/performance':
      await ok({ days: 30, visits: 42, revenue: '9800.00', no_shows: 2, no_show_rate: 0.045 })
      return true
    case 'GET /patients':
      await ok([
        { id: PATIENT_ID, first_name: 'Jonas', last_name: 'Weber', email: 'jonas@example.com' },
      ])
      return true
    case `GET /patients/${PATIENT_ID}`:
      await ok({
        id: PATIENT_ID,
        first_name: 'Jonas',
        last_name: 'Weber',
        email: 'jonas@example.com',
        phone: '+1 555 0100',
        date_of_birth: null,
        address: null,
        insurance_provider_id: null,
        insurance_member_id: null,
        marketing_consent: false,
        source: 'web',
        created_at: '2029-01-01T00:00:00Z',
      })
      return true
    case `GET /patients/${PATIENT_ID}/history`:
      await ok({ appointments: [visit(api, 0)], invoices: [] })
      return true
    case `GET /patients/${PATIENT_ID}/notes`:
    case `GET /patients/${PATIENT_ID}/duplicates`:
    case 'GET /billing/invoices':
    case 'GET /admin/chat/sessions':
    case 'GET /admin/kb/documents':
    case 'GET /admin/kb/intents':
    case 'GET /admin/audit-logs':
      await ok([])
      return true
    case 'GET /public/services':
      await ok([ROUTINE])
      return true

    // --- administration --------------------------------------------------------------------------
    case 'GET /admin/users':
      await ok([
        {
          id: '40000000-0000-4000-8000-000000000001',
          email: 'receptionist@example.com',
          role: 'receptionist',
          is_active: true,
          mfa_enabled: true,
          last_login_at: null,
          dentist_id: null,
          dentist_name: null,
        },
        {
          id: '11111111-1111-4111-8111-111111111111',
          email: 'admin@example.com',
          role: 'admin',
          is_active: true,
          mfa_enabled: true,
          last_login_at: null,
          dentist_id: null,
          dentist_name: null,
        },
      ])
      return true
    case 'GET /admin/settings':
      await ok({
        clinic: {
          name: 'Meridian Dental Care',
          address: '1200 Harbor View Drive',
          phone: '(555) 010-0199',
          email: 'frontdesk@meridian.test',
          timezone: 'America/New_York',
        },
        booking: {
          min_notice_hours: 2,
          max_horizon_days: 90,
          same_day_enabled: true,
          buffer_minutes: 10,
          slot_grid_minutes: 15,
          cancellation_free_hours: 24,
        },
        reminders: { hours_before: [48, 24], followup_days: 2, recall_months: 6 },
        billing: {
          tax_rate_percent: '0',
          receptionist_max_discount_percent: '10',
          monthly_revenue_target: '10000',
        },
        retention: { chat_retention_days: 90, guest_anonymize_months: 24 },
      })
      return true
    case 'GET /admin/llm/status':
      await ok({
        primary: 'groq',
        order: ['groq'],
        failover_threshold: 0.9,
        providers: {
          groq: {
            configured: true,
            model: 'model',
            utilization: 0.1,
            limits: { rpm: 30, rpd: null, tpm: null, tpd: null },
            usage: { rpm: 0, rpd: 0, tpm: 0, tpd: 0 },
          },
        },
      })
      return true

    // --- analytics ---------------------------------------------------------------------------------
    case 'GET /analytics/summary':
      await ok({
        meta: meta(asOf),
        previous_from: '2024-07-01',
        previous_to: '2025-06-30',
        kpis: [
          kpi('billed', 'Gross billed revenue', 'usd', 120000, 100000),
          kpi('collected', 'Collected revenue', 'usd', 110000, 100000),
          kpi('collection_rate', 'Collection rate', 'percent', 0.93, 0.9),
          kpi('completed', 'Completed visits', 'count', 900, 800),
          kpi('revenue_per_visit', 'Average revenue per visit', 'usd', 133, 125),
          kpi('utilization', 'Utilization', 'percent', 0.72, 0.7),
          kpi('no_show_rate', 'No show rate', 'percent', 0.05, 0.06),
          kpi('new_patients', 'New patients', 'count', 70, 60),
        ],
      })
      return true
    case 'GET /analytics/revenue/trend':
      await ok({
        meta: meta(asOf),
        points: [1, 2, 3, 4, 5, 6].map((n) => ({
          period: month(n),
          billed: String(10000 + n * 1000),
          collected: String(9000 + n * 900),
          prior_year_billed: String(9000 + n * 500),
          prior_year_collected: String(8000 + n * 400),
        })),
      })
      return true
    case 'GET /analytics/forecast/revenue':
      await ok({
        meta: meta(asOf),
        method: 'holt_winters',
        method_note: '',
        interval_level: 0.8,
        history: [],
        forecast: [7, 8, 9].map((n) => ({
          month: `2026-0${n}-01`,
          value: 15000 + n * 100,
          lower: 14000,
          upper: 16500,
        })),
      })
      return true
    case 'GET /analytics/revenue/by-service':
      await ok({
        meta: meta(asOf),
        rows: [
          {
            key: ROUTINE.id,
            label: ROUTINE.name,
            billed: '30000.00',
            collected: '29000.00',
            invoices: 250,
            share_of_billed: 1,
          },
        ],
      })
      return true
    case 'GET /analytics/appointments/status-trend':
      await ok({
        meta: meta(asOf),
        points: [1, 2, 3, 4, 5, 6].map((n) => ({
          period: month(n),
          total: 100,
          completed: 80,
          cancelled: 10,
          late_cancelled: 2,
          no_show: 5,
          open: 5,
          no_show_rate: 0.05,
          cancellation_rate: 0.1,
        })),
      })
      return true
    case 'GET /analytics/finance/ar-aging':
      await ok({
        meta: meta(asOf),
        as_of: api.today,
        total_outstanding: '3000.00',
        over_90_share: 0.1,
        buckets: [
          {
            label: '0 to 30 days',
            invoices: 10,
            insurer: '1000.00',
            patient: '500.00',
            total: '1500.00',
          },
          {
            label: 'Over 90 days',
            invoices: 1,
            insurer: '0.00',
            patient: '300.00',
            total: '300.00',
          },
        ],
      })
      return true
    case 'GET /analytics/finance/collection-rate':
      await ok({
        meta: meta(asOf),
        overall_rate: 0.9,
        average_days_to_collect: 21.4,
        points: [1, 2, 3].map((n) => ({
          period: month(n),
          billed: '10000.00',
          collected_to_date: '9000.00',
          rate: 0.9,
        })),
      })
      return true
  }
  return false
}
