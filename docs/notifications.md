# Notifications and background jobs

Email reminders and scheduled maintenance run in the ARQ worker (`app/jobs`). The API only enqueues work and the database holds the truth, so a Redis hiccup delays emails but never loses them.

## Reminders

One row per appointment and kind in `reminders` (unique on both).

| Kind | When it is sent | Dropped when |
|---|---|---|
| `confirmation` | Right after booking, with an `.ics` attachment | The appointment is not active any more |
| `48h` | 48 hours before (`reminder_hours_before`) | Already confirmed, cancelled, or started |
| `24h` | 24 hours before | Cancelled or started |
| `followup` | 2 days after completion (`reminder_followup_days`) | The visit is not completed |
| `recall` | About 6 months after completion (`reminder_recall_months`) | The patient already has a future visit booked |

Reminders whose moment has already passed at booking time are not created. Cancelling, rescheduling or a no show cancels pending visit reminders. A patient with no email address, or an anonymized record, is never emailed.

## Delivery

- `dispatch_due_reminders` runs every minute and at startup. It queues `send_reminder` with the job id `reminder:<id>`, so a reminder that is already queued, running or waiting for a retry is not queued twice. Booking also queues the confirmation immediately.
- `send_reminder` locks the reminder row, does nothing unless it is still `pending`, builds the email, sends it and records the result in one transaction. Running it twice, or concurrently, sends one email. Delivery is at least once: a crash after the mail server accepts a message and before the commit can cause one duplicate.
- **Retries:** a delivery failure raises an ARQ retry with exponential backoff (30 s, 1 min, 2 min, 4 min). The fifth failure marks the reminder `failed`, writes an `audit_logs` entry `job.dead_letter` and logs `reminder_dead_letter`. `GET /admin/reminders?status=failed` is the dead letter list.
- Authentication emails use the same templates but never raise on delivery problems, so a mail outage cannot reveal whether an account exists.

## Links in reminder emails

Confirm and cancel buttons carry a random 256 bit token. Only its hash is stored (`appointment_action_tokens`). A token works once and expires when the appointment starts. Opening the link in a browser shows a summary (`GET /public/appointment-actions/{token}`); the change happens only when the page posts to the same address, so mail scanners that pre-fetch links change nothing. Confirm moves `booked` to `confirmed`; cancel applies the normal 24 hour policy and may flag a late cancellation. A resent reminder invalidates the links of the failed attempt.

## Email templates

Jinja2 templates in `app/templates/email`, an HTML and a plain text version of each, rendered by `render_email`. The HTML uses inline styles only: no images, remote resources or tracking pixels. Tests check this for every template, and that no long dash character appears.

## Other jobs

| Job | Schedule | What it does |
|---|---|---|
| `refresh_analytics` | 03:00 | Refreshes every materialized view named `mv_*` (concurrently when it has a unique index). The views arrive with the analytics phase. |
| `score_no_show_risk` | 03:15 | Counts appointments in the next 7 days waiting to be scored. The model arrives with the analytics phase. |
| `retention_purge` | 03:30 | Purges old chat messages and anonymizes stale cancelled guest records. |

## Patient endpoints

`GET /me/notifications` lists what was sent to the signed in patient. `GET /me/appointments/{id}/ics` downloads the calendar file.

## Running it

`docker compose up` starts the worker next to the API. Emails land in Mailpit at http://localhost:8025 in development. To watch a reminder go out, book an appointment through the API, then open Mailpit; the confirmation appears within a minute at most.
