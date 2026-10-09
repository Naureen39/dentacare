"""Failover, budgets, cooldowns and the circuit breaker, with scripted providers."""

import asyncio

import pytest

from app.chat.budget import Purpose, estimate_tokens
from app.chat.circuit import BreakerState
from app.chat.types import Message, ProviderError, ProviderErrorKind
from tests.chat.conftest import FakeClock, Rig, RigFactory, fail, never_returns, ok

ASK = [Message("user", "What time do you open?")]
SECRET = "boom: secret internal detail 0xDEADBEEF"


async def ask(rig: Rig, **kwargs):  # type: ignore[no-untyped-def]
    return await rig.gateway.complete(ASK, 160, purpose=Purpose.FAQ_ANSWER, **kwargs)


# --- the happy path ------------------------------------------------------------------------------


async def test_the_primary_provider_answers_when_everything_is_healthy(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(groq=[ok("We open at 8:00 AM.", prompt=300, completion=15, cached=200)])
    result = await ask(rig)

    assert (result.text, result.provider, result.model) == (
        "We open at 8:00 AM.",
        "groq",
        "openai/gpt-oss-20b",
    )
    assert (result.prompt_tokens, result.completion_tokens, result.cached_tokens) == (300, 15, 200)
    assert result.degraded is False and result.failover_from is None and result.repaired is False
    assert len(rig.groq.calls) == 1 and rig.gemini.calls == []


async def test_the_primary_comes_from_the_environment_setting(make_rig: RigFactory) -> None:
    rig = make_rig(llm_primary="gemini")
    result = await ask(rig)
    assert result.provider == "gemini" and rig.groq.calls == []


async def test_a_provider_without_credentials_is_not_used(make_rig: RigFactory) -> None:
    rig = make_rig(providers=("gemini",))
    result = await ask(rig)
    assert result.provider == "gemini" and result.failover_from is None


# --- failover on errors ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        fail(ProviderErrorKind.RATE_LIMITED, status=429, retry_after=2),
        fail(ProviderErrorKind.SERVER_ERROR, status=503),
        fail(ProviderErrorKind.SERVER_ERROR, status=500),
        fail(ProviderErrorKind.TIMEOUT),
        fail(ProviderErrorKind.CONNECTION),
        fail(ProviderErrorKind.AUTH, status=401),
        fail(ProviderErrorKind.BAD_REQUEST, status=400),
        RuntimeError(SECRET),
    ],
)
async def test_every_kind_of_provider_failure_fails_over(
    make_rig: RigFactory, error: ProviderError | Exception
) -> None:
    rig = make_rig(groq=[error], gemini=[ok("backup answer")])
    result = await ask(rig)

    assert result.text == "backup answer" and result.provider == "gemini"
    assert result.failover_from == "groq" and result.degraded is False
    assert len(rig.groq.calls) == 1 and len(rig.gemini.calls) == 1


async def test_a_slow_provider_is_abandoned_after_the_timeout(make_rig: RigFactory) -> None:
    rig = make_rig(groq=[never_returns], gemini=[ok("fast answer")], llm_timeout_seconds=0.05)
    started = asyncio.get_running_loop().time()
    result = await ask(rig)
    elapsed = asyncio.get_running_loop().time() - started

    assert result.provider == "gemini" and result.failover_from == "groq"
    assert elapsed < 1.0  # the 30 second hang never reached the caller
    assert rig.groq.calls[0].timeout == 0.05  # the provider also received the limit


async def test_the_default_timeout_is_eight_seconds() -> None:
    from app.core.config import Settings

    assert Settings().llm_timeout_seconds == 8.0


