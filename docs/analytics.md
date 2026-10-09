# Analytics

Backend for the dashboards: materialized views, the `/analytics` endpoints, the revenue
forecast and the no show model. Metric definitions are in [metrics.md](metrics.md).

## Demo data

`backend/scripts/generate_data.py` simulates a clinic and `backend/scripts/seed.py` loads it.
The same seed always gives the same data.

```bash
cd backend
uv run python -m scripts.seed            # empty database
uv run python -m scripts.seed --reset    # replace existing clinic data
uv run python -m scripts.seed --csv      # also write CSV copies to data/generated/
```

History covers 24 whole calendar months plus the days of the current month before today, with
bookings for the next 30 days. A second run without `--reset` stops, because a marker row records
that the data is loaded. The script prints four development accounts with random passwords once.

| Target in the plan | Result with the default seed |
|---|---|
| About 4,500 patients, 7 dentists, 14 services | 4,500, 7, 14 |
| 18,000 to 25,000 appointments | about 21,000 |
| About 82 percent completed, 7 to 9 percent cancelled | 83 / 8 percent |
| 8 to 11 percent no shows | about 9 percent of visits, 9.3 percent of attended visits |
| Growth of 6 to 10 percent a year, price rise of 4 percent in month 13 | about 8 to 10 percent, 4 percent |
| Strong fourth quarter, slow July and August | present, see `tests/analytics/test_generator.py` |
| 58 percent insured, insurer payments after 14 to 45 days | 58 percent, 14 to 45 days |

Two things differ from the plan and are worth knowing:

- The no show reference dataset from Kaggle needs an account, so it was **not** used. The
  probabilities follow the rates in the plan and the drivers it names, and the model is validated
  on the generated data only. Its AUC therefore shows the model can recover the planted drivers,
  not how it would do on a real clinic.
- Average utilization is about 48 percent. The simulated schedules have more capacity than the
  simulated demand, which keeps every visit placeable. A real clinic usually runs fuller.

## Materialized views

Created by migration `0009`, refreshed every night at 03:00 by the worker and on demand by
`POST /api/v1/analytics/refresh` (administrators). Refresh is concurrent where the view allows,
so dashboards stay readable.

| View | One row per | Used for |
|---|---|---|
| `mv_daily_revenue` | day, dentist, service, payer type | billed, collected, collection rate, breakdowns |
| `mv_monthly_revenue` | month, dentist, service, payer type | forecast history, reconciliation |
| `mv_service_mix` | day, dentist, service | completed visits and minutes by service |
| `mv_dentist_performance` | day, dentist, service | statuses, no shows, cancellations |
| `mv_utilization_daily` | day, dentist | booked and available minutes |
| `mv_hourly_heatmap` | day, hour, dentist | weekday by hour heatmap |
| `mv_payer_mix` | day, insurer or self pay | billed and collected by insurer |
| `mv_ar_aging` | open invoice | receivables |
| `mv_cohort_retention` | cohort month, month offset | retention grid |
| `mv_chatbot_daily` | day | chatbot summary |

Every response carries `meta.data_as_of`, the time of the last refresh, so the interface can show
a staleness badge. Everything else is read live from the base tables.

## Endpoints

All under `/api/v1/analytics`, all accept `from`, `to`, `granularity` (day, week, month, quarter),
`dentist_id`, `service_id` and `payer_type`. Dates default to the last 365 days ending yesterday,
and a request may span at most 1,100 days. `as_of` makes the server treat another date as today,
which the tests use to get repeatable numbers.

| Path | What it returns | Who |
|---|---|---|
| `/summary` | KPI cards: value, previous period, change, sparkline | admin; dentist (own); receptionist (operational cards only) |
| `/revenue/trend` | billed and collected per bucket with the prior year | admin; dentist (own) |
| `/revenue/by-service`, `/revenue/by-payer` | breakdowns | admin; dentist (own, without insurer detail) |
| `/revenue/by-dentist` | breakdown by dentist | admin |
| `/appointments/status-trend`, `/appointments/heatmap`, `/appointments/lead-time` | outcomes, busy hours, booking lead time | admin, receptionist, dentist (own) |
| `/patients/new-vs-returning` | new and returning patients and visits | admin, receptionist, dentist (own) |
| `/patients/retention-cohorts` | cohort grid and 6 month retention | admin |
| `/finance/ar-aging`, `/finance/collection-rate` | receivables, collection by cohort | admin |
| `/forecast/revenue` | next three months with an 80 percent interval | admin |
| `/no-show/upcoming-risk` | next seven days with a score and top three reasons | admin, receptionist, dentist (own) |
| `/chatbot/summary` | conversations, zero model share, funnel, tokens by provider, failovers, feedback | admin, receptionist |
| `/export/csv?dataset=` | any table view as CSV, same filters and permissions | as the view |
| `POST /refresh` | refresh the views now | admin |

Responses are cached in Redis for five minutes. The key holds the endpoint, the filters, the
date and the caller's role and dentist, so one role's figures are never served to another. A
refresh clears every stored response. CSV cells that begin with `=`, `+`, `-` or `@` get a
leading apostrophe so a spreadsheet does not run them. Exports and risk list views are audited.

## Forecast

Holt-Winters (statsmodels) with additive trend and seasonality on monthly collected revenue when
there are 24 or more complete months; otherwise a seasonal naive or naive method, and the
response says which. The interval is simulated and its spread is corrected for the number of
parameters estimated from a short history. A test checks that the interval covers about 80
percent of outcomes in repeated simulations.

## No show model

```bash
cd backend
uv run python -m scripts.train_no_show
```

Trains LightGBM on the first 18 months of finished visits and tests it on the later ones. The
script prints AUC, precision in the top decile, the base rate, Brier score, a calibration table
and feature importance, saves the model with `joblib` under `MODEL_DIR`, and records a row in
`model_registry` with the version, SHA-256 checksum, metrics and feature list. The newest model
becomes the active one. Loading verifies the checksum first, because `joblib` files are pickles.

With the default seed the test period gives an AUC of about 0.75, a top decile precision of
about 36 percent against a base rate of about 10 percent, and a calibration error under 1
percent. Retrain after significant new data; the nightly job at 03:15 scores the appointments of
the next seven days with the active model and stores the score and reasons in
`appointment_risk`. The endpoint scores any upcoming appointment that has no score yet.

Features are built so that nothing from after booking leaks in: earlier no shows, late
cancellations and completed visits count only if they had happened by the time the appointment
was created, and confirmation counts only if made a day or more before the visit. Tests rewrite
the later history of a patient and check that earlier appointments keep identical features.
