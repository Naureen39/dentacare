from io import BytesIO

from pypdf import PdfReader

from app.db.enums import UserRole
from tests.billing.helpers import (
    GOOD_CARD,
    completed_visit,
    dentist_login,
    desk,
    issued_invoice,
    new_patient,
)
from tests.booking.conftest import Practice

PHONE = "(555) 010-0199"


def pdf_text(content: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)


# --- voids ------------------------------------------------------------------------------------


async def test_a_draft_or_unpaid_invoice_can_be_voided_with_a_reason(practice: Practice) -> None:
    billing_desk = await desk(practice)
    draft = await completed_visit(practice)
    issued = await issued_invoice(practice, billing_desk)

    for invoice_id in (draft, issued):
        response = await billing_desk.void(invoice_id, "Duplicate entry")
        assert response.status_code == 200
        assert (
            response.json()["status"] == "void"
            and response.json()["void_reason"] == "Duplicate entry"
        )
    rows = await practice.ctx.fetch("SELECT voided_at IS NOT NULL FROM invoices")
    assert rows == [(True,), (True,)]


async def test_void_needs_a_meaningful_reason(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    for reason in ("", "ab"):
        assert (await billing_desk.void(invoice_id, reason)).status_code == 422
    assert (await billing_desk.get(invoice_id))["status"] == "issued"


async def test_an_invoice_with_payments_cannot_be_voided(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    invoice_id = await issued_invoice(practice, billing_desk)
    await billing_desk.pay(invoice_id, "10.00")
    response = await billing_desk.void(invoice_id)
    assert response.status_code == 409 and response.json()["code"] == "invoice_has_payments"
    assert (await billing_desk.get(invoice_id))["status"] == "partially_paid"


async def test_a_void_invoice_cannot_be_voided_edited_or_issued_again(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    invoice_id = await issued_invoice(practice, billing_desk)
    await billing_desk.void(invoice_id)
    assert (await billing_desk.void(invoice_id)).status_code == 409
    assert (await billing_desk.issue(invoice_id)).status_code == 409
    assert (await billing_desk.add_item(invoice_id, "x", "1.00")).status_code == 409
    assert (await billing_desk.patch(invoice_id, insurance_expected="1.00")).status_code == 409


async def test_voiding_is_audited_and_status_stays_void(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await completed_visit(practice)
    await billing_desk.void(invoice_id)
    assert await practice.ctx.fetch(
        "SELECT count(*) FROM audit_logs WHERE action = 'invoice.void'"
    ) == [(1,)]
    assert (await billing_desk.get(invoice_id))["status"] == "void"


async def test_patients_still_see_voided_invoices_in_their_history(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk, patient=practice.patient)
    await billing_desk.void(invoice_id, "Billed in error")
    listing = await practice.ctx.client.get(
        "/api/v1/me/invoices", headers=practice.ctx.auth(await practice.patient_token())
    )
    assert [i["status"] for i in listing.json()] == ["void"]


# --- PDF --------------------------------------------------------------------------------------


async def test_pdf_contains_clinic_details_number_items_and_totals(practice: Practice) -> None:
    billing_desk = await desk(practice, UserRole.ADMIN)
    invoice_id = await completed_visit(practice)
    await billing_desk.add_item(invoice_id, "Fluoride treatment", "33.33", qty=3)
    await billing_desk.patch(
        invoice_id, discount_amount="19.99", discount_reason="Loyalty discount"
    )
    await billing_desk.issue(invoice_id)
    await billing_desk.pay(invoice_id, "100.00", method="card", card=GOOD_CARD)

    response = await billing_desk.client.get(
        f"/api/v1/billing/invoices/{invoice_id}/pdf", headers=billing_desk.headers
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    number = (await billing_desk.get(invoice_id))["display_number"]
    assert f'filename="invoice-{number}.pdf"' in response.headers["content-disposition"]

    text = pdf_text(response.content)
    for expected in (
        "Meridian Dental Care",
        "Harbor View Drive",
        PHONE,
        "INVOICE",
        number,
        "PARTIALLY PAID",
        "Routine Exam and Cleaning",
        "Fluoride treatment",
        "$99.99",
        "$219.99",
        "Discount (Loyalty discount)",
        "-$19.99",
        "$200.00",
        "Payments received",
        "ending 4242",
        "SBX-",
        "Balance due",
        "$100.00",
        "Demo environment, fictional clinic",
    ):
        assert expected in text, f"missing {expected!r} in PDF text"
    assert "4242424242424242" not in text
    assert chr(0x2014) not in text and chr(0x2013) not in text


async def test_pdf_shows_a_void_notice(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await issued_invoice(practice, billing_desk)
    await billing_desk.void(invoice_id, "Billed in error")
    response = await billing_desk.client.get(
        f"/api/v1/billing/invoices/{invoice_id}/pdf", headers=billing_desk.headers
    )
    text = pdf_text(response.content)
    assert "VOID" in text and "Billed in error" in text


async def test_pdf_escapes_markup_in_descriptions(practice: Practice) -> None:
    billing_desk = await desk(practice)
    invoice_id = await completed_visit(practice)
    await billing_desk.add_item(invoice_id, "Crown <b>& bridge</b> 5 < 6", "10.00")
    response = await billing_desk.client.get(
        f"/api/v1/billing/invoices/{invoice_id}/pdf", headers=billing_desk.headers
    )
    assert response.status_code == 200
    assert "Crown <b>& bridge</b> 5 < 6" in pdf_text(response.content)


async def test_patient_downloads_their_own_issued_invoice_only(practice: Practice) -> None:
    billing_desk = await desk(practice)
    mine = await issued_invoice(practice, billing_desk, patient=practice.patient)
    other, _ = await new_patient(practice)
    theirs = await issued_invoice(practice, billing_desk, patient=other)
    draft = await completed_visit(practice, patient=practice.patient)
    headers = practice.ctx.auth(await practice.patient_token())
    client = practice.ctx.client

    ok = await client.get(f"/api/v1/me/invoices/{mine}/pdf", headers=headers)
    assert ok.status_code == 200 and ok.content.startswith(b"%PDF")
    assert "Amelia Hartwell" in pdf_text(ok.content)
    assert (
        await client.get(f"/api/v1/me/invoices/{theirs}/pdf", headers=headers)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/me/invoices/{draft}/pdf", headers=headers)
    ).status_code == 404
    assert (await client.get(f"/api/v1/me/invoices/{theirs}", headers=headers)).status_code == 404


async def test_dentists_download_pdfs_only_for_their_own_appointments(practice: Practice) -> None:
    billing_desk = await desk(practice)
    own = await issued_invoice(practice, billing_desk, dentist=practice.dentist_a)
    foreign = await issued_invoice(practice, billing_desk, dentist=practice.dentist_b)
    headers = practice.ctx.auth(await dentist_login(practice, practice.dentist_a))
    client = practice.ctx.client
    assert (
        await client.get(f"/api/v1/billing/invoices/{own}/pdf", headers=headers)
    ).status_code == 200
    assert (
        await client.get(f"/api/v1/billing/invoices/{foreign}/pdf", headers=headers)
    ).status_code == 404


async def test_invoice_numbers_appear_sequentially_in_the_pdfs(practice: Practice) -> None:
    billing_desk = await desk(practice)
    first = await issued_invoice(practice, billing_desk)
    second = await issued_invoice(practice, billing_desk)
    numbers = []
    for invoice_id in (first, second):
        text = pdf_text(
            (
                await billing_desk.client.get(
                    f"/api/v1/billing/invoices/{invoice_id}/pdf", headers=billing_desk.headers
                )
            ).content
        )
        numbers.append(int(text.split("INV-")[1][:6]))
    assert numbers[1] == numbers[0] + 1
