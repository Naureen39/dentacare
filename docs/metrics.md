# Metric definitions

This page is the single source of truth for every number on the analytics dashboards. The code
that computes them is in `backend/app/analytics/service.py`, the materialized views are created
by migration `0009`, and `backend/tests/analytics_golden` checks each definition against a tiny
clinic whose figures were worked out by hand.

## Conventions

- **Days are clinic days.** A timestamp belongs to the calendar day in the clinic's own time zone
  (`CLINIC_TZ`, default America/New_York), not to the UTC day. A 23:30 payment on 1 March in New
  York is a 1 March payment. The views use the SQL function `clinic_date(timestamptz)`; changing
  the time zone later means recreating the views.
- **Money** is US dollars with two decimals. Voided and draft invoices are never counted.
- **Rates** are fractions between 0 and 1 in the API (`0.094` is 9.4 percent). A change in a rate
  is reported in percentage points; a change in an amount or a count is a relative percentage.
- **Previous period** is the period of the same length immediately before the selected one.
- **Prior year** is the same dates one year earlier.

## Revenue

| Metric | Definition |
|---|---|
| Gross billed revenue | Sum of invoice totals, by the day the invoice was issued. |
| Collected revenue | Sum of payments, by the day the payment was made. |
| Collection rate | Everything ever paid on invoices issued in the period, divided by what those invoices billed. It follows a cohort of invoices, so it is below 100 percent for recent periods whose insurers have not paid yet. |
| Average revenue per visit | Gross billed revenue divided by completed visits in the same period. |

Billing is split by who owes it. The **insurer's share** of an invoice is its `insurance_expected`
(never more than the total); the **patient's share** is the rest. A payer filter therefore applies
to billed amounts (the share) and to collected amounts (who paid). Revenue is attributed to the
dentist and service of the appointment the invoice belongs to.

Collected and billed revenue are different cuts of time, so collected can exceed billed in a
period when old invoices are paid.

## Appointments

| Metric | Definition |
|---|---|
| Completed visits | Appointments with status completed, by the day of the visit. |
| No show rate | no_show divided by (completed + no_show). Cancelled visits are left out because the outcome was not observed. |
| Cancellation rate | cancelled divided by all appointments scheduled for the period. |
| Late cancellation | A cancellation inside the free cancellation window (24 hours by default). |
| Utilization | Booked minutes divided by available schedule minutes. |
| Lead time | Days between booking creation and the appointment start, for every appointment in the period. |

**Booked minutes** are the length of appointments that occupy the schedule: booked, confirmed,
checked in or completed. No shows and cancellations free their time. **Available minutes** come
from each dentist's weekly template (opening hours minus the lunch break), minus schedule
exceptions such as leave and holidays, counted from the day the dentist joined. A service filter
does not apply to utilization, because a dentist's time is not divided by service.

The **weekday by hour heatmap** counts non-cancelled appointments by the local weekday and the
hour the appointment starts, with the no show rate of each cell.

## Patients

| Metric | Definition |
|---|---|
| New patient | A patient whose first completed visit is in the period and whose record was created after the data begins. |
| Returning patient | A patient with a completed visit in the period who is not a new patient in it. |
| 6 month retention | The share of a cohort with another completed visit within 210 days (6 months plus a month of grace for scheduling) of the first one. Reported only for cohorts at least 241 days old. |
| Cohort retention | For patients whose first completed visit was in a month, the share with a completed visit in each later calendar month. |
| Patient lifetime value | Collected revenue per patient to date (cumulative payments on that patient's invoices). Defined here; the figure appears on the patient record screen in the staff console phase. |
| Net new patients | New patients in the period. Patients are not deactivated, so no losses are subtracted. The summary reports it as new patients. |

Patients who were already in the practice when the data begins have an unknown earlier history, so
they are never counted as new, and they are left out of the cohort grid.

## Receivables

**Accounts receivable aging** lists issued or partly paid invoices with a balance, grouped by days
since issue as of the selected date: 0 to 30, 31 to 60, 61 to 90, over 90. A balance is split into
what the insurer still owes (its expected share less insurer payments) and what the patient still
owes (their share less patient payments). Views refresh nightly, so balances are as of the last
refresh and the aging is recomputed for the selected date.

## Forecast

The forecast covers collected revenue for the next three months with an 80 percent interval.

- With 24 or more complete months, Holt-Winters exponential smoothing (additive trend, additive
  seasonality, period 12). The interval is simulated from the model after correcting its spread
  for the number of parameters estimated from so few points.
- With 12 to 23 months, each month repeats the same month a year earlier, with an interval from
  how much months differed from the year before.
- With fewer than 12 months, the last month is repeated with a wide interval.

Only complete calendar months are used, never the current partial month. The response says which
method was used.

## No show risk

The score is the model's probability that an appointment ends as a no show. It uses only what is
known at booking time, plus whether the patient confirmed at least 24 hours before the visit:
lead time, weekday, hour, age band, new or returning, earlier no shows and their rate, earlier
late cancellations, service category, confirmation and whether the patient has insurance.
Earlier visits count only if they had happened by the time the appointment was booked.
A score is high if it is in the top 10 percent of scores in the test period, medium from the
70th percentile, otherwise low. The top three drivers are the features that push the score up
the most for that appointment.

## Chatbot

| Metric | Definition |
|---|---|
| Conversations | Chat sessions in which the visitor sent at least one message. |
| Zero model share | Assistant replies that needed no language model call, divided by all assistant replies (the opening greeting is not counted). |
| Resolved without a person | 1 minus (conversations that ended in a callback or handoff request divided by conversations). |
| Booking funnel | Conversations that started a booking, chose a time, and confirmed. Conversion is confirmed divided by started. |
| Tokens per conversation | Prompt plus completion tokens of all model calls divided by conversations. |
| Failovers | Model calls answered by the second provider because the first was skipped or failed. |
| Feedback score | Thumbs up divided by thumbs up plus thumbs down. |
