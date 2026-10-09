"""The LLM gateway: the only place in the application that talks to a language model.

Everything else asks the gateway for a completion and never imports a provider SDK. The
gateway

* sends every request through a fixed, byte identical system prompt so providers can cache it,
* enforces the token budget of the request's purpose,
* routes to the primary provider and fails over to the other one on rate limits (429), server
  errors (5xx), timeouts, an open circuit breaker or a local budget above the configured share
  of the provider's limits,
* validates structured output with Pydantic and repairs it at most once,
* records every call in ``llm_usage``, and
* when nothing answers, returns a fixed fallback, never an error message.

The model never gets tools, never sees the database and never runs in a loop. All actions are
carried out by ordinary backend code.
"""

import asyncio
import contextlib
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import openai
import structlog
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chat.budget import (
    PURPOSE_BUDGETS,
    BudgetTracker,
    ProviderLimits,
    Purpose,
    estimate_tokens,
    limit_to_tokens,
    parse_duration,
)
from app.chat.circuit import BreakerState, CircuitBreaker
from app.chat.prompts import build_system_prompt
from app.chat.schema import strict_json_schema
from app.chat.types import (
    GatewayError,
    LlmResult,
    Message,
    PromptTooLargeError,
    ProviderError,
    ProviderErrorKind,
    ProviderResponse,
)
from app.core.config import Settings
from app.db.models import AppSetting, LlmUsage

logger = structlog.get_logger(__name__)

TEMPERATURE = 0.2
CONFIG_CACHE_SECONDS = 10.0
MAX_COOLDOWN_SECONDS = 300.0
DEFAULT_COOLDOWN_SECONDS = 10.0
GROQ_DEFAULT_LIMITS = ProviderLimits(rpm=30, rpd=1000, tpm=8000, tpd=200_000)
SETTING_KEYS = (
    "llm_primary",
    "llm_budget_failover_threshold",
    *(f"{p}_{m}" for p in ("groq", "gemini") for m in ("rpm", "rpd", "tpm", "tpd")),
)
REPAIR_INSTRUCTION = (
    "Your last reply could not be used: {problem}. "
    "Reply again with only a JSON object that matches the required schema."
)

FallbackFactory = Callable[[], Awaitable[str | None]]


# --- providers ---------------------------------------------------------------------------------


class LlmProvider(Protocol):
    name: str
    model: str
    reset_tz: str
    counts_output_tokens: bool

    async def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
        schema_name: str,
        timeout: float,  # noqa: ASYNC109
    ) -> ProviderResponse: ...


def _retry_after(headers: Mapping[str, str]) -> float | None:
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return parse_duration(value)


class GroqProvider:
    """Groq through its OpenAI compatible endpoint, using the ``openai`` SDK."""

    name = "groq"
    counts_output_tokens = True

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        *,
        reset_tz: str = "UTC",
        reasoning_headroom: int = 100,
        http_client: Any = None,
    ) -> None:
        self.model = model
        self.reset_tz = reset_tz
        self.reasoning_headroom = reasoning_headroom
        # Retries are the gateway's job (failover), so the SDK must not retry on its own.
        self._client = openai.AsyncOpenAI(
            api_key=api_key, base_url=base_url, max_retries=0, http_client=http_client
        )

    @property
    def is_reasoning_model(self) -> bool:
        return self.model.startswith("openai/gpt-oss")

    async def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
        schema_name: str,
        timeout: float,  # noqa: ASYNC109
    ) -> ProviderResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": TEMPERATURE,
            "messages": [
                {"role": "system", "content": system},
                *({"role": m.role, "content": m.content} for m in messages),
            ],
            "max_completion_tokens": max_tokens,
            "timeout": timeout,
        }
        extra: dict[str, Any] = {}
        if self.is_reasoning_model:
            # Reasoning tokens count against the completion limit and against rate limits, so
            # use the lowest effort and leave the reasoning out of the response.
            extra = {"reasoning_effort": "low", "include_reasoning": False}
            body["max_completion_tokens"] = max_tokens + self.reasoning_headroom
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": json_schema},
            }
        try:
            raw = await self._client.chat.completions.with_raw_response.create(
                **body, extra_body=extra or None
            )
        except openai.APITimeoutError as exc:
            raise ProviderError(ProviderErrorKind.TIMEOUT, "request timed out") from exc
        except openai.APIConnectionError as exc:
            raise ProviderError(ProviderErrorKind.CONNECTION, "connection failed") from exc
        except openai.APIStatusError as exc:
            headers = {k.lower(): v for k, v in exc.response.headers.items()}
            raise _status_error(exc.status_code, headers) from exc
        headers = {k.lower(): v for k, v in raw.headers.items()}
        completion = raw.parse()
        choice = completion.choices[0] if completion.choices else None
        usage = completion.usage
        details = getattr(usage, "prompt_tokens_details", None) if usage else None
        return ProviderResponse(
            text=(choice.message.content or "") if choice else "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            cached_tokens=int(getattr(details, "cached_tokens", 0) or 0),
            finish_reason=choice.finish_reason if choice else None,
            headers=headers,
        )


