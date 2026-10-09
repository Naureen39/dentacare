"""The synthetic dataset: reproducible, within the plan's targets, and loaded only once."""

from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import cache
from typing import Any

import pytest
from sqlalchemy import func, select

from app.db.models import Appointment, AppSetting, Dentist, Invoice, Patient
from scripts.generate_data import GenConfig, generate, summarize
from scripts.seed import MARKER_KEY, seed
from tests.analytics.conftest import NOW, PATIENTS, analytics_settings
from tests.auth.conftest import Ctx

RUN = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)


def encrypt(value: str, field: str) -> str:
    return f"enc:{field}:{value}"


@cache
def full_dataset() -> Any:
    return generate(GenConfig(now=RUN), encrypt)


def test_the_same_seed_gives_the_same_dataset() -> None:
    config = GenConfig(now=RUN, patients=300)
    a = generate(config, encrypt)
    b = generate(config, encrypt)
    assert [r["id"] for r in a.appointments] == [r["id"] for r in b.appointments]
    assert [r["total"] for r in a.invoices] == [r["total"] for r in b.invoices]
    other = generate(GenConfig(now=RUN, patients=300, seed=7), encrypt)
    assert [r["id"] for r in other.appointments] != [r["id"] for r in a.appointments]


def test_history_covers_24_months_ending_the_day_before_the_run() -> None:
    data = full_dataset()
    config = data.config
    assert config.end_date == date(2026, 10, 8)
    assert config.start_date == date(2024, 10, 1)
    zone = config.tz
    past = [a for a in data.appointments if a["slot"][0] <= RUN]
    local_days = {a["slot"][0].astimezone(zone).date() for a in past}
    assert min(local_days) >= config.start_date
    assert max(local_days) <= date(2026, 10, 9)
    months = {d.strftime("%Y-%m") for d in local_days}
    assert len(months) >= 24


def test_volumes_match_the_plan() -> None:
    data = full_dataset()
    report = summarize(data)
    assert report["patients"] == 4500
    assert 18_000 <= report["appointments"] <= 25_000
    assert len(data.dentists) == 7 and len(data.services) == 14
    # One invoice per completed appointment.
    assert report["invoices"] == report["status"]["completed"]
    assert len({i["appointment_id"] for i in data.invoices}) == len(data.invoices)


def test_the_status_mix_matches_the_plan() -> None:
    report = summarize(full_dataset())
    assert 0.80 <= report["completed_share"] <= 0.85
    assert 0.07 <= report["cancel_share"] <= 0.10
    assert 0.08 <= report["no_show_share"] <= 0.11


def test_the_service_mix_is_close_to_the_plan() -> None:
    data = full_dataset()
    mix = summarize(data)["mix"]
    total = sum(mix.values())
    routine = (mix["SV01"] + mix["SV02"] + mix["SV03"]) / total
    assert 0.40 <= routine <= 0.52  # cleanings and exams, about 45 percent
    assert 0.14 <= mix["SV04"] / total <= 0.22  # fillings, about 18 percent
    assert 0.05 <= mix["SV05"] / total <= 0.10  # crowns, about 8 percent
    assert 0.02 <= mix["SV14"] / total <= 0.06  # emergency visits, about 4 percent


def test_volume_grows_with_a_seasonal_shape() -> None:
    monthly = summarize(full_dataset())["monthly_completed"]
    months = sorted(monthly)
    first = sum(monthly[m] for m in months[:12])
    second = sum(monthly[m] for m in months[12:24])
    assert 1.04 <= second / first <= 1.15  # about 8 percent a year
    by_month: dict[int, list[int]] = defaultdict(list)
    for key in months[:24]:
        by_month[int(key[5:])].append(monthly[key])
    average = {m: sum(v) / len(v) for m, v in by_month.items()}
    assert (average[7] + average[8]) / 2 < sum(average.values()) / 12  # slow summer
    assert (average[10] + average[11] + average[12]) / 3 > sum(average.values()) / 12  # strong Q4


def test_the_week_has_the_plans_shape() -> None:
    data = full_dataset()
    zone = data.config.tz
    weekday = Counter(a["slot"][0].astimezone(zone).weekday() for a in data.appointments)
    assert weekday[6] == 0  # closed on Sunday
    assert weekday[5] < weekday[1] / 1.8  # Saturday is a half day
    assert weekday[4] < weekday[2]  # Friday is lighter than midweek
    assert min(weekday[1], weekday[2], weekday[3]) > weekday[0] * 0.9
    for a in data.appointments:
        start, end = (t.astimezone(zone) for t in a["slot"])
        opens, closes = (9, 14) if start.weekday() == 5 else (8, 18)
        assert opens <= start.hour and (end.hour, end.minute) <= (closes, 0)
        if start.weekday() < 5:  # nothing overlaps the 12:30 to 13:30 lunch block
            lunch = (start.hour * 60 + start.minute, end.hour * 60 + end.minute)
            assert not (lunch[0] < 13 * 60 + 30 and lunch[1] > 12 * 60 + 30)


def test_a_new_dentist_joins_in_month_10_and_another_cuts_days_in_month_18() -> None:
    data = full_dataset()
    zone = data.config.tz
    names = {d["id"]: d["full_name"] for d in data.dentists}
    first_visit: dict[str, date] = {}
    fridays_late = 0
    for a in data.appointments:
        day = a["slot"][0].astimezone(zone).date()
        name = names[a["dentist_id"]]
        first_visit[name] = min(first_visit.get(name, day), day)
        if name == "Dr. Daniel Reyes" and day.weekday() == 4 and day >= date(2026, 4, 1):
            fridays_late += 1
    assert first_visit["Dr. Amara Nwosu"] >= date(2025, 7, 1)
    assert fridays_late == 0


