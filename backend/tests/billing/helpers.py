"""Shared helpers for billing tests."""

import itertools
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from httpx import Response
from sqlalchemy import select

from app.db.enums import AppointmentStatus, UserRole
from app.db.models import Dentist, Patient, Service
from tests.auth.conftest import unique_email
from tests.booking.conftest import Practice

API = "/api/v1/billing"
_visit_counter = itertools.count(1)
GOOD_CARD = {"card_number": "4242 4242 4242 4242", "exp_month": 12, "exp_year": 2099, "cvv": "123"}


def dec(value: Any) -> Decimal:
    return Decimal(str(value))


async def new_patient(practice: Practice, label: str = "extra") -> tuple[Patient, str]:
    """A second patient with an account. Returns the patient and the login email."""
    email = unique_email(label)
    user = await practice.ctx.create_user(
        email, UserRole.PATIENT, first_name="Other", last_name="Patient"
    )
    async with practice.ctx.session_factory() as db:
        patient = (await db.execute(select(Patient).where(Patient.user_id == user.id))).scalar_one()
    return patient, email


async def completed_visit(
    practice: Practice,
    *,
    patient: Patient | None = None,
    hours_ago: int = 5,
    dentist: Dentist | None = None,
    service: Service | None = None,
) -> uuid.UUID:
    """Finish a visit through the real status flow and return the invoice id it produced."""
    dentist = dentist or practice.dentist_a
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    appointment = await practice.book_direct(
        dentist,
        datetime.now(UTC) - timedelta(hours=hours_ago + 2 * next(_visit_counter)),
        patient=patient,
        service=service,
        status=AppointmentStatus.CHECKED_IN,
    )
    response = await practice.ctx.client.patch(
        f"/api/v1/staff/appointments/{appointment.id}/status",
        headers=practice.ctx.auth(token),
        json={"status": "completed"},
    )
    assert response.status_code == 200, response.text
    rows = await practice.ctx.fetch(
        "SELECT id FROM invoices WHERE appointment_id = :a", a=appointment.id
    )
    assert len(rows) == 1
    return rows[0][0]  # type: ignore[no-any-return]


class Desk:
    """A signed in front desk user with convenience calls."""

    def __init__(self, practice: Practice, token: str) -> None:
        self.practice = practice
        self.headers = practice.ctx.auth(token)
        self.client = practice.ctx.client

    async def get(self, invoice_id: uuid.UUID) -> dict[str, Any]:
        response = await self.client.get(f"{API}/invoices/{invoice_id}", headers=self.headers)
        assert response.status_code == 200, response.text
        return dict(response.json())

    async def patch(self, invoice_id: uuid.UUID, **body: Any) -> Response:
        return await self.client.patch(
            f"{API}/invoices/{invoice_id}", headers=self.headers, json=body
        )

    async def add_item(
        self, invoice_id: uuid.UUID, description: str, unit_price: str, qty: int = 1
    ) -> Response:
        return await self.client.post(
            f"{API}/invoices/{invoice_id}/items",
            headers=self.headers,
            json={"description": description, "unit_price": unit_price, "qty": qty},
        )

    async def issue(self, invoice_id: uuid.UUID) -> Response:
        return await self.client.post(f"{API}/invoices/{invoice_id}/issue", headers=self.headers)

    async def void(self, invoice_id: uuid.UUID, reason: str = "Entered in error") -> Response:
        return await self.client.post(
            f"{API}/invoices/{invoice_id}/void", headers=self.headers, json={"reason": reason}
        )

    async def pay(
        self, invoice_id: uuid.UUID, amount: str, method: str = "cash", **extra: Any
    ) -> Response:
        return await self.client.post(
            f"{API}/invoices/{invoice_id}/payments",
            headers=self.headers,
            json={"amount": amount, "method": method, **extra},
        )


async def desk(practice: Practice, role: UserRole = UserRole.RECEPTIONIST) -> Desk:
    return Desk(practice, await practice.staff_token(role))


async def issued_invoice(practice: Practice, desk_: Desk, **kwargs: Any) -> uuid.UUID:
    invoice_id = await completed_visit(practice, **kwargs)
    assert (await desk_.issue(invoice_id)).status_code == 200
    return invoice_id


async def dentist_login(practice: Practice, dentist) -> str:  # type: ignore[no-untyped-def]
    """Sign in as a user that owns the given dentist profile."""
    email = unique_email("dentist")
    user = await practice.ctx.create_user(email, UserRole.DENTIST)
    await practice.ctx.execute("DELETE FROM dentists WHERE user_id = :u", u=user.id)
    await practice.ctx.execute(
        "UPDATE dentists SET user_id = :u WHERE id = :d", u=user.id, d=dentist.id
    )
    return await practice.ctx.access_token(email)
