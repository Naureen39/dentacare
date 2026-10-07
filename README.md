# Meridian Dental Care

Clinic website, online booking, patient portal, staff console, revenue and analytics dashboard, and a support and booking assistant. The clinic is fictional and this is a demo environment.

The full build plan is in [plan (2).md](<plan (2).md>). This repository currently contains **Phase 1 (Foundations)** and **Phase 2 (Database schema and migrations)**.

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
| Backend security | `uv run bandit -q -r app` and `uv run pip-audit` |
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
