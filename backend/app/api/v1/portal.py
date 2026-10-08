"""Appointments and invoices of the signed in patient."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select

from app.api.v1.billing import pdf_response
from app.api.v1.booking_deps import Appointments, load_active_service
from app.core.deps import AppSettings, CurrentUser, OwnPatient, Session, require_roles
from app.core.errors import AppError
from app.core.rate_limit import ip_rate_limit, public_booking_rule
from app.db.enums import (
    AppointmentChannel,
    InvoiceStatus,
    PaymentMethod,
    ReminderStatus,
    UserRole,
)
from app.db.models import Appointment, Invoice, Reminder
from app.schemas.billing import InvoiceListItem, InvoiceOut, PayInvoiceRequest
from app.schemas.booking import (
    AppointmentOut,
    BookingRequest,
    CancelRequest,
    NotificationOut,
    RescheduleRequest,
)
from app.services.billing import BillingService, display_number  # noqa: E402
from app.services.calendar_ics import build_ics  # noqa: E402

router = APIRouter(prefix="/me", tags=["me"])

PatientUser = Annotated[CurrentUser, Depends(require_roles(UserRole.PATIENT))]
booking_limit = Depends(ip_rate_limit(public_booking_rule))


async def _own_appointment(
    appointments: Appointments, appointment_id: uuid.UUID, patient_id: uuid.UUID
) -> Appointment:
    """Load an appointment that belongs to the patient. Others are reported as missing."""
    appointment = await appointments.get(appointment_id, lock=True)
    if appointment.patient_id != patient_id:
        raise AppError("not_found", "Appointment not found.", 404)
    return appointment


@router.get("/appointments", response_model=list[AppointmentOut])
async def list_my_appointments(
    _: PatientUser,
    patient: OwnPatient,
    appointments: Appointments,
    db: Session,
    when: Literal["upcoming", "past", "all"] = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AppointmentOut]:
    starts_at = func.lower(Appointment.slot)
    stmt = select(Appointment).where(Appointment.patient_id == patient.id)
    now = datetime.now(UTC)
    if when == "upcoming":
        stmt = stmt.where(starts_at >= now).order_by(starts_at)
    elif when == "past":
        stmt = stmt.where(starts_at < now).order_by(starts_at.desc())
    else:
        stmt = stmt.order_by(starts_at.desc())
    rows = list((await db.execute(stmt.limit(limit))).scalars().all())
    return await appointments.present(rows)  # type: ignore[return-value]


@router.post(
    "/appointments", response_model=AppointmentOut, status_code=201, dependencies=[booking_limit]
)
async def book_my_appointment(
    body: BookingRequest, current: PatientUser, patient: OwnPatient, appointments: Appointments
) -> AppointmentOut:
    service = await load_active_service(appointments.db, body.service_id)
    appointment = await appointments.book(
        patient=patient,
        service=service,
        dentist_id=body.dentist_id,
        start=body.start,
        channel=AppointmentChannel.WEB,
        actor=current,
        reason_note=body.reason_note,
        hold_token=body.hold_token,
        require_hold=True,
        enforce_rules=True,
    )
    return (await appointments.present([appointment]))[0]


@router.post(
    "/appointments/{appointment_id}/reschedule", response_model=AppointmentOut, status_code=201
)
async def reschedule_my_appointment(
    appointment_id: uuid.UUID,
    body: RescheduleRequest,
    current: PatientUser,
    patient: OwnPatient,
    appointments: Appointments,
) -> AppointmentOut:
    appointment = await _own_appointment(appointments, appointment_id, patient.id)
    new = await appointments.reschedule_own(
        appointment,
        patient,
        current,
        start=body.start,
        dentist_id=body.dentist_id,
        hold_token=body.hold_token,
    )
    return (await appointments.present([new]))[0]


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
async def cancel_my_appointment(
    appointment_id: uuid.UUID,
    current: PatientUser,
    patient: OwnPatient,
    appointments: Appointments,
    body: CancelRequest | None = None,
) -> AppointmentOut:
    appointment = await _own_appointment(appointments, appointment_id, patient.id)
    cancelled = await appointments.cancel(appointment, current, body.reason if body else None)
    return (await appointments.present([cancelled]))[0]


def get_billing(request: Request, db: Session, settings: AppSettings) -> BillingService:
    return BillingService(db, settings, request)


Billing = Annotated[BillingService, Depends(get_billing)]


async def _own_invoice(
    billing: BillingService, invoice_id: uuid.UUID, patient_id: uuid.UUID, *, lock: bool = False
) -> Invoice:
    """An issued invoice of the signed in patient. Drafts and other people's are missing."""
    invoice = await billing.get(invoice_id, lock=lock)
    if invoice.patient_id != patient_id or invoice.status is InvoiceStatus.DRAFT:
        raise AppError("not_found", "Invoice not found.", 404)
    return invoice


