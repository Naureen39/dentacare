"""Work screens for clinic staff: appointment drawer, completing a visit, patient history and
notes, duplicate suggestions, a dentist's own numbers and the alert counts in the top bar."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, case, func, or_, select, text

from app.api.v1.booking_deps import Appointments
from app.api.v1.portal import Billing
from app.core.deps import AppSettings, Cipher, CurrentUser, MailerDep, Session, require_roles
from app.core.errors import AppError
from app.db.enums import (
    AppointmentStatus,
    InquiryStatus,
    InvoiceStatus,
    ReminderChannel,
    ReminderKind,
    ReminderStatus,
    UserRole,
)
from app.db.models import (
    Appointment,
    ContactInquiry,
    Invoice,
    Patient,
    PatientNote,
    Reminder,
    User,
)
from app.db.models import Service as ServiceRow
from app.schemas.analytics import ReminderResult
from app.schemas.billing import InvoiceItemCreate, InvoiceListItem
from app.schemas.booking import StaffAppointmentOut
from app.schemas.console import (
    Alerts,
    AppointmentDetail,
    ClinicalNote,
    CompleteRequest,
    DuplicateCandidate,
    PatientHistory,
    PatientNoteCreate,
    PatientNoteOut,
    Performance,
    StaffRescheduleRequest,
)
from app.services import audit, patients
from app.services.appointments import bounds
from app.services.audit import AuditAction
from app.services.billing import display_number
from app.services.notifications import NotificationService

router = APIRouter(tags=["staff"])

StaffUser = Annotated[
    CurrentUser,
    Depends(require_roles(UserRole.ADMIN, UserRole.RECEPTIONIST, UserRole.DENTIST)),
]
FrontDeskUser = Annotated[
    CurrentUser, Depends(require_roles(UserRole.ADMIN, UserRole.RECEPTIONIST))
]
DentistUser = Annotated[CurrentUser, Depends(require_roles(UserRole.DENTIST))]

NOTE_FIELD = "appointments.clinical_note"
PATIENT_NOTE_FIELD = "patient_notes.body"


async def _own_dentist(db: Session, current: CurrentUser) -> uuid.UUID:
    own = await patients.dentist_id_for_user(db, current)
    if own is None:
        raise AppError("forbidden", "No dentist profile is linked to this account.", 403)
    return own


async def _load_visible(
    appointments: Appointments,
    db: Session,
    current: CurrentUser,
    appointment_id: uuid.UUID,
    *,
    lock: bool = False,
) -> Appointment:
    """An appointment the member of staff may see. A dentist sees only their own."""
    appointment = await appointments.get(appointment_id, lock=lock)
    if current.role is UserRole.DENTIST:
        own = await patients.dentist_id_for_user(db, current)
        if own is None or appointment.dentist_id != own:
            raise AppError("not_found", "Appointment not found.", 404)
    return appointment


# --- the appointment drawer -----------------------------------------------------------------


@router.get("/staff/appointments/{appointment_id}", response_model=AppointmentDetail)
async def appointment_detail(
    appointment_id: uuid.UUID,
    current: StaffUser,
    db: Session,
    appointments: Appointments,
    cipher: Cipher,
) -> AppointmentDetail:
    appointment = await _load_visible(appointments, db, current, appointment_id)
    (view,) = await appointments.present([appointment], with_patient=True)
    patient = (
        await db.execute(select(Patient).where(Patient.id == appointment.patient_id))
    ).scalar_one()
    recent = list(
        (
            await db.execute(
                select(Appointment)
                .where(
                    Appointment.patient_id == patient.id,
                    Appointment.id != appointment.id,
                    Appointment.status == AppointmentStatus.COMPLETED,
                )
                .order_by(func.lower(Appointment.slot).desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    profile = patients.to_profile(patient, cipher)
    note = None
    if current.role is UserRole.DENTIST and appointment.clinical_note_enc:
        note = cipher.decrypt_optional(appointment.clinical_note_enc, NOTE_FIELD)
    return AppointmentDetail(
        **view.model_dump(),
        patient_email=profile.email,
        patient_phone=profile.phone,
        clinical_note=note,
        recent_visits=await appointments.present(recent),
    )


@router.put("/staff/appointments/{appointment_id}/clinical-note", response_model=ClinicalNote)
async def save_clinical_note(
    appointment_id: uuid.UUID,
    body: ClinicalNote,
    request: Request,
    current: DentistUser,
    db: Session,
    appointments: Appointments,
    cipher: Cipher,
) -> ClinicalNote:
    """The treating dentist's private note. Nobody else can read or change it."""
    appointment = await _load_visible(appointments, db, current, appointment_id, lock=True)
    appointment.clinical_note_enc = cipher.encrypt_optional(body.note or None, NOTE_FIELD)
    await audit.record(
        db,
        AuditAction.CLINICAL_NOTE,
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity="appointment",
        entity_id=appointment.id,
    )
    await db.commit()
    return body


