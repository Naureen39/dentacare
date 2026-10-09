# Booking wizard and patient portal

Frontend for booking (`/book`) and the signed in patient's area (`/portal`). Code is in
`frontend/src/pages/booking`, `frontend/src/pages/portal` and `frontend/src/components/booking`.

## Booking wizard

Steps: service, dentist, date and time, details, email check (guests only), confirmation. The
address follows the step (`/book/service`, `/book/time`, and so on). A layout route keeps the
choices in memory, so going back never loses them. A link may preselect a service and dentist:
`/book?service=SV05&dentist=priya-raman`.

- **Times** come from `/public/availability` one month at a time (the API allows 31 days). They
  are grouped into morning, afternoon and evening in the clinic's time zone, whatever the
  visitor's. With "first available", the dentist is shown under each time.
- **Hold.** Choosing a time calls `/public/hold` and starts a five minute countdown that stays
  visible through the details and email steps. When it runs out the visitor is sent back to pick
  a time again.
- **Conflict.** If the time was just taken (or held by someone else) the server answers 409 with
  nearby alternatives; they are offered as buttons. The same happens if the hold expires at the
  last moment.
- **Guests** get a six digit code by email (`/public/appointments/verification`) and book with it.
  A wrong code is explained and can be retyped; too many wrong codes require a new one.
- **Patients** who are signed in have their details filled in and book through
  `/me/appointments` without a code.
- "New or returning" is sent to the clinic as the start of the reason note. Insurance for a guest
  is kept only when the booking creates a new patient record; it never overwrites an existing one.
- The calendar file (.ics) is built in the browser so guests can have one too.

## Patient portal

Only the `patient` role can open `/portal` (the server checks the role on every call as well).
Overview, appointments (upcoming and past, reschedule and cancel dialogs that state the cancel
policy), billing (list, invoice, PDF, sandbox payment), notifications, and profile and security
(details, insurance, communication preference, password, two step verification, signed in
devices). Changing the password ends every session, this one included, so the page signs out.

Added to the API for this: `GET /auth/sessions`, `DELETE /auth/sessions/{id}` and
`GET /public/insurance-providers`.

## Tests

Unit tests: `booking.test.tsx` and `portal.test.tsx`. Browser tests: `npm run test:e2e` runs
Playwright (the installed Chrome) against the dev server with a stand in API
(`e2e/support/fake-api.ts`): guest booking, signed in booking, reschedule, cancel, a taken time
and a wrong email code.
