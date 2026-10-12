# Demo script

About ten minutes. It follows one patient from a chat conversation to an invoice, then shows what the owner sees and what happens when a language model provider fails.

## Before you start

```bash
cp .env.example .env
docker compose up --build            # development stack, or the production overlay (see runbook.md)
cd backend && uv run alembic upgrade head
uv run python -m scripts.seed        # prints four accounts and their passwords, once
uv run python -m scripts.embed_kb
uv run python -m scripts.train_no_show
```

With the production overlay, `SEED_DEMO=1` does all of this by itself and the passwords are in `docker compose ... logs api`.

Have open: the site (`http://localhost:5173`, or your `SITE_ADDRESS`), Mailpit (`http://localhost:8025`), and a second window signed in as `reception@meridian.test`. Admin and dentist accounts enrol an authenticator app on first sign in, so do that once beforehand.

## 1. A guest books through the chatbot

1. On the home page open the chat window (bottom right).
2. Choose **Book an appointment**, pick a service (for example a check up), a dentist or "no preference", and one of the offered times.
3. Give a name, an email address and consent when asked, then confirm.

Point out: no account was needed, only real free times were offered, and the model was not called for any of these steps (the conversation is rules driven; the model is the last resort). The assistant also answers a free text question such as "Do you take my insurance?" from the knowledge base.

## 2. The reminder email

Open Mailpit. The confirmation is there with an **Add to calendar** file and links to confirm or cancel. Reminders are queued for 48 and 24 hours before the visit and sent by the worker; for the demo the confirmation is enough to show the template and the one click links. Click **Confirm** in the email to see the appointment change to confirmed.

## 3. Check in, completion and invoice

In the reception window:

1. **Schedule**: find the new appointment, open it and **Check in**.
2. Open the appointment again and use **Complete the visit** (as the dentist, `dentist@meridian.test`, or as reception), adding a short note.
3. **Billing desk**: the invoice for the visit exists. Open it, apply an insurance estimate or a discount, **Issue**, then record a sandbox card payment. Download the PDF receipt.

## 4. The dashboard

Sign in as `admin@meridian.test` and open **Analytics**. Show the 24 months of history, the forecast, the filters and the CSV export. Note the "Figures last refreshed" line, press **Refresh**, and watch the revenue and appointment numbers include the visit you just completed. Every number is defined in [metrics.md](metrics.md) and reconciled with SQL in the tests.

## 5. Provider failover

This step needs real keys for both providers (`GROQ_API_KEY`, `GEMINI_API_KEY` and `GEMINI_MODEL` in `.env`).

1. Open **Settings** in the admin console, which has the language model section (or `GET /api/v1/admin/llm/status`): both providers are healthy and Groq is primary.
2. Force a Groq failure by restarting the API with a deliberately wrong key: `GROQ_API_KEY=invalid docker compose up -d api`.
3. In the chat, ask a question the rules and the FAQ cannot answer on their own, for example a long, unusual one about aftercare.
4. The answer still arrives. The status page now shows the call served by Gemini and Groq's circuit opening after repeated failures; the usage table shows the tokens per provider.

Without keys the assistant stays in rules and FAQ mode (no model call at all), which is the third thing to show: nothing breaks when both providers are down.

## Reset between demos

```bash
cd backend && uv run python -m scripts.seed --reset
```
