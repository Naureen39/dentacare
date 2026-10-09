"""Who may see which figures, response caching, input checks, CSV export, refresh, chatbot."""

import csv
import io
import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.db.enums import UserRole
from tests.analytics.conftest import AS_OF
from tests.analytics.helpers import RANGES, Api, billed, money, scalar, span
from tests.analytics.test_numbers import kpi
from tests.auth.conftest import Ctx, unique_email

START, END = RANGES[1]
WINDOW = span(START, END)
BASE = "/api/v1/analytics"

OPERATIONS = ["/appointments/status-trend", "/appointments/heatmap", "/appointments/lead-time", "/patients/new-vs-returning", "/no-show/upcoming-risk"]  # fmt: skip
OWN_FINANCE = ["/revenue/trend", "/revenue/by-service", "/revenue/by-payer"]
ADMIN_ONLY = ["/revenue/by-dentist", "/patients/retention-cohorts", "/finance/ar-aging", "/finance/collection-rate", "/forecast/revenue"]  # fmt: skip
FRONT_DESK = ["/chatbot/summary"]
EVERYTHING = ["/summary", *OPERATIONS, *OWN_FINANCE, *ADMIN_ONLY, *FRONT_DESK]


async def api_for(ctx: Ctx, role: UserRole, *, dentist_id: str | None = None) -> Api:
    email = unique_email(role.value)
    user = await ctx.create_user(email, role, with_patient=role is UserRole.PATIENT)
    if role is UserRole.DENTIST and dentist_id:
        await ctx.execute("DELETE FROM dentists WHERE user_id = :u", u=str(user.id))
        await ctx.execute(
            "UPDATE dentists SET user_id = :u WHERE id = :d", u=str(user.id), d=dentist_id
        )
    return Api(ctx, ctx.auth(await ctx.access_token(email)))


async def status(api: Api, path: str, **params: Any) -> int:
    query = {"as_of": AS_OF.isoformat(), **WINDOW, **params}
    return (
        await api.ctx.client.get(f"{BASE}{path}", params=query, headers=api.headers)
    ).status_code


@pytest.fixture
async def busy_dentist(ctx: Ctx) -> str:
    return str(
        await scalar(
            ctx,
            "SELECT dentist_id::text FROM appointments GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1",
        )
    )


# --- who may see what ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", EVERYTHING)
async def test_anonymous_visitors_and_patients_see_nothing(ctx: Ctx, path: str) -> None:
    assert (await ctx.client.get(f"{BASE}{path}", params=WINDOW)).status_code == 401
    patient = await api_for(ctx, UserRole.PATIENT)
    assert await status(patient, path) == 403


@pytest.mark.parametrize("path", ["/summary", *OPERATIONS, *OWN_FINANCE, *ADMIN_ONLY, *FRONT_DESK])
async def test_an_administrator_can_see_everything(admin: Api, path: str) -> None:
    assert await status(admin, path) == 200


async def test_a_receptionist_sees_operations_and_the_front_desk_but_no_money(ctx: Ctx) -> None:
    api = await api_for(ctx, UserRole.RECEPTIONIST)
    for path in ["/summary", *OPERATIONS, *FRONT_DESK]:
        assert await status(api, path) == 200, path
    for path in [*OWN_FINANCE, *ADMIN_ONLY]:
        assert await status(api, path) == 403, path
    assert (await ctx.client.post(f"{BASE}/refresh", headers=api.headers)).status_code == 403
    body = await api.get("/summary", **WINDOW)
    assert {k["key"] for k in body["kpis"]} == {
        "completed",
        "utilization",
        "no_show_rate",
        "new_patients",
    }


