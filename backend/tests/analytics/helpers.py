"""Independent calculations for the analytics tests: plain SQL on the base tables, never the
materialized views, and plain Python for schedules."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from tests.analytics.conftest import AS_OF
from tests.auth.conftest import Ctx

TZ = ZoneInfo("America/New_York")
LOCAL = "(%s AT TIME ZONE 'America/New_York')::date"

RANGES = [
    (date(2024, 9, 1), date(2025, 2, 28)),
    (date(2025, 7, 1), date(2025, 9, 30)),
    (date(2026, 3, 1), date(2026, 5, 31)),
]


@dataclass
class Api:
    ctx: Ctx
    headers: dict[str, str]

    async def get(self, path: str, **params: Any) -> dict[str, Any]:
        query = {"as_of": AS_OF.isoformat(), **{k: v for k, v in params.items() if v is not None}}
        response = await self.ctx.client.get(
            f"/api/v1/analytics{path}", params=query, headers=self.headers
        )
        assert response.status_code == 200, (path, response.status_code, response.text)
        body: dict[str, Any] = response.json()
        return body


def span(f: date, t: date) -> dict[str, str]:
    return {"from": f.isoformat(), "to": t.isoformat()}


def money(value: Any) -> Decimal:
    return Decimal(str(value))


async def scalar(ctx: Ctx, sql: str, **params: Any) -> Any:
    rows = await ctx.fetch(sql, **params)
    return rows[0][0]


def filters_sql(
    dentist: str | None, service: str | None, alias: str = "a"
) -> tuple[str, dict[str, Any]]:
    clause, params = "", {}
    if dentist:
        clause += f" AND {alias}.dentist_id = :dentist"
        params["dentist"] = dentist
    if service:
        clause += f" AND {alias}.service_id = :service"
        params["service"] = service
    return clause, params


async def billed(
    ctx: Ctx,
    f: date,
    t: date,
    dentist: str | None = None,
    service: str | None = None,
    payer: str | None = None,
) -> Decimal:
    extra, params = filters_sql(dentist, service)
    expression = {
        None: "i.total",
        "insurer": "LEAST(i.insurance_expected, i.total)",
        "patient": "i.total - LEAST(i.insurance_expected, i.total)",
    }[payer]
    value = await scalar(
        ctx,
        f"""SELECT COALESCE(sum({expression}), 0) FROM invoices i JOIN appointments a ON a.id = i.appointment_id
            WHERE i.status NOT IN ('draft', 'void') AND {LOCAL % 'i.issued_at'} BETWEEN :f AND :t {extra}""",  # noqa: S608
        f=f, t=t, **params,
    )  # fmt: skip
    return money(value)


async def collected(
    ctx: Ctx,
    f: date,
    t: date,
    dentist: str | None = None,
    service: str | None = None,
    payer: str | None = None,
) -> Decimal:
    extra, params = filters_sql(dentist, service)
    if payer:
        extra += " AND p.payer_type = CAST(:payer AS payer_type)"
        params["payer"] = payer
    value = await scalar(
        ctx,
        f"""SELECT COALESCE(sum(p.amount), 0) FROM payments p
            JOIN invoices i ON i.id = p.invoice_id JOIN appointments a ON a.id = i.appointment_id
            WHERE {LOCAL % 'p.paid_at'} BETWEEN :f AND :t {extra}""",  # noqa: S608
        f=f, t=t, **params,
    )  # fmt: skip
    return money(value)


async def paid_to_date(
    ctx: Ctx,
    f: date,
    t: date,
    dentist: str | None = None,
    service: str | None = None,
    payer: str | None = None,
) -> Decimal:
    """Payments, whenever made, on invoices issued in the range."""
    extra, params = filters_sql(dentist, service)
    if payer:
        extra += " AND p.payer_type = CAST(:payer AS payer_type)"
        params["payer"] = payer
    value = await scalar(
        ctx,
        f"""SELECT COALESCE(sum(p.amount), 0) FROM payments p
            JOIN invoices i ON i.id = p.invoice_id JOIN appointments a ON a.id = i.appointment_id
            WHERE i.status NOT IN ('draft', 'void') AND {LOCAL % 'i.issued_at'} BETWEEN :f AND :t {extra}""",  # noqa: S608
        f=f, t=t, **params,
    )  # fmt: skip
    return money(value)


async def status_counts(
    ctx: Ctx, f: date, t: date, dentist: str | None = None, service: str | None = None
) -> dict[str, int]:
    extra, params = filters_sql(dentist, service)
    rows = await ctx.fetch(
        f"""SELECT a.status::text, count(*) FROM appointments a
            WHERE {LOCAL % 'lower(a.slot)'} BETWEEN :f AND :t {extra} GROUP BY 1""",  # noqa: S608
        f=f, t=t, **params,
    )  # fmt: skip
    return {status: int(n) for status, n in rows}


async def booked_minutes(ctx: Ctx, f: date, t: date, dentist: str | None = None) -> int:
    extra, params = filters_sql(dentist, None)
    value = await scalar(
        ctx,
        f"""SELECT COALESCE(sum(EXTRACT(epoch FROM upper(a.slot) - lower(a.slot)) / 60), 0)
            FROM appointments a
            WHERE a.status IN ('booked', 'confirmed', 'checked_in', 'completed')
              AND {LOCAL % 'lower(a.slot)'} BETWEEN :f AND :t {extra}""",  # noqa: S608
        f=f, t=t, **params,
    )  # fmt: skip
    return int(value)


async def available_minutes(ctx: Ctx, f: date, t: date, dentist: str | None = None) -> int:
    """Schedule minutes worked out in Python: the weekly template, minus the lunch break and
    the schedule exceptions, from the day each dentist joined."""
    clause = " WHERE d.id = :d" if dentist else ""
    params = {"d": dentist} if dentist else {}
    dentists = await ctx.fetch(f"SELECT d.id::text, d.created_at FROM dentists d{clause}", **params)  # noqa: S608
    schedules = await ctx.fetch(
        "SELECT dentist_id::text, weekday, start_time, end_time, break_start, break_end FROM dentist_schedules"
    )
    exceptions = await ctx.fetch(
        "SELECT dentist_id::text, starts_at, ends_at FROM schedule_exceptions"
    )
    templates = {(d, w): (s, e, bs, be) for d, w, s, e, bs, be in schedules}
    blocked: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for d, start, end in exceptions:
        blocked[d].append((start, end))
    total = 0.0
    for dentist_id, created in dentists:
        joined = created.astimezone(TZ).date()
        day = max(f, joined)
        while day <= t:
            template = templates.get((dentist_id, day.weekday()))
            if template:
                start, end, bs, be = template
                windows = [(start, bs), (be, end)] if bs and be else [(start, end)]
                for lo, hi in windows:
                    w0 = datetime.combine(day, lo, tzinfo=TZ).astimezone(UTC)
                    w1 = datetime.combine(day, hi, tzinfo=TZ).astimezone(UTC)
                    minutes = (w1 - w0).total_seconds() / 60
                    for e0, e1 in blocked[dentist_id]:
                        overlap = (min(w1, e1) - max(w0, e0)).total_seconds() / 60
                        minutes -= max(overlap, 0)
                    total += minutes
            day += timedelta(days=1)
    return int(round(total))


def bucket_start(day: date, granularity: str) -> date:
    if granularity == "day":
        return day
    if granularity == "week":
        return day - timedelta(days=day.weekday())
    if granularity == "month":
        return day.replace(day=1)
    return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ).astimezone(UTC)