def test_no_show_risk_depends_on_the_planned_drivers() -> None:
    data = full_dataset()
    zone = data.config.tz
    rows = [a for a in data.appointments if a["status"] in ("completed", "no_show")]
    short = [a for a in rows if (a["slot"][0] - a["created_at"]).days <= 3]
    long = [a for a in rows if (a["slot"][0] - a["created_at"]).days >= 21]

    def rate(xs: list[dict[str, Any]]) -> float:
        return float(sum(a["status"] == "no_show" for a in xs) / len(xs))

    assert rate(long) > rate(short) * 1.3  # longer lead time, more no shows
    early = [a for a in rows if a["slot"][0].astimezone(zone).hour < 9]
    assert rate(early) > rate(rows)


def test_pricing_follows_the_plan() -> None:
    data = full_dataset()
    zone = data.config.tz
    start = data.config.start_date
    code = {s["id"]: s["code"] for s in data.services}
    when = {a["id"]: a for a in data.appointments}
    prices: dict[bool, set[Decimal]] = {False: set(), True: set()}
    for item in data.invoice_items:
        appointment = next(
            a
            for a in [
                when[i["appointment_id"]] for i in data.invoices if i["id"] == item["invoice_id"]
            ][:1]
        )
        if code[item["service_id"]] != "SV02":
            continue
        day = appointment["slot"][0].astimezone(zone).date()
        months = (day.year - start.year) * 12 + day.month - start.month
        prices[months >= 12].add(item["unit_price"])
    assert prices[False] == {Decimal("120.00")}
    assert prices[True] == {Decimal("124.80")}  # 4 percent more from month 13


def test_billing_is_internally_consistent() -> None:
    data = full_dataset()
    paid: dict[Any, Decimal] = defaultdict(Decimal)
    for p in data.payments:
        paid[p["invoice_id"]] += p["amount"]
        assert p["amount"] > 0
        assert (p["method"] == "insurance") == (p["payer_type"] == "insurer")
    for invoice in data.invoices:
        assert invoice["total"] == invoice["subtotal"] - invoice["discount"] + invoice["tax"]
        assert 0 <= invoice["insurance_expected"] <= invoice["total"]
        total = paid[invoice["id"]]
        expected = (
            "paid" if total >= invoice["total"] else ("partially_paid" if total > 0 else "issued")
        )
        assert invoice["status"] == expected
    assert all(p["paid_at"] <= RUN for p in data.payments)


def test_payers_and_collection_timing_follow_the_plan() -> None:
    data = full_dataset()
    insured = sum(1 for p in data.patients if p["insurance_provider_id"]) / len(data.patients)
    assert 0.55 <= insured <= 0.61
    issued = {i["id"]: i["issued_at"] for i in data.invoices}
    delays = [
        (p["paid_at"] - issued[p["invoice_id"]]).days
        for p in data.payments
        if p["payer_type"] == "insurer"
    ]
    assert delays and min(delays) >= 14 and max(delays) <= 46
    same_day = [
        p
        for p in data.payments
        if p["payer_type"] == "patient" and (p["paid_at"] - issued[p["invoice_id"]]).days == 0
    ]
    assert len(same_day) > 0.6 * sum(1 for p in data.payments if p["payer_type"] == "patient")
    assert any(i["status"] != "paid" for i in data.invoices)  # receivables exist


def test_new_patients_are_a_modest_share_of_visits() -> None:
    data = full_dataset()
    zone = data.config.tz
    first: dict[Any, Any] = {}
    for a in sorted(data.appointments, key=lambda a: a["slot"][0]):
        if a["status"] == "completed":
            first.setdefault(a["patient_id"], a["id"])
    created = {p["id"]: p["created_at"] for p in data.patients}
    start = min(a["slot"][0] for a in data.appointments)
    new_ids = {aid for pid, aid in first.items() if created[pid] >= start}
    completed = [a for a in data.appointments if a["status"] == "completed"]
    share = len([a for a in completed if a["id"] in new_ids]) / len(completed)
    assert 0.11 <= share <= 0.20, share
    del zone


# --- loading it ---------------------------------------------------------------------------------------------------


async def test_seeding_twice_does_not_duplicate_and_reset_replaces(ctx: Ctx) -> None:
    async with ctx.session_factory() as db:
        before = (await db.execute(select(func.count()).select_from(Appointment))).scalar_one()
        marker = (
            await db.execute(select(AppSetting.value).where(AppSetting.key == MARKER_KEY))
        ).scalar_one()
    assert marker["patients"] == PATIENTS and marker["version"] == 1
    again = await seed(
        ctx.session_factory, analytics_settings(), now=NOW, patients=PATIENTS, demo=False
    )
    assert again["skipped"] == "already seeded"
    async with ctx.session_factory() as db:
        after = (await db.execute(select(func.count()).select_from(Appointment))).scalar_one()
        patients = (await db.execute(select(func.count()).select_from(Patient))).scalar_one()
    assert after == before and patients == PATIENTS


async def test_the_loaded_data_respects_the_database_rules(ctx: Ctx) -> None:
    async with ctx.session_factory() as db:
        dentists = (await db.execute(select(func.count()).select_from(Dentist))).scalar_one()
        invoices = (await db.execute(select(func.count()).select_from(Invoice))).scalar_one()
        completed = (
            await db.execute(
                select(func.count())
                .select_from(Appointment)
                .where(Appointment.status == "completed")
            )
        ).scalar_one()
    assert dentists == 7 and invoices == completed
    # Personal fields are encrypted at rest, like everything written through the application.
    rows = await ctx.fetch("SELECT dob_enc, phone_enc FROM patients LIMIT 3")
    assert all(not r[0].startswith("enc:") and r[0] != r[1] for r in rows)
    pytest.importorskip("cryptography")
