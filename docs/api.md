# API reference

The API is described by an OpenAPI 3 document that is generated from the code, so it cannot drift from it.

| Where | What |
|---|---|
| `/docs` | Interactive reference (Swagger UI). Available when `ENV` is not `production`. |
| `/api/v1/openapi.json` | The machine readable description of the running API (also served in production). |
| [frontend/openapi.json](../frontend/openapi.json) | A committed copy, used to generate the typed client (`npm run gen:api`). |
| `cd backend && uv run python -m scripts.export_openapi` | Rewrites the committed copy after a change to the API. |

All endpoints are under `/api/v1`, except `/health` (is the process alive) and `/ready` (are the database and Redis reachable).

## Conventions

- **Authentication.** Sign in at `POST /api/v1/auth/login`. The access and refresh tokens are `HttpOnly` cookies; the refresh token rotates on every use. Staff and administrators also complete a one time code step. See [security.md](security.md).
- **Roles.** `patient`, `receptionist`, `dentist` and `admin`. Each endpoint states what it needs; a signed in user outside that role gets `403`, and one record never reveals another patient's data.
- **Errors.** Every error has the same shape: `{"code": "...", "message": "...", "details": null, "request_id": "..."}`. Validation failures list the offending fields in `details`.
- **Rate limits.** Sign in, public booking and chat are limited per client address; a limited request gets `429` with a `Retry-After` header.
- **Times.** Instants are ISO 8601 in UTC. Dates shown to people use the clinic time zone (`CLINIC_TZ`).

## Areas

| Prefix | Purpose | Guide |
|---|---|---|
| `/public` | Services, dentists, testimonials, availability, guest booking | [booking.md](booking.md) |
| `/auth` | Registration, sign in, MFA, sessions, password reset | [security.md](security.md) |
| `/portal` | The signed in patient's appointments, invoices, profile and data export | [booking-and-portal.md](booking-and-portal.md) |
| `/staff`, `/records` | Schedule, check in, completion, patient records, billing desk | [console.md](console.md), [billing.md](billing.md) |
| `/admin` | Accounts, schedules, knowledge base, language model controls, audit log | [console.md](console.md), [llm-gateway.md](llm-gateway.md) |
| `/analytics` | Summary, trends, forecast, no show risk, exports | [analytics.md](analytics.md), [metrics.md](metrics.md) |
| `/chat` | Assistant sessions and messages | [chatbot.md](chatbot.md) |