async def test_a_dentist_sees_their_own_figures_only(
    ctx: Ctx, admin: Api, busy_dentist: str
) -> None:
    api = await api_for(ctx, UserRole.DENTIST, dentist_id=busy_dentist)
    for path in ["/summary", *OPERATIONS, *OWN_FINANCE]:
        assert await status(api, path) == 200, path
    for path in [*ADMIN_ONLY, *FRONT_DESK]:
        assert await status(api, path) == 403, path
    other = str(uuid.uuid4())
    assert await status(api, "/summary", dentist_id=other) == 403
    assert await status(api, "/summary", dentist_id=busy_dentist) == 200

    mine = await api.get("/summary", **WINDOW)
    theirs = await admin.get("/summary", dentist_id=busy_dentist, **WINDOW)
    for key in ("billed", "collected", "completed", "no_show_rate", "utilization"):
        assert kpi(mine, key)["value"] == kpi(theirs, key)["value"], key
    assert money(kpi(mine, "billed")["value"]) == await billed(
        ctx, START, END, dentist=busy_dentist
    )
    everyone = await admin.get("/summary", **WINDOW)
    assert kpi(mine, "billed")["value"] < kpi(everyone, "billed")["value"]


async def test_a_dentist_cannot_widen_the_view_with_filters_or_exports(
    ctx: Ctx, busy_dentist: str
) -> None:
    api = await api_for(ctx, UserRole.DENTIST, dentist_id=busy_dentist)
    body = await api.get("/revenue/by-payer", **WINDOW)
    assert body["by_provider"] == []  # the clinic wide insurer mix is not theirs
    response = await ctx.client.get(
        f"{BASE}/export/csv", params={"dataset": "by_dentist", **WINDOW}, headers=api.headers
    )
    assert response.status_code == 403


async def test_a_dentist_with_no_profile_gets_no_data(ctx: Ctx) -> None:
    email = unique_email("dentist")
    user = await ctx.create_user(email, UserRole.DENTIST, with_patient=False)
    await ctx.execute("DELETE FROM dentists WHERE user_id = :u", u=str(user.id))
    api = Api(ctx, ctx.auth(await ctx.access_token(email)))
    assert await status(api, "/summary") == 403


