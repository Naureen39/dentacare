import { CROWN, LINDQVIST, RAMAN, ROUTINE } from '@/test/booking-fixtures'
import { staffSession } from '@/test/console-fixtures'
import { json, type Handlers } from '@/test/utils'

const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString()

export const meta = (asOf: string | null = hoursAgo(3)) => ({
  date_from: '2025-07-01',
  date_to: '2026-06-30',
  granularity: 'month',
  data_as_of: asOf,
  cached: false,
})

const kpi = (
  key: string,
  label: string,
  unit: string,
  value: number,
  previous: number,
  over: Record<string, unknown> = {},
) => ({
  key,
  label,
  unit,
  value,
  previous,
  change_percent:
    unit === 'percent'
      ? (value - previous) * 100
      : previous
        ? ((value - previous) / previous) * 100
        : null,
  change_kind: unit === 'percent' ? 'points' : 'relative',
  higher_is_better: key !== 'no_show_rate',
  sparkline: [1, 2, 3].map((n) => ({ period: `2026-0${n}-01`, value: value * (0.8 + n / 10) })),
  ...over,
})

export const summary = (scale = 1, asOf?: string | null) => ({
  meta: meta(asOf),
  previous_from: '2024-07-01',
  previous_to: '2025-06-30',
  kpis: [
    kpi('billed', 'Gross billed revenue', 'usd', 120000 * scale, 100000),
    kpi('collected', 'Collected revenue', 'usd', 110000 * scale, 100000),
    kpi('collection_rate', 'Collection rate', 'percent', 0.88, 0.9),
    kpi('completed', 'Completed visits', 'count', 900 * scale, 800),
    kpi('revenue_per_visit', 'Average revenue per visit', 'usd', 133, 125),
    kpi('utilization', 'Utilization', 'percent', 0.55, 0.6),
    kpi('no_show_rate', 'No show rate', 'percent', 0.09, 0.07),
    kpi('new_patients', 'New patients', 'count', 70, 60),
  ],
})

const month = (n: number) => `2026-0${n}-01`
export const trend = {
  meta: meta(),
  points: [1, 2, 3].map((n) => ({
    period: month(n),
    billed: String(10000 + n * 1000),
    collected: String(9000 + n * 900),
    prior_year_billed: String(9000 + n * 500),
    prior_year_collected: String(8000 + n * 400),
  })),
}

export const forecast = {
  meta: meta(),
  method: 'holt_winters',
  method_note: 'Seasonal trend',
  interval_level: 0.8,
  history: [],
  forecast: [4, 5, 6].map((n) => ({
    month: month(n),
    value: 12000 + n * 100,
    lower: 11000,
    upper: 13500,
  })),
}

const row = (key: string, label: string, billed: string, invoices: number) => ({
  key,
  label,
  billed,
  collected: billed,
  invoices,
  share_of_billed: null,
})

export const status = {
  meta: meta(),
  points: [1, 2, 3].map((n) => ({
    period: month(n),
    total: 100 + n,
    completed: 80 + n,
    cancelled: 10,
    late_cancelled: 2,
    no_show: 5,
    open: 5 + n,
    no_show_rate: 0.05,
    cancellation_rate: 0.1,
  })),
}

export const serviceTrends = {
  meta: meta(),
  rows: [
    {
      key: ROUTINE.id,
      label: ROUTINE.name,
      category: 'preventive',
      billed: '30000.00',
      collected: '29000.00',
      invoices: 250,
      visits: 250,
      minutes: 11250,
      revenue_per_hour: 160,
      series: [
        { period: month(1), value: 9000 },
        { period: month(2), value: 10000 },
        { period: month(3), value: 11000 },
      ],
    },
    {
      key: CROWN.id,
      label: CROWN.name,
      category: 'restorative',
      billed: '50000.00',
      collected: '45000.00',
      invoices: 40,
      visits: 40,
      minutes: 3600,
      revenue_per_hour: 833,
      series: [
        { period: month(1), value: 15000 },
        { period: month(2), value: 16000 },
        { period: month(3), value: 19000 },
      ],
    },
  ],
}

