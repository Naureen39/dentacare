"""Every figure the dashboards show, checked against SQL written separately on the base tables
for three date ranges and for filtered views."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from tests.analytics.conftest import AS_OF
from tests.analytics.helpers import (
    RANGES,
    TZ,
    Api,
    available_minutes,
    billed,
    booked_minutes,
    bucket_start,
    collected,
    money,
    paid_to_date,
    scalar,
    span,
    status_counts,
)
from tests.auth.conftest import Ctx


@pytest.fixture
async def busy_dentist(ctx: Ctx) -> str:
    return str(
        await scalar(
            ctx,
            "SELECT dentist_id::text FROM appointments GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1",
        )
    )


@pytest.fixture
async def busy_service(ctx: Ctx) -> str:
    return str(
        await scalar(
            ctx,
            "SELECT service_id::text FROM appointments GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1",
        )
    )


def kpi(summary: dict[str, Any], key: str) -> dict[str, Any]:
    return next(k for k in summary["kpis"] if k["key"] == key)


def approx(value: float | None, expected: float | None) -> bool:
    if expected is None:
        return value is None
    return value is not None and abs(value - expected) < 1e-9 * max(1.0, abs(expected))


# --- reconciliation ---------------------------------------------------------------------------------------------------


async def test_monthly_revenue_reconciles_with_payments_and_invoices(ctx: Ctx) -> None:
    payments = money(await scalar(ctx, "SELECT sum(amount) FROM payments"))
    invoices = money(
        await scalar(ctx, "SELECT sum(total) FROM invoices WHERE status NOT IN ('draft', 'void')")
    )
    assert payments > 0 and invoices > payments  # some receivables are still open
    assert money(await scalar(ctx, "SELECT sum(collected) FROM mv_monthly_revenue")) == payments
    assert money(await scalar(ctx, "SELECT sum(collected) FROM mv_daily_revenue")) == payments
    assert money(await scalar(ctx, "SELECT sum(billed) FROM mv_monthly_revenue")) == invoices
    # Billed is split between the insurer's and the patient's share of every invoice.
    parts = await ctx.fetch(
        "SELECT payer_type::text, sum(billed) FROM mv_monthly_revenue GROUP BY 1"
    )
    assert sum(money(v) for _, v in parts) == invoices


async def test_the_trend_over_all_history_reconciles_with_payments(ctx: Ctx, admin: Api) -> None:
    first = await scalar(
        ctx, "SELECT min((lower(slot) AT TIME ZONE 'America/New_York')::date) FROM appointments"
    )
    body = await admin.get(
        "/revenue/trend",
        granularity="month",
        **span(first - timedelta(days=60), AS_OF + timedelta(days=60)),
    )
    total = sum(money(p["collected"]) for p in body["points"])
    assert total == money(await scalar(ctx, "SELECT sum(amount) FROM payments"))
    assert sum(money(p["billed"]) for p in body["points"]) == money(
        await scalar(ctx, "SELECT sum(total) FROM invoices WHERE status NOT IN ('draft', 'void')")
    )


# --- summary ----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("start", "end"), RANGES)
async def test_summary_matches_sql(ctx: Ctx, admin: Api, start: date, end: date) -> None:
    body = await admin.get("/summary", **span(start, end))
    length = (end - start).days + 1
    p_end = start - timedelta(days=1)
    p_start = p_end - timedelta(days=length - 1)
    assert body["previous_from"] == p_start.isoformat() and body["previous_to"] == p_end.isoformat()

    b, c = await billed(ctx, start, end), await collected(ctx, start, end)
    pb, pc = await billed(ctx, p_start, p_end), await collected(ctx, p_start, p_end)
    assert money(kpi(body, "billed")["value"]) == b and money(kpi(body, "billed")["previous"]) == pb
    assert (
        money(kpi(body, "collected")["value"]) == c
        and money(kpi(body, "collected")["previous"]) == pc
    )
    rate = float(await paid_to_date(ctx, start, end)) / float(b)
    assert approx(kpi(body, "collection_rate")["value"], rate)
    expected_change = (float(b) - float(pb)) / float(pb) * 100
    assert abs(kpi(body, "billed")["change_percent"] - round(expected_change, 2)) < 0.01

    counts = await status_counts(ctx, start, end)
    prev_counts = await status_counts(ctx, p_start, p_end)
    done, missed = counts.get("completed", 0), counts.get("no_show", 0)
    assert kpi(body, "completed")["value"] == done
    assert kpi(body, "completed")["previous"] == prev_counts.get("completed", 0)
    assert approx(kpi(body, "no_show_rate")["value"], missed / (done + missed))
    assert approx(kpi(body, "revenue_per_visit")["value"], float(b) / done)

    util = await booked_minutes(ctx, start, end) / await available_minutes(ctx, start, end)
    assert approx(kpi(body, "utilization")["value"], util)
    assert 0.0 < util < 1.0  # this small test clinic is quiet; the full demo dataset runs fuller

    new = await scalar(
        ctx,
        """WITH f AS (
               SELECT DISTINCT ON (a.patient_id) a.patient_id, (lower(a.slot) AT TIME ZONE 'America/New_York')::date AS day
               FROM appointments a JOIN patients p ON p.id = a.patient_id
               WHERE a.status = 'completed' AND p.created_at >= (SELECT min(lower(slot)) FROM appointments)
               ORDER BY a.patient_id, lower(a.slot))
           SELECT count(*) FROM f WHERE day BETWEEN :f AND :t""",
        f=start, t=end,
    )  # fmt: skip
    assert kpi(body, "new_patients")["value"] == new


async def test_every_kpi_has_a_sparkline_and_a_direction(admin: Api) -> None:
    body = await admin.get("/summary", **span(date(2025, 7, 1), date(2025, 9, 30)))
    keys = [k["key"] for k in body["kpis"]]
    assert keys == ["billed", "collected", "collection_rate", "completed", "revenue_per_visit", "utilization", "no_show_rate", "new_patients"]  # fmt: skip
    for item in body["kpis"]:
        assert item["sparkline"], item["key"]
        assert all(point["period"] for point in item["sparkline"])
    assert kpi(body, "no_show_rate")["higher_is_better"] is False
    assert kpi(body, "utilization")["change_kind"] == "points"


async def test_sparkline_totals_equal_the_kpi(admin: Api) -> None:
    body = await admin.get("/summary", **span(date(2025, 7, 1), date(2025, 9, 30)))
    billed_total = sum(p["value"] for p in kpi(body, "billed")["sparkline"])
    assert abs(billed_total - kpi(body, "billed")["value"]) < 0.01
    assert (
        sum(p["value"] for p in kpi(body, "completed")["sparkline"])
        == kpi(body, "completed")["value"]
    )


async def test_summary_filters_by_dentist_and_service(
    ctx: Ctx, admin: Api, busy_dentist: str, busy_service: str
) -> None:
    start, end = RANGES[0]
    body = await admin.get(
        "/summary", dentist_id=busy_dentist, service_id=busy_service, **span(start, end)
    )
    assert money(kpi(body, "billed")["value"]) == await billed(
        ctx, start, end, busy_dentist, busy_service
    )
    assert money(kpi(body, "collected")["value"]) == await collected(
        ctx, start, end, busy_dentist, busy_service
    )
    counts = await status_counts(ctx, start, end, busy_dentist, busy_service)
    assert kpi(body, "completed")["value"] == counts.get("completed", 0)
    body = await admin.get("/summary", dentist_id=busy_dentist, **span(start, end))
    util = await booked_minutes(ctx, start, end, busy_dentist) / await available_minutes(
        ctx, start, end, busy_dentist
    )
    assert approx(kpi(body, "utilization")["value"], util)


async def test_summary_filters_by_payer_type(ctx: Ctx, admin: Api) -> None:
    start, end = RANGES[1]
    for payer in ("insurer", "patient"):
        body = await admin.get("/summary", payer_type=payer, **span(start, end))
        assert money(kpi(body, "billed")["value"]) == await billed(ctx, start, end, payer=payer)
        assert money(kpi(body, "collected")["value"]) == await collected(
            ctx, start, end, payer=payer
        )


# --- revenue ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("start", "end"), RANGES)
async def test_revenue_trend_by_month_with_the_prior_year(
    ctx: Ctx, admin: Api, start: date, end: date
) -> None:
    body = await admin.get("/revenue/trend", granularity="month", **span(start, end))
    assert body["meta"]["granularity"] == "month"
    for point in body["points"]:
        month = date.fromisoformat(point["period"])
        last = (month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        lo, hi = max(month, start), min(last, end)
        assert money(point["billed"]) == await billed(ctx, lo, hi)
        assert money(point["collected"]) == await collected(ctx, lo, hi)
        before_lo, before_hi = (
            lo.replace(year=lo.year - 1),
            hi.replace(year=hi.year - 1)
            if hi.day != 29 or hi.month != 2
            else hi.replace(year=hi.year - 1, day=28),
        )
        assert money(point["prior_year_billed"]) == await billed(ctx, before_lo, before_hi)
    assert sum(money(p["billed"]) for p in body["points"]) == await billed(ctx, start, end)


@pytest.mark.parametrize("granularity", ["day", "week", "month", "quarter"])
async def test_granularities_bucket_the_same_totals(ctx: Ctx, admin: Api, granularity: str) -> None:
    start, end = date(2025, 1, 1), date(2025, 12, 31)
    body = await admin.get("/revenue/trend", granularity=granularity, **span(start, end))
    periods = [date.fromisoformat(p["period"]) for p in body["points"]]
    assert periods == sorted(periods) and len(set(periods)) == len(periods)
    assert all(bucket_start(p, granularity) == p for p in periods)
    expected = {"day": 300, "week": 52, "month": 12, "quarter": 4}[granularity]
    assert (
        len(periods) >= expected * 0.85
        if granularity == "day"
        else len(periods) in (expected, expected + 1)
    )
    assert sum(money(p["collected"]) for p in body["points"]) == await collected(ctx, start, end)


@pytest.mark.parametrize(("start", "end"), RANGES)
async def test_revenue_by_service_dentist_and_payer(
    ctx: Ctx, admin: Api, start: date, end: date
) -> None:
    by_service = await admin.get("/revenue/by-service", **span(start, end))
    rows = await ctx.fetch("SELECT id::text FROM services")
    for (service_id,) in rows:
        row = next((r for r in by_service["rows"] if r["key"] == service_id), None)
        expected = await billed(ctx, start, end, service=service_id)
        assert (money(row["billed"]) if row else Decimal(0)) == expected
        if row:
            assert money(row["collected"]) == await collected(ctx, start, end, service=service_id)
    assert abs(sum(r["share_of_billed"] for r in by_service["rows"]) - 1.0) < 1e-9
    assert [r["billed"] for r in by_service["rows"]] == sorted(
        (r["billed"] for r in by_service["rows"]), key=money, reverse=True
    )

    by_dentist = await admin.get("/revenue/by-dentist", **span(start, end))
    assert sum(money(r["billed"]) for r in by_dentist["rows"]) == await billed(ctx, start, end)
    for row in by_dentist["rows"]:
        assert money(row["billed"]) == await billed(ctx, start, end, dentist=row["key"])

    by_payer = await admin.get("/revenue/by-payer", **span(start, end))
    types = {r["key"]: r for r in by_payer["by_payer_type"]}
    for payer in ("patient", "insurer"):
        assert money(types[payer]["billed"]) == await billed(ctx, start, end, payer=payer)
        assert money(types[payer]["collected"]) == await collected(ctx, start, end, payer=payer)
    assert sum(money(r["billed"]) for r in by_payer["by_provider"]) == await billed(ctx, start, end)
    assert any(r["key"] == "self_pay" for r in by_payer["by_provider"])


async def test_insured_patients_are_about_58_percent_of_billing_patients(ctx: Ctx) -> None:
    share = await scalar(ctx, "SELECT avg((insurance_provider_id IS NOT NULL)::int) FROM patients")
    assert 0.52 <= float(share) <= 0.64


# --- appointments --------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("start", "end"), RANGES)
async def test_status_trend_matches_sql(ctx: Ctx, admin: Api, start: date, end: date) -> None:
    body = await admin.get("/appointments/status-trend", granularity="month", **span(start, end))
    totals: dict[str, int] = defaultdict(int)
    for point in body["points"]:
        month = date.fromisoformat(point["period"])
        last = (month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        counts = await status_counts(ctx, max(month, start), min(last, end))
        assert point["completed"] == counts.get("completed", 0)
        assert point["cancelled"] == counts.get("cancelled", 0)
        assert point["no_show"] == counts.get("no_show", 0)
        assert point["total"] == sum(counts.values())
        assert point["open"] == counts.get("booked", 0) + counts.get("confirmed", 0) + counts.get(
            "checked_in", 0
        )
        done = point["completed"] + point["no_show"]
        assert approx(point["no_show_rate"], point["no_show"] / done if done else None)
        assert approx(point["cancellation_rate"], point["cancelled"] / point["total"])
        for key in ("total", "completed", "cancelled", "no_show", "late_cancelled"):
            totals[key] += point[key]
    late = await scalar(
        ctx,
        """SELECT count(*) FROM appointments WHERE status = 'cancelled' AND late_cancel
           AND (lower(slot) AT TIME ZONE 'America/New_York')::date BETWEEN :f AND :t""",
        f=start, t=end,
    )  # fmt: skip
    assert totals["late_cancelled"] == late


@pytest.mark.parametrize(("start", "end"), RANGES)
async def test_heatmap_matches_sql(ctx: Ctx, admin: Api, start: date, end: date) -> None:
    body = await admin.get("/appointments/heatmap", **span(start, end))
    rows = await ctx.fetch(
        """SELECT (EXTRACT(isodow FROM lower(slot) AT TIME ZONE 'America/New_York')::int - 1),
                  EXTRACT(hour FROM lower(slot) AT TIME ZONE 'America/New_York')::int,
                  count(*) FILTER (WHERE status <> 'cancelled'), count(*) FILTER (WHERE status = 'no_show')
           FROM appointments
           WHERE (lower(slot) AT TIME ZONE 'America/New_York')::date BETWEEN :f AND :t GROUP BY 1, 2""",
        f=start, t=end,
    )  # fmt: skip
    expected = {(w, h): (int(a), int(n)) for w, h, a, n in rows if a}
    got = {(c["weekday"], c["hour"]): (c["appointments"], c["no_show"]) for c in body["cells"]}
    assert got == expected
    assert body["max_appointments"] == max(a for a, _ in expected.values())
    assert all(w != 6 for w, _ in got)  # nothing on Sunday
    assert all(8 <= h <= 17 for _, h in got)
    friday_late = sum(a for (w, h), (a, _) in got.items() if w == 4 and h >= 15)
    tuesday_late = sum(a for (w, h), (a, _) in got.items() if w == 1 and h >= 15)
    assert friday_late < tuesday_late


@pytest.mark.parametrize(("start", "end"), RANGES)
async def test_lead_time_matches_sql(ctx: Ctx, admin: Api, start: date, end: date) -> None:
    body = await admin.get("/appointments/lead-time", **span(start, end))
    days = [
        float(r[0])
        for r in await ctx.fetch(
            """SELECT GREATEST(EXTRACT(epoch FROM (lower(slot) - created_at)) / 86400.0, 0) FROM appointments
               WHERE (lower(slot) AT TIME ZONE 'America/New_York')::date BETWEEN :f AND :t""",
            f=start, t=end,
        )
    ]  # fmt: skip
    edges = [(0, 1), (1, 3), (3, 8), (8, 15), (15, 31), (31, 10**6)]
    assert [b["appointments"] for b in body["buckets"]] == [
        sum(1 for d in days if lo <= d < hi) for lo, hi in edges
    ]
    assert body["appointments"] == len(days)
    assert abs(body["average_days"] - sum(days) / len(days)) < 0.01
    ordered = sorted(days)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    assert abs(body["median_days"] - median) < 0.01
    assert abs(sum(b["share"] for b in body["buckets"]) - 1.0) < 1e-9


# --- patients -------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("start", "end"), RANGES)
async def test_new_versus_returning_matches_sql(
    ctx: Ctx, admin: Api, start: date, end: date
) -> None:
    body = await admin.get("/patients/new-vs-returning", granularity="month", **span(start, end))
    visits = await ctx.fetch(
        """SELECT a.patient_id::text, (lower(a.slot) AT TIME ZONE 'America/New_York')::date, lower(a.slot),
                  p.created_at >= (SELECT min(lower(slot)) FROM appointments)
           FROM appointments a JOIN patients p ON p.id = a.patient_id WHERE a.status = 'completed'"""
    )  # fmt: skip
    first: dict[str, Any] = {}
    for patient, _, moment, _ in sorted(visits, key=lambda v: v[2]):
        first.setdefault(patient, moment)
    new_visits: dict[date, int] = defaultdict(int)
    old_visits: dict[date, int] = defaultdict(int)
    new_people: dict[date, set[str]] = defaultdict(set)
    old_people: dict[date, set[str]] = defaultdict(set)
    all_new: set[str] = set()
    all_old: set[str] = set()
    for patient, local_day, moment, qualifies in visits:
        if not start <= local_day <= end:
            continue
        month = local_day.replace(day=1)
        if qualifies and moment == first[patient]:
            new_visits[month] += 1
            new_people[month].add(patient)
            all_new.add(patient)
        else:
            old_visits[month] += 1
            old_people[month].add(patient)
            all_old.add(patient)
    got = {p["period"]: p for p in body["points"]}
    assert set(got) == {m.isoformat() for m in set(new_visits) | set(old_visits)}
    for month in set(new_visits) | set(old_visits):
        point = got[month.isoformat()]
        assert (
            point["new_visits"] == new_visits[month]
            and point["returning_visits"] == old_visits[month]
        )
        assert point["new_patients"] == len(new_people[month])
        assert point["returning_patients"] == len(old_people[month])
    assert body["new_patients"] == len(all_new) and body["returning_patients"] == len(all_old)


async def test_cohort_retention_matches_an_independent_count(ctx: Ctx, admin: Api) -> None:
    body = await admin.get(
        "/patients/retention-cohorts", **span(date(2024, 6, 1), date(2025, 6, 30))
    )
    visits = await ctx.fetch(
        """SELECT a.patient_id::text, (lower(a.slot) AT TIME ZONE 'America/New_York')::date
           FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE a.status = 'completed' AND p.created_at >= (SELECT min(lower(slot)) FROM appointments)"""
    )  # fmt: skip
    by_patient: dict[str, list[date]] = defaultdict(list)
    for patient, day in visits:
        by_patient[patient].append(day)
    cohorts: dict[date, list[str]] = defaultdict(list)
    for patient, days in by_patient.items():
        cohorts[min(days).replace(day=1)].append(patient)
    assert body["cohorts"]
    for row in body["cohorts"]:
        month = date.fromisoformat(row["cohort_month"])
        members = cohorts[month]
        assert row["cohort_size"] == len(members)
        assert row["retention"][0] == 1.0
        for offset in (1, 3, 6):
            index = month.year * 12 + month.month - 1 + offset
            target = date(index // 12, index % 12 + 1, 1)
            active = sum(
                1 for m in members if any(d.replace(day=1) == target for d in by_patient[m])
            )
            expected = active / len(members)
            if (AS_OF.year * 12 + AS_OF.month) - (month.year * 12 + month.month) >= offset:
                assert approx(row["retention"][offset], expected), (month, offset)
            else:
                assert row["retention"][offset] is None
    mature = [r for r in body["cohorts"] if r["returned_within_6_months"] is not None]
    assert body["mature_cohorts"] == len(mature)
    if mature:
        returned = sum(
            1
            for r in mature
            for m in cohorts[date.fromisoformat(r["cohort_month"])]
            if any(
                min(by_patient[m]) < d <= min(by_patient[m]) + timedelta(days=210)
                for d in by_patient[m]
            )
        )
        size = sum(r["cohort_size"] for r in mature)
        assert approx(body["six_month_retention"], returned / size)
        assert 0.3 < body["six_month_retention"] < 0.9


# --- finance --------------------------------------------------------------------------------------------------------------------------------


async def test_ar_aging_matches_sql(ctx: Ctx, admin: Api) -> None:
    body = await admin.get("/finance/ar-aging")
    rows = await ctx.fetch(
        """SELECT i.id, (i.issued_at AT TIME ZONE 'America/New_York')::date, i.total,
                  LEAST(i.insurance_expected, i.total),
                  COALESCE((SELECT sum(amount) FROM payments p WHERE p.invoice_id = i.id AND p.payer_type = 'insurer'), 0),
                  COALESCE((SELECT sum(amount) FROM payments p WHERE p.invoice_id = i.id AND p.payer_type = 'patient'), 0)
           FROM invoices i WHERE i.status IN ('issued', 'partially_paid')"""
    )  # fmt: skip
    buckets = [(0, 30), (31, 60), (61, 90), (91, 10**6)]
    expected: list[dict[str, Decimal]] = [
        {"n": Decimal(0), "insurer": Decimal(0), "patient": Decimal(0)} for _ in buckets
    ]
    for _, issued, total, expected_insurer, paid_insurer, paid_patient in rows:
        if total <= paid_insurer + paid_patient:
            continue
        age = (AS_OF - issued).days
        if age < 0:
            continue
        slot = next(i for i, (lo, hi) in enumerate(buckets) if lo <= age <= hi)
        expected[slot]["n"] += 1
        expected[slot]["insurer"] += max(expected_insurer - paid_insurer, Decimal(0))
        expected[slot]["patient"] += max(total - expected_insurer - paid_patient, Decimal(0))
    for got, want in zip(body["buckets"], expected, strict=True):
        assert got["invoices"] == want["n"]
        assert money(got["insurer"]) == want["insurer"] and money(got["patient"]) == want["patient"]
        assert money(got["total"]) == want["insurer"] + want["patient"]
    total = sum((w["insurer"] + w["patient"] for w in expected), Decimal(0))
    assert money(body["total_outstanding"]) == total and total > 0
    assert [b["label"] for b in body["buckets"]][-1] == "Over 90 days"
    # Insurers pay 14 to 45 days after a visit, so the newest bucket holds mostly insurer balances.
    assert money(body["buckets"][0]["insurer"]) >= money(body["buckets"][0]["patient"])


@pytest.mark.parametrize(("start", "end"), RANGES)
async def test_collection_rate_matches_sql(ctx: Ctx, admin: Api, start: date, end: date) -> None:
    body = await admin.get("/finance/collection-rate", granularity="month", **span(start, end))
    for point in body["points"]:
        month = date.fromisoformat(point["period"])
        last = (month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        lo, hi = max(month, start), min(last, end)
        b, c = await billed(ctx, lo, hi), await paid_to_date(ctx, lo, hi)
        assert money(point["billed"]) == b and money(point["collected_to_date"]) == c
        assert approx(point["rate"], float(c) / float(b))
    b, c = await billed(ctx, start, end), await paid_to_date(ctx, start, end)
    assert approx(body["overall_rate"], float(c) / float(b))
    assert 0.85 < body["overall_rate"] <= 1.0  # old cohorts are almost fully collected


async def test_recent_invoices_are_collected_less_than_old_ones(admin: Api) -> None:
    old = await admin.get("/finance/collection-rate", **span(date(2024, 9, 1), date(2024, 11, 30)))
    recent = await admin.get(
        "/finance/collection-rate", **span(date(2026, 5, 16), date(2026, 6, 15))
    )
    assert recent["overall_rate"] < old["overall_rate"]


# --- utilization and schedules -----------------------------------------------------------------------------------------------------


async def test_utilization_never_exceeds_the_schedule(ctx: Ctx) -> None:
    rows = await ctx.fetch(
        "SELECT day, dentist_id, booked_minutes, available_minutes FROM mv_utilization_daily WHERE available_minutes > 0"
    )
    assert rows and all(booked <= available + 1 for _, _, booked, available in rows)
    off = await ctx.fetch(
        "SELECT count(*) FROM mv_utilization_daily WHERE booked_minutes > 0 AND available_minutes = 0"
    )
    assert off[0][0] == 0  # nothing is ever booked outside a dentist's schedule


async def test_available_minutes_follow_the_template_and_exceptions(ctx: Ctx) -> None:
    dentist = await scalar(ctx, "SELECT id::text FROM dentists WHERE full_name = 'Dr. Priya Raman'")
    assert (
        await scalar(
            ctx,
            "SELECT sum(available_minutes) FROM mv_utilization_daily WHERE day = :d AND dentist_id = :x",
            d=date(2025, 3, 3),
            x=dentist,
        )
        == 540
    )  # a Monday: 8 to 18 less lunch
    assert (
        await scalar(
            ctx,
            "SELECT sum(available_minutes) FROM mv_utilization_daily WHERE day = :d AND dentist_id = :x",
            d=date(2025, 3, 8),
            x=dentist,
        )
        == 300
    )  # Saturday 9 to 14
    assert (
        await scalar(
            ctx,
            "SELECT sum(available_minutes) FROM mv_utilization_daily WHERE day = :d AND dentist_id = :x",
            d=date(2025, 7, 4),
            x=dentist,
        )
    ) in (0, None)  # holiday
    assert (
        await scalar(
            ctx,
            "SELECT sum(available_minutes) FROM mv_utilization_daily WHERE day = :d AND dentist_id = :x",
            d=date(2025, 3, 9),
            x=dentist,
        )
    ) in (0, None)  # Sunday
    joined = await scalar(
        ctx,
        "SELECT min(day) FROM mv_utilization_daily u JOIN dentists d ON d.id = u.dentist_id WHERE d.full_name = 'Dr. Amara Nwosu' AND available_minutes > 0",
    )
    assert joined >= date(2025, 4, 1)  # the dentist who starts in month 10 has no hours before


async def test_the_local_calendar_day_follows_the_clinic_time_zone(ctx: Ctx) -> None:
    # 23:30 in New York on 1 March is 04:30 UTC on 2 March: it still belongs to 1 March.
    assert await scalar(ctx, "SELECT clinic_date(TIMESTAMPTZ '2025-03-02 04:30:00+00')") == date(
        2025, 3, 1
    )
    assert await scalar(ctx, "SELECT clinic_date(TIMESTAMPTZ '2025-07-01 03:59:00+00')") == date(
        2025, 6, 30
    )  # daylight time
    assert TZ.key == "America/New_York"
