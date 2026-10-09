"""A tiny clinic whose every figure was worked out by hand.

Eight appointments in one week, four invoices, a handful of payments. The expected values are
written as plain arithmetic in the comments, so a reviewer can check the definitions in
docs/metrics.md without trusting any query.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.dialects.postgresql import Range

from app.analytics.refresh import refresh_views
from app.db.enums import (
    AppointmentChannel,
    AppointmentStatus,
    InvoiceStatus,
    PaymentMethod,
    UserRole,
)
from app.db.models import (
    Appointment,
    Dentist,
    DentistSchedule,
    InsuranceProvider,
    Invoice,
    InvoiceItem,
    Patient,
    Payment,
    Service,
)
from tests.analytics.helpers import TZ
from tests.auth.conftest import Ctx, unique_email

AS_OF = date(2026, 2, 28)
WEEK = {"from": "2026-02-02", "to": "2026-02-08", "as_of": AS_OF.isoformat()}


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ).astimezone(UTC)


@dataclass
class Golden:
    ctx: Ctx
    headers: dict[str, str]

    async def get(self, path: str, **params: Any) -> dict[str, Any]:
        query = {**WEEK, **params}
        response = await self.ctx.client.get(
            f"/api/v1/analytics{path}", params=query, headers=self.headers
        )
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body


@pytest.fixture
async def golden(ctx: Ctx) -> Golden:
    async with ctx.session_factory() as db:
        exam = Service(code="SV02", name="Routine Exam and Cleaning", category="preventive", duration_min=45, base_price=Decimal("120"))  # fmt: skip
        filling = Service(code="SV04", name="Tooth Colored Filling", category="restorative", duration_min=45, base_price=Decimal("210"))  # fmt: skip
        crown = Service(code="SV05", name="Porcelain Crown", category="restorative", duration_min=90, base_price=Decimal("1150"))  # fmt: skip
        consult = Service(code="SV12", name="Orthodontic Consultation", category="orthodontic", duration_min=45, base_price=Decimal("75"))  # fmt: skip
        joined = at(date(2026, 1, 1), 6)
        a = Dentist(full_name="Dr. Alma Test", specialty="general", created_at=joined)
        b = Dentist(full_name="Dr. Bruno Test", specialty="general", created_at=joined)
        insurer = InsuranceProvider(name="Golden Mutual", plan_types=["ppo"])
        db.add_all([exam, filling, crown, consult, a, b, insurer])
        await db.flush()
        for weekday in range(5):
            db.add(
                DentistSchedule(
                    dentist_id=a.id, weekday=weekday, start_time=time(8, 0), end_time=time(18, 0),
                    break_start=time(12, 30), break_end=time(13, 30),
                )
            )  # fmt: skip
        db.add(DentistSchedule(dentist_id=b.id, weekday=1, start_time=time(9, 0), end_time=time(13, 0)))  # fmt: skip

        def patient(name: str, created: datetime, insured: bool = False) -> Patient:
            return Patient(
                first_name=name, last_name="Golden", email=f"{name.lower()}@example.com",
                created_at=created, insurance_provider_id=insurer.id if insured else None,
            )  # fmt: skip

        p1 = patient("Pia", at(date(2026, 1, 20), 9), insured=True)
        p2 = patient("Omar", at(date(2025, 12, 1), 9))
        p3 = patient("Tess", at(date(2026, 1, 13), 9), insured=True)
        p4 = patient("Rhea", at(date(2025, 12, 15), 9))
        p5 = patient("Sol", at(date(2026, 1, 14), 9))
        p6 = patient("Una", at(date(2026, 1, 16), 9))
        db.add_all([p1, p2, p3, p4, p5, p6])
        await db.flush()

        def appointment(
            who: Patient, dentist: Dentist, service: Service, start: datetime, minutes: int,
            status: AppointmentStatus, lead_days: float, late: bool = False,
        ) -> Appointment:  # fmt: skip
            return Appointment(
                patient_id=who.id, dentist_id=dentist.id, service_id=service.id,
                slot=Range(start, start + timedelta(minutes=minutes), bounds="[)"), status=status,
                channel=AppointmentChannel.STAFF, created_at=start - timedelta(days=lead_days),
                late_cancel=late,
            )  # fmt: skip

        S = AppointmentStatus
        week = date(2026, 2, 2)
        day = timedelta(days=1)
        j1 = appointment(
            p2, a, exam, at(date(2026, 1, 12), 9), 45, S.COMPLETED, 7
        )  # the data begins here
        a1 = appointment(p1, a, exam, at(week, 9), 45, S.COMPLETED, 1 / 24)
        a2 = appointment(p2, a, filling, at(week, 10), 45, S.COMPLETED, 2)
        a3 = appointment(p3, a, crown, at(week + day, 9), 90, S.COMPLETED, 4)
        a4 = appointment(p4, b, consult, at(week + day, 9), 45, S.COMPLETED, 10)
        a5 = appointment(p5, a, exam, at(week + 2 * day, 14), 45, S.NO_SHOW, 20)
        a6 = appointment(p6, a, exam, at(week + 3 * day, 11), 45, S.CANCELLED, 40, late=True)
        a7 = appointment(p1, a, filling, at(week + 4 * day, 9), 45, S.BOOKED, 7)
        a8 = appointment(p2, b, exam, at(week + day, 10), 45, S.CONFIRMED, 14)
        db.add_all([j1, a1, a2, a3, a4, a5, a6, a7, a8])
        await db.flush()

        def bill(appt: Appointment, who: Patient, total: str, expected: str, issued: datetime) -> Invoice:  # fmt: skip
            invoice = Invoice(
                appointment_id=appt.id, patient_id=who.id, issued_at=issued, subtotal=Decimal(total),
                discount=Decimal("0"), tax=Decimal("0"), total=Decimal(total),
                insurance_expected=Decimal(expected), status="paid",
            )  # fmt: skip
            db.add(invoice)
            return invoice

        i0 = bill(j1, p2, "120", "0", at(date(2026, 1, 12), 10))
        i1 = bill(a1, p1, "120", "100", at(week, 10))
        i2 = bill(a2, p2, "210", "0", at(week, 11))
        i3 = bill(a3, p3, "1150", "575", at(week + day, 11))
        i4 = bill(a4, p4, "75", "0", at(week + day, 10))
        i3.status = InvoiceStatus.PARTIALLY_PAID
        await db.flush()
        for invoice, service in ((i0, exam), (i1, exam), (i2, filling), (i3, crown), (i4, consult)):
            db.add(
                InvoiceItem(
                    invoice_id=invoice.id, service_id=service.id, description=service.name, qty=1,
                    unit_price=invoice.total, amount=invoice.total,
                )
            )  # fmt: skip

        def pay(invoice: Invoice, amount: str, when: datetime, insurer_pays: bool = False) -> Payment:  # fmt: skip
            return Payment(
                invoice_id=invoice.id, amount=Decimal(amount), paid_at=when,
                method=PaymentMethod.INSURANCE if insurer_pays else PaymentMethod.CARD,
                payer_type="insurer" if insurer_pays else "patient",
            )  # fmt: skip

        db.add_all(
            [
                pay(i0, "120", at(date(2026, 1, 12), 10)),
                pay(i1, "20", at(week, 10)),
                pay(i1, "100", at(date(2026, 2, 20), 12), True),
                pay(i2, "210", at(week, 11)),
                pay(i3, "575", at(week + day, 12)),  # the insurer's 575 is still unpaid
                pay(i4, "75", at(week + day, 11)),
            ]
        )
        await db.commit()
    await refresh_views(ctx.app.state.engine, concurrently=False)
    email = unique_email("admin")
    await ctx.create_user(email, UserRole.ADMIN)
    return Golden(ctx, ctx.auth(await ctx.access_token(email)))


def kpi(body: dict[str, Any], key: str) -> dict[str, Any]:
    return next(k for k in body["kpis"] if k["key"] == key)


async def test_kpis_for_the_week(golden: Golden) -> None:
    body = await golden.get("/summary")
    # Billed: 120 + 210 + 1150 + 75 = 1555. Collected in the week: 20 + 210 + 575 + 75 = 880;
    # the insurer's 100 arrives on 20 February, so it belongs to a later week.
    assert kpi(body, "billed")["value"] == 1555.0
    assert kpi(body, "collected")["value"] == 880.0
    # Collection rate: everything ever paid on these invoices, (20 + 100 + 210 + 575 + 75) / 1555.
    assert kpi(body, "collection_rate")["value"] == pytest.approx(980 / 1555)
    # Four completed visits; 1555 / 4 per visit; one no show out of 4 + 1 attended or missed.
    assert kpi(body, "completed")["value"] == 4
    assert kpi(body, "revenue_per_visit")["value"] == 388.75
    assert kpi(body, "no_show_rate")["value"] == 0.2
    # Booked minutes: 45 + 45 + 90 + 45 + 45 + 45 = 315 (the no show and the cancellation free
    # their time). Available: dentist A works 5 x 540 minutes, dentist B 240 on Tuesday.
    assert kpi(body, "utilization")["value"] == pytest.approx(315 / 2940)
    # New patients: Pia and Tess had their first visit this week and were registered after the
    # data began. Omar and Rhea were already patients.
    assert kpi(body, "new_patients")["value"] == 2
    # The week before had no billing at all, so a relative change cannot be given.
    assert kpi(body, "billed")["previous"] == 0.0
    assert kpi(body, "billed")["change_percent"] is None
    assert body["previous_from"] == "2026-01-26" and body["previous_to"] == "2026-02-01"


async def test_the_previous_period_and_change(golden: Golden) -> None:
    body = await golden.get("/summary", **{"from": "2026-02-09", "to": "2026-02-15"})
    assert kpi(body, "billed")["value"] == 0.0 and kpi(body, "billed")["previous"] == 1555.0
    assert kpi(body, "billed")["change_percent"] == -100.0
    month = await golden.get("/summary", **{"from": "2026-01-01", "to": "2026-01-31"})
    assert kpi(month, "billed")["value"] == 120.0 and kpi(month, "collected")["value"] == 120.0


async def test_revenue_by_service_dentist_and_payer(golden: Golden) -> None:
    by_service = await golden.get("/revenue/by-service")
    rows = {r["label"]: r for r in by_service["rows"]}
    assert [r["label"] for r in by_service["rows"]] == [
        "Porcelain Crown", "Tooth Colored Filling", "Routine Exam and Cleaning", "Orthodontic Consultation",
    ]  # fmt: skip
    crown = rows["Porcelain Crown"]
    assert (crown["billed"], crown["collected"]) == ("1150.00", "575.00")
    exam = rows["Routine Exam and Cleaning"]
    assert (exam["billed"], exam["collected"]) == ("120.00", "20.00")
    assert crown["share_of_billed"] == pytest.approx(1150 / 1555)

    by_dentist = {r["label"]: r for r in (await golden.get("/revenue/by-dentist"))["rows"]}
    assert by_dentist["Dr. Alma Test"]["billed"] == "1480.00"
    assert by_dentist["Dr. Alma Test"]["collected"] == "805.00"
    assert by_dentist["Dr. Bruno Test"]["billed"] == "75.00"
    assert by_dentist["Dr. Bruno Test"]["collected"] == "75.00"

    payer = await golden.get("/revenue/by-payer")
    types = {r["key"]: r for r in payer["by_payer_type"]}
    # The insurer's share of billing: 100 + 575. The patients' share: 20 + 210 + 575 + 75.
    assert types["insurer"]["billed"] == "675.00" and types["insurer"]["collected"] == "0.00"
    assert types["patient"]["billed"] == "880.00" and types["patient"]["collected"] == "880.00"
    providers = {r["label"]: r for r in payer["by_provider"]}
    assert providers["Golden Mutual"]["billed"] == "1270.00"
    assert providers["Golden Mutual"]["collected"] == "695.00"
    assert providers["Self pay"]["billed"] == "285.00"
    assert providers["Self pay"]["collected"] == "285.00"


async def test_revenue_trend_by_week_and_filters(golden: Golden) -> None:
    body = await golden.get("/revenue/trend", granularity="week", **{"from": "2026-01-05", "to": "2026-02-22"})  # fmt: skip
    points = {p["period"]: p for p in body["points"]}
    assert points["2026-01-12"]["billed"] == "120.00"
    assert points["2026-01-12"]["collected"] == "120.00"
    assert points["2026-02-02"]["billed"] == "1555.00"
    assert points["2026-02-02"]["collected"] == "880.00"
    assert points["2026-02-16"]["billed"] == "0.00"
    assert points["2026-02-16"]["collected"] == "100.00"
    only = await golden.get("/revenue/trend", granularity="week", payer_type="insurer", **{"from": "2026-02-02", "to": "2026-02-08"})  # fmt: skip
    assert only["points"][0]["billed"] == "675.00" and only["points"][0]["collected"] == "0.00"
    alma = (await golden.ctx.fetch("SELECT id FROM dentists WHERE full_name = 'Dr. Alma Test'"))[0][
        0
    ]
    assert kpi(await golden.get("/summary", dentist_id=str(alma)), "billed")["value"] == 1480.0


async def test_appointment_outcomes_for_the_week(golden: Golden) -> None:
    body = await golden.get("/appointments/status-trend", granularity="week")
    point = body["points"][0]
    counts = (point["total"], point["completed"], point["cancelled"], point["late_cancelled"], point["no_show"], point["open"])  # fmt: skip
    assert counts == (8, 4, 1, 1, 1, 2)
    assert point["no_show_rate"] == 0.2 and point["cancellation_rate"] == 1 / 8


async def test_the_weekday_by_hour_heatmap(golden: Golden) -> None:
    body = await golden.get("/appointments/heatmap")
    cells = {(c["weekday"], c["hour"]): (c["appointments"], c["no_show"]) for c in body["cells"]}
    # Monday 9 and 10, Tuesday 9 (two dentists) and 10, Wednesday 14 (the no show), Friday 9.
    assert cells == {(0, 9): (1, 0), (0, 10): (1, 0), (1, 9): (2, 0), (1, 10): (1, 0), (2, 14): (1, 1), (4, 9): (1, 0)}  # fmt: skip
    assert body["max_appointments"] == 2


async def test_lead_time(golden: Golden) -> None:
    body = await golden.get("/appointments/lead-time")
    # 1 hour, 2, 4, 7, 10, 14, 20 and 40 days ahead.
    assert [b["appointments"] for b in body["buckets"]] == [1, 1, 2, 2, 1, 1]
    assert body["appointments"] == 8 and body["median_days"] == 8.5
    assert body["average_days"] == pytest.approx((1 / 24 + 2 + 4 + 7 + 10 + 14 + 20 + 40) / 8, abs=0.01)  # fmt: skip


async def test_new_and_returning_patients(golden: Golden) -> None:
    body = await golden.get("/patients/new-vs-returning", granularity="week")
    point = body["points"][0]
    counts = (point["new_visits"], point["returning_visits"], point["new_patients"], point["returning_patients"])  # fmt: skip
    assert counts == (2, 2, 2, 2)
    cohorts = await golden.get("/patients/retention-cohorts", **{"from": "2026-01-01", "to": "2026-02-28"})  # fmt: skip
    assert [(c["cohort_month"], c["cohort_size"]) for c in cohorts["cohorts"]] == [
        ("2026-02-01", 2)
    ]
    assert cohorts["cohorts"][0]["retention"][0] == 1.0
    assert cohorts["cohorts"][0]["retention"][1] is None
    assert cohorts["six_month_retention"] is None and cohorts["mature_cohorts"] == 0


async def test_receivables(golden: Golden) -> None:
    body = await golden.get("/finance/ar-aging")
    # Only the crown is unpaid: the insurer still owes 575, issued 3 February (25 days old).
    assert body["total_outstanding"] == "575.00" and body["over_90_share"] == 0.0
    shape = [(b["invoices"], b["insurer"], b["patient"]) for b in body["buckets"]]
    assert shape == [(1, "575.00", "0.00"), (0, "0.00", "0.00"), (0, "0.00", "0.00"), (0, "0.00", "0.00")]  # fmt: skip
    later = await golden.get("/finance/ar-aging", as_of="2026-05-15")
    assert later["buckets"][3]["total"] == "575.00"  # 101 days old by then
    rate = await golden.get("/finance/collection-rate")
    assert rate["overall_rate"] == pytest.approx(980 / 1555)


async def test_forecast_with_one_month_of_history_is_a_flagged_naive_repeat(golden: Golden) -> None:  # fmt: skip
    body = await golden.get("/forecast/revenue")
    assert body["method"] == "naive" and "wide interval" in body["method_note"]
    assert [h["month"] for h in body["history"]] == ["2026-01-01"]
    assert body["history"][0]["value"] == 120.0
    assert [p["month"] for p in body["forecast"]] == ["2026-02-01", "2026-03-01", "2026-04-01"]
    assert all(p["value"] == 120.0 and p["lower"] < 120.0 < p["upper"] for p in body["forecast"])
