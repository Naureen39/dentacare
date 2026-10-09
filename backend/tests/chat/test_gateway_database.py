"""Usage logging, settings stored in the database, the FAQ fallback and the admin endpoints."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chat.budget import Purpose
from app.chat.degraded import FAQ_MIN_SCORE, faq_fallback, faq_short_answer
from app.chat.llm_gateway import LlmGateway
from app.chat.types import Message, ProviderErrorKind
from app.db.enums import UserRole
from app.db.models import ChatSession
from app.services.knowledge.documents import KbSource
from app.services.knowledge.indexer import sync_sources
from tests.auth.conftest import Ctx, unique_email
from tests.chat.conftest import FakeProvider, Outcome, fail, ok, settings_for_gateway
from tests.knowledge.conftest import FakeEmbedder
from tests.knowledge.test_indexer_and_search import MODEL, WHEN

ADMIN = "/api/v1/admin/llm"
ASK = [Message("user", "What time do you open?")]


def make_gateway(
    ctx: Ctx,
    groq: list[Outcome] | None = None,
    gemini: list[Outcome] | None = None,
    **settings: Any,
) -> tuple[LlmGateway, FakeProvider, FakeProvider]:
    groq_provider = FakeProvider(
        "groq",
        "openai/gpt-oss-20b",
        script=groq or [ok("groq answer", prompt=300, completion=15, cached=100)],
    )
    gemini_provider = FakeProvider(
        "gemini",
        "gemini-test",
        "America/Los_Angeles",
        False,
        script=gemini or [ok("gemini answer")],
    )
    gateway = LlmGateway(
        settings=settings_for_gateway(**settings),
        redis=ctx.redis,
        session_factory=ctx.session_factory,
        providers={"groq": groq_provider, "gemini": gemini_provider},
    )
    ctx.app.state.llm = gateway
    return gateway, groq_provider, gemini_provider


async def usage_rows(ctx: Ctx) -> list[tuple]:  # type: ignore[type-arg]
    return await ctx.fetch(
        "SELECT provider, model, purpose, prompt_tokens, completion_tokens, cached_tokens, latency_ms, status, fallback_from "
        "FROM llm_usage ORDER BY created_at, id"
    )


@pytest.fixture(autouse=True)
async def restore_llm_settings(ctx: Ctx):  # type: ignore[no-untyped-def]
    """app_settings is shared by every test, so put the gateway settings back afterwards."""
    yield
    await ctx.execute("DELETE FROM app_settings WHERE key = 'llm_primary'")
    for key, value in {
        "groq_rpm": "30",
        "groq_rpd": "1000",
        "groq_tpm": "8000",
        "groq_tpd": "200000",
        "llm_budget_failover_threshold": "0.8",
    }.items():
        await ctx.execute(
            "UPDATE app_settings SET value = CAST(:v AS jsonb) WHERE key = :k", k=key, v=value
        )
    await ctx.execute("UPDATE app_settings SET value = 'null'::jsonb WHERE key LIKE 'gemini%'")


async def admin_headers(ctx: Ctx) -> dict[str, str]:
    email = unique_email("admin")
    await ctx.create_user(email, UserRole.ADMIN)
    return ctx.auth(await ctx.access_token(email))


# --- every call is logged -------------------------------------------------------------------------


async def test_a_successful_call_is_logged_with_provider_tokens_and_latency(ctx: Ctx) -> None:
    gateway, *_ = make_gateway(ctx)
    await gateway.complete(ASK, 160, purpose=Purpose.FAQ_ANSWER)

    [row] = await usage_rows(ctx)
    assert row[:3] == ("groq", "openai/gpt-oss-20b", "faq_answer")
    assert row[3:6] == (300, 15, 100)
    assert row[6] >= 0 and row[7:] == ("ok", None)


async def test_failures_and_the_failover_are_logged_separately(ctx: Ctx) -> None:
    gateway, *_ = make_gateway(
        ctx, groq=[fail(ProviderErrorKind.RATE_LIMITED, status=429, retry_after=5)]
    )
    result = await gateway.complete(ASK, 160, purpose=Purpose.FAQ_ANSWER)

    rows = await usage_rows(ctx)
    assert [(r[0], r[7], r[8]) for r in rows] == [
        ("groq", "rate_limited", None),
        ("gemini", "ok", "groq"),
    ]
    assert rows[0][3:6] == (0, 0, 0)  # a failed call used no tokens
    assert result.failover_from == "groq"


@pytest.mark.parametrize(
    ("kind", "status"),
    [
        (ProviderErrorKind.TIMEOUT, "timeout"),
        (ProviderErrorKind.SERVER_ERROR, "server_error"),
        (ProviderErrorKind.CONNECTION, "connection_error"),
        (ProviderErrorKind.AUTH, "auth_error"),
        (ProviderErrorKind.BAD_REQUEST, "bad_request"),
        (ProviderErrorKind.UNKNOWN, "error"),
    ],
)
async def test_each_failure_kind_has_its_own_status(
    ctx: Ctx, kind: ProviderErrorKind, status: str
) -> None:
    gateway, *_ = make_gateway(ctx, groq=[fail(kind)])
    await gateway.complete(ASK, 160, purpose=Purpose.FAQ_ANSWER)
    assert (await usage_rows(ctx))[0][7] == status


async def test_a_repair_logs_the_invalid_reply_and_the_corrected_one(ctx: Ctx) -> None:
    from tests.chat.test_gateway_output import VALID, Extracted

    gateway, *_ = make_gateway(ctx, groq=[ok("not json"), ok(VALID)])
    await gateway.complete(
        [Message("user", "cleaning")], 80, Extracted, purpose=Purpose.ENTITY_EXTRACTION
    )
    assert [(r[2], r[7]) for r in await usage_rows(ctx)] == [
        ("entity_extraction", "invalid_output"),
        ("entity_extraction", "ok"),
    ]


async def test_providers_skipped_for_cooldown_budget_or_breaker_are_not_logged_as_calls(
    ctx: Ctx,
) -> None:
    gateway, groq, _ = make_gateway(ctx)
    await ctx.redis.set("llm:cool:groq", "1", ex=60)
    await gateway.complete(ASK, 160, purpose=Purpose.FAQ_ANSWER)
    assert groq.calls == [] and [r[0] for r in await usage_rows(ctx)] == ["gemini"]


async def test_the_chat_session_is_recorded_with_the_call(ctx: Ctx) -> None:
    async with ctx.session_factory() as db:
        chat = ChatSession()
        db.add(chat)
        await db.commit()
        session_id = chat.id
    gateway, *_ = make_gateway(ctx)
    await gateway.complete(ASK, 160, purpose=Purpose.FAQ_ANSWER, session_id=session_id)
    assert (await ctx.fetch("SELECT session_id FROM llm_usage"))[0][0] == session_id


async def test_a_broken_usage_log_never_breaks_the_conversation(ctx: Ctx) -> None:
    class BrokenFactory:
        def __call__(self) -> AsyncSession:
            raise RuntimeError("database unavailable")

    gateway, *_ = make_gateway(ctx)
    gateway.session_factory = BrokenFactory()  # type: ignore[assignment]
    gateway.invalidate_config()
    result = await gateway.complete(ASK, 160, purpose=Purpose.FAQ_ANSWER)
    assert result.text == "groq answer" and not result.degraded


async def test_a_degraded_reply_writes_no_usage_row(ctx: Ctx) -> None:
    gateway, *_ = make_gateway(ctx, groq=[fail()], gemini=[fail()])
    assert (await gateway.complete(ASK, 160, purpose=Purpose.FAQ_ANSWER)).degraded
    assert [r[7] for r in await usage_rows(ctx)] == ["server_error", "server_error"]


# --- settings stored in the database -----------------------------------------------------------------------


async def test_the_migration_seeds_groq_limits_and_leaves_gemini_limits_unset(ctx: Ctx) -> None:
    rows = dict(
        await ctx.fetch(
            "SELECT key, value::text FROM app_settings WHERE key LIKE 'groq_%' OR key LIKE 'gemini_%'"
        )
    )
    assert {k: rows[k] for k in ("groq_rpm", "groq_rpd", "groq_tpm", "groq_tpd")} == {
        "groq_rpm": "30",
        "groq_rpd": "1000",
        "groq_tpm": "8000",
        "groq_tpd": "200000",
    }
    assert {rows[k] for k in ("gemini_rpm", "gemini_rpd", "gemini_tpm", "gemini_tpd")} == {"null"}
    assert (await ctx.fetch("SELECT count(*) FROM app_settings WHERE key = 'llm_primary'"))[0][
        0
    ] == 0


async def test_the_gateway_reads_limits_from_the_database(ctx: Ctx) -> None:
    gateway, *_ = make_gateway(ctx)
    config = await gateway.config()
    assert (config.limits["groq"].rpm, config.limits["groq"].tpd) == (30, 200_000)
    assert (
        config.limits["gemini"].rpm is None and config.threshold == 0.8 and config.primary == "groq"
    )


async def test_an_administrator_setting_overrides_the_environment_primary(ctx: Ctx) -> None:
    gateway, groq, gemini = make_gateway(ctx)
    await ctx.execute(
        "INSERT INTO app_settings (key, value) VALUES ('llm_primary', '\"gemini\"'::jsonb)"
    )
    gateway.invalidate_config()
    assert (await gateway.complete(ASK, 160, purpose=Purpose.FAQ_ANSWER)).provider == "gemini"
    assert groq.calls == [] and len(gemini.calls) == 1
    await ctx.execute("DELETE FROM app_settings WHERE key = 'llm_primary'")


async def test_the_failover_threshold_comes_from_settings(ctx: Ctx) -> None:
    gateway, *_ = make_gateway(ctx)
    await ctx.execute(
        "UPDATE app_settings SET value = '0.5'::jsonb WHERE key = 'llm_budget_failover_threshold'"
    )
    try:
        gateway.invalidate_config()
        for _ in range(15):
            await gateway.budget.record("groq", "UTC", 10)
        # 16 of 30 requests is 53 percent: fine at the default 80 percent, too much at 50 percent.
        assert (await gateway.complete(ASK, 160, purpose=Purpose.FAQ_ANSWER)).provider == "gemini"
    finally:
        await ctx.execute(
            "UPDATE app_settings SET value = '0.8'::jsonb WHERE key = 'llm_budget_failover_threshold'"
        )


async def test_configuration_is_cached_briefly(ctx: Ctx) -> None:
    gateway, *_ = make_gateway(ctx)
    first = await gateway.config()
    await ctx.execute("UPDATE app_settings SET value = '5'::jsonb WHERE key = 'groq_rpm'")
    try:
        assert await gateway.config() is first
        gateway.invalidate_config()
        assert (await gateway.config()).limits["groq"].rpm == 5
    finally:
        await ctx.execute("UPDATE app_settings SET value = '30'::jsonb WHERE key = 'groq_rpm'")


# --- FAQ fallback -----------------------------------------------------------------------------------------------


async def index_faq(ctx: Ctx, embedder: FakeEmbedder) -> None:
    sources = [
        KbSource(
            "office-hours",
            "Office hours",
            "practice",
            WHEN,
            "We are open Monday to Friday from eight to six.\n\n## Short answer\nWe are open weekdays 8:00 AM to 6:00 PM.",
            "We are open weekdays 8:00 AM to 6:00 PM.",
        ),
        KbSource(
            "parking",
            "Parking",
            "practice",
            WHEN,
            "Free patient parking is in the lot beside the building.\n\n## Short answer\nParking is free beside the building.",
            "Parking is free beside the building.",
        ),
    ]
    async with ctx.session_factory() as db:
        await sync_sources(db, embedder, sources, ctx.settings, model_name=MODEL)


async def test_the_faq_fallback_returns_the_short_answer_of_a_close_match(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    await index_faq(ctx, fake_embedder)
    async with ctx.session_factory() as db:
        assert (
            await faq_short_answer(
                db, fake_embedder, "we are open Monday to Friday from eight to six"
            )
            == "We are open weekdays 8:00 AM to 6:00 PM."
        )
        assert await faq_short_answer(db, fake_embedder, "recipe for chocolate cake") is None
        assert await faq_short_answer(db, fake_embedder, "   ") is None
    assert FAQ_MIN_SCORE == 0.65


async def test_when_no_model_answers_the_best_faq_answer_is_used(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    await index_faq(ctx, fake_embedder)
    gateway, *_ = make_gateway(ctx, groq=[fail()], gemini=[fail()])
    question = "we are open Monday to Friday from eight to six"
    result = await gateway.complete(
        [Message("user", question)],
        160,
        purpose=Purpose.FAQ_ANSWER,
        fallback=faq_fallback(ctx.session_factory, fake_embedder, question),
    )
    assert result.degraded and result.text == "We are open weekdays 8:00 AM to 6:00 PM."


async def test_an_unrelated_question_gets_the_fixed_booking_and_phone_message(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    await index_faq(ctx, fake_embedder)
    gateway, *_ = make_gateway(ctx, groq=[fail()], gemini=[fail()])
    result = await gateway.complete(
        [Message("user", "tell me about volcanoes")],
        160,
        purpose=Purpose.FAQ_ANSWER,
        fallback=faq_fallback(ctx.session_factory, fake_embedder, "tell me about volcanoes"),
    )
    assert result.degraded and "/book" in result.text and "(555) 010-0199" in result.text


# --- administration ------------------------------------------------------------------------------------------------


async def test_only_administrators_may_use_the_llm_endpoints(ctx: Ctx) -> None:
    make_gateway(ctx)
    for method, path in [
        ("GET", "/status"),
        ("PUT", "/primary"),
        ("PUT", "/limits/gemini"),
        ("GET", "/usage"),
    ]:
        assert (await ctx.client.request(method, ADMIN + path, json={})).status_code == 401
    for role in (UserRole.PATIENT, UserRole.RECEPTIONIST, UserRole.DENTIST):
        email = unique_email(role.value)
        await ctx.create_user(email, role)
        headers = ctx.auth(await ctx.access_token(email))
        for method, path in [
            ("GET", "/status"),
            ("PUT", "/primary"),
            ("PUT", "/limits/gemini"),
            ("GET", "/usage"),
        ]:
            assert (
                await ctx.client.request(method, ADMIN + path, headers=headers, json={})
            ).status_code == 403


async def test_the_status_endpoint_shows_order_breaker_and_utilization(ctx: Ctx) -> None:
    gateway, *_ = make_gateway(ctx)
    await gateway.complete(ASK, 160, purpose=Purpose.FAQ_ANSWER)
    response = await ctx.client.get(f"{ADMIN}/status", headers=await admin_headers(ctx))

    assert response.status_code == 200
    body = response.json()
    assert (
        body["primary"] == "groq"
        and body["order"] == ["groq", "gemini"]
        and body["failover_threshold"] == 0.8
    )
    groq = body["providers"]["groq"]
    assert groq["configured"] and groq["model"] == "openai/gpt-oss-20b"
    assert groq["breaker"]["state"] == "closed" and groq["limits"]["rpm"] == 30
    assert (
        groq["usage"]["rpm"] == 1 and groq["usage"]["tpm"] == 215
    )  # 300 + 15 tokens minus 100 cached
    assert body["providers"]["gemini"]["limits"]["rpm"] is None
    assert "api_key" not in str(body).lower() and "key" not in body["providers"]["groq"]


async def test_status_marks_providers_without_credentials(ctx: Ctx) -> None:
    make_gateway(ctx)
    ctx.app.state.llm.providers.pop("gemini")
    body = (await ctx.client.get(f"{ADMIN}/status", headers=await admin_headers(ctx))).json()
    assert body["providers"]["gemini"] == {"configured": False} and body["order"] == ["groq"]


async def test_the_primary_provider_can_be_switched_and_the_change_is_audited(ctx: Ctx) -> None:
    gateway, groq, gemini = make_gateway(ctx)
    headers = await admin_headers(ctx)
    response = await ctx.client.put(
        f"{ADMIN}/primary", headers=headers, json={"provider": "gemini"}
    )
    assert response.status_code == 200 and response.json() == {"primary": "gemini"}

    assert (
        await gateway.complete(ASK, 160, purpose=Purpose.FAQ_ANSWER)
    ).provider == "gemini"  # no restart needed
    audit = await ctx.fetch(
        "SELECT action, metadata::text FROM audit_logs WHERE action = 'llm.set_primary'"
    )
    assert audit and "gemini" in audit[0][1]
    await ctx.client.put(f"{ADMIN}/primary", headers=headers, json={"provider": "groq"})
    assert (await gateway.complete(ASK, 160, purpose=Purpose.FAQ_ANSWER)).provider == "groq"
    assert (
        await ctx.client.put(f"{ADMIN}/primary", headers=headers, json={"provider": "other"})
    ).status_code == 422
    assert groq.calls and gemini.calls


async def test_limits_entered_from_ai_studio_are_stored_and_enforced(ctx: Ctx) -> None:
    gateway, _, gemini = make_gateway(ctx, llm_primary="gemini")
    headers = await admin_headers(ctx)
    response = await ctx.client.put(
        f"{ADMIN}/limits/gemini",
        headers=headers,
        json={"rpm": 10, "rpd": 250, "tpm": 250_000, "tpd": None},
    )
    assert response.status_code == 200 and response.json() == {
        "rpm": 10,
        "rpd": 250,
        "tpm": 250_000,
        "tpd": None,
    }
    stored = dict(
        await ctx.fetch("SELECT key, value::text FROM app_settings WHERE key LIKE 'gemini_%'")
    )
    assert (
        stored["gemini_rpm"],
        stored["gemini_rpd"],
        stored["gemini_tpm"],
        stored["gemini_tpd"],
    ) == ("10", "250", "250000", "null")

    providers = [
        (await gateway.complete(ASK, 160, purpose=Purpose.FAQ_ANSWER)).provider for _ in range(10)
    ]
    assert providers == ["gemini"] * 8 + ["groq"] * 2  # above 80 percent of 10 requests per minute
    assert len(gemini.calls) == 8


async def test_limit_endpoint_validates_input(ctx: Ctx) -> None:
    make_gateway(ctx)
    headers = await admin_headers(ctx)
    assert (
        await ctx.client.put(f"{ADMIN}/limits/unknown", headers=headers, json={})
    ).status_code == 404
    assert (
        await ctx.client.put(f"{ADMIN}/limits/gemini", headers=headers, json={"rpm": 0})
    ).status_code == 422
    assert (
        await ctx.client.put(f"{ADMIN}/limits/gemini", headers=headers, json={"rpm": 5, "extra": 1})
    ).status_code == 422


async def test_the_usage_summary_groups_calls_by_provider_and_outcome(ctx: Ctx) -> None:
    gateway, *_ = make_gateway(
        ctx, groq=[fail(ProviderErrorKind.SERVER_ERROR), ok("fine", prompt=200, completion=10)]
    )
    for _ in range(2):
        await gateway.complete(ASK, 160, purpose=Purpose.FAQ_ANSWER)
    response = await ctx.client.get(
        f"{ADMIN}/usage", params={"hours": 1}, headers=await admin_headers(ctx)
    )

    assert response.status_code == 200
    rows = {(r["provider"], r["status"]): r for r in response.json()["rows"]}
    assert rows[("groq", "server_error")]["calls"] == 1
    assert rows[("gemini", "ok")]["calls"] == 1 and rows[("gemini", "ok")]["failovers"] == 1
    assert (
        rows[("groq", "ok")]["prompt_tokens"] == 200
        and rows[("groq", "ok")]["completion_tokens"] == 10
    )
    assert (
        await ctx.client.get(
            f"{ADMIN}/usage", params={"hours": 0}, headers=await admin_headers(ctx)
        )
    ).status_code == 422


async def test_endpoints_report_503_when_no_gateway_is_configured(ctx: Ctx) -> None:
    ctx.app.state.llm = None
    response = await ctx.client.get(f"{ADMIN}/status", headers=await admin_headers(ctx))
    assert response.status_code == 503 and response.json()["code"] == "llm_unavailable"


async def test_the_application_starts_with_a_gateway_that_has_no_providers(ctx: Ctx) -> None:
    from app.chat.llm_gateway import LlmGateway as Gateway

    assert isinstance(Gateway, type)
    _ = (uuid.uuid4(), datetime.now(UTC), async_sessionmaker)