export const leaderboard = {
  meta: meta(),
  rows: [
    {
      dentist_id: RAMAN.id,
      dentist: RAMAN.full_name,
      billed: '70000.00',
      collected: '65000.00',
      visits: 300,
      no_shows: 12,
      no_show_rate: 0.038,
      booked_hours: 800,
      available_hours: 1000,
      utilization: 0.8,
      revenue_per_visit: 233,
    },
    {
      dentist_id: LINDQVIST.id,
      dentist: LINDQVIST.full_name,
      billed: '50000.00',
      collected: '48000.00',
      visits: 250,
      no_shows: 20,
      no_show_rate: 0.074,
      booked_hours: 500,
      available_hours: 1000,
      utilization: 0.5,
      revenue_per_visit: 200,
    },
  ],
}

const aging = {
  meta: meta(),
  as_of: '2026-06-30',
  buckets: [
    {
      label: '0 to 30 days',
      invoices: 10,
      insurer: '1000.00',
      patient: '500.00',
      total: '1500.00',
    },
    { label: '31 to 60 days', invoices: 4, insurer: '800.00', patient: '200.00', total: '1000.00' },
    { label: '61 to 90 days', invoices: 2, insurer: '100.00', patient: '100.00', total: '200.00' },
    { label: 'Over 90 days', invoices: 1, insurer: '0.00', patient: '300.00', total: '300.00' },
  ],
  total_outstanding: '3000.00',
  over_90_share: 0.1,
}

const chatbot = {
  meta: meta(),
  conversations: 120,
  turns: 600,
  zero_llm_turns: 450,
  zero_llm_share: 0.75,
  resolved_without_human: 0.9,
  booking_started: 40,
  booking_slot_chosen: 30,
  booking_confirmed: 25,
  booking_conversion: 0.625,
  handoffs: 12,
  providers: [{ provider: 'groq', calls: 100, tokens: 50000, failovers: 2 }],
  failovers: 2,
  feedback_up: 30,
  feedback_down: 5,
  feedback_score: 0.857,
  tokens_per_conversation: 416,
  days: [1, 2, 3].map((n) => ({
    day: `2026-06-0${n}`,
    conversations: 10 * n,
    turns: 50 * n,
    zero_llm_turns: 40 * n,
    tokens: 1000 * n,
  })),
  unanswered: [{ question: 'do you take [email] insurance', count: 4 }],
}

export const risk = {
  meta: meta(),
  model_version: 'v3',
  model_auc: 0.74,
  base_rate: 0.08,
  note: null,
  rows: [
    {
      appointment_id: '30000000-0000-4000-8000-0000000000aa',
      start: new Date(Date.now() + 86_400_000).toISOString(),
      patient_name: 'Jonas Weber',
      service_name: ROUTINE.name,
      dentist_id: RAMAN.id,
      dentist_name: RAMAN.full_name,
      status: 'booked',
      score: 0.62,
      level: 'high',
      drivers: [{ feature: 'lead', label: 'Booked a long time ago', contribution: 0.2 }],
    },
  ],
}

