import uuid

from httpx import Response

from app.db.enums import UserRole
from tests.billing.helpers import (
    API,
    completed_visit,
    dec,
    dentist_login,
    desk,
    issued_invoice,
    new_patient,
)
from tests.booking.conftest import Practice


async def test_anonymous_callers_are_rejected_everywhere(practice: Practice) -> None:
    some = uuid.uuid4()
    client = practice.ctx.client
    for method, path in [
        ("GET", f"{API}/invoices"),
        ("GET", f"{API}/invoices/{some}"),
        ("GET", f"{API}/invoices/{some}/pdf"),
        ("PATCH", f"{API}/invoices/{some}"),
        ("POST", f"{API}/invoices/{some}/items"),
        ("POST", f"{API}/invoices/{some}/payments"),
        ("GET", f"/api/v1/me/invoices/{some}"),
        ("POST", f"/api/v1/me/invoices/{some}/pay"),
    ]:
        assert (await client.request(method, path, json={})).status_code == 401, (method, path)


async def test_patients_have_no_access_to_the_billing_desk(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk, patient=practice.patient)
    headers = practice.ctx.auth(await practice.patient_token())
    client = practice.ctx.client
    assert (await client.get(f"{API}/invoices", headers=headers)).status_code == 403
    assert (await client.get(f"{API}/invoices/{invoice_id}", headers=headers)).status_code == 403
    assert (
        await client.get(f"{API}/invoices/{invoice_id}/pdf", headers=headers)
    ).status_code == 403


async def test_patient_invoice_list_hides_drafts_and_other_patients(practice: Practice) -> None:
    billing_desk = await desk(practice)
    mine = await issued_invoice(practice, billing_desk, patient=practice.patient)
    await completed_visit(practice, patient=practice.patient)  # a draft
    other, _ = await new_patient(practice)
    await issued_invoice(practice, billing_desk, patient=other)

    listing = await practice.ctx.client.get(
        "/api/v1/me/invoices", headers=practice.ctx.auth(await practice.patient_token())
    )
    assert [i["id"] for i in listing.json()] == [str(mine)]
    item = listing.json()[0]
    assert item["display_number"].startswith("INV-") and dec(item["balance"]) == dec("120.00")


async def test_patient_invoice_detail_shows_items_and_payments(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk, patient=practice.patient)
    await billing_desk.pay(invoice_id, "20.00", method="cash")
    body = (
        await practice.ctx.client.get(
            f"/api/v1/me/invoices/{invoice_id}",
            headers=practice.ctx.auth(await practice.patient_token()),
        )
    ).json()
    assert body["items"][0]["description"] == "Routine Exam and Cleaning"
    assert len(body["payments"]) == 1 and dec(body["balance"]) == dec("100.00")


async def test_dentists_see_only_invoices_for_their_own_appointments(practice: Practice) -> None:
    billing_desk = await desk(practice)
    own = await issued_invoice(practice, billing_desk, dentist=practice.dentist_a)
    foreign = await issued_invoice(practice, billing_desk, dentist=practice.dentist_b)
    headers = practice.ctx.auth(await dentist_login(practice, practice.dentist_a))
    client = practice.ctx.client

    listing = await client.get(f"{API}/invoices", headers=headers)
    assert [i["id"] for i in listing.json()] == [str(own)]
    assert (await client.get(f"{API}/invoices/{own}", headers=headers)).status_code == 200
    assert (await client.get(f"{API}/invoices/{foreign}", headers=headers)).status_code == 404


async def test_billing_desk_lists_filters_and_searches(practice: Practice) -> None:
    billing_desk = await desk(practice)
    first = await issued_invoice(practice, billing_desk, patient=practice.patient)
    other, _ = await new_patient(practice)
    second = await issued_invoice(practice, billing_desk, patient=other)
    await billing_desk.pay(second, "120.00")
    draft = await completed_visit(practice, patient=practice.patient)
    client = practice.ctx.client

    def ids(response: Response) -> set[str]:
        return {i["id"] for i in response.json()}

    everything = await client.get(f"{API}/invoices", headers=billing_desk.headers)
    assert ids(everything) == {str(first), str(second), str(draft)}
    assert ids(
        await client.get(
            f"{API}/invoices", params={"open_only": "true"}, headers=billing_desk.headers
        )
    ) == {str(first)}
    assert ids(
        await client.get(
            f"{API}/invoices", params={"status": "draft"}, headers=billing_desk.headers
        )
    ) == {str(draft)}
    assert ids(
        await client.get(f"{API}/invoices", params={"status": "paid"}, headers=billing_desk.headers)
    ) == {str(second)}
    assert ids(
        await client.get(
            f"{API}/invoices", params={"patient_id": str(other.id)}, headers=billing_desk.headers
        )
    ) == {str(second)}
    assert ids(
        await client.get(f"{API}/invoices", params={"q": "Hartw"}, headers=billing_desk.headers)
    ) == {str(first), str(draft)}

    number = (await billing_desk.get(second))["display_number"]
    assert ids(
        await client.get(f"{API}/invoices", params={"q": number}, headers=billing_desk.headers)
    ) == {str(second)}
    assert (
        await client.get(f"{API}/invoices", params={"limit": 1}, headers=billing_desk.headers)
    ).json().__len__() == 1


async def test_listing_reports_paid_and_balance_per_invoice(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    await billing_desk.pay(invoice_id, "33.33")
    row = (await billing_desk.client.get(f"{API}/invoices", headers=billing_desk.headers)).json()[0]
    assert dec(row["paid"]) == dec("33.33") and dec(row["balance"]) == dec("86.67")
    assert row["status"] == "partially_paid"


async def test_unknown_invoices_are_not_found(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    for path in (f"{API}/invoices/{uuid.uuid4()}", f"{API}/invoices/{uuid.uuid4()}/pdf"):
        assert (
            await billing_desk.client.get(path, headers=billing_desk.headers)
        ).status_code == 404
    assert (
        await billing_desk.client.get(f"{API}/invoices/not-a-uuid", headers=billing_desk.headers)
    ).status_code == 422


async def test_billing_actions_are_audited_without_personal_data(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    invoice_id = await completed_visit(practice)
    await billing_desk.patch(
        invoice_id, discount_amount="10.00", discount_reason="Loyalty for Amelia Hartwell"
    )
    await billing_desk.issue(invoice_id)
    await billing_desk.pay(invoice_id, "110.00", method="cash", reference="Receipt 77")

    actions = [
        r[0]
        for r in await practice.ctx.fetch(
            "SELECT action FROM audit_logs WHERE action LIKE 'invoice.%' OR action LIKE 'payment.%' ORDER BY created_at"
        )
    ]
    assert actions == ["invoice.create", "invoice.update", "invoice.issue", "payment.record"]
    dump = str(await practice.ctx.fetch("SELECT metadata::text FROM audit_logs"))
    assert "Amelia" not in dump and "Receipt 77" not in dump
