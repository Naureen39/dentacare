"""The extra figures of the analytics dashboard, each compared with SQL written separately on the
base tables for the three date ranges, and checks on who sees what."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.enums import UserRole
from tests.analytics.conftest import AS_OF
from tests.analytics.helpers import (
    LOCAL,
    RANGES,
    Api,
    available_minutes,
    billed,
    booked_minutes,
    money,
    scalar,
    span,
    status_counts,
)
from tests.analytics.test_access_and_export import api_for
from tests.auth.conftest import Ctx


def close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) < 1e-6 * max(1.0, abs(b))


@pytest.mark.parametrize(("start", "end"), RANGES)
async def test_revenue_by_weekday_matches_invoices_and_payments(
    ctx: Ctx, admin: Api, start: date, end: date
) -> None:
    body = await admin.get("/revenue/by-weekday", **span(start, end))
    invoices = {
        int(d): (money(b), int(n))
        for d, b, n in await ctx.fetch(
            f"""SELECT EXTRACT(isodow FROM {LOCAL % 'i.issued_at'})::int - 1, sum(i.total), count(*)
                FROM invoices i WHERE i.status NOT IN ('draft', 'void')
                  AND {LOCAL % 'i.issued_at'} BETWEEN :f AND :t GROUP BY 1""",  # noqa: S608
            f=start, t=end,
        )
    }  # fmt: skip
    payments = {
        int(d): money(v)
        for d, v in await ctx.fetch(
            f"""SELECT EXTRACT(isodow FROM {LOCAL % 'p.paid_at'})::int - 1, sum(p.amount)
                FROM payments p WHERE {LOCAL % 'p.paid_at'} BETWEEN :f AND :t GROUP BY 1""",  # noqa: S608
            f=start, t=end,
        )
    }  # fmt: skip
    assert [r["weekday"] for r in body["rows"]] == list(range(7))
    for row in body["rows"]:
        weekday = row["weekday"]
        expected_days = sum(
            1 for n in range((end - start).days + 1) if (start + timedelta(n)).weekday() == weekday
        )
        assert row["days"] == expected_days
        assert money(row["billed"]) == invoices.get(weekday, (Decimal(0), 0))[0]
        assert row["invoices"] == invoices.get(weekday, (Decimal(0), 0))[1]
        assert money(row["collected"]) == payments.get(weekday, Decimal(0))


@pytest.mark.parametrize(("start", "end"), RANGES)
async def test_service_trends_match_invoices_and_visits(
    ctx: Ctx, admin: Api, start: date, end: date
) -> None:
    body = await admin.get("/revenue/service-trends", **span(start, end))
    expected = {
        key: (money(total), int(n))
        for key, total, n in await ctx.fetch(
            f"""SELECT a.service_id::text, sum(i.total), count(*) FROM invoices i
                JOIN appointments a ON a.id = i.appointment_id
                WHERE i.status NOT IN ('draft', 'void') AND {LOCAL % 'i.issued_at'} BETWEEN :f AND :t
                GROUP BY 1""",  # noqa: S608
            f=start, t=end,
        )
    }  # fmt: skip
    visits = {
        key: (int(n), int(minutes))
        for key, n, minutes in await ctx.fetch(
            f"""SELECT service_id::text, count(*),
                       sum(EXTRACT(epoch FROM upper(slot) - lower(slot)) / 60)
                FROM appointments WHERE status = 'completed' AND {LOCAL % 'lower(slot)'} BETWEEN :f AND :t
                GROUP BY 1""",  # noqa: S608
            f=start, t=end,
        )
    }  # fmt: skip
    assert {r["key"] for r in body["rows"]} == set(expected)
    ordered = [money(r["billed"]) for r in body["rows"]]
    assert ordered == sorted(ordered, reverse=True)
    for row in body["rows"]:
        total, count = expected[row["key"]]
        assert money(row["billed"]) == total and row["invoices"] == count
        n, minutes = visits.get(row["key"], (0, 0))
        assert row["visits"] == n and row["minutes"] == minutes
        assert close(row["revenue_per_hour"], float(total) / (minutes / 60) if minutes else None)
    # The ten leading services carry a series that adds up to what they billed.
    for row in body["rows"][:10]:
        assert sum(Decimal(str(p["value"])) for p in row["series"]) == money(row["billed"])
    assert all(r["series"] == [] for r in body["rows"][10:])


@pytest.mark.parametrize(("start", "end"), RANGES)
async def test_dentist_service_cells_match_invoices(
    ctx: Ctx, admin: Api, start: date, end: date
) -> None:
    body = await admin.get("/revenue/dentist-services", **span(start, end))
    expected = {
        (d, s): money(v)
        for d, s, v in await ctx.fetch(
            f"""SELECT a.dentist_id::text, a.service_id::text, sum(i.total) FROM invoices i
                JOIN appointments a ON a.id = i.appointment_id
                WHERE i.status NOT IN ('draft', 'void') AND {LOCAL % 'i.issued_at'} BETWEEN :f AND :t
                GROUP BY 1, 2 HAVING sum(i.total) > 0""",  # noqa: S608
            f=start, t=end,
        )
    }  # fmt: skip
    got = {(c["dentist_id"], c["service_id"]): money(c["billed"]) for c in body["cells"]}
    assert got == expected


@pytest.mark.parametrize(("start", "end"), RANGES)
async def test_leaderboard_matches_the_base_tables(
    ctx: Ctx, admin: Api, start: date, end: date
) -> None:
    body = await admin.get("/dentists/leaderboard", **span(start, end))
    assert len(body["rows"]) >= 2
    for row in body["rows"]:
        dentist = row["dentist_id"]
        counts = await status_counts(ctx, start, end, dentist=dentist)
        completed, no_show = counts.get("completed", 0), counts.get("no_show", 0)
        assert row["visits"] == completed and row["no_shows"] == no_show
        assert close(
            row["no_show_rate"], no_show / (completed + no_show) if completed + no_show else None
        )
        assert money(row["billed"]) == await billed(ctx, start, end, dentist=dentist)
        booked = await booked_minutes(ctx, start, end, dentist=dentist)
        available = await available_minutes(ctx, start, end, dentist=dentist)
        assert close(row["utilization"], booked / available if available else None)
        assert close(row["booked_hours"], round(booked / 60, 1))
    revenue = [money(r["billed"]) for r in body["rows"]]
    assert revenue == sorted(revenue, reverse=True)


@pytest.mark.parametrize(("start", "end"), RANGES)
async def test_demographics_count_the_patients_who_were_seen(
    ctx: Ctx, admin: Api, start: date, end: date
) -> None:
    body = await admin.get("/patients/demographics", **span(start, end))
    expected = int(
        await scalar(
            ctx,
            f"""SELECT count(DISTINCT patient_id) FROM appointments
                WHERE status = 'completed' AND {LOCAL % 'lower(slot)'} BETWEEN :f AND :t""",  # noqa: S608
            f=start, t=end,
        )
    )  # fmt: skip
    assert body["patients"] == expected
    assert sum(b["patients"] for b in body["age_bands"]) == expected
    sources = {
        key: int(n)
        for key, n in await ctx.fetch(
            f"""SELECT p.source::text, count(DISTINCT p.id) FROM appointments a
                JOIN patients p ON p.id = a.patient_id
                WHERE a.status = 'completed' AND {LOCAL % 'lower(a.slot)'} BETWEEN :f AND :t GROUP BY 1""",  # noqa: S608
            f=start, t=end,
        )
    }  # fmt: skip
    assert {s["key"]: s["patients"] for s in body["sources"]} == sources
    assert all(b["share"] is None or 0 <= b["share"] <= 1 for b in body["age_bands"])


async def test_top_patients_are_ranked_by_lifetime_billing(ctx: Ctx, admin: Api) -> None:
    body = await admin.get("/patients/top", **span(*RANGES[1]))
    expected = await ctx.fetch(
        """SELECT p.id::text, p.first_name, p.last_name, sum(i.total)
           FROM invoices i JOIN patients p ON p.id = i.patient_id
           WHERE i.status NOT IN ('draft', 'void') AND p.anonymized_at IS NULL
           GROUP BY p.id ORDER BY sum(i.total) DESC, p.id LIMIT 10"""
    )
    assert [r["patient_id"] for r in body["rows"]] == [e[0] for e in expected]
    assert [money(r["lifetime_value"]) for r in body["rows"]] == [money(e[3]) for e in expected]
    assert body["rows"][0]["name"] == f"{expected[0][1]} {expected[0][2]}"
    assert not body["rows"][0]["masked"]


async def test_a_receptionist_sees_only_initials_of_top_patients(ctx: Ctx) -> None:
    desk = await api_for(ctx, UserRole.RECEPTIONIST)
    body = await desk.get("/patients/top", **span(*RANGES[1]))
    assert body["rows"] and all(r["masked"] for r in body["rows"])
    for row in body["rows"]:
        first, last = row["name"].split()
        assert len(first) == 2 and first.endswith(".") and len(last) == 2
    # The masked figure must not be served from the cache entry made for the administrator.
    admin_view = await Api(ctx, ctx.auth(await ctx.access_token(await _admin(ctx)))).get(
        "/patients/top", **span(*RANGES[1])
    )
    assert not admin_view["rows"][0]["masked"]


async def _admin(ctx: Ctx) -> str:
    from tests.auth.conftest import unique_email

    email = unique_email("admin2")
    await ctx.create_user(email, UserRole.ADMIN)
    return email


@pytest.mark.parametrize(("start", "end"), RANGES)
async def test_channels_match_the_appointments(
    ctx: Ctx, admin: Api, start: date, end: date
) -> None:
    body = await admin.get("/appointments/channels", **span(start, end))
    expected = {
        key: (int(n), int(done))
        for key, n, done in await ctx.fetch(
            f"""SELECT channel::text, count(*), count(*) FILTER (WHERE status = 'completed')
                FROM appointments WHERE status <> 'cancelled' AND {LOCAL % 'lower(slot)'} BETWEEN :f AND :t
                GROUP BY 1""",  # noqa: S608
            f=start, t=end,
        )
    }  # fmt: skip
    assert {r["key"]: (r["appointments"], r["completed"]) for r in body["rows"]} == expected
    total = sum(n for n, _ in expected.values())
    assert all(close(r["share"], r["appointments"] / total) for r in body["rows"])


@pytest.mark.parametrize(("start", "end"), RANGES)
async def test_days_to_collect_matches_paid_invoices(
    ctx: Ctx, admin: Api, start: date, end: date
) -> None:
    body = await admin.get("/finance/collection-rate", **span(start, end))
    rows = await ctx.fetch(
        f"""SELECT i.issued_at, (SELECT max(paid_at) FROM payments WHERE invoice_id = i.id)
            FROM invoices i WHERE i.status = 'paid' AND {LOCAL % 'i.issued_at'} BETWEEN :f AND :t""",  # noqa: S608
        f=start, t=end,
    )  # fmt: skip
    days = [max((paid - issued).total_seconds() / 86400, 0.0) for issued, paid in rows]
    expected = round(sum(days) / len(days), 1) if days else None
    assert close(body["average_days_to_collect"], expected)


async def test_chatbot_days_and_unanswered_questions(ctx: Ctx, admin: Api) -> None:
    start, end = date(2025, 1, 1), AS_OF - timedelta(days=1)
    body = await admin.get("/chatbot/summary", **span(start, end))
    assert sum(d["conversations"] for d in body["days"]) == body["conversations"]
    assert sum(d["turns"] for d in body["days"]) == body["turns"]
    assert sum(d["zero_llm_turns"] for d in body["days"]) == body["zero_llm_turns"]
    assert sum(d["tokens"] for d in body["days"]) == sum(p["tokens"] for p in body["providers"])
    assert [d["day"] for d in body["days"]] == sorted(d["day"] for d in body["days"])

    flagged: dict[str, int] = defaultdict(int)
    for (question,) in await ctx.fetch(
        f"""SELECT lower(trim((SELECT u.content FROM chat_messages u
                              WHERE u.session_id = m.session_id AND u.role = 'user'
                                AND u.created_at <= m.created_at ORDER BY u.created_at DESC LIMIT 1)))
            FROM chat_messages m
            WHERE m.role = 'assistant' AND (m.route = 'handoff' OR m.feedback = -1)
              AND {LOCAL % 'm.created_at'} BETWEEN :f AND :t""",  # noqa: S608
        f=start, t=end,
    ):  # fmt: skip
        if question:
            flagged[question] += 1
    counts = sorted(flagged.values(), reverse=True)[:10]
    assert [u["count"] for u in body["unanswered"]] == counts
    assert all("@" not in u["question"] for u in body["unanswered"])


# --- who sees what and the export -----------------------------------------------------------------------------


NEW_ADMIN_ONLY = ["/revenue/dentist-services", "/dentists/leaderboard"]
NEW_OWN_FINANCE = ["/revenue/by-weekday", "/revenue/service-trends"]
NEW_FRONT_DESK = ["/patients/demographics", "/patients/top"]


async def code(api: Api, path: str) -> int:
    response = await api.ctx.client.get(
        f"/api/v1/analytics{path}",
        params={"as_of": AS_OF.isoformat(), **span(*RANGES[1])},
        headers=api.headers,
    )
    return response.status_code


@pytest.mark.parametrize(
    "path", [*NEW_ADMIN_ONLY, *NEW_OWN_FINANCE, *NEW_FRONT_DESK, "/appointments/channels"]
)
async def test_new_figures_follow_the_same_access_rules(ctx: Ctx, admin: Api, path: str) -> None:
    desk = await api_for(ctx, UserRole.RECEPTIONIST)
    patient = await api_for(ctx, UserRole.PATIENT)
    assert await code(admin, path) == 200
    assert await code(patient, path) == 403
    desk_ok = path in NEW_FRONT_DESK or path == "/appointments/channels"
    assert await code(desk, path) == (200 if desk_ok else 403)


@pytest.mark.parametrize("path", [*NEW_ADMIN_ONLY, *NEW_FRONT_DESK])
async def test_a_dentist_cannot_see_clinic_wide_figures(ctx: Ctx, path: str) -> None:
    dentist = await api_for(ctx, UserRole.DENTIST)
    assert await code(dentist, path) == 403


@pytest.mark.parametrize(
    "dataset",
    [
        "by_weekday",
        "service_trends",
        "dentist_services",
        "leaderboard",
        "demographics",
        "top_patients",
        "channels",
    ],
)
async def test_new_datasets_export_as_csv(admin: Api, dataset: str) -> None:
    response = await admin.ctx.client.get(
        "/api/v1/analytics/export/csv",
        params={"dataset": dataset, "as_of": AS_OF.isoformat(), **span(*RANGES[1])},
        headers=admin.headers,
    )
    assert response.status_code == 200
    lines = response.text.strip().splitlines()
    assert len(lines) >= 2 and "," in lines[0]
    assert "series" not in lines[0]
