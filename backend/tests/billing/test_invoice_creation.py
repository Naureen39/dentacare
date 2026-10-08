from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.enums import AppointmentStatus, UserRole
from app.services.billing import BillingService
from tests.billing.helpers import completed_visit, dentist_login, desk, new_patient
from tests.booking.conftest import Practice


async def test_completing_a_visit_creates_one_draft_invoice_from_the_service_price(
    practice: Practice,
) -> None:
    invoice_id = await completed_visit(practice)
    rows = await practice.ctx.fetch(
        "SELECT status::text, subtotal, discount, tax, total, number FROM invoices WHERE id = :i",
        i=invoice_id,
    )
    status, subtotal, discount, tax, total, number = rows[0]
    assert (status, subtotal, discount, tax, total) == (
        "draft",
        Decimal("120.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("120.00"),
    )
    assert number >= 1000
    items = await practice.ctx.fetch(
        "SELECT description, qty, unit_price, amount FROM invoice_items WHERE invoice_id = :i",
        i=invoice_id,
    )
    assert items == [("Routine Exam and Cleaning", 1, Decimal("120.00"), Decimal("120.00"))]


async def test_invoice_uses_the_price_of_the_service_that_was_performed(practice: Practice) -> None:
    invoice_id = await completed_visit(practice, service=practice.crown)
    [(total,)] = await practice.ctx.fetch("SELECT total FROM invoices WHERE id = :i", i=invoice_id)
    assert total == Decimal("1150.00")


async def test_later_price_changes_do_not_alter_existing_invoices(practice: Practice) -> None:
    invoice_id = await completed_visit(practice)
    await practice.ctx.execute("UPDATE services SET base_price = 999.00")
    [(total,)] = await practice.ctx.fetch("SELECT total FROM invoices WHERE id = :i", i=invoice_id)
    assert total == Decimal("120.00")


async def test_invoice_numbers_are_sequential(practice: Practice) -> None:
    patients = [await new_patient(practice, f"p{i}") for i in range(3)]
    ids = [await completed_visit(practice, patient=p) for p, _ in patients]
    numbers = [
        (await practice.ctx.fetch("SELECT number FROM invoices WHERE id = :i", i=i))[0][0]
        for i in ids
    ]
    assert numbers == list(range(numbers[0], numbers[0] + 3))


@pytest.mark.parametrize("target", ["confirmed", "cancelled"])
async def test_other_status_changes_do_not_create_invoices(practice: Practice, target: str) -> None:
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    appointment = await practice.book_direct(
        practice.dentist_a, datetime.now(UTC) + timedelta(days=2)
    )
    await practice.ctx.client.patch(
        f"/api/v1/staff/appointments/{appointment.id}/status",
        headers=practice.ctx.auth(token),
        json={"status": target},
    )
    assert await practice.ctx.fetch("SELECT count(*) FROM invoices") == [(0,)]


async def test_creating_an_invoice_twice_for_one_appointment_returns_the_same_invoice(
    practice: Practice,
) -> None:
    invoice_id = await completed_visit(practice)
    async with practice.ctx.session_factory() as db:
        from sqlalchemy import select

        from app.db.models import Appointment, Invoice

        invoice = (await db.execute(select(Invoice).where(Invoice.id == invoice_id))).scalar_one()
        appointment = (
            await db.execute(select(Appointment).where(Appointment.id == invoice.appointment_id))
        ).scalar_one()
        again = await BillingService(db, practice.ctx.settings).create_for_appointment(
            appointment, None
        )
        assert again.id == invoice_id
    assert await practice.ctx.fetch("SELECT count(*) FROM invoices") == [(1,)]


async def test_a_voided_invoice_can_be_replaced_for_the_same_appointment(
    practice: Practice,
) -> None:
    invoice_id = await completed_visit(practice)
    billing_desk = await desk(practice)
    assert (await billing_desk.void(invoice_id)).status_code == 200
    async with practice.ctx.session_factory() as db:
        from sqlalchemy import select

        from app.db.models import Appointment, Invoice

        old = (await db.execute(select(Invoice).where(Invoice.id == invoice_id))).scalar_one()
        appointment = (
            await db.execute(select(Appointment).where(Appointment.id == old.appointment_id))
        ).scalar_one()
        replacement = await BillingService(db, practice.ctx.settings).create_for_appointment(
            appointment, None
        )
        await db.commit()
        assert replacement.id != invoice_id and replacement.status.value == "draft"
    assert await practice.ctx.fetch("SELECT count(*) FROM invoices WHERE status <> 'void'") == [
        (1,)
    ]


async def test_invoice_creation_is_audited(practice: Practice) -> None:
    await completed_visit(practice)
    rows = await practice.ctx.fetch(
        "SELECT entity, metadata::text FROM audit_logs WHERE action = 'invoice.create'"
    )
    assert rows and rows[0][0] == "invoice"


async def test_dentist_completing_a_visit_also_produces_the_invoice(practice: Practice) -> None:
    token = await dentist_login(practice, practice.dentist_a)
    appointment = await practice.book_direct(
        practice.dentist_a,
        datetime.now(UTC) - timedelta(hours=3),
        status=AppointmentStatus.CHECKED_IN,
    )
    response = await practice.ctx.client.patch(
        f"/api/v1/staff/appointments/{appointment.id}/status",
        headers=practice.ctx.auth(token),
        json={"status": "completed"},
    )
    assert response.status_code == 200
    assert await practice.ctx.fetch("SELECT count(*) FROM invoices") == [(1,)]