/** Every analytics call, answered, so any tab can be opened. */
export function analyticsApi(
  role: 'admin' | 'receptionist' = 'admin',
  extra: Handlers = {},
): Handlers {
  return {
    ...staffSession(role),
    'GET /analytics/summary*': (_i, url) => {
      const year = new URL(url, 'http://x').searchParams.get('from')?.startsWith('2024')
      return json(summary(year ? 0.8 : 1))
    },
    'GET /analytics/revenue/trend*': { status: 200, body: trend },
    'GET /analytics/forecast/revenue*': { status: 200, body: forecast },
    'GET /analytics/revenue/by-service*': {
      status: 200,
      body: {
        meta: meta(),
        rows: [
          row(ROUTINE.id, ROUTINE.name, '30000.00', 250),
          row(CROWN.id, CROWN.name, '50000.00', 40),
        ],
      },
    },
    'GET /analytics/revenue/by-dentist*': { status: 200, body: { meta: meta(), rows: [] } },
    'GET /analytics/revenue/by-payer*': {
      status: 200,
      body: { meta: meta(), by_payer_type: [], by_provider: [] },
    },
    'GET /analytics/revenue/by-weekday*': {
      status: 200,
      body: {
        meta: meta(),
        rows: Array.from({ length: 7 }, (_, weekday) => ({
          weekday,
          billed: '1000.00',
          collected: '900.00',
          invoices: 10,
          days: 4,
        })),
      },
    },
    'GET /analytics/revenue/service-trends*': { status: 200, body: serviceTrends },
    'GET /analytics/revenue/dentist-services*': {
      status: 200,
      body: {
        meta: meta(),
        cells: [
          {
            dentist_id: RAMAN.id,
            dentist: RAMAN.full_name,
            service_id: ROUTINE.id,
            service: ROUTINE.name,
            billed: '3000.00',
          },
        ],
      },
    },
    'GET /analytics/appointments/status-trend*': { status: 200, body: status },
    'GET /analytics/appointments/heatmap*': {
      status: 200,
      body: {
        meta: meta(),
        max_appointments: 20,
        cells: [
          { weekday: 0, hour: 9, appointments: 20, no_show: 1, no_show_rate: 0.05 },
          { weekday: 1, hour: 10, appointments: 10, no_show: 0, no_show_rate: 0 },
        ],
      },
    },
    'GET /analytics/appointments/lead-time*': {
      status: 200,
      body: {
        meta: meta(),
        average_days: 9.5,
        median_days: 7,
        appointments: 100,
        buckets: [
          { label: 'Same day', appointments: 10, share: 0.1 },
          { label: '1 to 2 days', appointments: 90, share: 0.9 },
        ],
      },
    },
    'GET /analytics/appointments/channels*': {
      status: 200,
      body: {
        meta: meta(),
        rows: [
          { key: 'web', label: 'Website', appointments: 80, completed: 70, share: 0.8 },
          { key: 'staff', label: 'Front desk', appointments: 20, completed: 18, share: 0.2 },
        ],
      },
    },
    'GET /analytics/patients/new-vs-returning*': {
      status: 200,
      body: {
        meta: meta(),
        new_patients: 30,
        returning_patients: 300,
        points: [1, 2, 3].map((n) => ({
          period: month(n),
          new_patients: 10 * n,
          returning_patients: 100,
          new_visits: 10,
          returning_visits: 120,
        })),
      },
    },
    'GET /analytics/patients/retention-cohorts*': {
      status: 200,
      body: {
        meta: meta(),
        six_month_retention: 0.62,
        mature_cohorts: 1,
        cohorts: [
          {
            cohort_month: month(1),
            cohort_size: 20,
            retention: [1, 0.6, 0.5, null],
            returned_within_6_months: 0.6,
          },
        ],
      },
    },
    'GET /analytics/patients/demographics*': {
      status: 200,
      body: {
        meta: meta(),
        patients: 100,
        age_bands: [
          { key: '18 to 34', label: '18 to 34', patients: 40, share: 0.4 },
          { key: '35 to 49', label: '35 to 49', patients: 60, share: 0.6 },
        ],
        sources: [
          { key: 'web', label: 'Website', patients: 70, share: 0.7 },
          { key: 'walk_in', label: 'Walk in', patients: 30, share: 0.3 },
        ],
      },
    },
    'GET /analytics/patients/top*': () =>
      json({
        meta: meta(),
        rows: [
          {
            patient_id: '22222222-2222-4222-8222-222222222222',
            name: role === 'admin' ? 'Jonas Weber' : 'J. W.',
            lifetime_value: '9000.00',
            visits: 12,
            last_visit: '2026-05-01',
            masked: role !== 'admin',
          },
        ],
      }),
    'GET /analytics/dentists/leaderboard*': { status: 200, body: leaderboard },
    'GET /analytics/finance/ar-aging*': { status: 200, body: aging },
    'GET /analytics/finance/collection-rate*': {
      status: 200,
      body: {
        meta: meta(),
        overall_rate: 0.9,
        average_days_to_collect: 21.4,
        points: [1, 2, 3].map((n) => ({
          period: month(n),
          billed: '10000.00',
          collected_to_date: '9000.00',
          rate: 0.9,
        })),
      },
    },
    'GET /analytics/no-show/upcoming-risk*': { status: 200, body: risk },
    'GET /analytics/chatbot/summary*': { status: 200, body: chatbot },
    'POST /analytics/refresh': { status: 200, body: { refreshed: 7, failed: 0 } },
    'GET /analytics/export/csv*': () => new Response('a,b\n1,2\n', { status: 200 }),
    'GET /admin/settings': {
      status: 200,
      body: {
        clinic: { name: 'M', address: 'a', phone: 'p', email: 'e', timezone: 'America/New_York' },
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
      },
    },
    'GET /admin/llm/status': {
      status: 200,
      body: {
        primary: 'groq',
        order: ['groq'],
        failover_threshold: 0.9,
        providers: {
          groq: {
            configured: true,
            limits: { rpm: 30, rpd: null, tpm: null, tpd: 100000 },
            usage: { rpm: 0, rpd: 0, tpm: 0, tpd: 0 },
          },
        },
      },
    },
    'GET /billing/invoices*': { status: 200, body: [] },
    ...extra,
  }
}
