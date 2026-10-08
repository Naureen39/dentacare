# Billing and payments

Invoices, discounts, payments, PDFs and receivables. Behaviour described here is covered by `backend/tests/billing`.

## Money rules

- All amounts are `numeric(12,2)` in the database and `Decimal` in code. Floats are never used.
- Every computed amount is rounded **half up** to whole cents (`2.675` becomes `2.68`, `0.005` becomes `0.01`).
- The identities below hold at all times and are also enforced by database check constraints:
  - `subtotal` is the sum of the item amounts, and each item `amount = round(qty * unit_price, 2)`.
  - `total = subtotal - discount + tax`.
  - `discount <= subtotal`, `insurance_expected <= total`, and a discount above zero needs a reason.
- Tax is `round((subtotal - discount) * rate, 2)`. The rate is `billing_tax_rate_percent` in `app_settings` (default 0, because dental services are commonly exempt). Change it in the settings screen, not in code.
- A randomized test builds invoices with random items, discounts and a 7.25 percent tax rate and checks the identities on every one.

## Invoice lifecycle

```
completed visit -> draft -> issued -> partially_paid -> paid
                     \-> void   (also from issued, but never once a payment exists)
```

1. **Creation.** Moving an appointment to `completed` (by a receptionist, administrator or the treating dentist) creates one draft invoice with one line for the service at its current base price. Later price changes never alter an existing invoice. Creation is idempotent: a second attempt returns the live invoice. A voided invoice can be replaced.
2. **Drafting.** While the invoice is a draft the billing desk can add and remove items, apply a discount and set the expected insurance payment.
3. **Issue.** `POST /billing/invoices/{id}/issue` fixes the amounts and sets the issue time. An invoice with a zero total (a 100 percent discount) is paid on issue.
4. **Payments** move the status automatically: no payment is `issued`, a part payment is `partially_paid`, and payments covering the total make it `paid`. The status is derived from the payments and recomputed after every payment.
5. **Void.** Requires a reason. An invoice with any payment cannot be voided, because refunds are outside the plan. Void invoices are excluded from receivables and from payment.

After issue, items and discounts are locked (409 `invoice_locked`); only the expected insurance payment may still change. To correct an issued invoice, void it and bill again.

Invoice numbers come from the database sequence `invoice_number_seq`, starting at 1000 and shown as `INV-001000`. They are strictly increasing. A number can be skipped when a transaction rolls back, as with any database sequence; a legal gap-free requirement would need a different design.

## Discounts

Give either `discount_amount` or `discount_percent` (percent of the subtotal, rounded half up to cents) together with a reason.

| Role | Limit |
|---|---|
| Receptionist | Up to `receptionist_max_discount_percent` of the subtotal (default 10). Above it: 403 `discount_limit_exceeded` with the limit in `details`. The limit is re-checked when items are removed, so it cannot be bypassed by shrinking the subtotal. |
| Administrator | Any amount up to the subtotal. |
| Dentist, patient | No access. |

## Payments

`POST /billing/invoices/{id}/payments` (billing desk) with `amount`, `method` (`card`, `cash`, `bank_transfer`, `insurance`), optional `reference` and optional `paid_at` (not in the future; insurer payments arrive weeks after the visit and may be back dated). Patient payments by card go through `POST /me/invoices/{id}/pay`.

- The payer follows the method: `insurance` is an insurer payment, everything else is a patient payment. The database rejects any other combination.
- A payment larger than the remaining balance is rejected with 422 `overpayment` and the balance in `details`.
- The invoice row is locked while a payment is recorded, so parallel requests cannot overpay. Twenty parallel $10 payments on a $120 invoice produce exactly twelve successes.

### Sandbox card payments

Card payments are simulated and labelled as such everywhere (`sandbox: true`, the reference prefix `SBX-`, the PDF footer).

- The number must pass the Luhn check, the expiry must not be in the past and the security code must have 3 or 4 digits. Spaces and dashes are accepted.
- Test numbers: `4000 0000 0000 0002` is declined, `4000 0000 0000 9995` has insufficient funds (both return 402 `card_declined` and record no payment). Any other valid number is approved.
- **Card data is never stored or logged.** The request fields are `SecretStr`, the validation error responses do not echo input, and only the last four digits and a generated reference are saved. Tests assert that the number, expiry and security code appear in no table and no audit entry.

## Receivables

The SQL view `ar_aging` lists every issued or partially paid invoice with a balance and puts it into a bucket by whole UTC days since issue: `0_30`, `31_60`, `61_90`, `over_90`. It also splits the balance into the amount still expected from the insurer (`insurance_expected` minus insurer payments, capped at the balance) and the patient's share. `ar_aging_summary` totals the four buckets and always returns all four rows. Both are plain views, so they are always current. The analytics phase wraps them in the materialized view `mv_ar_aging`.

`GET /billing/ar-aging` (receptionist and administrator) returns the summary.

## PDF

`GET /billing/invoices/{id}/pdf` and `GET /me/invoices/{id}/pdf` render the invoice with ReportLab (BSD licensed, pure Python, no system libraries). The document carries the clinic name, address, phone and email from configuration (`CLINIC_NAME`, `CLINIC_ADDRESS`, `CLINIC_PHONE`, `CLINIC_EMAIL`), the invoice number, status, dates, provider, items, discount with its reason, tax, totals, payments (card payments show only "ending 1234") and the balance due. User supplied text is escaped before rendering.

## Endpoints

| Endpoint | Who |
|---|---|
| `GET /billing/invoices` (filters `status`, `open_only`, `patient_id`, `q`, `limit`, `offset`) | admin, receptionist; dentists see only invoices for their own appointments |
| `GET /billing/invoices/{id}`, `/pdf` | same |
| `PATCH /billing/invoices/{id}`, `POST .../items`, `DELETE .../items/{item}`, `POST .../issue`, `.../void`, `.../payments` | admin, receptionist |
| `GET /billing/ar-aging` | admin, receptionist |
| `GET /me/invoices`, `/me/invoices/{id}`, `/pdf` | patient, own issued invoices (drafts are hidden) |
| `POST /me/invoices/{id}/pay` | patient, sandbox card |

Other people's invoices, and drafts for patients, are reported as 404. Every billing action writes an audit entry without amounts of personal data, card details or free text.

## Known limits

- No refunds, credit notes or payment reversals. A paid invoice cannot be voided.
- One tax rate for the whole invoice.
- Prices are not effective dated yet; that arrives with service management in the staff console phase.
- Ageing counts UTC days; it can differ by one day from the clinic's local date near midnight.