async def test_rate_limit_responses_start_a_cooldown_that_skips_the_provider(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(
        groq=[fail(ProviderErrorKind.RATE_LIMITED, status=429, retry_after=30)], gemini=[ok("g1")]
    )
    assert (await ask(rig)).provider == "gemini"
    ttl = await rig.redis.ttl("llm:cool:groq")
    assert 25 <= ttl <= 30

    again = await ask(rig)
    assert again.provider == "gemini" and len(rig.groq.calls) == 1  # groq was not even tried

    await rig.redis.delete("llm:cool:groq")  # the cooldown ends
    rig.groq.script = [ok("groq is back")]
    assert (await ask(rig)).provider == "groq"


async def test_cooldowns_are_capped_and_have_a_default(make_rig: RigFactory) -> None:
    rig = make_rig(groq=[fail(ProviderErrorKind.RATE_LIMITED, status=429, retry_after=100_000)])
    await ask(rig)
    assert await rig.redis.ttl("llm:cool:groq") <= 300
    rig2 = make_rig(groq=[fail(ProviderErrorKind.RATE_LIMITED, status=429)])
    await rig2.redis.flushall()
    await ask(rig2)
    assert 1 <= await rig2.redis.ttl("llm:cool:groq") <= 10


async def test_failover_is_transparent_to_the_next_request_after_recovery(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(
        groq=[fail(ProviderErrorKind.SERVER_ERROR, status=500), ok("groq again")], gemini=[ok("g")]
    )
    assert (await ask(rig)).provider == "gemini"
    assert (await ask(rig)).provider == "groq"  # one failure is not enough to avoid the primary


# --- nothing answers: a fixed fallback, never an error ---------------------------------------------------


async def test_when_both_providers_fail_a_degraded_reply_offers_booking_and_the_phone(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(
        groq=[RuntimeError(SECRET)], gemini=[fail(ProviderErrorKind.RATE_LIMITED, status=429)]
    )
    result = await ask(rig)

    assert result.degraded is True and result.provider is None and result.parsed is None
    assert "(555) 010-0199" in result.text and "https://clinic.example/book" in result.text
    assert SECRET not in result.text and "429" not in result.text and "Traceback" not in result.text
    assert chr(0x2014) not in result.text


async def test_the_degraded_reply_prefers_the_supplied_faq_answer(make_rig: RigFactory) -> None:
    async def faq() -> str:
        return "We are open weekdays 8:00 AM to 6:00 PM."

    rig = make_rig(groq=[fail()], gemini=[fail()])
    result = await ask(rig, fallback=faq)
    assert result.degraded and result.text == "We are open weekdays 8:00 AM to 6:00 PM."


@pytest.mark.parametrize("faq_result", ["none", "raises"])
async def test_a_missing_or_broken_faq_fallback_uses_the_fixed_message(
    make_rig: RigFactory, faq_result: str
) -> None:
    async def faq() -> str | None:
        if faq_result == "raises":
            raise RuntimeError("database down")
        return None

    rig = make_rig(groq=[fail()], gemini=[fail()])
    result = await ask(rig, fallback=faq)
    assert result.degraded and "call us at (555) 010-0199" in result.text


async def test_no_configured_provider_degrades_immediately(make_rig: RigFactory) -> None:
    rig = make_rig(providers=())
    result = await ask(rig)
    assert result.degraded and "(555) 010-0199" in result.text


async def test_degraded_replies_are_counted(make_rig: RigFactory) -> None:
    rig = make_rig(groq=[fail()], gemini=[fail()])
    await ask(rig)
    await ask(rig)
    keys = [k async for k in rig.redis.scan_iter("llm:stats:degraded:*")]
    assert len(keys) == 1 and await rig.redis.get(keys[0]) == "2"


# --- local budgets ---------------------------------------------------------------------------------------


async def set_limits(rig: Rig, provider: str, **limits: int | None) -> None:
    from app.chat.budget import ProviderLimits
    from app.chat.llm_gateway import GatewayConfig

    config = await rig.gateway.config()
    merged = dict(config.limits)
    merged[provider] = ProviderLimits(**limits)
    rig.gateway._config_cache = (
        rig.clock(),
        GatewayConfig(config.primary, config.threshold, merged),
    )


async def test_requests_per_minute_above_80_percent_switch_to_the_other_provider(
    make_rig: RigFactory,
) -> None:
    rig = make_rig()
    await set_limits(rig, "groq", rpm=10)

    providers = [(await ask(rig)).provider for _ in range(10)]
    # Eight of ten requests is exactly 80 percent, which is allowed. The ninth would be 90.
    assert providers == ["groq"] * 8 + ["gemini"] * 2
    assert rig.groq.calls.__len__() == 8


async def test_tokens_per_minute_above_80_percent_switch_to_the_other_provider(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(groq=[ok("a", prompt=1500, completion=100)])
    await set_limits(rig, "groq", tpm=8000)
    first = await ask(rig)
    second = await ask(rig)
    third = await ask(rig)
    # Each call uses 1,600 tokens; the estimate for the next one is around 600 more.
    assert [first.provider, second.provider, third.provider] == ["groq", "groq", "groq"]
    fourth, fifth = await ask(rig), await ask(rig)
    assert fourth.provider == "groq" and fifth.provider == "gemini"
    assert fifth.failover_from == "groq"


async def test_the_daily_request_limit_is_enforced(make_rig: RigFactory) -> None:
    rig = make_rig()
    await set_limits(rig, "groq", rpd=100)
    for _ in range(79):
        await rig.gateway.budget.record("groq", "UTC", 10)
    assert (await ask(rig)).provider == "groq"  # the 80th request is exactly 80 percent
    assert (await ask(rig)).provider == "gemini"


async def test_the_daily_token_limit_is_enforced(make_rig: RigFactory) -> None:
    rig = make_rig()
    await set_limits(rig, "groq", tpd=200_000)
    await rig.gateway.budget.record("groq", "UTC", 159_000)
    assert (await ask(rig)).provider == "groq"
    await rig.gateway.budget.record("groq", "UTC", 1_000)
    assert (await ask(rig)).provider == "gemini"


async def test_a_new_day_clears_the_daily_counters(make_rig: RigFactory, clock: FakeClock) -> None:
    rig = make_rig()
    await set_limits(rig, "groq", rpd=10)
    for _ in range(9):
        await rig.gateway.budget.record("groq", "UTC", 10)
    assert (await ask(rig)).provider == "gemini"
    clock.advance(24 * 3600)
    rig.gateway.invalidate_config()
    await set_limits(rig, "groq", rpd=10)
    assert (await ask(rig)).provider == "groq"


async def test_when_both_providers_are_over_budget_the_reply_is_degraded(
    make_rig: RigFactory,
) -> None:
    rig = make_rig()
    await set_limits(rig, "groq", rpm=1)
    await set_limits(rig, "gemini", rpm=1)
    await rig.gateway.budget.record("groq", "UTC", 10)
    await rig.gateway.budget.record("gemini", "America/Los_Angeles", 10)
    result = await ask(rig)
    assert result.degraded and rig.groq.calls == [] and rig.gemini.calls == []


async def test_unknown_limits_mean_no_local_throttling(make_rig: RigFactory) -> None:
    rig = make_rig(llm_primary="gemini")
    await set_limits(rig, "gemini")  # all None, as before an administrator enters them
    for _ in range(40):
        await rig.gateway.budget.record("gemini", "America/Los_Angeles", 50_000)
    assert (await ask(rig)).provider == "gemini"


async def test_cached_prompt_tokens_do_not_count_against_the_budget(make_rig: RigFactory) -> None:
    rig = make_rig(groq=[ok("a", prompt=1000, completion=50, cached=900)])
    await ask(rig)
    usage = await rig.gateway.budget.usage("groq", "UTC")
    assert usage.tpm == 150 and usage.tpd == 150  # 1,050 minus 900 served from cache


async def test_gemini_counts_input_tokens_only(make_rig: RigFactory) -> None:
    rig = make_rig(llm_primary="gemini", gemini=[ok("a", prompt=500, completion=300)])
    await ask(rig)
    assert (await rig.gateway.budget.usage("gemini", "America/Los_Angeles")).tpm == 500


async def test_groq_rate_limit_headers_correct_the_local_counters(make_rig: RigFactory) -> None:
    headers = {
        "x-ratelimit-limit-tokens": "8000",
        "x-ratelimit-remaining-tokens": "600",
        "x-ratelimit-reset-tokens": "7.66s",
        "x-ratelimit-limit-requests": "1000",
        "x-ratelimit-remaining-requests": "990",
        "x-ratelimit-reset-requests": "2m59.56s",
    }
    rig = make_rig(groq=[ok("a", prompt=100, completion=10, headers=headers)])
    await set_limits(rig, "groq", tpm=8000)
    assert (await ask(rig)).provider == "groq"
    # Groq says 7,400 of 8,000 tokens are used this minute although we only counted 110.
    assert (await rig.gateway.budget.usage("groq", "UTC")).tpm == 7400
    assert (await ask(rig)).provider == "gemini"


async def test_retry_after_and_headers_on_a_429_are_honoured(make_rig: RigFactory) -> None:
    headers = {
        "retry-after": "12",
        "x-ratelimit-limit-tokens": "8000",
        "x-ratelimit-remaining-tokens": "0",
        "x-ratelimit-reset-tokens": "12s",
    }
    rig = make_rig(
        groq=[fail(ProviderErrorKind.RATE_LIMITED, status=429, retry_after=12, headers=headers)]
    )
    await ask(rig)
    assert 9 <= await rig.redis.ttl("llm:cool:groq") <= 12
    assert (await rig.gateway.budget.usage("groq", "UTC")).tpm == 8000


# --- circuit breaker through the gateway ---------------------------------------------------------------


async def test_the_breaker_stops_calling_a_failing_provider_and_recovers(
    make_rig: RigFactory, clock: FakeClock
) -> None:
    rig = make_rig(
        groq=[fail(), fail(), fail(), ok("groq recovered")], gemini=[ok("gemini answer")]
    )

    for _ in range(3):  # three consecutive failures, each answered by the fallback
        assert (await ask(rig)).provider == "gemini"
    assert await rig.gateway.breaker_state("groq") is BreakerState.OPEN

    assert (await ask(rig)).provider == "gemini"
    assert len(rig.groq.calls) == 3  # the open breaker kept the fourth request away from groq

    clock.advance(61)  # half open: one probe is allowed
    result = await ask(rig)
    assert result.provider == "groq" and result.text == "groq recovered"
    assert await rig.gateway.breaker_state("groq") is BreakerState.CLOSED
    assert (await ask(rig)).provider == "groq"


async def test_a_failed_probe_keeps_the_provider_out_for_another_minute(
    make_rig: RigFactory, clock: FakeClock
) -> None:
    rig = make_rig(groq=[fail()], gemini=[ok("gemini answer")])
    for _ in range(3):
        await ask(rig)
    clock.advance(61)
    assert (await ask(rig)).provider == "gemini"  # the probe went to groq and failed
    assert len(rig.groq.calls) == 4
    clock.advance(30)
    await ask(rig)
    assert len(rig.groq.calls) == 4  # still open
    clock.advance(31)
    await ask(rig)
    assert len(rig.groq.calls) == 5  # next probe


async def test_two_failures_followed_by_a_success_do_not_open_the_breaker(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(groq=[fail(), fail(), ok("fine"), fail(), fail()], gemini=[ok("g")])
    providers = [(await ask(rig)).provider for _ in range(5)]
    assert providers == ["gemini", "gemini", "groq", "gemini", "gemini"]
    assert await rig.gateway.breaker_state("groq") is BreakerState.CLOSED


async def test_budget_skips_do_not_count_as_failures(make_rig: RigFactory) -> None:
    rig = make_rig()
    await set_limits(rig, "groq", rpm=1)
    for _ in range(6):
        await ask(rig)
    assert await rig.gateway.breaker_state("groq") is BreakerState.CLOSED


async def test_a_probe_slot_is_not_wasted_when_the_budget_skips_the_provider(
    make_rig: RigFactory, clock: FakeClock
) -> None:
    rig = make_rig(groq=[fail(), fail(), fail(), ok("back")], gemini=[ok("g")])
    for _ in range(3):
        await ask(rig)
    clock.advance(61)
    await set_limits(rig, "groq", rpm=1)
    await rig.gateway.budget.record("groq", "UTC", 10)
    assert (await ask(rig)).provider == "gemini"  # skipped for budget before the probe was taken
    assert await rig.redis.exists("llm:cb:groq:probe") == 0


async def test_both_providers_can_be_unavailable_and_then_come_back(
    make_rig: RigFactory, clock: FakeClock
) -> None:
    rig = make_rig(
        groq=[fail(), fail(), fail(), ok("groq back")],
        gemini=[fail(), fail(), fail(), ok("gemini back")],
    )
    for _ in range(3):
        assert (await ask(rig)).degraded
    assert (await ask(rig)).degraded  # both breakers are open now
    assert len(rig.groq.calls) == 3 and len(rig.gemini.calls) == 3
    clock.advance(61)
    result = await ask(rig)
    assert not result.degraded and result.provider == "groq"


async def test_force_provider_bypasses_the_order(make_rig: RigFactory) -> None:
    rig = make_rig()
    result = await ask(rig, force_provider="gemini")
    assert result.provider == "gemini" and result.failover_from is None and rig.groq.calls == []
    assert (await ask(rig, force_provider="missing")).degraded


def test_the_estimate_helper_is_what_the_budget_uses() -> None:
    assert estimate_tokens("What time do you open?") >= 5
    _ = ProviderError
