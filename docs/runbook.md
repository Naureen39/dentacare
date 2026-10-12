# Runbook

Operating the production stack. Commands are run from the repository root and assume:

```bash
export COMPOSE="docker compose -f compose.yaml -f compose.prod.yaml"
```

## Deploy

1. Copy `.env.example` to `.env` and set at least `SITE_ADDRESS` (the public host name, with DNS pointing at the server and ports 80 and 443 open), `POSTGRES_PASSWORD`, `JWT_SECRET` and `FIELD_ENCRYPTION_KEY`.
2. Generate the secrets:

   ```bash
   openssl rand -base64 48                                  # JWT_SECRET
   docker compose run --rm --no-deps api python -m scripts.generate_encryption_key k1   # FIELD_ENCRYPTION_KEY
   ```

3. Start everything. Add `SEED_DEMO=1` for a demo with 24 months of history on first load:

   ```bash
   SEED_DEMO=1 $COMPOSE up -d --build
   ```

On every start of the API container the entrypoint (`backend/docker-entrypoint.sh`) runs `alembic upgrade head`; with `SEED_DEMO=1` it also loads the demo dataset (skipped when already loaded), indexes the knowledge base (unchanged documents are skipped) and trains the no show model when none exists. The embedding model is pre-warmed by the API on start. The worker waits for the API to be healthy, so it never runs against an unmigrated database. The first start can take several minutes (the model download is the slowest part); the health check allows 15 minutes.

The demo accounts (`admin@`, `reception@`, `dentist@`, `patient@meridian.test`) get random passwords that are printed once:

```bash
$COMPOSE logs api | grep -A6 "Development accounts"
```

Admin and dentist accounts must enrol an authenticator app on first sign in. Delete or change the demo accounts before any real use.

Check the stack:

```bash
$COMPOSE ps                     # every service healthy
curl -s https://$SITE_ADDRESS/ready
```

What runs, and its limits: `caddy` (TLS, security headers, static site, 256 MB), `api` (Gunicorn, 2 workers, 2 GB), `worker` (ARQ jobs and nightly tasks, 1 GB), `db` (PostgreSQL 16 with a persistent volume, 1 GB), `redis` (no persistence, 200 MB cap), `mailpit` (loopback only), `backup` (nightly dump). Every container restarts unless stopped and keeps three to five rotated 10 MB log files.

## Update

```bash
git pull
$COMPOSE up -d --build          # migrations run automatically on the new API container
```

Roll back the code with `git checkout <tag>` and rebuild. A migration that must be undone is reverted by hand with `$COMPOSE exec api alembic downgrade -1` before the old code is started.

## Backup

The `backup` service writes a `pg_dump --format=custom` file to the `backups` volume every night at `BACKUP_HOUR:BACKUP_MINUTE` (UTC, default 02:30). Each dump is checked with `pg_restore --list` before it is kept, and files older than `BACKUP_KEEP_DAYS` (14) are removed.

```bash
$COMPOSE exec backup /scripts/backup.sh                 # one dump now
$COMPOSE exec backup ls -lh /backups
$COMPOSE cp backup:/backups/<file>.dump ./offsite/      # copy it off the host
```

The volume lives on the same host as the database. Copy dumps to another machine or storage on a schedule; a backup that shares the disk with the data does not survive losing the disk.

## Restore

Prove a backup works (safe to run at any time; it uses a scratch database and compares the row count of every table with the live one):

```bash
$COMPOSE exec backup /scripts/restore_test.sh
```

Restore into production after data loss:

```bash
$COMPOSE stop api worker caddy
$COMPOSE exec backup sh -c 'psql -d postgres -c "DROP DATABASE meridian" -c "CREATE DATABASE meridian"'
$COMPOSE exec backup pg_restore --no-owner --exit-on-error --dbname=meridian /backups/<file>.dump
$COMPOSE up -d
```

Schedule a restore test at least monthly and after every change to the backup scripts.

## Rotate keys

**Field encryption key** (protects date of birth, phone, address, insurance id and MFA secrets):

1. Generate a new key with a new id: `... generate_encryption_key k2`.
2. Set `FIELD_ENCRYPTION_KEY` to the new key and `FIELD_ENCRYPTION_OLD_KEYS` to the previous one (comma separated for several).
3. Restart: `$COMPOSE up -d`. New writes use `k2`; values written with `k1` stay readable.
4. Keep the old key until every row has been rewritten, then remove it.

**JWT secret:** set a new `JWT_SECRET` and restart. Every signed-in user is signed out once. Do this at once if the secret may have leaked.

**Database password:** change it with `ALTER USER`, update `POSTGRES_PASSWORD` in `.env` and run `$COMPOSE up -d`.

## Switch the language model provider

Both providers are configured by `GROQ_API_KEY` / `GROQ_MODEL` and `GEMINI_API_KEY` / `GEMINI_MODEL`; a provider is used only when its key and model are set. To change which one is tried first without a restart, use the admin API (or the language model section of Settings in the admin console):

```bash
curl -X PUT https://$SITE_ADDRESS/api/v1/admin/llm/primary \
  -H "Content-Type: application/json" -d '{"provider": "gemini"}'    # signed in as an admin
```

`GET /api/v1/admin/llm/status` shows each provider, its circuit state and today's use. The gateway fails over by itself on rate limits, timeouts and server errors, and opens a circuit after repeated failures. With no key at all the assistant keeps working in rules and FAQ mode. Details are in [llm-gateway.md](llm-gateway.md). To check new keys: `$COMPOSE exec api python -m scripts.llm_smoke`.

## Update the knowledge base

The documents are in `data/kb` and the intent examples in `data/intents.yaml` (format in [knowledge-base.md](knowledge-base.md)).

```bash
python -m scripts.embed_kb --check                     # validate the files (in backend/)
git pull && $COMPOSE restart api                       # data/ is mounted read only; the API re-reads it
$COMPOSE exec api python -m scripts.embed_kb           # index only what changed
```

A single document can also be edited from the console, which saves and embeds it at once (`POST /api/v1/admin/kb/documents/{slug}/reembed` re-embeds one, `POST /api/v1/admin/kb/reindex` all).

## Everyday checks

| Question | Command |
|---|---|
| Are all services up? | `$COMPOSE ps` |
| Why did something fail? | `$COMPOSE logs --tail 200 api worker` (JSON lines with a request id) |
| Are reminders being sent? | the Notifications page of the console, or Mailpit at `http://127.0.0.1:8025` for the demo |
| Is the queue stuck? | `$COMPOSE exec redis redis-cli llen arq:queue` |
| Refresh the dashboard numbers now | the Refresh button on the analytics page, or `POST /api/v1/analytics/refresh` |
| Stop everything, keep data | `$COMPOSE down` (add `-v` only to delete the database and backups) |

## Known limits

- One host, one database. There is no high availability; recovery is a restore from the latest dump (data loss up to one day unless a dump is taken before a risky change).
- Redis holds cache, rate limit counters, slot holds and the job queue without persistence. A Redis restart drops short slot holds and any queued but unsent job; the nightly jobs and the reminder dispatcher rebuild their work from the database.
- Mail in the demo goes to Mailpit. For real delivery set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER` and `SMTP_PASS` and remove Mailpit from the stack.
