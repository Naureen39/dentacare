// Load scenarios for the clinic API at 50 virtual users each. They run one after the other so
// each is measured on its own:
//
//   availability   public reads: services, dentists, openings                (read:  p95 < 300 ms)
//   booking        hold a time, then book it for a patient                   (write: p95 < 600 ms)
//   analytics      the dashboard's figures over 24 months, with changing filters (read: p95 < 300 ms)
//   chat           turns the assistant answers without a language model     (p95 < 150 ms)
//
// Run `perf/run.sh`, which starts a test server and passes the settings below.
//
//   BASE_URL     where the API is (default http://127.0.0.1:8199)
//   ADMIN_TOKEN  an administrator's access token (needed by booking and analytics)
//   DURATION     length of each scenario (default 30s)
//   THINK        seconds each virtual user pauses between actions, as a person does (default 1;
//                0 turns the test into a saturation test that measures throughput, not latency)
import http from 'k6/http'
import { check, fail, sleep } from 'k6'
import { Counter } from 'k6/metrics'

const BASE = __ENV.BASE_URL || 'http://127.0.0.1:8199'
const API = `${BASE}/api/v1`
const TOKEN = __ENV.ADMIN_TOKEN || ''
const DURATION = __ENV.DURATION || '30s'
const THINK = Number(__ENV.THINK === undefined ? 1 : __ENV.THINK)
const think = () => THINK > 0 && sleep(THINK * (0.5 + Math.random()))
const GAP = 8 // seconds between scenarios, so one does not run into the next
const length = Number(DURATION.replace('s', ''))
const at = (n) => `${n * (length + GAP)}s`

const bookings = new Counter('bookings_made')
const clashes = new Counter('bookings_clashed')

const scenario = (exec, n) => ({
  executor: 'constant-vus',
  vus: 50,
  duration: DURATION,
  startTime: at(n),
  exec,
  gracefulStop: '5s',
})

export const options = {
  scenarios: {
    availability: scenario('availability', 0),
    booking: scenario('booking', 1),
    analytics: scenario('analytics', 2),
    chat: scenario('chat', 3),
  },
  thresholds: {
    'http_req_duration{scenario:availability}': ['p(95)<300'],
    'http_req_duration{scenario:booking,kind:write}': ['p(95)<600'],
    'http_req_duration{scenario:analytics}': ['p(95)<300'],
    'http_req_duration{scenario:chat,kind:turn}': ['p(95)<150'],
    'http_req_failed{scenario:availability}': ['rate<0.01'],
    'http_req_failed{scenario:analytics}': ['rate<0.01'],
    'http_req_failed{scenario:chat}': ['rate<0.01'],
  },
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'max'],
}

