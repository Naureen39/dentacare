from decimal import Decimal

import pytest

from app.db.enums import UserRole
from tests.billing.helpers import API, dec, dentist_login, desk, issued_invoice, new_patient
from tests.booking.conftest import Practice


async def aged_invoice(practice: Practice, billing_desk, days: int, *, patient=None):  # type: ignore[no-untyped-def]
    invoice_id = await issued_invoice(practice, billing_desk, patient=patient)
    await practice.ctx.execute(
        "UPDATE invoices SET issued_at = now() - make_interval(days => :d) WHERE id = :i",
        d=days,
        i=invoice_id,
    )
    return invoice_id


async def bucket_of(practice: Practice, invoice_id) -> str | None:  # type: ignore[no-untyped-def]
    rows = await practice.ctx.fetch(
        "SELECT bucket FROM ar_aging WHERE invoice_id = :i", i=invoice_id
    )
    return str(rows[0][0]) if rows else None


@pytest.mark.parametrize(
    ("days", "bucket"),
    [
        (0, "0_30"),
        (1, "0_30"),
        (30, "0_30"),
        (31, "31_60"),
        (60, "31_60"),
        (61, "61_90"),
        (90, "61_90"),
        (91, "over_90"),
        (400, "over_90"),
    ],
)
async def test_invoices_fall_into_the_right_age_bucket(
    practice: Practice, days: int, bucket: str
) -> None:
    billing_desk = await desk(practice)
    invoice_id = await aged_invoice(practice, billing_desk, days)
    assert await bucket_of(practice, invoice_id) == bucket


async def test_only_open_issued_invoices_with_a_balance_appear(practice: Practice) -> None:
    from tests.billing.helpers import completed_visit

    billing_desk = await desk(practice)
    draft = await completed_visit(practice)
    paid = await issued_invoice(practice, billing_desk)
    await billing_desk.pay(paid, "120.00")
    voided = await issued_invoice(practice, billing_desk)
    await billing_desk.void(voided)
    open_invoice = await issued_invoice(practice, billing_desk)
    partial = await issued_invoice(practice, billing_desk)
    await billing_desk.pay(partial, "20.00")

    listed = {r[0] for r in await practice.ctx.fetch("SELECT invoice_id FROM ar_aging")}
    assert listed == {open_invoice, partial}
    assert draft not in listed and paid not in listed and voided not in listed


async def test_balances_reflect_partial_payments(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    await billing_desk.pay(invoice_id, "45.25")
    [(total, paid, balance)] = await practice.ctx.fetch(
        "SELECT total, paid, balance FROM ar_aging WHERE invoice_id = :i", i=invoice_id
    )
    assert (total, paid, balance) == (Decimal("120.00"), Decimal("45.25"), Decimal("74.75"))


async def test_balance_splits_into_insurance_and_patient_shares(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    await billing_desk.patch(invoice_id, insurance_expected="84.00")
    query = "SELECT insurance_outstanding, patient_outstanding FROM ar_aging WHERE invoice_id = :i"

    assert await practice.ctx.fetch(query, i=invoice_id) == [(Decimal("84.00"), Decimal("36.00"))]
    await billing_desk.pay(invoice_id, "50.00", method="insurance")
    assert await practice.ctx.fetch(query, i=invoice_id) == [(Decimal("34.00"), Decimal("36.00"))]
    await billing_desk.pay(invoice_id, "36.00", method="cash")
    assert await practice.ctx.fetch(query, i=invoice_id) == [(Decimal("34.00"), Decimal("0.00"))]
    await billing_desk.pay(invoice_id, "34.00", method="insurance")
    assert await practice.ctx.fetch(query, i=invoice_id) == []


async def test_patient_payments_reduce_the_patient_share_first_when_insurance_is_pending(
    practice: Practice,
) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    await billing_desk.patch(invoice_id, insurance_expected="100.00")
    await billing_desk.pay(invoice_id, "20.00", method="cash")  # the patient's whole share
    [(insurance, patient)] = await practice.ctx.fetch(
        "SELECT insurance_outstanding, patient_outstanding FROM ar_aging WHERE invoice_id = :i",
        i=invoice_id,
    )
    assert (insurance, patient) == (Decimal("100.00"), Decimal("0.00"))


async def test_summary_always_lists_the_four_buckets_in_order(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    response = await billing_desk.client.get(f"{API}/ar-aging", headers=billing_desk.headers)
    assert response.status_code == 200
    body = response.json()
    assert [b["bucket"] for b in body["buckets"]] == ["0_30", "31_60", "61_90", "over_90"]
    assert all(b["invoices"] == 0 and dec(b["balance"]) == 0 for b in body["buckets"])
    assert dec(body["total_balance"]) == 0


async def test_summary_totals_per_bucket(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    patients = [(await new_patient(practice, f"ar{i}"))[0] for i in range(5)]
    await aged_invoice(practice, billing_desk, 5, patient=patients[0])
    await aged_invoice(practice, billing_desk, 20, patient=patients[1])
    second = await aged_invoice(practice, billing_desk, 45, patient=patients[2])
    await billing_desk.pay(second, "20.00")
    await billing_desk.patch(second, insurance_expected="60.00")
    await aged_invoice(practice, billing_desk, 75, patient=patients[3])
    await aged_invoice(practice, billing_desk, 200, patient=patients[4])

    body = (await billing_desk.client.get(f"{API}/ar-aging", headers=billing_desk.headers)).json()
    by_bucket = {b["bucket"]: b for b in body["buckets"]}
    assert (by_bucket["0_30"]["invoices"], dec(by_bucket["0_30"]["balance"])) == (
        2,
        Decimal("240.00"),
    )
    assert (by_bucket["31_60"]["invoices"], dec(by_bucket["31_60"]["balance"])) == (
        1,
        Decimal("100.00"),
    )
    assert dec(by_bucket["31_60"]["insurance_outstanding"]) == Decimal("60.00")
    assert dec(by_bucket["31_60"]["patient_outstanding"]) == Decimal("40.00")
    assert (by_bucket["61_90"]["invoices"], by_bucket["over_90"]["invoices"]) == (1, 1)
    assert dec(body["total_balance"]) == Decimal("580.00")


async def test_summary_is_for_the_billing_desk_only(practice: Practice) -> None:
    client = practice.ctx.client
    assert (await client.get(f"{API}/ar-aging")).status_code == 401
    for headers in (
        practice.ctx.auth(await practice.patient_token()),
        practice.ctx.auth(await dentist_login(practice, practice.dentist_a)),
    ):
        assert (await client.get(f"{API}/ar-aging", headers=headers)).status_code == 403
    for role in (UserRole.RECEPTIONIST, UserRole.ADMIN):
        billing_desk = await desk(practice, role)
        assert (
            await client.get(f"{API}/ar-aging", headers=billing_desk.headers)
        ).status_code == 200
