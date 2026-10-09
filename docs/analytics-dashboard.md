# Analytics dashboard

`/admin/analytics`, for administrators. Seven tabs (Overview, Revenue, Appointments, Patients,
Dentists and services, Finance, Assistant), all driven by the figures the API already serves from
the materialized views (see [analytics.md](analytics.md) and [metrics.md](metrics.md)).
Code: `frontend/src/analytics`.

## Controls

Date range presets (30 days, quarter to date, year to date, 12 and 24 months, custom), grouping
(day, week, month, quarter), a comparison (previous period, same period last year, none), dentist,
service and payer filters. Everything is in the address, so a view can be shared and the back button
works. A range ends yesterday, because figures are complete up to then.
"Same period last year" asks for the summary again with the dates moved back 365 days.

Each chart has "Show data" (the same numbers as a table, also read by screen readers, the picture is
hidden from them) and "Save picture" (PNG). "Export CSV" downloads the tables of the current tab
with the same filters and permissions. The page says when the views were last refreshed and shows an
"Out of date" badge after 36 hours; "Refresh figures" rebuilds them now.

## Charts and where the numbers come from

Charts are drawn with Apache ECharts in one shared style, loaded only on this page. The functions in
`options.ts` turn API data into chart options and are unit tested.

- Month over month change: revenue of the latest complete month against the one before, split into
  volume (more or fewer invoices), mix (a shift toward dearer or cheaper services) and price,
  computed from the services' invoice counts; the three parts add up exactly to the change.
- Year to date against target: collected revenue so far against the monthly target in Settings
  multiplied by the months gone.
- The booking funnel is Booked, Not cancelled, Completed. Whether a visit was confirmed is not kept
  as a count by the views, so confirmed is not a stage.
- "Revenue per chair hour" stands in for service profitability, because costs are not recorded.
- Receptionists, if given access later, see top patients as initials.

New endpoints for the dashboard: revenue by weekday, service trends (with a series for the ten
leading services), dentist by service, dentist leaderboard, age and source of patients, top patients,
booking channels, average days to collect (on collection rate), and per day and unanswered-question
data on the assistant summary. `POST /staff/appointments/{id}/remind` sends the visit reminder now.

## Checks

- `backend/tests/analytics/test_dashboard_numbers.py` compares each new figure with SQL written
  separately on the base tables for three date ranges, and checks access and CSV export.
- `frontend/src/analytics/logic.test.ts` and `analytics.test.tsx` check the maths, the options sent to
  the charts, the filters, comparisons and each tab.
- `uv run python -m scripts.benchmark_dashboard` times the dashboard against the seeded database
  (24 months, about 21,000 visits and 4,500 patients). On the development machine, with connections
  open, the slowest tab loaded in about 0.3 seconds and a repeated view in 15 milliseconds
  (limits: 2.5 seconds and 0.8 seconds). That is the server only; it does not include drawing.
  On Windows with Docker, use `127.0.0.1` rather than `localhost` for Redis: resolving `localhost`
  added about two seconds to each new connection.
