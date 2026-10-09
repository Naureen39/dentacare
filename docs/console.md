# Staff and admin console

The console is the part of the site for clinic staff. It lives under `/staff` and `/admin`, has its
own layout (no public header or footer) and is closed to everyone who is not signed in as staff.
Code: `frontend/src/console`, `backend/app/api/v1/staff_work.py`, `backend/app/api/v1/admin_console.py`.

## Who sees what

| Area | Receptionist | Dentist | Administrator |
|---|---|---|---|
| Today (arrivals, check in queue, visits to confirm) | yes | yes, their own, with their numbers | yes |
| Schedule | all dentists, can move visits | their own only | all dentists |
| Patients, billing desk | yes | no | yes |
| Clinical note on a visit | cannot read or write | own visits only | cannot read or write |
| Staff, services and prices, dentists and hours, knowledge base, chat review, settings, audit log, analytics | no | no | yes |

The interface hides what a role cannot use, and shows a 403 page if the address is typed. The server
decides every time: `backend/tests/booking/test_console.py` calls each new route as every role and
expects a refusal, and `frontend/src/console/console.test.tsx` checks the menu and the refusals for
each role.

## Screens

- **Schedule.** A day shows one column per dentist, a week shows the seven days of one dentist.
  Colours are by status and also written in each block. Drag a booked or confirmed visit to move it
  (snaps to 15 minutes; a clash is refused here and again by the server). The same move is available
  as a form in the visit drawer for keyboard use. Double click an empty space to book.
  FullCalendar's resource view is a paid product, so the grid is built here.
- **Visit drawer.** Status actions follow the allowed transitions. Completing a visit adds the other
  services performed to the draft invoice. A dentist's clinical note is stored encrypted and is
  returned only to the dentist of that visit.
- **Patients.** Search by name, edit details, visits, invoices, front desk notes (encrypted), and
  possible duplicates found by trigram similarity of the name or the same email. Suggestions only;
  nothing is merged.
- **Billing desk.** Open invoices, issue, record a cash, transfer or insurance payment, void,
  print the PDF.
- **Administration.** Staff accounts (a new person gets an emailed link to set a password; deactivating
  ends their sessions; resetting two step verification signs them out), services with dated price
  changes (today or earlier applies at once, later waits; applied when read), weekly hours and time
  off per dentist (reports how many booked visits fall in the period; it does not move them), the
  knowledge base with preview and re-embed and an intent example editor, chat transcripts with
  emails, phone numbers, dates and introduced names hidden, settings, and the audit log with CSV export.
- **Ctrl K** opens a search for pages and, for the front desk, patients by name.

## Settings

Booking rules, reminder timing, tax and discount limits, the monthly revenue target and data
retention are stored in `app_settings`. Clinic name, address, phone, email and time zone are shown but
come from the server environment. The language model provider order and limits are on the same page.
