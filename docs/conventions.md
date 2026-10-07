# Engineering Conventions

## Branch strategy

- `main`: always deployable. Protected, updated only through reviewed merges.
- `develop`: integration branch for completed work.
- `feature/<short-description>`: one branch per task, created from `develop`.
- `fix/<short-description>`: bug fixes, same flow as feature branches.

## Commit messages

Conventional commits, written in a professional tone in the imperative mood.

```
<type>(<scope>): <summary>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `build`, `perf`.
Scopes: `api`, `web`, `db`, `chat`, `infra`, `ci`, `docs`.

Example: `feat(api): add health and readiness endpoints`

## Content rules

1. Professional tone in UI copy, code comments, commit messages, docs and seed data. No placeholder text.
2. No AI assistant or vendor brand names in code, comments, commits, UI or docs. The chatbot is named "Meridian Assistant". Model names appear only in environment variables and the internal configuration.
3. No long dash characters anywhere. Use a hyphen, colon or comma. `scripts/check_text_rules.py` enforces this in the pre-commit hook and in CI.
4. Free and open source tooling only.
5. Clinic name, logo, colors, address and phone are configuration, not hardcoded.
6. Never copy copyrighted text or images.

## Error format

Every failing API response uses the same body:

```json
{ "code": "not_found", "message": "Not Found", "details": null, "request_id": "..." }
```

The `request_id` matches the `X-Request-ID` response header and the `request_id` field in the JSON logs.

## Health endpoints

- `GET /health`: liveness, returns 200 while the process runs.
- `GET /ready`: readiness, returns 200 only when PostgreSQL and Redis respond, otherwise 503 with per dependency status.
