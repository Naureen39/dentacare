"""Staff scheduling endpoints: the schedule view, booking for patients, status changes."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Range

from app.api.v1.booking_deps import Appointments, load_active_service
from app.core.deps import AppSettings, Cipher, CurrentUser, Session, require_roles
from app.core.errors import AppError
from app.db.enums import AppointmentChannel, UserRole
from app.db.models import Appointment, Patient
from app.schemas.booking import (
    ScheduleResponse,
    StaffAppointmentOut,
    StaffBookingRequest,
    StatusChangeRequest,
)
from app.schemas.patients import PatientCreate, PatientProfile
from app.services import audit, patients
from app.services.audit import AuditAction

router = APIRouter(tags=["staff"])

StaffUser = Annotated[
    CurrentUser,
    Depends(require_roles(UserRole.ADMIN, UserRole.RECEPTIONIST, UserRole.DENTIST)),
]
FrontDeskUser = Annotated[
    CurrentUser, Depends(require_roles(UserRole.ADMIN, UserRole.RECEPTIONIST))
]


@router.get("/staff/schedule", response_model=ScheduleResponse)
async def schedule(
    request: Request,
    current: StaffUser,
    db: Session,
    settings: AppSettings,
    appointments: Appointments,
    view: Literal["day", "week"] = "day",
    on: date | None = None,
    dentist_id: uuid.UUID | None = None,
) -> ScheduleResponse:
    """Appointments of one clinic day, or of the Monday to Sunday week containing it."""
    tz = ZoneInfo(settings.clinic_tz)
    anchor = on or datetime.now(tz).date()
    first = anchor - timedelta(days=anchor.weekday()) if view == "week" else anchor
    last = first + timedelta(days=6 if view == "week" else 0)
    lo = datetime.combine(first, time(0, 0), tzinfo=tz).astimezone(UTC)
    hi = datetime.combine(last + timedelta(days=1), time(0, 0), tzinfo=tz).astimezone(UTC)

    if current.role is UserRole.DENTIST:
        own = await patients.dentist_id_for_user(db, current)
        if own is None or (dentist_id is not None and dentist_id != own):
            raise AppError("forbidden", "You can only view your own schedule.", 403)
        dentist_id = own

    stmt = select(Appointment).where(Appointment.slot.overlaps(Range(lo, hi, bounds="[)")))
    if dentist_id is not None:
        stmt = stmt.where(Appointment.dentist_id == dentist_id)
    rows = list(
        (await db.execute(stmt.order_by(func.lower(Appointment.slot), Appointment.dentist_id)))
        .scalars()
        .all()
    )
    result = await appointments.present(rows, with_patient=True)
    await audit.record(
        db,
        AuditAction.SCHEDULE_VIEW,
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity="appointment",
        metadata={"results": len(rows), "view": view},
    )
    await db.commit()
    return ScheduleResponse(view=view, start=first, end=last, appointments=result)


@router.post("/staff/appointments", response_model=StaffAppointmentOut, status_code=201)
async def book_for_patient(
    body: StaffBookingRequest, current: FrontDeskUser, db: Session, appointments: Appointments
) -> StaffAppointmentOut:
    patient = (
        await db.execute(select(Patient).where(Patient.id == body.patient_id))
    ).scalar_one_or_none()
    if patient is None:
        raise AppError("not_found", "Patient not found.", 404)
    service = await load_active_service(db, body.service_id)
    appointment = await appointments.book(
        patient=patient,
        service=service,
        dentist_id=body.dentist_id,
        start=body.start,
        channel=AppointmentChannel.STAFF,
        actor=current,
        reason_note=body.reason_note,
        hold_token=None,
        require_hold=False,
        enforce_rules=False,
    )
    return (await appointments.present([appointment], with_patient=True))[0]  # type: ignore[return-value]


@router.patch("/staff/appointments/{appointment_id}/status", response_model=StaffAppointmentOut)
async def change_status(
    appointment_id: uuid.UUID,
    body: StatusChangeRequest,
    current: StaffUser,
    db: Session,
    appointments: Appointments,
) -> StaffAppointmentOut:
    appointment = await appointments.get(appointment_id, lock=True)
    if current.role is UserRole.DENTIST:
        own = await patients.dentist_id_for_user(db, current)
        if own is None or appointment.dentist_id != own:
            raise AppError("not_found", "Appointment not found.", 404)
    updated = await appointments.change_status(appointment, body.status, current, body.reason)
    return (await appointments.present([updated], with_patient=True))[0]  # type: ignore[return-value]


@router.post("/patients", response_model=PatientProfile, status_code=201, tags=["patients"])
async def create_patient(
    body: PatientCreate, request: Request, current: FrontDeskUser, db: Session, cipher: Cipher
) -> PatientProfile:
    patient = Patient(
        first_name=body.first_name,
        last_name=body.last_name,
        email=str(body.email).lower() if body.email else None,
        source=body.source,
    )
    patients.apply_update(patient, body, cipher)
    db.add(patient)
    await db.flush()
    await audit.record(
        db,
        AuditAction.PATIENT_CREATE,
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity="patient",
        entity_id=patient.id,
    )
    await db.commit()
    return patients.to_profile(patient, cipher)
