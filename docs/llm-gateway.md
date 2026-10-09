# LLM gateway

`backend/app/chat/llm_gateway.py` is the only module that talks to a language model. No other file imports a provider SDK (a test enforces this). The rest of the application calls one method and gets back text, parsed data, or a safe fallback.

```python
result = await gateway.complete(
    [Message("user", "...")], max_tokens=160, json_schema=None, purpose=Purpose.FAQ_ANSWER
)
```

The model has no tools, no database access and never runs in a loop. All actions are carried out by ordinary backend code.

## Providers

| | Groq (primary) | Gemini (fallback) |
|---|---|---|
| SDK | `openai` pointed at `https://api.groq.com/openai/v1` | `google-genai` |
| Model | `GROQ_MODEL`, default `openai/gpt-oss-20b` | `GEMINI_MODEL`, no default |
| Structured output | `response_format` JSON schema with `strict: true` | `response_mime_type=application/json` and `response_json_schema` |
| Reasoning | `reasoning_effort="low"` and `include_reasoning=false` for `openai/gpt-oss-*` models | `thinking_budget=0` (set `GEMINI_THINKING_BUDGET=-1` to omit it) |
| Daily reset | UTC by default (`GROQ_RESET_TZ`; the documentation names no time zone) | midnight Pacific time (`GEMINI_RESET_TZ`) |

Pick a Flash-Lite class Gemini model that shows a free tier in Google AI Studio and put its name in `GEMINI_MODEL`. A provider is used only when both its key and its model are set.

Groq's documented free tier limits for the default model are 30 requests per minute, 1,000 per day, 8,000 tokens per minute and 200,000 per day. They change and apply per organization, so check the Groq console before launch. They live in `app_settings` (`groq_rpm`, `groq_rpd`, `groq_tpm`, `groq_tpd`), as do Gemini's (`gemini_*`), which start unset and are entered from Google AI Studio.

## Request discipline

- **One static system prompt**, built once from configuration (`app/chat/prompts.py`, under 250 tokens) and sent first with every request, byte for byte. This is what lets Groq cache the prefix, and cached tokens do not count against rate limits. Callers can pass only `user` and `assistant` messages; anything that changes goes there.
- **Temperature 0.2**, and `max_tokens` is cut to the purpose budget:

| Purpose | Max prompt tokens | Max completion tokens | Calls |
|---|---|---|---|
| `entity_extraction` | 350 | 80 | 0 or 1 |
| `faq_answer` | 700 | 160 | 0 or 1 |
| `fallback_rephrase` | 300 | 100 | rare |

  The prompt limit applies to the messages the caller supplies (the static system prompt is separate and cached). A larger prompt is refused with `PromptTooLargeError` before any call, because trimming silently would change the answer. Replies longer than the budget are cut at a sentence boundary.
- **Reasoning headroom.** `gpt-oss` models count hidden reasoning against the completion limit, so the Groq request asks for `GROQ_REASONING_HEADROOM` (100) extra tokens. The visible answer is still cut to the purpose budget. If a real model returns empty replies with `finish_reason=length`, raise this value.
- **Structured output** is validated with Pydantic. An invalid reply is repaired at most once, in the same provider, by showing it its own reply and the problem. A second failure moves on to the other provider.

## Routing

Order: the provider named by the `llm_primary` setting, otherwise `LLM_PRIMARY`, then the other one. The next provider is used when the first

- returns 429 (its `retry-after` starts a cooldown during which it is skipped, capped at five minutes),
- returns a 5xx, a connection error or an authentication error,
- takes longer than 8 seconds (`LLM_TIMEOUT_SECONDS`),
- is behind an open circuit breaker, or
- is above 80 percent of any known limit once this call is counted.

**Local budget counters** live in Redis and are shared by all API processes: a sliding 60 second window for requests and tokens, and per day counters keyed by the provider's own reset date. Groq's `x-ratelimit-remaining-tokens` and `x-ratelimit-remaining-requests` response headers raise the counters when Groq reports more usage than we counted (for example because the key is shared), and never lower them. Cached tokens are not counted, and Gemini counts input tokens only, as its limits are defined. The threshold is `llm_budget_failover_threshold` (0.8). A limit that is not known is not enforced locally; the provider's 429 then triggers failover.

**Circuit breaker.** Three consecutive failures mark a provider unhealthy for 60 seconds. After that one probe request is let through (half open); success closes the breaker, failure reopens it for another 60 seconds. Skips caused by budgets or cooldowns do not count as failures, and neither do bad replies (empty, truncated, invalid JSON), which say nothing about the provider's health.

**When nothing answers** the result has `degraded=True`. The text is the short answer of the best matching FAQ document (`app/chat/degraded.py`, score at least 0.65) when the caller supplies it, otherwise a fixed message offering the booking page and the clinic phone number. Provider errors, status codes and exception text never reach the user.

## Observability

Every call is a row in `llm_usage`: provider, model, purpose, prompt, completion and cached tokens, latency, status (`ok`, `rate_limited`, `timeout`, `server_error`, `connection_error`, `auth_error`, `bad_request`, `invalid_output`, `truncated`, `empty_output`) and `fallback_from`, which names the first choice when another provider answered. Counting `fallback_from` rows gives the failover count. Prompts and replies are never logged.

| Endpoint (admin) | Purpose |
|---|---|
| `GET /admin/llm/status` | Order, breaker state, cooldowns, limits, current usage and utilization per provider |
| `PUT /admin/llm/primary` | Switch the first-choice provider without a restart |
| `PUT /admin/llm/limits/{provider}` | Enter published limits, for example from Google AI Studio |
| `GET /admin/llm/usage?hours=24` | Calls, tokens, latency and failovers by provider and outcome |

## Runbook

- **Switch provider:** `PUT /admin/llm/primary` with `{"provider": "gemini"}`. It takes effect within seconds.
- **A provider keeps failing:** read `GET /admin/llm/status`. An open breaker closes by itself after a successful probe; fix the key, model name or quota, there is nothing to reset by hand.
- **After changing a key or model:** run `uv run python -m scripts.llm_smoke` (add `--provider groq` for one). It asks each configured provider a plain question twice, then a structured request, prints tokens, cached tokens and latency, and exits with a non zero code if anything fails. The second plain call should show cached prompt tokens on Groq.
- **Test failover on purpose:** set a wrong `GROQ_API_KEY` for a minute and watch `fallback_from` fill in `llm_usage`.

## What is verified without keys

The tests (`backend/tests/chat`) cover routing, failover on 429, 5xx, timeouts, connection and authentication errors, every budget threshold, the circuit breaker including half open recovery, structured output repair, prompt discipline, usage logging and the admin endpoints with scripted providers. They also drive the real Groq and Gemini provider classes through their SDKs against fake HTTP servers to check exactly what is sent (endpoint, headers, reasoning parameters, strict schema, no tools, no SDK retries) and how every status code is mapped. A live call with real keys is the one thing they cannot do, which is what `scripts/llm_smoke.py` is for.
