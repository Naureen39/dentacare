# Booking

How appointments are offered, held, booked and changed. The rules here are enforced by the backend and covered by tests in `backend/tests/booking`.

## Availability engine

`app/services/availability.py`. Input: a service, a date range (at most 31 days) and optionally one dentist. For every eligible dentist (active, linked to the service in `dentist_services`) and every clinic day:

1. Take the weekly template from `dentist_schedules` (weekday 0 is Monday).
2. Subtract the break, `schedule_exceptions` and active appointments. An existing appointment occupies its slot plus the cleanup buffer that follows it.
3. Cut the remaining windows into slots on a 15 minute grid. A slot is offered only when the service duration plus the buffer (default 10 minutes) fits inside the free window, so the last slot of a session ends at least one buffer before the window closes.
4. Apply the booking rules from `app_settings`: minimum notice (2 hours), horizon (90 days), same day booking toggle, buffer and grid size.

The response contains every requested date, with an empty list for closed days, so a calendar can draw availability dots directly:

```json
[{ "date": "2027-05-05", "slots": [
  { "start": "2027-05-05T12:00:00Z", "end": "2027-05-05T12:45:00Z",
    "dentist_id": "...", "dentist_name": "Dr. Priya Raman" } ] }]
```

### Time zones

Slot instants are UTC. Clinic wall clock times (`CLINIC_TZ`, default `America/New_York`) are converted to UTC at the edges with the time zone database, so a schedule that starts at 08:00 maps to 13:00Z before the spring change and 12:00Z after it. On the spring forward day the missing local hour never yields a slot and the day is one real hour shorter; on the fall back day the repeated hour is covered and the day is one real hour longer. Tests cover 13 and 15 March and 6 to 8 November 2027. A schedule boundary that falls inside a nonexistent hour resolves with `fold=0`, as in the standard library.

### Caching

Results for the public endpoint are cached in Redis for 30 seconds per query. Every booking, cancellation and no show increments `avail:version`, which makes all earlier cache entries unreachable at once. Held slots are filtered after the cache read, so a new hold is visible immediately.

## Slot holds

`POST /public/hold` checks the slot is currently bookable, then creates `hold:{dentist}:{start}` with `SET NX` and a five minute TTL. The value is a secret token returned to the caller; booking must present it. A second hold on the same slot returns 409 `slot_held`. Held slots are hidden from availability results for everyone. A hold is released when the booking succeeds and expires on its own otherwise.

## The final guard

Two exclusion constraints in PostgreSQL (see [database.md](database.md)) reject overlapping active appointments for the same dentist and for the same patient. Before inserting, the service re-checks availability; if two requests race past that check, the database lets exactly one commit and the other receives:

```json
{ "code": "slot_unavailable", "message": "This time was just taken. Please choose another.",
  "details": { "alternatives": [ { "start": "...", "end": "...", "dentist_id": "...", "dentist_name": "..." } ] },
  "request_id": "..." }
```

`alternatives` holds the five open slots nearest to the requested time, across all eligible dentists. A patient who already has an overlapping appointment gets 409 `patient_double_booked`. The concurrency tests fire 20 parallel booking attempts at one slot and require exactly one success.

## Endpoints

| Endpoint | Who | Notes |
|---|---|---|
| `GET /public/services`, `/public/dentists`, `/public/testimonials` | anyone | Active records only; no license numbers or account ids. |
| `GET /public/availability?service_id&from&to&dentist_id` | anyone | Cached 30 seconds. |
| `POST /public/hold` | anyone | 20 per hour per IP. |
| `POST /public/appointments/verification` | anyone | Sends a six digit code; limited per IP and per address. |
| `POST /public/appointments` | anyone | Guest booking; needs the hold token and the emailed code. |
| `POST /public/contact`, `/public/newsletter` | anyone | 5 per hour per IP. The newsletter response is identical for new and existing addresses. |
| `GET /me/appointments?when=upcoming\|past\|all` | patient | |
| `POST /me/appointments` | patient | Needs a hold token. |
| `POST /me/appointments/{id}/reschedule` | patient | New appointment linked through `rescheduled_from`; the old one is cancelled in the same transaction. |
| `POST /me/appointments/{id}/cancel` | patient | Free until 24 hours before the start, later cancellations are flagged `late_cancel`. |
| `GET /me/invoices` | patient | Own invoices only. |
| `GET /staff/schedule?view=day\|week&on&dentist_id` | admin, receptionist, dentist (own chair) | Viewing is audited. |
| `POST /staff/appointments` | admin, receptionist | No hold needed; minimum notice and horizon do not apply, working hours and conflicts do. |
| `PATCH /staff/appointments/{id}/status` | staff; dentists for own appointments | |
| `POST /patients` | admin, receptionist | Walk in registration. |

Other patients' appointments are reported as 404, never 403, so identifiers cannot be probed.

## Guest verification

A guest enters their details, the API emails a six digit code (stored only as a keyed hash, valid 10 minutes, at most 5 wrong attempts, single use) and the booking request carries `verification_id` and `otp`. Requesting a new code invalidates earlier ones. A wrong guess is counted even though the request fails; a booking that fails for another reason (for example the slot was taken) does not consume the code, so the guest can pick another time. The patient record is created on the first successful booking and reused by email afterwards.

## Appointment state machine

```
booked -> confirmed -> checked_in -> completed
booked | confirmed -> cancelled
booked | confirmed -> no_show        (only after the start time)
```

Anything else returns 422 `invalid_transition`. Dentists may only mark their own appointments `completed` or `no_show`; all other changes belong to the front desk. Every change writes `appointment_status_history` and an audit entry, and cancellations and no shows free the slot immediately.

## Cancellation policy

`cancellation_free_hours` (24) comes from `app_settings`. Each appointment response includes `free_cancellation_until` so the interface can show the policy before the patient confirms. Reschedules inside the window are allowed and flagged the same way on the cancelled original.

## Known limits

- A patient cannot hold a slot that overlaps their own existing appointment with the same dentist, because that time is not free. To move an appointment by a few minutes, choose another dentist or a non overlapping time.
- Group bookings, recurring appointments and waiting lists are not part of the plan.