const json = { headers: { 'Content-Type': 'application/json' } }
const auth = { headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${TOKEN}` } }
const ymd = (d) => d.toISOString().slice(0, 10)
const addDays = (d, n) => new Date(d.getTime() + n * 86_400_000)

export function setup() {
  const services = http.get(`${API}/public/services`).json()
  const dentists = http.get(`${API}/public/dentists`).json()
  const service = services.find((s) => s.code === 'SV02') || services[0]
  if (!service) fail('the server has no services; seed the database first')

  // A month of openings, one per start time, for the booking scenario to spread over.
  const from = addDays(new Date(), 3)
  const days = http
    .get(`${API}/public/availability?service_id=${service.id}&from=${ymd(from)}&to=${ymd(addDays(from, 27))}`)
    .json()
  const slots = days.flatMap((d) => d.slots)

  let patients = []
  if (TOKEN) {
    patients = http.get(`${API}/patients?q=a`, auth).json().map((p) => p.id)
  }
  return { service: service.id, dentists: dentists.map((d) => d.id), slots, patients }
}

export function availability(data) {
  const from = addDays(new Date(), 1 + (__ITER % 20))
  const to = addDays(from, 6)
  const dentist = __ITER % 3 === 0 ? `&dentist_id=${data.dentists[__ITER % data.dentists.length]}` : ''
  const reads = http.batch([
    ['GET', `${API}/public/services`, null, { tags: { kind: 'read' } }],
    ['GET', `${API}/public/dentists`, null, { tags: { kind: 'read' } }],
    [
      'GET',
      `${API}/public/availability?service_id=${data.service}&from=${ymd(from)}&to=${ymd(to)}${dentist}`,
      null,
      { tags: { kind: 'read' } },
    ],
  ])
  check(reads[2], { 'openings returned': (r) => r.status === 200 })
  think()
}

export function booking(data) {
  if (!TOKEN || data.slots.length === 0) fail('booking needs ADMIN_TOKEN and openings')
  // Each virtual user works through its own part of the month, so clashes are rare and real.
  const slot = data.slots[(__VU * 997 + __ITER * 31) % data.slots.length]
  const hold = http.post(
    `${API}/public/hold`,
    JSON.stringify({ service_id: data.service, dentist_id: slot.dentist_id, start: slot.start }),
    { ...json, tags: { kind: 'write', step: 'hold' }, responseCallback: http.expectedStatuses(201, 409) },
  )
  if (hold.status !== 201) {
    clashes.add(1)
    think()
    return
  }
  const made = http.post(
    `${API}/staff/appointments`,
    JSON.stringify({
      patient_id: data.patients[(__VU + __ITER) % data.patients.length],
      service_id: data.service,
      dentist_id: slot.dentist_id,
      start: slot.start,
    }),
    { ...auth, tags: { kind: 'write', step: 'book' }, responseCallback: http.expectedStatuses(201, 409) },
  )
  if (made.status === 201) bookings.add(1)
  else clashes.add(1)
  think()
}

const FIGURES = [
  '/summary',
  '/revenue/trend',
  '/revenue/by-service',
  '/revenue/by-dentist',
  '/revenue/by-payer',
  '/appointments/status-trend',
  '/appointments/heatmap',
  '/patients/new-vs-returning',
  '/patients/retention-cohorts',
  '/finance/ar-aging',
  '/finance/collection-rate',
  '/forecast/revenue',
  '/revenue/service-trends',
  '/dentists/leaderboard',
]

export function analytics(data) {
  const end = addDays(new Date(), -1)
  const start = addDays(end, -729) // 24 months
  const grains = ['month', 'week', 'quarter']
  // Every few iterations the filters change, so some answers are worked out and some are stored.
  const dentist = __ITER % 4 === 0 ? `&dentist_id=${data.dentists[__ITER % data.dentists.length]}` : ''
  const query = `from=${ymd(start)}&to=${ymd(end)}&granularity=${grains[Math.floor(__ITER / 5) % 3]}${dentist}`
  const path = FIGURES[(__VU + __ITER) % FIGURES.length]
  const res = http.get(`${API}/analytics${path}?${query}`, { ...auth, tags: { kind: 'read', figure: path } })
  check(res, { 'figure returned': (r) => r.status === 200 })
  think()
}

const TURNS = [
  { choice: { kind: 'action', value: 'hours', label: 'Opening hours' } },
  { choice: { kind: 'action', value: 'prices', label: 'Prices' } },
  { text: 'what are your opening hours' },
  { text: 'where are you located' },
  { text: 'thank you' },
]

export function chat() {
  // The conversation is opened once per virtual user and then used for every turn.
  if (!globalThis.session) {
    const opened = http.post(`${API}/chat/sessions`, null, { tags: { kind: 'open' } })
    check(opened, { 'chat opened': (r) => r.status === 201 })
    globalThis.session = opened.json()
  }
  const turn = TURNS[__ITER % TURNS.length]
  const res = http.post(`${API}/chat/sessions/${globalThis.session.session_id}/messages`, JSON.stringify(turn), {
    headers: { 'Content-Type': 'application/json', 'X-Chat-Token': globalThis.session.session_token },
    tags: { kind: 'turn' },
  })
  check(res, {
    'turn answered': (r) => r.status === 200,
    'no language model': (r) => r.json('route') !== 'llm',
  })
  think()
}
