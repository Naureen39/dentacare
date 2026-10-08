"""Patient self service profile, staff patient records and administration endpoints."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select, update

from app.core.deps import Cipher, CurrentUser, OwnPatient, RedisDep, Session, require_roles
from app.core.errors import AppError
from app.db.enums import ReminderStatus, UserRole
from app.db.models import AuditLog, RefreshToken, Reminder, User
from app.schemas.booking import ReminderOut
from app.schemas.patients import (
    AuditLogEntry,
    PatientProfile,
    PatientSummary,
    PatientUpdate,
    RoleChangeRequest,
    RoleChangeResponse,
    StaffPatientUpdate,
)
from app.services import audit, patients
from app.services.audit import AuditAction

router = APIRouter()

PatientUser = Annotated[CurrentUser, Depends(require_roles(UserRole.PATIENT))]
StaffUser = Annotated[
    CurrentUser,
    Depends(require_roles(UserRole.ADMIN, UserRole.RECEPTIONIST, UserRole.DENTIST)),
]
FrontDeskUser = Annotated[
    CurrentUser, Depends(require_roles(UserRole.ADMIN, UserRole.RECEPTIONIST))
]
AdminUser = Annotated[CurrentUser, Depends(require_roles(UserRole.ADMIN))]


# --- the signed in patient ---------------------------------------------------------


@router.get("/me", response_model=PatientProfile, tags=["me"])
async def get_my_profile(_: PatientUser, patient: OwnPatient, cipher: Cipher) -> PatientProfile:
    return patients.to_profile(patient, cipher)


@router.patch("/me", response_model=PatientProfile, tags=["me"])
async def update_my_profile(
    body: PatientUpdate,
    request: Request,
    current: PatientUser,
    patient: OwnPatient,
    db: Session,
    cipher: Cipher,
) -> PatientProfile:
    changed = patients.apply_update(patient, body, cipher)
    await audit.record(
        db,
        AuditAction.PROFILE_UPDATE,
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity="patient",
        entity_id=patient.id,
        metadata={"fields": changed},
    )
    await db.commit()
    return patients.to_profile(patient, cipher)


# --- staff access to patient records -----------------------------------------------


@router.get("/patients", response_model=list[PatientSummary], tags=["patients"])
async def search_patients(
    request: Request,
    current: StaffUser,
    db: Session,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> list[PatientSummary]:
    rows = await patients.search_patients(db, current, q)
    await audit.record(
        db,
        AuditAction.PATIENT_LIST,
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity="patient",
        metadata={"results": len(rows)},
    )
    await db.commit()
    return [patients.to_summary(p) for p in rows]


@router.get("/patients/{patient_id}", response_model=PatientProfile, tags=["patients"])
async def get_patient(
    patient_id: uuid.UUID, request: Request, current: StaffUser, db: Session, cipher: Cipher
) -> PatientProfile:
    patient = await patients.get_patient_for_staff(db, current, patient_id)
    await audit.record(
        db,
        AuditAction.PATIENT_VIEW,
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity="patient",
        entity_id=patient.id,
    )
    await db.commit()
    return patients.to_profile(patient, cipher)


@router.patch("/patients/{patient_id}", response_model=PatientProfile, tags=["patients"])
async def update_patient(
    patient_id: uuid.UUID,
    body: StaffPatientUpdate,
    request: Request,
    current: FrontDeskUser,
    db: Session,
    cipher: Cipher,
) -> PatientProfile:
    patient = await patients.get_patient_for_staff(db, current, patient_id, write=True)
    changed = patients.apply_update(patient, body, cipher)
    await audit.record(
        db,
        AuditAction.PATIENT_UPDATE,
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity="patient",
        entity_id=patient.id,
        metadata={"fields": changed},
    )
    await db.commit()
    return patients.to_profile(patient, cipher)


# --- administration ----------------------------------------------------------------


@router.get("/admin/audit-logs", response_model=list[AuditLogEntry], tags=["admin"])
async def list_audit_logs(
    request: Request,
    current: AdminUser,
    db: Session,
    action: Annotated[str | None, Query(max_length=80)] = None,
    actor_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLogEntry]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if since:
        stmt = stmt.where(AuditLog.created_at >= since)
    if until:
        stmt = stmt.where(AuditLog.created_at <= until)
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()
    await audit.record(
        db,
        AuditAction.AUDIT_VIEW,
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        metadata={"results": len(rows)},
    )
    await db.commit()
    return [
        AuditLogEntry(
            id=r.id,
            actor_id=r.actor_id,
            actor_role=r.actor_role,
            action=r.action,
            entity=r.entity,
            entity_id=r.entity_id,
            ip=str(r.ip) if r.ip else None,
            metadata=r.metadata_,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.patch("/admin/users/{user_id}/role", response_model=RoleChangeResponse, tags=["admin"])
async def change_user_role(
    user_id: uuid.UUID,
    body: RoleChangeRequest,
    request: Request,
    current: AdminUser,
    db: Session,
    redis: RedisDep,
) -> RoleChangeResponse:
    if user_id == current.id:
        raise AppError("forbidden", "You cannot change your own role.", 403)
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise AppError("not_found", "User not found.", 404)
    previous = user.role
    if previous is not body.role:
        user.role = body.role
        # Existing sessions were issued for the old role: end them so the new rules apply.
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await audit.record(
            db,
            AuditAction.ROLE_CHANGE,
            request=request,
            actor_id=current.id,
            actor_role=current.role.value,
            entity="user",
            entity_id=user.id,
            metadata={"from": previous.value, "to": body.role.value},
        )
    await db.commit()
    return RoleChangeResponse(id=user.id, role=user.role)


@router.get("/admin/reminders", response_model=list[ReminderOut], tags=["admin"])
async def list_reminders(
    _: AdminUser,
    db: Session,
    status: ReminderStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ReminderOut]:
    """Reminder delivery state. ``status=failed`` is the dead letter list."""
    stmt = select(Reminder).order_by(Reminder.scheduled_at.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(Reminder.status == status)
    return [
        ReminderOut(
            id=r.id,
            appointment_id=r.appointment_id,
            kind=r.kind.value,
            status=r.status.value,
            scheduled_at=r.scheduled_at,
            sent_at=r.sent_at,
            attempts=r.attempts,
            error=r.error,
        )
        for r in (await db.execute(stmt)).scalars()
    ]