def _status_error(status: int, headers: Mapping[str, str]) -> ProviderError:
    if status == 429:
        return ProviderError(
            ProviderErrorKind.RATE_LIMITED,
            "rate limited",
            status_code=status,
            retry_after=_retry_after(headers),
            headers=headers,
        )
    if status >= 500:
        return ProviderError(
            ProviderErrorKind.SERVER_ERROR,
            f"server error {status}",
            status_code=status,
            headers=headers,
        )
    if status in (401, 403):
        return ProviderError(
            ProviderErrorKind.AUTH,
            f"authentication failed {status}",
            status_code=status,
            headers=headers,
        )
    return ProviderError(
        ProviderErrorKind.BAD_REQUEST,
        f"request rejected {status}",
        status_code=status,
        headers=headers,
    )


class GeminiProvider:
    """Gemini through the ``google-genai`` SDK."""

    name = "gemini"
    # Free tier token limits are measured on input tokens.
    counts_output_tokens = False

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        reset_tz: str = "America/Los_Angeles",
        thinking_budget: int = 0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.reset_tz = reset_tz
        self.thinking_budget = thinking_budget
        options = genai_types.HttpOptions(httpx_async_client=http_client) if http_client else None
        self._client = genai.Client(api_key=api_key, http_options=options)

    async def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
        schema_name: str,
        timeout: float,  # noqa: ASYNC109
    ) -> ProviderResponse:
        config = genai_types.GenerateContentConfig(
            system_instruction=system,
            temperature=TEMPERATURE,
            max_output_tokens=max_tokens,
            http_options=genai_types.HttpOptions(timeout=int(timeout * 1000)),
        )
        if self.thinking_budget >= 0:
            config.thinking_config = genai_types.ThinkingConfig(
                thinking_budget=self.thinking_budget
            )
        if json_schema is not None:
            config.response_mime_type = "application/json"
            config.response_json_schema = json_schema
        contents: list[Any] = [
            genai_types.Content(
                role="user" if m.role == "user" else "model",
                parts=[genai_types.Part(text=m.content)],
            )
            for m in messages
        ]
        try:
            response = await self._client.aio.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except genai_errors.APIError as exc:
            raise _gemini_error(exc) from exc
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise ProviderError(ProviderErrorKind.TIMEOUT, "request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ProviderErrorKind.CONNECTION, "connection failed") from exc
        usage = response.usage_metadata
        candidates = response.candidates or []
        reason = candidates[0].finish_reason if candidates else None
        return ProviderResponse(
            text=response.text or "",
            prompt_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
            completion_tokens=int(getattr(usage, "candidates_token_count", 0) or 0)
            + int(getattr(usage, "thoughts_token_count", 0) or 0),
            cached_tokens=int(getattr(usage, "cached_content_token_count", 0) or 0),
            finish_reason=str(getattr(reason, "name", reason)) if reason is not None else None,
        )


def _gemini_error(exc: genai_errors.APIError) -> ProviderError:
    code = int(getattr(exc, "code", 0) or 0)
    error = _status_error(code if code else 500, {})
    if error.kind is ProviderErrorKind.RATE_LIMITED:
        match = re.search(r"retry in ([\d.]+)s|\"retryDelay\":\s*\"([\d.]+)s\"", str(exc))
        if match:
            error.retry_after = float(match.group(1) or match.group(2))
    return error


def build_providers(
    settings: Settings, http_client: httpx.AsyncClient | None = None
) -> dict[str, LlmProvider]:
    """The providers that have credentials. A provider without a key or model is not used."""
    providers: dict[str, LlmProvider] = {}
    if settings.groq_api_key and settings.groq_model:
        providers["groq"] = GroqProvider(
            settings.groq_api_key,
            settings.groq_model,
            settings.groq_base_url,
            reset_tz=settings.groq_reset_tz,
            reasoning_headroom=settings.groq_reasoning_headroom,
            http_client=http_client,
        )
    if settings.gemini_api_key and settings.gemini_model:
        providers["gemini"] = GeminiProvider(
            settings.gemini_api_key,
            settings.gemini_model,
            reset_tz=settings.gemini_reset_tz,
            thinking_budget=settings.gemini_thinking_budget,
            http_client=http_client,
        )
    return providers


# --- gateway -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GatewayConfig:
    primary: str
    threshold: float
    limits: dict[str, ProviderLimits]


def default_degraded_message(settings: Settings) -> str:
    return (
        "I am sorry, I cannot answer that right now. You can book online at "
        f"{settings.public_base_url}/book or call us at {settings.clinic_phone}."
    )


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    return match.group(1) if match else cleaned


class LlmGateway:
    def __init__(
        self,
        *,
        settings: Settings,
        redis: Redis,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        providers: Mapping[str, LlmProvider] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self.redis = redis
        self.session_factory = session_factory
        self.providers: dict[str, LlmProvider] = dict(
            providers if providers is not None else build_providers(settings)
        )
        self.clock = clock
        self.budget = BudgetTracker(redis, clock)
        self.breaker = CircuitBreaker(
            redis, settings.llm_circuit_failures, settings.llm_circuit_open_seconds, clock
        )
        # Built once: the first message of every request, identical down to the byte.
        self.system_prompt = build_system_prompt(settings)
        self._config_cache: tuple[float, GatewayConfig] | None = None

    # --- configuration ---

    async def config(self) -> GatewayConfig:
        now = self.clock()
        if self._config_cache and now - self._config_cache[0] < CONFIG_CACHE_SECONDS:
            return self._config_cache[1]
        stored: dict[str, Any] = {}
        if self.session_factory is not None:
            try:
                async with self.session_factory() as db:
                    rows = await db.execute(
                        select(AppSetting).where(AppSetting.key.in_(SETTING_KEYS))
                    )
                    stored = {row.key: row.value for row in rows.scalars()}
            except Exception:  # noqa: BLE001
                logger.warning("llm_config_unavailable")

        def limit(provider: str, metric: str, default: int | None) -> int | None:
            value = stored.get(f"{provider}_{metric}", default)
            return int(value) if value is not None else None

        limits = {
            "groq": ProviderLimits(
                *(
                    limit("groq", m, getattr(GROQ_DEFAULT_LIMITS, m))
                    for m in ("rpm", "rpd", "tpm", "tpd")
                )
            ),
            # Gemini limits depend on the model and the account and are read from Google AI
            # Studio into app_settings. Until they are entered nothing is enforced locally and
            # the provider's own 429 responses drive failover.
            "gemini": ProviderLimits(
                *(limit("gemini", m, None) for m in ("rpm", "rpd", "tpm", "tpd"))
            ),
        }
        primary = str(stored.get("llm_primary") or self.settings.llm_primary)
        threshold = float(stored.get("llm_budget_failover_threshold", 0.8))
        config = GatewayConfig(
            primary if primary in ("groq", "gemini") else "groq", threshold, limits
        )
        self._config_cache = (now, config)
        return config

    def invalidate_config(self) -> None:
        self._config_cache = None

    def _order(self, config: GatewayConfig, force_provider: str | None) -> list[LlmProvider]:
        if force_provider is not None:
            provider = self.providers.get(force_provider)
            return [provider] if provider else []
        names = [config.primary, "gemini" if config.primary == "groq" else "groq"]
        return [self.providers[n] for n in names if n in self.providers]

    # --- the one public call ---

    async def complete(
        self,
        messages: list[Message],
        max_tokens: int,
        json_schema: type[BaseModel] | None = None,
        *,
        purpose: Purpose,
        session_id: Any = None,
        fallback: FallbackFactory | None = None,
        force_provider: str | None = None,
    ) -> LlmResult:
        """Run one completion and return the model's answer, or a fixed fallback."""
        if not messages:
            raise GatewayError("at least one message is required")
        if any(m.role not in ("user", "assistant") for m in messages):
            # The system prompt is fixed. Callers can only add user and assistant messages.
            raise GatewayError("only user and assistant messages are accepted")
        budget = PURPOSE_BUDGETS[purpose]
        max_tokens = max(1, min(max_tokens, budget.max_completion_tokens))
        dynamic_tokens = sum(estimate_tokens(m.content) for m in messages)
        if dynamic_tokens > budget.max_prompt_tokens:
            raise PromptTooLargeError(
                f"{purpose.value} allows {budget.max_prompt_tokens} prompt tokens, got about {dynamic_tokens}"
            )
        estimate = estimate_tokens(self.system_prompt) + dynamic_tokens + max_tokens

        config = await self.config()
        order = self._order(config, force_provider)
        first = order[0].name if order else None
        schema = strict_json_schema(json_schema) if json_schema is not None else None

        for provider in order:
            skip = await self._skip_reason(provider, config, estimate)
            if skip is not None:
                logger.info(
                    "llm_provider_skipped",
                    provider=provider.name,
                    reason=skip,
                    purpose=purpose.value,
                )
                continue
            result = await self._attempt(
                provider,
                messages,
                max_tokens,
                json_schema,
                schema,
                purpose,
                session_id,
                failover_from=first if provider.name != first else None,
            )
            if result is not None:
                return result
        return await self._degrade(fallback, purpose)

    # --- choosing a provider ---

    async def _skip_reason(
        self, provider: LlmProvider, config: GatewayConfig, estimate: int
    ) -> str | None:
        if await self.redis.exists(f"llm:cool:{provider.name}"):
            return "cooldown"
        limits = config.limits.get(provider.name, ProviderLimits())
        used = await self.budget.utilization(provider.name, limits, provider.reset_tz, estimate)
        if used.ratio > config.threshold:
            return f"budget:{used.limit}"
        permit = await self.breaker.allow(provider.name)  # last: it may hand out the probe
        if not permit.allowed:
            return f"circuit:{permit.state.value}"
        return None

    # --- one provider ---

    async def _call(
        self,
        provider: LlmProvider,
        messages: list[Message],
        max_tokens: int,
        schema: dict[str, Any] | None,
        schema_name: str,
    ) -> ProviderResponse:
        timeout = self.settings.llm_timeout_seconds
        try:
            async with asyncio.timeout(timeout * 1.25 + 0.25):
                return await provider.complete(
                    self.system_prompt,
                    messages,
                    max_tokens=max_tokens,
                    json_schema=schema,
                    schema_name=schema_name,
                    timeout=timeout,
                )
        except ProviderError:
            raise
        except TimeoutError as exc:
            raise ProviderError(ProviderErrorKind.TIMEOUT, "request timed out") from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(ProviderErrorKind.UNKNOWN, type(exc).__name__) from exc

    async def _attempt(
        self,
        provider: LlmProvider,
        messages: list[Message],
        max_tokens: int,
        model_class: type[BaseModel] | None,
        schema: dict[str, Any] | None,
        purpose: Purpose,
        session_id: Any,
        *,
        failover_from: str | None,
    ) -> LlmResult | None:
        schema_name = model_class.__name__ if model_class else "reply"
        history = list(messages)
        repaired = False
        total_latency = 0
        for attempt in range(2):  # the first call, and at most one repair
            started = time.perf_counter()
            try:
                response = await self._call(provider, history, max_tokens, schema, schema_name)
            except ProviderError as error:
                latency = int((time.perf_counter() - started) * 1000)
                await self._record_failure(
                    provider, error, purpose, session_id, latency, failover_from
                )
                return None
            latency = int((time.perf_counter() - started) * 1000)
            total_latency += latency
            await self.breaker.record_success(provider.name)  # the provider is reachable
            await self._record_usage_counters(provider, response)

            text = response.text.strip()
            if not text:
                status = (
                    "truncated"
                    if response.finish_reason in ("length", "MAX_TOKENS")
                    else "empty_output"
                )
                await self._log(
                    provider, purpose, status, response, latency, session_id, failover_from
                )
                return None

            parsed: BaseModel | None = None
            if model_class is not None:
                try:
                    parsed = model_class.model_validate_json(_strip_fences(text))
                except (ValidationError, ValueError) as exc:
                    await self._log(
                        provider,
                        purpose,
                        "invalid_output",
                        response,
                        latency,
                        session_id,
                        failover_from,
                    )
                    if attempt == 0 and response.finish_reason not in ("length", "MAX_TOKENS"):
                        repaired = True
                        problem = re.sub(r"\s+", " ", str(exc))[:200]
                        history = [
                            *messages,
                            Message("assistant", text[:500]),
                            Message("user", REPAIR_INSTRUCTION.format(problem=problem)),
                        ]
                        continue
                    return None
                answer = _strip_fences(text)
            else:
                answer = limit_to_tokens(text, max_tokens)

            await self._log(provider, purpose, "ok", response, latency, session_id, failover_from)
            return LlmResult(
                text=answer,
                parsed=parsed,
                provider=provider.name,
                model=provider.model,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                cached_tokens=response.cached_tokens,
                latency_ms=total_latency,
                failover_from=failover_from,
                repaired=repaired,
            )
        return None

    # --- bookkeeping ---

    async def _record_usage_counters(
        self, provider: LlmProvider, response: ProviderResponse
    ) -> None:
        tokens = response.prompt_tokens
        if provider.counts_output_tokens:
            tokens += response.completion_tokens
        tokens = max(tokens - response.cached_tokens, 0)  # cached tokens do not count
        await self.budget.record(provider.name, provider.reset_tz, tokens)
        await self._apply_hints(provider, response.headers)

    async def _apply_hints(self, provider: LlmProvider, headers: Mapping[str, str]) -> None:
        """Correct our counters from Groq's rate limit headers."""

        def number(name: str) -> int | None:
            try:
                return int(float(headers[name]))
            except (KeyError, ValueError):
                return None

        if (
            "x-ratelimit-remaining-tokens" not in headers
            and "x-ratelimit-remaining-requests" not in headers
        ):
            return
        await self.budget.apply_server_hints(
            provider.name,
            limit_tokens=number("x-ratelimit-limit-tokens"),
            remaining_tokens=number("x-ratelimit-remaining-tokens"),
            reset_tokens_seconds=parse_duration(headers.get("x-ratelimit-reset-tokens")),
            limit_requests=number("x-ratelimit-limit-requests"),
            remaining_requests=number("x-ratelimit-remaining-requests"),
            reset_requests_seconds=parse_duration(headers.get("x-ratelimit-reset-requests")),
        )

    async def _record_failure(
        self,
        provider: LlmProvider,
        error: ProviderError,
        purpose: Purpose,
        session_id: Any,
        latency_ms: int,
        failover_from: str | None,
    ) -> None:
        failures = await self.breaker.record_failure(provider.name)
        if error.kind is ProviderErrorKind.RATE_LIMITED:
            wait = min(error.retry_after or DEFAULT_COOLDOWN_SECONDS, MAX_COOLDOWN_SECONDS)
            await self.redis.set(f"llm:cool:{provider.name}", "1", ex=max(1, int(wait + 0.999)))
            await self._apply_hints(provider, error.headers)
        logger.warning(
            "llm_provider_failed",
            provider=provider.name,
            kind=error.kind.value,
            status=error.status_code,
            consecutive_failures=failures,
            purpose=purpose.value,
        )
        await self._log(
            provider, purpose, error.kind.value, None, latency_ms, session_id, failover_from
        )

    async def _log(
        self,
        provider: LlmProvider,
        purpose: Purpose,
        status: str,
        response: ProviderResponse | None,
        latency_ms: int,
        session_id: Any,
        failover_from: str | None,
    ) -> None:
        """Write one ``llm_usage`` row. A logging problem never breaks the conversation."""
        if self.session_factory is None:
            return
        try:
            async with self.session_factory() as db:
                db.add(
                    LlmUsage(
                        session_id=session_id,
                        provider=provider.name,
                        model=provider.model,
                        purpose=purpose.value,
                        prompt_tokens=response.prompt_tokens if response else 0,
                        completion_tokens=response.completion_tokens if response else 0,
                        cached_tokens=response.cached_tokens if response else 0,
                        latency_ms=latency_ms,
                        status=status,
                        fallback_from=failover_from,
                    )
                )
                await db.commit()
        except Exception:  # noqa: BLE001
            logger.warning("llm_usage_log_failed", provider=provider.name)

    # --- nothing answered ---

    async def _degrade(self, fallback: FallbackFactory | None, purpose: Purpose) -> LlmResult:
        text: str | None = None
        if fallback is not None:
            try:
                text = await fallback()
            except Exception:  # noqa: BLE001
                logger.warning("llm_fallback_failed")
        logger.error("llm_degraded", purpose=purpose.value)
        with contextlib.suppress(Exception):
            day = time.strftime("%Y%m%d", time.gmtime(self.clock()))
            await self.redis.incr(f"llm:stats:degraded:{day}")
        return LlmResult(text=text or default_degraded_message(self.settings), degraded=True)

    # --- administration ---

    async def status(self) -> dict[str, Any]:
        config = await self.config()
        now = self.clock()
        providers: dict[str, Any] = {}
        for name in ("groq", "gemini"):
            provider = self.providers.get(name)
            if provider is None:
                providers[name] = {"configured": False}
                continue
            limits = config.limits.get(name, ProviderLimits())
            usage = await self.budget.usage(name, provider.reset_tz)
            utilization = await self.budget.utilization(name, limits, provider.reset_tz, 0)
            cooldown = await self.redis.ttl(f"llm:cool:{name}")
            providers[name] = {
                "configured": True,
                "model": provider.model,
                "breaker": await self.breaker.snapshot(name),
                "cooldown_seconds": max(int(cooldown), 0),
                "limits": {
                    "rpm": limits.rpm,
                    "rpd": limits.rpd,
                    "tpm": limits.tpm,
                    "tpd": limits.tpd,
                },
                "usage": {"rpm": usage.rpm, "rpd": usage.rpd, "tpm": usage.tpm, "tpd": usage.tpd},
                "utilization": round(utilization.ratio, 3),
                "busiest_limit": utilization.limit,
            }
        return {
            "primary": config.primary,
            "order": [p.name for p in self._order(config, None)],
            "failover_threshold": config.threshold,
            "providers": providers,
            "checked_at": now,
        }

    async def breaker_state(self, provider: str) -> BreakerState:
        return await self.breaker.state(provider)