@router.post("/staff/appointments/{appointment_id}/complete", response_model=StaffAppointmentOut)
async def complete_visit(
    appointment_id: uuid.UUID,
    body: CompleteRequest,
    request: Request,
    current: StaffUser,
    db: Session,
    appointments: Appointments,
    billing: Billing,
    cipher: Cipher,
) -> StaffAppointmentOut:
    """Mark a visit completed, add the services performed to the draft invoice and keep the note."""
    appointment = await _load_visible(appointments, db, current, appointment_id, lock=True)
    if body.clinical_note is not None:
        if current.role is not UserRole.DENTIST:
            raise AppError("forbidden", "Only the dentist can write a clinical note.", 403)
        appointment.clinical_note_enc = cipher.encrypt_optional(
            body.clinical_note or None, NOTE_FIELD
        )
    extra = list(dict.fromkeys(body.performed_service_ids))
    services = (
        (await db.execute(select(ServiceRow).where(ServiceRow.id.in_(extra)))).scalars().all()
        if extra
        else []
    )
    if len(services) != len(extra):
        raise AppError("validation_error", "One of the services does not exist.", 422)

    updated = await appointments.change_status(
        appointment, AppointmentStatus.COMPLETED, current, None
    )
    if services:
        invoice = (
            await db.execute(select(Invoice).where(Invoice.appointment_id == updated.id))
        ).scalar_one_or_none()
        if invoice is not None and invoice.status is InvoiceStatus.DRAFT:
            for service in services:
                if service.id == updated.service_id:
                    continue
                await billing.add_item(
                    invoice,
                    InvoiceItemCreate(
                        description=service.name,
                        qty=1,
                        unit_price=service.base_price,
                        service_id=service.id,
                    ),
                    current,
                )
            await db.commit()
    return (await appointments.present([updated], with_patient=True))[0]  # type: ignore[return-value]


@router.patch("/staff/appointments/{appointment_id}/reschedule", response_model=StaffAppointmentOut)
async def reschedule_for_patient(
    appointment_id: uuid.UUID,
    body: StaffRescheduleRequest,
    current: FrontDeskUser,
    db: Session,
    appointments: Appointments,
) -> StaffAppointmentOut:
    """Move a visit to another time or dentist, for example by dragging it on the schedule."""
    appointment = await appointments.get(appointment_id, lock=True)
    new = await appointments.reschedule_staff(
        appointment, current, start=body.start, dentist_id=body.dentist_id
    )
    return (await appointments.present([new], with_patient=True))[0]  # type: ignore[return-value]


# --- patient records --------------------------------------------------------------------------


