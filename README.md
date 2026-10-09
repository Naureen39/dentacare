# Meridian Dental Care

Clinic website, online booking, patient portal, staff console, revenue and analytics dashboard, and a support and booking assistant. The clinic is fictional and this is a demo environment.

The full build plan is in [plan (2).md](<plan (2).md>). This repository currently contains **Phase 1 (Foundations)**, **Phase 2 (Database schema and migrations)** and **Phase 3 (Authentication, authorization and security baseline)** **Phase 4 (Core booking backend)** **Phase 5 (Billing and payments)** **Phase 6 (Notifications and background jobs)** **Phase 7 (Knowledge base and embeddings)**, **Phase 8 (LLM gateway)**, **Phase 9 (Chatbot orchestration)** **Phase 10 (Analytics backend, forecasting and no show model)** **Phase 11 (Frontend foundation and design system)** **Phase 12 (Public website)** **Phase 13 (Booking wizard and patient portal)**, **Phase 14 (Staff and admin console)** and **Phase 15 (Analytics dashboard)**.

## Quick start

Requirements: Docker with Compose v2. For local tooling outside Docker: Python 3.12 with [uv](https://docs.astral.sh/uv/) and Node.js 22 or later.

```bash
cp .env.example .env      # optional, defaults work for development
docker compose up --build
```

| Service | Default address |
|---|---|
| Web (Vite dev server) | http://localhost:5173 |
| API | http://localhost:8000 (docs at `/docs`) |
| Health and readiness | http://localhost:8000/health and `/ready` |
| Mailpit inbox | http://localhost:8025 |
| PostgreSQL 16 with pgvector | localhost:5432 |
| Redis 7 | localhost:6379 |

If a host port is already in use, override it in `.env` with `API_PORT`, `WEB_PORT`, `DB_PORT`, `REDIS_PORT`, `MAILPIT_UI_PORT` or `MAILPIT_SMTP_PORT`.

The production profile adds Caddy with automatic TLS and security headers:

```bash
SITE_ADDRESS=clinic.example.com docker compose --profile production up -d --build
```

## Database

```bash
cd backend
uv run alembic upgrade head     # create the schema in the Compose database
uv run pytest tests/db          # constraint and migration tests (needs the db service)
```

See [docs/database.md](docs/database.md) for the schema, constraints and migration workflow.

## Authentication

Patients register at `POST /api/v1/auth/register` and confirm their email (the message appears in Mailpit at http://localhost:8025). Admin and dentist accounts must enrol an authenticator app (TOTP) on first sign in. The API reference is at `/docs` in development, and the design and ASVS review are in [docs/security.md](docs/security.md).

Generate an encryption key for personal data fields (required in production):

```bash
cd backend && uv run python -m scripts.generate_encryption_key k1
```

## Booking

Availability, slot holds, guest and patient booking, rescheduling, cancellation policy and the staff schedule are documented in [docs/booking.md](docs/booking.md).

## Billing

Invoices, discounts, sandbox card payments, PDFs and receivables aging are documented in [docs/billing.md](docs/billing.md). Clinic details on invoices come from `CLINIC_NAME`, `CLINIC_ADDRESS`, `CLINIC_PHONE` and `CLINIC_EMAIL`.

## Notifications

Reminder emails, confirm and cancel links and the nightly jobs are documented in [docs/notifications.md](docs/notifications.md).

## Knowledge base

68 documents in `data/kb` and the intent examples in `data/intents.yaml` are indexed with `uv run python -m scripts.embed_kb`. See [docs/knowledge-base.md](docs/knowledge-base.md) for the format, search behaviour, administration endpoints and quality gates.

## LLM gateway

The single entry point to the language models (Groq first, Gemini as fallback) with budgets, failover and a circuit breaker is described in [docs/llm-gateway.md](docs/llm-gateway.md). Check real keys with `uv run python -m scripts.llm_smoke`.

## Chat assistant

Questions, bookings, reschedules and cancellations through a conversation that uses a language model only as a last resort. See [docs/chatbot.md](docs/chatbot.md).

## Frontend

The design system, the authentication client and the `/styleguide` route are described in [docs/frontend.md](docs/frontend.md). Run `npm run dev` in `frontend` and open `/styleguide`.

The public website (pages, search engine markup, prerendering and the Lighthouse audit) is described in [docs/website.md](docs/website.md). Run `npm run audit:site` in `frontend` to check it.

The booking wizard and the patient portal, and how to run their browser tests (`npm run test:e2e`), are described in [docs/booking-and-portal.md](docs/booking-and-portal.md).

The staff and admin console is described in [docs/console.md](docs/console.md) and the analytics dashboard in [docs/analytics-dashboard.md](docs/analytics-dashboard.md).

## Analytics

Materialized views, the `/analytics` endpoints, the revenue forecast and the no show model are described in [docs/analytics.md](docs/analytics.md); every number is defined in [docs/metrics.md](docs/metrics.md). To load 24 months of demo data and train the model:

```bash
cd backend
uv run python -m scripts.seed
uv run python -m scripts.train_no_show
```

## Development without Docker

```bash
# Backend
cd backend
uv sync
uv run uvicorn app.main:app --reload
uv run pytest

# Frontend
cd frontend
npm ci
npm run dev
```

Regenerate the typed API client after changing backend schemas:

```bash
cd frontend && npm run gen:api
```

## Quality checks

| Area | Command |
|---|---|
| Backend lint and format | `uv run ruff check . && uv run ruff format --check .` |
| Backend types | `uv run mypy app tests scripts` |
| Backend tests | `uv run pytest` |
| Backend security | `uv run bandit -q -c pyproject.toml -r app` and `uv run pip-audit` |
| Frontend lint and format | `npm run lint && npm run format:check` |
| Frontend types, tests, build | `npm run typecheck && npm test && npm run build` |
| Repository text rules | `python scripts/check_text_rules.py` |

Install the git hooks once with `pre-commit install`. CI runs the same checks plus Trivy and gitleaks.

## Repository layout

```
backend/    FastAPI application, ARQ worker, tests
frontend/   React, Vite, TypeScript, Tailwind, shadcn/ui
data/       knowledge base, reference and generated datasets
infra/      Docker Compose file and Caddyfile
docs/       architecture, conventions and runbooks
scripts/    repository level tooling
```

## Conventions

See [docs/conventions.md](docs/conventions.md) for the branch strategy, commit format and content rules.
