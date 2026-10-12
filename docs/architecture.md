# Architecture

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontFamily": "Inter, Segoe UI, Arial, sans-serif", "lineColor": "#475569"}}}%%
flowchart LR
    U["<b>Browser</b><br/>visitor, patient, staff, admin"]
    subgraph PROD["<b>PRODUCTION STACK</b>  |  docker compose, compose.prod.yaml"]
        direction LR
        C["<b>Caddy</b><br/>TLS, headers, static site"]
        A["<b>API</b><br/>FastAPI under Gunicorn<br/><i>migrations on start</i>"]
        W["<b>Worker</b><br/>ARQ jobs, nightly tasks"]
        P[("<b>PostgreSQL 16</b><br/>pgvector, volume")]
        R[("<b>Redis 7</b><br/>cache, queue, holds<br/><i>no persistence</i>")]
        B["<b>Backup</b><br/>nightly pg_dump"]
        M["<b>Mailpit</b><br/>demo mail inbox"]
    end
    L["<b>Language models</b><br/>Groq, Gemini fallback"]
    U ==>|"HTTPS"| C
    C ==>|"/api/*, /health, /ready"| A
    A --> P
    A <--> R
    R ==>|"jobs"| W
    W --> P
    W -->|"SMTP"| M
    A ==>|"last resort"| L
    B --> P
    classDef edge fill:#fef3c7,stroke:#b45309,stroke-width:2px,color:#78350f
    classDef app fill:#ede9fe,stroke:#6d28d9,stroke-width:2px,color:#3b0764
    classDef data fill:#dbeafe,stroke:#1d4ed8,stroke-width:2px,color:#1e3a8a
    classDef misc fill:#f1f5f9,stroke:#475569,stroke-width:2px,color:#0f172a
    classDef user fill:#e0f2fe,stroke:#0369a1,stroke-width:2px,color:#0c4a6e
    class C edge
    class A,W app
    class P,R data
    class B,M,L misc
    class U user
    style PROD fill:#faf5ff,stroke:#6d28d9,stroke-dasharray: 4 3
```

The full component diagram, with the chat orchestration inside the API, is in the [README](../README.md#architecture).


In development the Vite dev server proxies `/api` and `/health` to the API container, so the browser uses a single origin and cookies behave as they will in production.

## Backend

- `app/core`: settings (`pydantic-settings`), structured JSON logging, request ID middleware, uniform error handling.
- `app/db`: async SQLAlchemy engine and session factory, declarative models in `models/`, native enums in `enums.py`, and Alembic migrations in `migrations/`. See [database.md](database.md).
- `app/api`: unversioned operational routes (`/health`, `/ready`) and the versioned `/api/v1` router.
- `app/jobs`: ARQ worker settings and tasks.

Dependencies reachable from the request are held on `app.state` (settings, engine, session factory, Redis client) and created in the application lifespan, which keeps tests free of global state.

## Frontend

- `src/app`: providers and route table. Pages are code split with `React.lazy`.
- `src/lib/api-client.ts`: typed fetch wrapper. Types in `src/lib/api-types.ts` are generated from the backend OpenAPI schema with `npm run gen:api` and are never edited by hand.
- `src/styles/globals.css`: Tailwind v4 theme tokens for the brand palette and self hosted fonts.
- `src/components/ui`: shadcn/ui style primitives built on Radix.
