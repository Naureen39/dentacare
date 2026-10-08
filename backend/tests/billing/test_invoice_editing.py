import random
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.db.enums import UserRole
from app.services.billing import money
from tests.billing.helpers import API, completed_visit, dec, dentist_login, desk
from tests.booking.conftest import Practice

# --- rounding ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2.675", "2.68"),  # binary floats would give 2.67
        ("2.665", "2.67"),
        ("0.005", "0.01"),
        ("0.004", "0.00"),
        ("1.005", "1.01"),
        ("10.125", "10.13"),
        ("-0.005", "-0.01"),
        ("99.999", "100.00"),
        ("120", "120.00"),
    ],
)
def test_money_rounds_half_up_to_cents(raw: str, expected: str) -> None:
    assert money(raw) == Decimal(expected)
    assert ROUND_HALF_UP  # the rounding mode used everywhere


# --- items and totals -------------------------------------------------------------------------


async def test_adding_items_updates_the_totals_to_the_cent(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await completed_visit(practice)

    response = await billing_desk.add_item(invoice_id, "Fluoride treatment", "33.33", qty=3)
    assert response.status_code == 201
    body = response.json()
    assert dec(body["items"][-1]["amount"]) == Decimal("99.99")  # stable insertion order
    assert dec(body["subtotal"]) == Decimal("219.99")
    assert dec(body["total"]) == Decimal("219.99")


async def test_removing_an_item_updates_the_totals(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await completed_visit(practice)
    body = (await billing_desk.add_item(invoice_id, "X-ray", "40.00")).json()
    extra = next(i for i in body["items"] if i["description"] == "X-ray")

    response = await billing_desk.client.delete(
        f"{API}/invoices/{invoice_id}/items/{extra['id']}", headers=billing_desk.headers
    )
    assert response.status_code == 200 and dec(response.json()["total"]) == Decimal("120.00")


async def test_removing_an_unknown_item_is_not_found(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await completed_visit(practice)
    response = await billing_desk.client.delete(
        f"{API}/invoices/{invoice_id}/items/00000000-0000-0000-0000-000000000000",
        headers=billing_desk.headers,
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"description": "", "unit_price": "10.00"},
        {"description": "Item", "unit_price": "-1.00"},
        {"description": "Item", "unit_price": "10.001"},
        {"description": "Item", "unit_price": "10.00", "qty": 0},
        {"description": "Item", "unit_price": "10.00", "qty": 100},
        {"description": "Item", "unit_price": "100000.01"},
        {"description": "Item", "unit_price": "10.00", "amount": "1.00"},
    ],
)
async def test_invalid_items_are_rejected(practice: Practice, payload: dict[str, object]) -> None:
    billing_desk = await desk(practice)
    invoice_id = await completed_visit(practice)
    response = await billing_desk.client.post(
        f"{API}/invoices/{invoice_id}/items", headers=billing_desk.headers, json=payload
    )
    assert response.status_code == 422


async def test_tax_is_applied_to_the_discounted_subtotal_and_rounded_half_up(
    practice: Practice,
) -> None:
    await practice.ctx.execute(
        "UPDATE app_settings SET value = '8.875'::jsonb WHERE key = 'billing_tax_rate_percent'"
    )
    try:
        billing_desk = await desk(practice, UserRole.ADMIN)
        invoice_id = await completed_visit(practice)
        await billing_desk.add_item(invoice_id, "Whitening kit", "45.10")
        body = (
            await billing_desk.patch(
                invoice_id, discount_amount="5.10", discount_reason="Promotion"
            )
        ).json()

        # (165.10 - 5.10) = 160.00; 8.875% of 160.00 is exactly 14.20
        assert dec(body["subtotal"]) == Decimal("165.10")
        assert dec(body["tax"]) == Decimal("14.20")
        assert dec(body["total"]) == Decimal("174.20")
    finally:
        await practice.ctx.execute(
            "UPDATE app_settings SET value = '0'::jsonb WHERE key = 'billing_tax_rate_percent'"
        )


async def test_tax_rounding_goes_up_at_exactly_half_a_cent(practice: Practice) -> None:
    await practice.ctx.execute(
        "UPDATE app_settings SET value = '12.5'::jsonb WHERE key = 'billing_tax_rate_percent'"
    )
    try:
        billing_desk = await desk(practice, UserRole.ADMIN)
        invoice_id = await completed_visit(practice)
        # Make the subtotal $0.04: 12.5% of 0.04 is 0.005, which must round up to 0.01.
        body = await billing_desk.get(invoice_id)
        await billing_desk.client.delete(
            f"{API}/invoices/{invoice_id}/items/{body['items'][0]['id']}",
            headers=billing_desk.headers,
        )
        result = (await billing_desk.add_item(invoice_id, "Sample", "0.04")).json()
        assert dec(result["tax"]) == Decimal("0.01") and dec(result["total"]) == Decimal("0.05")
    finally:
        await practice.ctx.execute(
            "UPDATE app_settings SET value = '0'::jsonb WHERE key = 'billing_tax_rate_percent'"
        )


async def test_totals_always_equal_the_items_and_components_for_random_invoices(
    practice: Practice,
) -> None:
    """Property style check: subtotal is the item sum and total = subtotal - discount + tax."""
    rng = random.Random(20261008)
    await practice.ctx.execute(
        "UPDATE app_settings SET value = '7.25'::jsonb WHERE key = 'billing_tax_rate_percent'"
    )
    try:
        billing_desk = await desk(practice, UserRole.ADMIN)
        for _ in range(6):
            invoice_id = await completed_visit(practice)
            for _ in range(rng.randint(1, 4)):
                price = Decimal(rng.randint(1, 250000)) / 100
                await billing_desk.add_item(
                    invoice_id, "Random item", f"{price:.2f}", rng.randint(1, 5)
                )
            percent = Decimal(rng.randint(0, 6000)) / 100
            body = (
                await billing_desk.patch(
                    invoice_id, discount_percent=f"{percent:.2f}", discount_reason="Random"
                )
            ).json()

            items_sum = sum(dec(i["amount"]) for i in body["items"])
            assert all(
                dec(i["amount"]) == money(dec(i["unit_price"]) * i["qty"]) for i in body["items"]
            )
            assert dec(body["subtotal"]) == items_sum
            assert dec(body["total"]) == dec(body["subtotal"]) - dec(body["discount"]) + dec(
                body["tax"]
            )
            assert dec(body["discount"]) == money(dec(body["subtotal"]) * percent / 100)
            assert dec(body["tax"]) == money(
                (dec(body["subtotal"]) - dec(body["discount"])) * Decimal("7.25") / 100
            )
            for key in ("subtotal", "discount", "tax", "total"):
                assert dec(body[key]) == dec(body[key]).quantize(Decimal("0.01"))
    finally:
        await practice.ctx.execute(
            "UPDATE app_settings SET value = '0'::jsonb WHERE key = 'billing_tax_rate_percent'"
        )


# --- discounts -------------------------------------------------------------------------------


async def test_discount_requires_a_reason(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    invoice_id = await completed_visit(practice)
    response = await billing_desk.patch(invoice_id, discount_amount="5.00")
    assert response.status_code == 422 and response.json()["code"] == "discount_reason_required"
    assert dec((await billing_desk.get(invoice_id))["discount"]) == 0


async def test_discount_by_amount_and_by_percent(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    invoice_id = await completed_visit(practice)
    by_amount = (
        await billing_desk.patch(invoice_id, discount_amount="12.00", discount_reason="Courtesy")
    ).json()
    assert dec(by_amount["discount"]) == Decimal("12.00") and dec(by_amount["total"]) == Decimal(
        "108.00"
    )
    by_percent = (await billing_desk.patch(invoice_id, discount_percent="12.50")).json()
    assert (
        dec(by_percent["discount"]) == Decimal("15.00")
        and by_percent["discount_reason"] == "Courtesy"
    )


async def test_giving_both_amount_and_percent_is_rejected(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    invoice_id = await completed_visit(practice)
    response = await billing_desk.patch(
        invoice_id, discount_amount="5.00", discount_percent="5.00", discount_reason="Both"
    )
    assert response.status_code == 422


async def test_discount_larger_than_the_subtotal_is_rejected(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    invoice_id = await completed_visit(practice)
    response = await billing_desk.patch(
        invoice_id, discount_amount="120.01", discount_reason="Too much"
    )
    assert response.status_code == 422 and response.json()["code"] == "invalid_discount"


async def test_clearing_the_discount_clears_the_reason(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    invoice_id = await completed_visit(practice)
    await billing_desk.patch(invoice_id, discount_amount="10.00", discount_reason="Promotion")
    body = (await billing_desk.patch(invoice_id, discount_amount="0.00")).json()
    assert dec(body["discount"]) == 0 and body["discount_reason"] is None


async def test_receptionists_may_discount_up_to_the_configured_percentage(
    practice: Practice,
) -> None:
    billing_desk = await desk(practice, UserRole.RECEPTIONIST)
    invoice_id = await completed_visit(practice)

    ok = await billing_desk.patch(invoice_id, discount_percent="10.00", discount_reason="Loyalty")
    assert ok.status_code == 200 and dec(ok.json()["discount"]) == Decimal("12.00")

    over = await billing_desk.patch(invoice_id, discount_amount="12.01", discount_reason="Loyalty")
    assert over.status_code == 403 and over.json()["code"] == "discount_limit_exceeded"
    assert over.json()["details"]["limit_percent"] == "10"
    # The rejected change must not have been stored.
    assert dec((await billing_desk.get(invoice_id))["discount"]) == Decimal("12.00")


async def test_the_receptionist_limit_comes_from_settings(practice: Practice) -> None:
    await practice.ctx.execute(
        "UPDATE app_settings SET value = '25'::jsonb WHERE key = 'receptionist_max_discount_percent'"
    )
    try:
        billing_desk = await desk(practice, UserRole.RECEPTIONIST)
        invoice_id = await completed_visit(practice)
        ok = await billing_desk.patch(
            invoice_id, discount_percent="25.00", discount_reason="Hardship"
        )
        assert ok.status_code == 200
        assert (await billing_desk.patch(invoice_id, discount_percent="25.01")).status_code == 403
    finally:
        await practice.ctx.execute(
            "UPDATE app_settings SET value = '10'::jsonb WHERE key = 'receptionist_max_discount_percent'"
        )


async def test_administrators_have_no_percentage_limit(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    invoice_id = await completed_visit(practice)
    full = await billing_desk.patch(
        invoice_id, discount_percent="100.00", discount_reason="Charity care"
    )
    assert full.status_code == 200 and dec(full.json()["total"]) == 0


async def test_removing_items_cannot_push_a_receptionist_discount_over_the_limit(
    practice: Practice,
) -> None:
    admin = await desk(practice, UserRole.ADMIN)
    receptionist = await desk(practice, UserRole.RECEPTIONIST)
    invoice_id = await completed_visit(practice)
    body = (await admin.add_item(invoice_id, "Extra", "120.00")).json()
    await admin.patch(
        invoice_id, discount_amount="20.00", discount_reason="Promotion"
    )  # 8.33% of 240
    original = body["items"][0]["id"]

    response = await receptionist.client.delete(
        f"{API}/invoices/{invoice_id}/items/{original}", headers=receptionist.headers
    )
    assert response.status_code == 403  # 20 of 120 is 16.7 percent


# --- insurance, locking and permissions ---------------------------------------------------------


async def test_expected_insurance_cannot_exceed_the_total(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await completed_visit(practice)
    assert (await billing_desk.patch(invoice_id, insurance_expected="120.01")).status_code == 422
    ok = await billing_desk.patch(invoice_id, insurance_expected="84.00")
    assert ok.status_code == 200
    assert dec(ok.json()["insurance_expected"]) == Decimal("84.00")
    assert dec(ok.json()["patient_responsibility"]) == Decimal("36.00")


async def test_expected_insurance_follows_the_total_down(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    invoice_id = await completed_visit(practice)
    await billing_desk.patch(invoice_id, insurance_expected="100.00")
    response = await billing_desk.patch(
        invoice_id, discount_amount="30.00", discount_reason="Promotion"
    )
    assert response.status_code == 422 and response.json()["code"] == "invalid_insurance_amount"


async def test_issued_invoices_are_locked_for_items_and_discounts(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    invoice_id = await completed_visit(practice)
    assert (await billing_desk.issue(invoice_id)).status_code == 200

    assert (await billing_desk.add_item(invoice_id, "Late item", "5.00")).status_code == 409
    assert (
        await billing_desk.patch(invoice_id, discount_amount="5.00", discount_reason="Late")
    ).status_code == 409
    # The expected insurance payment may still be corrected after issue.
    assert (await billing_desk.patch(invoice_id, insurance_expected="60.00")).status_code == 200


async def test_an_empty_invoice_cannot_be_issued(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await completed_visit(practice)
    body = await billing_desk.get(invoice_id)
    await billing_desk.client.delete(
        f"{API}/invoices/{invoice_id}/items/{body['items'][0]['id']}", headers=billing_desk.headers
    )
    response = await billing_desk.issue(invoice_id)
    assert response.status_code == 422 and response.json()["code"] == "invoice_empty"


async def test_issuing_sets_the_issue_time_and_cannot_be_repeated(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await completed_visit(practice)
    first = await billing_desk.issue(invoice_id)
    assert first.status_code == 200 and first.json()["status"] == "issued"
    assert (await billing_desk.issue(invoice_id)).status_code == 409


async def test_only_front_desk_roles_can_edit_invoices(practice: Practice) -> None:
    invoice_id = await completed_visit(practice)
    patient_headers = practice.ctx.auth(await practice.patient_token())
    dentist_headers = practice.ctx.auth(await dentist_login(practice, practice.dentist_a))
    for headers in (patient_headers, dentist_headers):
        client = practice.ctx.client
        assert (
            await client.patch(
                f"{API}/invoices/{invoice_id}", headers=headers, json={"insurance_expected": "1.00"}
            )
        ).status_code == 403
        assert (
            await client.post(
                f"{API}/invoices/{invoice_id}/items",
                headers=headers,
                json={"description": "x", "unit_price": "1.00"},
            )
        ).status_code == 403
        assert (
            await client.post(f"{API}/invoices/{invoice_id}/issue", headers=headers)
        ).status_code == 403
        assert (
            await client.post(
                f"{API}/invoices/{invoice_id}/void", headers=headers, json={"reason": "nope"}
            )
        ).status_code == 403
        assert (
            await client.post(
                f"{API}/invoices/{invoice_id}/payments",
                headers=headers,
                json={"amount": "1.00", "method": "cash"},
            )
        ).status_code == 403


async def test_unknown_fields_are_rejected_when_editing(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    invoice_id = await completed_visit(practice)
    for field in ({"total": "1.00"}, {"status": "paid"}, {"patient_id": "x"}, {"subtotal": "5.00"}):
        assert (await billing_desk.patch(invoice_id, **field)).status_code == 422