@router.get("/invoices", response_model=list[InvoiceListItem])
async def list_my_invoices(
    _: PatientUser, patient: OwnPatient, db: Session, billing: Billing
) -> list[InvoiceListItem]:
    invoices = (
        (
            await db.execute(
                select(Invoice)
                .where(Invoice.patient_id == patient.id, Invoice.status != InvoiceStatus.DRAFT)
                .order_by(Invoice.issued_at.desc(), Invoice.number.desc())
            )
        )
        .scalars()
        .all()
    )
    out: list[InvoiceListItem] = []
    for invoice in invoices:
        totals = await billing.totals(invoice.id)
        out.append(
            InvoiceListItem(
                id=invoice.id,
                number=invoice.number,
                display_number=display_number(invoice.number),
                patient_id=invoice.patient_id,
                patient_name=f"{patient.first_name} {patient.last_name}",
                issued_at=invoice.issued_at,
                status=invoice.status,
                total=invoice.total,
                paid=totals.paid,
                balance=totals.balance(invoice.total),
            )
        )
    return out


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
async def get_my_invoice(
    invoice_id: uuid.UUID, _: PatientUser, patient: OwnPatient, billing: Billing
) -> InvoiceOut:
    return await billing.present(await _own_invoice(billing, invoice_id, patient.id))


@router.get("/invoices/{invoice_id}/pdf")
async def download_my_invoice(
    invoice_id: uuid.UUID,
    _: PatientUser,
    patient: OwnPatient,
    db: Session,
    settings: AppSettings,
    billing: Billing,
) -> Response:
    invoice = await _own_invoice(billing, invoice_id, patient.id)
    return await pdf_response(db, settings, billing, invoice)


@router.post("/invoices/{invoice_id}/pay", response_model=InvoiceOut, status_code=201)
async def pay_my_invoice(
    invoice_id: uuid.UUID,
    body: PayInvoiceRequest,
    current: PatientUser,
    patient: OwnPatient,
    db: Session,
    billing: Billing,
) -> InvoiceOut:
    """Sandbox card payment. The amount defaults to the whole remaining balance."""
    invoice = await _own_invoice(billing, invoice_id, patient.id, lock=True)
    amount = body.amount
    if amount is None:
        amount = (await billing.totals(invoice.id)).balance(invoice.total)
        if amount <= 0:
            raise AppError("invoice_not_payable", "There is nothing left to pay.", 409)
    await billing.record_payment(
        invoice,
        current,
        amount=amount,
        method=PaymentMethod.CARD,
        reference=None,
        paid_at=None,
        card=body.card,
    )
    await db.commit()
    return await billing.present(invoice)


# --- calendar file and notification history -------------------------------------------------

NOTIFICATION_TITLES = {
    "confirmation": "Appointment booked",
    "48h": "Appointment reminder",
    "24h": "Appointment reminder",
    "followup": "Thank you for your visit",
    "recall": "Time for your next check-up",
}


@router.get("/appointments/{appointment_id}/ics")
async def download_calendar_file(
    appointment_id: uuid.UUID,
    _: PatientUser,
    patient: OwnPatient,
    appointments: Appointments,
    settings: AppSettings,
) -> Response:
    appointment = await _own_appointment(appointments, appointment_id, patient.id)
    view = (await appointments.present([appointment]))[0]
    content = build_ics(
        appointment_id=appointment.id,
        start=view.start,
        end=view.end,
        service_name=view.service_name,
        dentist_name=view.dentist_name,
        settings=settings,
    )
    return Response(
        content=content,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="appointment.ics"'},
    )


@router.get("/notifications", response_model=list[NotificationOut])
async def list_my_notifications(
    _: PatientUser,
    patient: OwnPatient,
    db: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[NotificationOut]:
    """Reminders and messages that were sent to the signed in patient, newest first."""
    rows = (
        await db.execute(
            select(Reminder)
            .join(Appointment, Appointment.id == Reminder.appointment_id)
            .where(Appointment.patient_id == patient.id, Reminder.status == ReminderStatus.SENT)
            .order_by(Reminder.sent_at.desc())
            .limit(limit)
        )
    ).scalars()
    return [
        NotificationOut(
            id=r.id,
            kind=r.kind.value,
            title=NOTIFICATION_TITLES.get(r.kind.value, "Message"),
            sent_at=r.sent_at or r.scheduled_at,
            appointment_id=r.appointment_id,
        )
        for r in rows
    ]