# --- input checks ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2025-09-30", "to": "2025-07-01"},
        {"from": "2020-01-01", "to": "2025-01-01"},
        {"granularity": "decade"},
        {"dentist_id": "not-a-uuid"},
        {"service_id": "123"},
        {"payer_type": "robot"},
        {"from": "last week"},
    ],
)
async def test_bad_filters_are_rejected_with_a_clear_error(
    admin: Api, params: dict[str, str]
) -> None:
    response = await admin.ctx.client.get(
        f"{BASE}/summary", params={"as_of": AS_OF.isoformat(), **params}, headers=admin.headers
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_default_filters_cover_the_last_year_up_to_yesterday(admin: Api) -> None:
    body = await admin.get("/summary")
    assert body["meta"]["date_to"] == "2026-06-15" and body["meta"]["date_from"] == "2025-06-16"
    assert body["meta"]["granularity"] == "month"


async def test_an_unknown_dentist_gives_empty_figures_not_an_error(admin: Api) -> None:
    body = await admin.get("/revenue/trend", dentist_id=str(uuid.uuid4()), **WINDOW)
    assert body["points"] == []


# --- caching -------------------------------------------------------------------------------------------------------------


async def test_a_second_identical_request_is_served_from_the_cache(ctx: Ctx, admin: Api) -> None:
    first = await admin.get("/revenue/trend", **WINDOW)
    second = await admin.get("/revenue/trend", **WINDOW)
    assert first["meta"]["cached"] is False and second["meta"]["cached"] is True
    assert first["points"] == second["points"]
    other = await admin.get("/revenue/trend", granularity="week", **WINDOW)
    assert other["meta"]["cached"] is False
    keys = [k async for k in ctx.redis.scan_iter("analytics:*:revenue_trend:*")]
    assert len(keys) == 2
    for key in keys:
        assert 0 < await ctx.redis.ttl(key) <= 300  # five minutes


async def test_cached_figures_are_never_shared_between_roles(
    ctx: Ctx, admin: Api, busy_dentist: str
) -> None:
    dentist = await api_for(ctx, UserRole.DENTIST, dentist_id=busy_dentist)
    mine = await dentist.get("/revenue/trend", **WINDOW)
    everyone = await admin.get("/revenue/trend", **WINDOW)
    assert everyone["meta"]["cached"] is False
    assert sum(money(p["billed"]) for p in everyone["points"]) > sum(
        money(p["billed"]) for p in mine["points"]
    )


async def test_refreshing_clears_stored_responses_and_updates_the_figures(
    ctx: Ctx, admin: Api
) -> None:
    before = await admin.get("/summary", **WINDOW)
    invoice = (await ctx.fetch(
        """SELECT i.id::text FROM invoices i WHERE (i.issued_at AT TIME ZONE 'America/New_York')::date BETWEEN :f AND :t
           AND i.status = 'issued' LIMIT 1""", f=START, t=END))  # fmt: skip
    invoice_id = invoice[0][0] if invoice else None
    if invoice_id is None:
        invoice_id = (
            await ctx.fetch(
                "SELECT id::text FROM invoices WHERE (issued_at AT TIME ZONE 'America/New_York')::date BETWEEN :f AND :t LIMIT 1",
                f=START,
                t=END,
            )
        )[0][0]
    payment = str(uuid.uuid4())
    await ctx.execute(
        """INSERT INTO payments (id, invoice_id, amount, method, payer_type, paid_at)
           VALUES (:id, :inv, 1.00, 'cash', 'patient', TIMESTAMPTZ '2025-08-01 15:00:00+00')""",
        id=payment, inv=invoice_id,
    )  # fmt: skip
    try:
        stale = await admin.get("/summary", **WINDOW)
        assert stale["meta"]["cached"] is True
        assert (
            kpi(stale, "collected")["value"] == kpi(before, "collected")["value"]
        )  # nothing refreshed yet

        refresh = await admin.ctx.client.post(f"{BASE}/refresh", headers=admin.headers)
        assert refresh.status_code == 200 and refresh.json() == {"refreshed": 10, "failed": 0}
        fresh = await admin.get("/summary", **WINDOW)
        assert fresh["meta"]["cached"] is False
        assert (
            round(kpi(fresh, "collected")["value"] - kpi(before, "collected")["value"], 2) == 1.00
        )
        assert fresh["meta"]["data_as_of"] is not None
    finally:
        await ctx.execute("DELETE FROM payments WHERE id = :id", id=payment)
        await admin.ctx.client.post(f"{BASE}/refresh", headers=admin.headers)
    audit = await ctx.fetch("SELECT count(*) FROM audit_logs WHERE action = 'analytics.refresh'")
    assert audit[0][0] >= 1


# --- CSV -------------------------------------------------------------------------------------------------------------------


async def export(api: Api, dataset: str, **params: Any) -> tuple[int, list[dict[str, str]], Any]:
    response = await api.ctx.client.get(
        f"{BASE}/export/csv",
        params={"dataset": dataset, "as_of": AS_OF.isoformat(), **WINDOW, **params},
        headers=api.headers,
    )
    rows = list(csv.DictReader(io.StringIO(response.text))) if response.status_code == 200 else []
    return response.status_code, rows, response


@pytest.mark.parametrize(
    ("dataset", "path", "key"),
    [
        ("revenue_trend", "/revenue/trend", "points"),
        ("by_service", "/revenue/by-service", "rows"),
        ("by_dentist", "/revenue/by-dentist", "rows"),
        ("status_trend", "/appointments/status-trend", "points"),
        ("heatmap", "/appointments/heatmap", "cells"),
        ("lead_time", "/appointments/lead-time", "buckets"),
        ("new_returning", "/patients/new-vs-returning", "points"),
        ("retention", "/patients/retention-cohorts", "cohorts"),
        ("ar_aging", "/finance/ar-aging", "buckets"),
        ("collection", "/finance/collection-rate", "points"),
    ],
)
async def test_every_table_view_exports_the_same_rows_as_csv(
    admin: Api, dataset: str, path: str, key: str
) -> None:
    code, rows, response = await export(admin, dataset, granularity="month")
    body = await admin.get(path, granularity="month", **WINDOW)
    assert code == 200 and response.headers["content-type"].startswith("text/csv")
    assert f'filename="{dataset}-{START}-{END}.csv"' in response.headers["content-disposition"]
    assert len(rows) == len(body[key]) > 0
    assert response.headers["cache-control"] == "no-store"


async def test_csv_values_match_the_json_values(admin: Api) -> None:
    _, rows, _ = await export(admin, "revenue_trend", granularity="month")
    body = await admin.get("/revenue/trend", granularity="month", **WINDOW)
    assert [r["period"] for r in rows] == [p["period"] for p in body["points"]]
    assert [money(r["billed"]) for r in rows] == [money(p["billed"]) for p in body["points"]]


async def test_other_exports_have_sensible_shapes(admin: Api) -> None:
    _, rows, _ = await export(admin, "forecast")
    assert {r["kind"] for r in rows} == {"history", "forecast"}
    _, rows, _ = await export(admin, "by_payer")
    assert {r["group"] for r in rows} == {"payer_type", "provider"}
    _, rows, _ = await export(admin, "chatbot")
    assert len(rows) == 1 and "zero_llm_share" in rows[0]
    _, rows, _ = await export(admin, "summary")
    assert {r["key"] for r in rows} >= {"billed", "no_show_rate"} and "sparkline" not in rows[0]
    _, rows, _ = await export(admin, "retention", **span(date(2024, 6, 1), date(2025, 6, 30)))
    assert "month_0" in rows[0] and "month_12" in rows[0]


async def test_exports_follow_the_same_permissions_and_are_audited(ctx: Ctx, admin: Api) -> None:
    desk = await api_for(ctx, UserRole.RECEPTIONIST)
    assert (await export(desk, "revenue_trend"))[0] == 403
    assert (await export(desk, "status_trend"))[0] == 200
    await export(admin, "heatmap")
    rows = await ctx.fetch(
        "SELECT metadata FROM audit_logs WHERE action = 'data.export' ORDER BY created_at DESC LIMIT 1"
    )
    assert rows[0][0]["dataset"] == "heatmap" and rows[0][0]["rows"] > 0


async def test_a_cell_that_looks_like_a_formula_is_defused(ctx: Ctx, admin: Api) -> None:
    service = (await ctx.fetch("SELECT id::text, name FROM services ORDER BY code LIMIT 1"))[0]
    await ctx.execute(
        "UPDATE services SET name = :n WHERE id = :i",
        n='=HYPERLINK("http://evil.example","x")',
        i=service[0],
    )
    await ctx.execute(
        "UPDATE dentists SET full_name = '@SUM(1+1)' WHERE full_name = 'Dr. Priya Raman'"
    )
    try:
        await admin.ctx.client.post(
            f"{BASE}/refresh", headers=admin.headers
        )  # also clears stored responses
        _, rows, _ = await export(admin, "by_service")
        _, dentists, _ = await export(admin, "by_dentist")
        labels = [r["label"] for r in rows] + [r["label"] for r in dentists]
        assert any(label.startswith("'=HYPERLINK") for label in labels)
        assert any(label.startswith("'@SUM") for label in labels)
        assert not any(label[:1] in "=+-@" for label in labels)
    finally:
        await ctx.execute("UPDATE services SET name = :n WHERE id = :i", n=service[1], i=service[0])
        await ctx.execute(
            "UPDATE dentists SET full_name = 'Dr. Priya Raman' WHERE full_name = '@SUM(1+1)'"
        )
        await admin.ctx.client.post(f"{BASE}/refresh", headers=admin.headers)


# --- the chatbot ---------------------------------------------------------------------------------------------------------


async def test_chatbot_summary_adds_up_the_conversations(ctx: Ctx, admin: Api) -> None:
    day = datetime(2026, 5, 20, 15, 0, tzinfo=UTC)
    sessions = {name: str(uuid.uuid4()) for name in ("a", "b", "c")}
    funnels = {
        "a": '{"funnel": {"started": true, "slot_chosen": true, "confirmed": true}}',
        "b": '{"funnel": {"started": true}}',
        "c": "{}",
    }
    for name, sid in sessions.items():
        await ctx.execute(
            "INSERT INTO chat_sessions (id, state, created_at) VALUES (:i, CAST(:s AS jsonb), :d)",
            i=sid, s=funnels[name], d=day,
        )  # fmt: skip

    async def message(
        name: str,
        role: str,
        intent: str | None,
        route: str | None,
        calls: int = 0,
        feedback: int | None = None,
    ) -> None:
        await ctx.execute(
            """INSERT INTO chat_messages (id, session_id, role, content, intent, route, llm_calls, feedback, created_at)
               VALUES (:id, :s, CAST(:r AS chat_role), 'x', :intent, CAST(:route AS chat_route), :calls, :fb, :d)""",
            id=str(uuid.uuid4()), s=sessions[name], r=role, intent=intent, route=route, calls=calls, fb=feedback, d=day,
        )  # fmt: skip

    for name in sessions:
        await message(name, "assistant", "session_open", "rule")
    for _ in range(3):
        await message("a", "user", "faq", None)
    await message("a", "assistant", "faq", "faq_direct")
    await message("a", "assistant", "faq", "rule", feedback=1)
    await message("a", "assistant", "faq", "llm", calls=1)
    for _ in range(2):
        await message("b", "user", "human_handoff", None)
    await message("b", "assistant", "faq", "rule", feedback=-1)
    await message("b", "assistant", "human_handoff", "handoff")
    for session, provider, prompt, completion, fallback in (
        ("a", "groq", 300, 50, None),
        ("a", "gemini", 200, 40, "groq"),
    ):
        await ctx.execute(
            """INSERT INTO llm_usage (id, session_id, provider, model, purpose, prompt_tokens, completion_tokens, status, fallback_from, created_at)
               VALUES (:id, :s, :p, 'm', 'faq_answer', :pt, :ct, 'ok', :fb, :d)""",
            id=str(uuid.uuid4()), s=sessions[session], p=provider, pt=prompt, ct=completion, fb=fallback, d=day,
        )  # fmt: skip
    try:
        await admin.ctx.client.post(f"{BASE}/refresh", headers=admin.headers)
        body = await admin.get("/chatbot/summary", **span(date(2026, 5, 20), date(2026, 5, 20)))
        assert body["conversations"] == 2 and body["turns"] == 5
        assert body["zero_llm_turns"] == 4 and body["zero_llm_share"] == 0.8
        assert (
            body["booking_started"] == 2
            and body["booking_slot_chosen"] == 1
            and body["booking_confirmed"] == 1
        )
        assert body["booking_conversion"] == 0.5
        assert body["handoffs"] == 1 and body["resolved_without_human"] == 0.5
        assert (
            body["feedback_up"] == 1
            and body["feedback_down"] == 1
            and body["feedback_score"] == 0.5
        )
        providers = {p["provider"]: p for p in body["providers"]}
        assert providers["groq"] == {"provider": "groq", "calls": 1, "tokens": 350, "failovers": 0}
        assert providers["gemini"] == {
            "provider": "gemini",
            "calls": 1,
            "tokens": 240,
            "failovers": 1,
        }
        assert body["failovers"] == 1 and body["tokens_per_conversation"] == 295.0
        # The same session figures come out of the admin chat metrics added with the chatbot.
        metrics = (
            await admin.ctx.client.get("/api/v1/admin/chat/metrics?days=365", headers=admin.headers)
        ).json()
        assert (
            metrics["turns"] == 5
            and metrics["zero_llm_turns"] == 4
            and metrics["conversations"] == 2
        )
        assert metrics["funnel_started"] == 2 and metrics["funnel_confirmed"] == 1
        empty = await admin.get("/chatbot/summary", **span(date(2026, 5, 21), date(2026, 5, 22)))
        assert empty["conversations"] == 0 and empty["zero_llm_share"] is None
    finally:
        await ctx.execute("DELETE FROM llm_usage")
        await ctx.execute("DELETE FROM chat_messages")
        await ctx.execute("DELETE FROM chat_sessions")
        await admin.ctx.client.post(f"{BASE}/refresh", headers=admin.headers)
    json.dumps(body)
