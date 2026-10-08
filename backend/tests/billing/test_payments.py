import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.enums import UserRole
from tests.billing.helpers import API, GOOD_CARD, completed_visit, dec, desk, issued_invoice
from tests.booking.conftest import Practice


async def test_partial_then_full_payment_moves_the_status_through_the_lifecycle(
    practice: Practice,
) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    assert (await billing_desk.get(invoice_id))["status"] == "issued"

    first = await billing_desk.pay(invoice_id, "50.00")
    assert first.status_code == 201
    body = first.json()
    assert body["status"] == "partially_paid"
    assert dec(body["paid"]) == Decimal("50.00") and dec(body["balance"]) == Decimal("70.00")

    last = (await billing_desk.pay(invoice_id, "70.00")).json()
    assert last["status"] == "paid"
    assert dec(last["paid"]) == Decimal("120.00") and dec(last["balance"]) == Decimal("0.00")
    assert [dec(p["amount"]) for p in last["payments"]] == [Decimal("50.00"), Decimal("70.00")]


async def test_many_small_payments_add_up_to_the_cent(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    invoice_id = await completed_visit(practice)
    body = await billing_desk.get(invoice_id)
    await billing_desk.client.delete(
        f"{API}/invoices/{invoice_id}/items/{body['items'][0]['id']}", headers=billing_desk.headers
    )
    await billing_desk.add_item(invoice_id, "Plan fee", "100.00")
    await billing_desk.issue(invoice_id)

    for amount in ("33.33", "33.33"):
        assert (await billing_desk.pay(invoice_id, amount)).json()["status"] == "partially_paid"
    final = (await billing_desk.pay(invoice_id, "33.34")).json()
    assert (
        final["status"] == "paid"
        and dec(final["paid"]) == Decimal("100.00")
        and dec(final["balance"]) == 0
    )


async def test_one_cent_short_is_still_partially_paid(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    body = (await billing_desk.pay(invoice_id, "119.99")).json()
    assert body["status"] == "partially_paid" and dec(body["balance"]) == Decimal("0.01")


async def test_overpayment_is_rejected_and_reports_the_balance(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    await billing_desk.pay(invoice_id, "100.00")
    response = await billing_desk.pay(invoice_id, "20.01")
    assert response.status_code == 422 and response.json()["code"] == "overpayment"
    assert response.json()["details"]["balance"] == "20.00"
    assert len((await billing_desk.get(invoice_id))["payments"]) == 1


@pytest.mark.parametrize("amount", ["0", "0.00", "-5.00", "10.001", "abc", "1e3"])
async def test_invalid_amounts_are_rejected(practice: Practice, amount: str) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    assert (await billing_desk.pay(invoice_id, amount)).status_code == 422


async def test_payments_are_refused_unless_the_invoice_is_issued_and_open(
    practice: Practice,
) -> None:
    billing_desk = await desk(practice)
    draft = await completed_visit(practice)
    assert (await billing_desk.pay(draft, "10.00")).json()["code"] == "invoice_not_payable"

    paid = await issued_invoice(practice, billing_desk)
    await billing_desk.pay(paid, "120.00")
    assert (await billing_desk.pay(paid, "1.00")).status_code == 409

    voided = await issued_invoice(practice, billing_desk)
    await billing_desk.void(voided)
    assert (await billing_desk.pay(voided, "10.00")).status_code == 409


async def test_a_fully_discounted_invoice_is_paid_on_issue(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    invoice_id = await completed_visit(practice)
    await billing_desk.patch(invoice_id, discount_percent="100.00", discount_reason="Charity care")
    issued = (await billing_desk.issue(invoice_id)).json()
    assert issued["status"] == "paid" and dec(issued["total"]) == 0
    assert (await billing_desk.pay(invoice_id, "1.00")).status_code == 409


# --- payers and methods ----------------------------------------------------------------------


async def test_insurer_payments_are_recorded_separately_from_patient_payments(
    practice: Practice,
) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    await billing_desk.patch(invoice_id, insurance_expected="84.00")

    paid_at = (datetime.now(UTC) - timedelta(days=20)).isoformat()
    insurer = await billing_desk.pay(
        invoice_id, "84.00", method="insurance", reference="CLAIM-5521", paid_at=paid_at
    )
    assert insurer.status_code == 201
    patient = (
        await billing_desk.pay(invoice_id, "36.00", method="bank_transfer", reference="TRF-1")
    ).json()

    assert patient["status"] == "paid"
    by_method = {p["method"]: p for p in patient["payments"]}
    assert by_method["insurance"]["payer_type"] == "insurer"
    assert by_method["bank_transfer"]["payer_type"] == "patient"
    assert by_method["insurance"]["reference"] == "CLAIM-5521"
    rows = await practice.ctx.fetch(
        "SELECT payer_type::text, recorded_by IS NOT NULL FROM payments ORDER BY paid_at"
    )
    assert rows == [("insurer", True), ("patient", True)]


async def test_future_payment_dates_are_rejected(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert (await billing_desk.pay(invoice_id, "10.00", paid_at=future)).status_code == 422


async def test_card_details_are_only_accepted_for_card_payments(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    assert (
        await billing_desk.pay(invoice_id, "10.00", method="cash", card=GOOD_CARD)
    ).status_code == 422
    assert (await billing_desk.pay(invoice_id, "10.00", method="card")).status_code == 422


async def test_cash_payments_keep_the_supplied_reference(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    body = (
        await billing_desk.pay(invoice_id, "20.00", method="cash", reference="Receipt 8841")
    ).json()
    assert (
        body["payments"][0]["reference"] == "Receipt 8841"
        and body["payments"][0]["sandbox"] is False
    )


async def test_the_database_rejects_inconsistent_method_and_payer(practice: Practice) -> None:
    from sqlalchemy.exc import IntegrityError

    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    with pytest.raises(IntegrityError):
        await practice.ctx.execute(
            "INSERT INTO payments (invoice_id, amount, method, payer_type) "
            "VALUES (:i, 5.00, 'insurance', 'patient')",
            i=invoice_id,
        )
    with pytest.raises(IntegrityError):
        await practice.ctx.execute(
            "INSERT INTO payments (invoice_id, amount, method, payer_type, card_last4) "
            "VALUES (:i, 5.00, 'cash', 'patient', '4242')",
            i=invoice_id,
        )


# --- sandbox card ---------------------------------------------------------------------------


async def test_sandbox_card_payment_records_only_the_last_four_digits(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    response = await billing_desk.pay(invoice_id, "120.00", method="card", card=GOOD_CARD)

    assert response.status_code == 201, response.text
    payment = response.json()["payments"][0]
    assert payment["card_last4"] == "4242" and payment["sandbox"] is True
    assert payment["reference"].startswith("SBX-")
    assert "4242424242424242" not in response.text and "4242 4242 4242 4242" not in response.text
    assert response.json()["status"] == "paid"


async def test_card_numbers_never_reach_the_database_or_the_audit_log(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    await billing_desk.pay(
        invoice_id, "60.00", method="card", card={**GOOD_CARD, "cardholder": "Amelia Hartwell"}
    )

    dump = str(await practice.ctx.fetch("SELECT * FROM payments"))
    dump += str(await practice.ctx.fetch("SELECT metadata::text, action FROM audit_logs"))
    for secret in ("4242424242424242", "4242 4242 4242 4242", "'123'", "2099"):
        assert secret not in dump
    audit = await practice.ctx.fetch(
        "SELECT metadata::text FROM audit_logs WHERE action = 'payment.record'"
    )
    assert audit and "card_number" not in audit[0][0] and "4242" not in audit[0][0]


async def test_card_numbers_with_dashes_and_spaces_are_accepted(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    card = {**GOOD_CARD, "card_number": "4242-4242-4242-4242"}
    assert (
        await billing_desk.pay(invoice_id, "10.00", method="card", card=card)
    ).status_code == 201


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"card_number": "4242 4242 4242 4241"}, "card_number"),
        ({"card_number": "1234 5678 9012 3456"}, "card_number"),
        ({"card_number": "4242 4242 4242 42ab"}, "card_number"),
        ({"exp_year": 2020}, "exp_year"),
        ({"cvv": "12a"}, "cvv"),
    ],
)
async def test_invalid_cards_are_rejected_with_the_failing_field(
    practice: Practice, override: dict[str, object], field: str
) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    response = await billing_desk.pay(
        invoice_id, "10.00", method="card", card={**GOOD_CARD, **override}
    )
    assert response.status_code == 422
    assert field in str(response.json()["details"])
    assert str(override.get("card_number", "")) not in response.text or not override.get(
        "card_number"
    )
    assert await practice.ctx.fetch("SELECT count(*) FROM payments") == [(0,)]


@pytest.mark.parametrize(
    ("number", "word"),
    [("4000 0000 0000 0002", "declined"), ("4000 0000 0000 9995", "insufficient")],
)
async def test_declined_cards_return_402_and_record_no_payment(
    practice: Practice, number: str, word: str
) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    response = await billing_desk.pay(
        invoice_id, "10.00", method="card", card={**GOOD_CARD, "card_number": number}
    )
    assert response.status_code == 402 and response.json()["code"] == "card_declined"
    assert word in response.json()["message"]
    assert await practice.ctx.fetch("SELECT count(*) FROM payments") == [(0,)]
    assert await practice.ctx.fetch(
        "SELECT count(*) FROM audit_logs WHERE action = 'payment.declined'"
    ) == [(1,)]
    assert (await billing_desk.get(invoice_id))["status"] == "issued"


async def test_validation_errors_do_not_echo_the_card_number(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    response = await billing_desk.pay(
        invoice_id,
        "10.00",
        method="card",
        card={**GOOD_CARD, "card_number": "4242424242424242", "exp_month": 99},
    )
    assert response.status_code == 422
    assert "4242424242424242" not in response.text


# --- patient portal payment --------------------------------------------------------------------


async def test_patient_pays_their_invoice_in_full_with_the_sandbox_card(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk, patient=practice.patient)
    token = await practice.patient_token()

    response = await practice.ctx.client.post(
        f"/api/v1/me/invoices/{invoice_id}/pay",
        headers=practice.ctx.auth(token),
        json={"card": GOOD_CARD},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "paid" and dec(body["balance"]) == 0
    assert body["payments"][0]["sandbox"] is True and body["payments"][0]["card_last4"] == "4242"


async def test_patient_can_pay_part_of_an_invoice(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk, patient=practice.patient)
    token = await practice.patient_token()
    response = await practice.ctx.client.post(
        f"/api/v1/me/invoices/{invoice_id}/pay",
        headers=practice.ctx.auth(token),
        json={"amount": "45.50", "card": GOOD_CARD},
    )
    assert response.json()["status"] == "partially_paid" and dec(
        response.json()["balance"]
    ) == Decimal("74.50")
    assert (
        await practice.ctx.client.post(
            f"/api/v1/me/invoices/{invoice_id}/pay",
            headers=practice.ctx.auth(token),
            json={"amount": "74.51", "card": GOOD_CARD},
        )
    ).status_code == 422


async def test_patient_cannot_pay_a_paid_a_draft_or_someone_elses_invoice(
    practice: Practice,
) -> None:
    from tests.billing.helpers import new_patient

    billing_desk = await desk(practice)
    token = await practice.patient_token()
    headers = practice.ctx.auth(token)
    url = "/api/v1/me/invoices/{}/pay"

    paid = await issued_invoice(practice, billing_desk, patient=practice.patient)
    await billing_desk.pay(paid, "120.00")
    assert (
        await practice.ctx.client.post(url.format(paid), headers=headers, json={"card": GOOD_CARD})
    ).status_code == 409

    draft = await completed_visit(practice, patient=practice.patient)
    assert (
        await practice.ctx.client.post(url.format(draft), headers=headers, json={"card": GOOD_CARD})
    ).status_code == 404

    other, _ = await new_patient(practice)
    theirs = await issued_invoice(practice, billing_desk, patient=other)
    assert (
        await practice.ctx.client.post(
            url.format(theirs), headers=headers, json={"card": GOOD_CARD}
        )
    ).status_code == 404
    assert await practice.ctx.fetch(
        "SELECT count(*) FROM payments WHERE invoice_id = :i", i=theirs
    ) == [(0,)]


async def test_patient_payment_requires_card_details_and_rejects_extra_fields(
    practice: Practice,
) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk, patient=practice.patient)
    headers = practice.ctx.auth(await practice.patient_token())
    url = f"/api/v1/me/invoices/{invoice_id}/pay"
    assert (await practice.ctx.client.post(url, headers=headers, json={})).status_code == 422
    assert (
        await practice.ctx.client.post(
            url, headers=headers, json={"card": GOOD_CARD, "method": "insurance"}
        )
    ).status_code == 422


# --- concurrency ------------------------------------------------------------------------------


async def test_parallel_payments_can_never_overpay_an_invoice(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)

    responses = await asyncio.gather(*(billing_desk.pay(invoice_id, "10.00") for _ in range(20)))
    successes = [r for r in responses if r.status_code == 201]

    assert len(successes) == 12  # exactly enough $10 payments to settle $120.00
    assert all(r.status_code in (409, 422) for r in responses if r.status_code != 201)
    final = await billing_desk.get(invoice_id)
    assert (
        final["status"] == "paid"
        and dec(final["paid"]) == Decimal("120.00")
        and dec(final["balance"]) == 0
    )


async def test_parallel_full_payments_yield_exactly_one_success(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    responses = await asyncio.gather(*(billing_desk.pay(invoice_id, "120.00") for _ in range(10)))
    assert sorted(r.status_code for r in responses) == [201] + [409] * 9
    assert await practice.ctx.fetch("SELECT count(*) FROM payments") == [(1,)]