@router.get("/patients/{patient_id}/history", response_model=PatientHistory, tags=["patients"])
async def patient_history(
    patient_id: uuid.UUID,
    current: StaffUser,
    db: Session,
    appointments: Appointments,
    billing: Billing,
) -> PatientHistory:
    patient = await patients.get_patient_for_staff(db, current, patient_id)
    rows = list(
        (
            await db.execute(
                select(Appointment)
                .where(Appointment.patient_id == patient.id)
                .order_by(func.lower(Appointment.slot).desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    invoices: list[InvoiceListItem] = []
    if current.role is not UserRole.DENTIST:  # money matters stay with the front desk
        for invoice in (
            (
                await db.execute(
                    select(Invoice)
                    .where(Invoice.patient_id == patient.id, Invoice.status != InvoiceStatus.DRAFT)
                    .order_by(Invoice.issued_at.desc())
                )
            )
            .scalars()
            .all()
        ):
            totals = await billing.totals(invoice.id)
            invoices.append(
                InvoiceListItem(
                    id=invoice.id,
                    number=invoice.number,
                    display_number=display_number(invoice.number),
                    patient_id=patient.id,
                    patient_name=f"{patient.first_name} {patient.last_name}",
                    issued_at=invoice.issued_at,
                    status=invoice.status,
                    total=invoice.total,
                    paid=totals.paid,
                    balance=totals.balance(invoice.total),
                )
            )
    return PatientHistory(appointments=await appointments.present(rows), invoices=invoices)


@router.get("/patients/{patient_id}/notes", response_model=list[PatientNoteOut], tags=["patients"])
async def list_patient_notes(
    patient_id: uuid.UUID, current: FrontDeskUser, db: Session, cipher: Cipher
) -> list[PatientNoteOut]:
    patient = await patients.get_patient_for_staff(db, current, patient_id)
    rows = (
        await db.execute(
            select(PatientNote, User.email)
            .outerjoin(User, User.id == PatientNote.author_id)
            .where(PatientNote.patient_id == patient.id)
            .order_by(PatientNote.created_at.desc())
        )
    ).all()
    return [
        PatientNoteOut(
            id=n.id,
            body=cipher.decrypt_optional(n.body_enc, PATIENT_NOTE_FIELD) or "",
            author=email,
            created_at=n.created_at,
        )
        for n, email in rows
    ]


@router.post(
    "/patients/{patient_id}/notes",
    response_model=PatientNoteOut,
    status_code=201,
    tags=["patients"],
)
async def add_patient_note(
    patient_id: uuid.UUID,
    body: PatientNoteCreate,
    request: Request,
    current: FrontDeskUser,
    db: Session,
    cipher: Cipher,
) -> PatientNoteOut:
    patient = await patients.get_patient_for_staff(db, current, patient_id, write=True)
    note = PatientNote(
        patient_id=patient.id,
        author_id=current.id,
        body_enc=cipher.encrypt_optional(body.body, PATIENT_NOTE_FIELD) or "",
    )
    db.add(note)
    await db.flush()
    await audit.record(
        db,
        AuditAction.PATIENT_NOTE,
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity="patient",
        entity_id=patient.id,
    )
    await db.commit()
    return PatientNoteOut(
        id=note.id, body=body.body, author=current.user.email, created_at=note.created_at
    )


@router.get(
    "/patients/{patient_id}/duplicates",
    response_model=list[DuplicateCandidate],
    tags=["patients"],
)
async def duplicate_candidates(
    patient_id: uuid.UUID, current: FrontDeskUser, db: Session
) -> list[DuplicateCandidate]:
    """Other records that may be the same person: similar name (trigram), same email or phone.

    This only suggests. Nothing is merged automatically.
    """
    patient = await patients.get_patient_for_staff(db, current, patient_id)
    full = f"{patient.first_name} {patient.last_name}".lower()
    similarity = func.similarity(func.lower(Patient.first_name + " " + Patient.last_name), full)
    same_email = (
        and_(Patient.email.is_not(None), func.lower(Patient.email) == (patient.email or "").lower())
        if patient.email
        else text("false")
    )
    rows = (
        await db.execute(
            select(Patient, similarity.label("score"), same_email.label("same_email"))
            .where(Patient.id != patient.id, or_(similarity >= 0.55, same_email))
            .order_by(similarity.desc())
            .limit(10)
        )
    ).all()
    out = []
    for other, score, email_match in rows:
        reasons = []
        if score >= 0.55:
            reasons.append("similar name")
        if email_match:
            reasons.append("same email address")
        out.append(
            DuplicateCandidate(
                patient=patients.to_summary(other),
                score=round(float(score), 2),
                reasons=reasons,
            )
        )
    return out


# --- a dentist's own numbers and the top bar -------------------------------------------------------


@router.get("/staff/me/performance", response_model=Performance)
async def my_performance(
    current: DentistUser,
    db: Session,
    days: Annotated[int, Query(ge=7, le=365)] = 30,
) -> Performance:
    dentist_id = await _own_dentist(db, current)
    since = datetime.now(UTC) - timedelta(days=days)
    start = func.lower(Appointment.slot)
    completed, no_shows = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(case((Appointment.status == AppointmentStatus.COMPLETED, 1), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(case((Appointment.status == AppointmentStatus.NO_SHOW, 1), else_=0)), 0
                ),
            ).where(Appointment.dentist_id == dentist_id, start >= since, start < func.now())
        )
    ).one()
    revenue = (
        await db.execute(
            select(func.coalesce(func.sum(Invoice.total), 0))
            .join(Appointment, Appointment.id == Invoice.appointment_id)
            .where(
                Appointment.dentist_id == dentist_id,
                start >= since,
                Invoice.status.notin_([InvoiceStatus.DRAFT, InvoiceStatus.VOID]),
            )
        )
    ).scalar_one()
    seen = int(completed) + int(no_shows)
    return Performance(
        days=days,
        visits=int(completed),
        revenue=Decimal(revenue),
        no_shows=int(no_shows),
        no_show_rate=round(int(no_shows) / seen, 4) if seen else 0.0,
    )


@router.get("/staff/alerts", response_model=Alerts)
async def alerts(_: FrontDeskUser, db: Session) -> Alerts:
    """Counts for the bell in the top bar."""
    now = datetime.now(UTC)
    unconfirmed = (
        await db.execute(
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.status == AppointmentStatus.BOOKED,
                func.lower(Appointment.slot) > now,
                func.lower(Appointment.slot) <= now + timedelta(hours=48),
            )
        )
    ).scalar_one()
    inquiries = (
        await db.execute(
            select(func.count())
            .select_from(ContactInquiry)
            .where(ContactInquiry.status == InquiryStatus.NEW)
        )
    ).scalar_one()
    return Alerts(unconfirmed_soon=unconfirmed, new_inquiries=inquiries)


@router.post("/staff/appointments/{appointment_id}/remind", response_model=ReminderResult)
async def send_reminder_now(
    appointment_id: uuid.UUID,
    request: Request,
    current: FrontDeskUser,
    db: Session,
    appointments: Appointments,
    settings: AppSettings,
    mailer: MailerDep,
) -> ReminderResult:
    """Send the visit reminder email now, for example to a patient the no show score flags."""
    appointment = await appointments.get(appointment_id)
    if appointment.status not in (AppointmentStatus.BOOKED, AppointmentStatus.CONFIRMED):
        raise AppError("invalid_transition", "Only booked or confirmed visits get a reminder.", 422)
    if bounds(appointment)[0] <= datetime.now(UTC):
        raise AppError("invalid_transition", "That visit has already started.", 422)
    reminder = (
        await db.execute(
            select(Reminder).where(
                Reminder.appointment_id == appointment.id, Reminder.kind == ReminderKind.HOURS_24
            )
        )
    ).scalar_one_or_none()
    if reminder is None:
        reminder = Reminder(
            appointment_id=appointment.id,
            kind=ReminderKind.HOURS_24,
            channel=ReminderChannel.EMAIL,
            scheduled_at=datetime.now(UTC),
            status=ReminderStatus.PENDING,
        )
        db.add(reminder)
    else:
        reminder.status = ReminderStatus.PENDING
        reminder.scheduled_at = datetime.now(UTC)
        reminder.attempts = 0
        reminder.error = None
    await db.flush()
    await audit.record(
        db,
        AuditAction.REMINDER_MANUAL,
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity="appointment",
        entity_id=appointment.id,
    )
    await db.commit()
    outcome = await NotificationService(db, settings, mailer).send(reminder.id)
    if outcome.status != "sent":
        raise AppError(
            "reminder_not_sent",
            f"The reminder was not sent: {outcome.detail or outcome.status}.",
            409,
        )
    return ReminderResult(message="The reminder email was sent.")
