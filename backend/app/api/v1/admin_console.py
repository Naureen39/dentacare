"""Administration for the console: staff, services and prices, dentists, schedules, chat review,
settings and the audit log export. Every route here is for administrators only."""

import csv
import io
import secrets
import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.api.v1.auth import Service as AuthServiceDep
from app.core.deps import AppSettings, CurrentUser, Passwords, RedisDep, Session, require_roles
from app.core.errors import AppError
from app.db.enums import AppointmentStatus, UserRole
from app.db.models import (
    Appointment,
    AppSetting,
    AuditLog,
    ChatMessage,
    ChatSession,
    Dentist,
    DentistSchedule,
    DentistService,
    IntentExample,
    MfaRecoveryCode,
    RefreshToken,
    ScheduleException,
    ServicePriceChange,
    User,
)
from app.db.models import Service as ServiceRow
from app.schemas.auth import MessageResponse
from app.schemas.console import (
    BillingSettings,
    BookingSettings,
    ChatSessionRow,
    ClinicInfo,
    DentistAdminOut,
    DentistUpdate,
    IntentExampleCreate,
    IntentExampleOut,
    PriceChangeCreate,
    PriceChangeOut,
    ReminderSettings,
    RetentionSettings,
    ScheduleDay,
    ScheduleReplace,
    ServiceAdminOut,
    ServiceCreate,
    ServiceUpdate,
    SettingsOut,
    SettingsUpdate,
    StaffUserCreate,
    StaffUserOut,
    StaffUserUpdate,
    TimeOffCreate,
    TimeOffCreated,
    TimeOffOut,
    Transcript,
    TranscriptMessage,
)
from app.services import audit
from app.services.app_settings import get_setting
from app.services.audit import AuditAction
from app.services.availability import AvailabilityService
from app.services.console import apply_due_price_changes
from app.services.pii import mask_text

router = APIRouter(prefix="/admin", tags=["admin"])

AdminUser = Annotated[CurrentUser, Depends(require_roles(UserRole.ADMIN))]


def _today(settings: AppSettings) -> date:
    return datetime.now(ZoneInfo(settings.clinic_tz)).date()


async def _revoke_sessions(db: Session, user_id: uuid.UUID) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=func.now())
    )


async def _record(
    db: Session,
    action: str,
    request: Request,
    current: CurrentUser,
    entity: str,
    entity_id: uuid.UUID | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await audit.record(
        db,
        action,
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity=entity,
        entity_id=entity_id,
        metadata=metadata,
    )


# --- staff accounts ------------------------------------------------------------------------


async def _staff_out(db: Session, user_id: uuid.UUID | None = None) -> list[StaffUserOut]:
    stmt = (
        select(User, Dentist.id, Dentist.full_name)
        .outerjoin(Dentist, Dentist.user_id == User.id)
        .where(User.role != UserRole.PATIENT)
        .order_by(User.role, User.email)
    )
    if user_id is not None:
        stmt = stmt.where(User.id == user_id)
    return [
        StaffUserOut(
            id=u.id,
            email=u.email,
            role=u.role,
            is_active=u.is_active,
            mfa_enabled=u.mfa_enabled,
            last_login_at=u.last_login_at,
            dentist_id=dentist_id,
            dentist_name=name,
        )
        for u, dentist_id, name in (await db.execute(stmt)).all()
    ]


@router.get("/users", response_model=list[StaffUserOut])
async def list_staff(_: AdminUser, db: Session) -> list[StaffUserOut]:
    return await _staff_out(db)


@router.post("/users", response_model=StaffUserOut, status_code=201)
async def create_staff(
    body: StaffUserCreate,
    request: Request,
    current: AdminUser,
    db: Session,
    passwords: Passwords,
    auth: AuthServiceDep,
) -> StaffUserOut:
    """Create a staff account. The person sets their own password from an emailed link."""
    email = str(body.email).lower()
    if body.role == "dentist" and not body.full_name:
        raise AppError("validation_error", "A dentist needs a full name.", 422)
    taken = (await db.execute(select(User.id).where(User.email == email))).scalar_one_or_none()
    if taken is not None:
        raise AppError("email_taken", "An account with that email address already exists.", 409)
    user = User(
        email=email,
        # Nobody knows this password; the emailed reset link replaces it.
        password_hash=passwords.hash(secrets.token_urlsafe(32)),
        role=UserRole(body.role),
        email_verified_at=datetime.now(UTC),
    )
    db.add(user)
    await db.flush()
    if body.role == "dentist":
        db.add(Dentist(user_id=user.id, full_name=body.full_name or "", specialty=body.specialty))
    await _record(
        db, AuditAction.USER_CREATE, request, current, "user", user.id, {"role": body.role}
    )
    await db.commit()
    await auth.forgot_password(email)
    return (await _staff_out(db, user.id))[0]


async def _staff_target(db: Session, user_id: uuid.UUID, current: CurrentUser) -> User:
    if user_id == current.id:
        raise AppError("forbidden", "You cannot do this to your own account.", 403)
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or user.role is UserRole.PATIENT:
        raise AppError("not_found", "Staff account not found.", 404)
    return user


@router.patch("/users/{user_id}", response_model=StaffUserOut)
async def update_staff(
    user_id: uuid.UUID, body: StaffUserUpdate, request: Request, current: AdminUser, db: Session
) -> StaffUserOut:
    user = await _staff_target(db, user_id, current)
    user.is_active = body.is_active
    if not body.is_active:
        await _revoke_sessions(db, user.id)
    await _record(
        db, AuditAction.USER_UPDATE, request, current, "user", user.id, {"active": body.is_active}
    )
    await db.commit()
    return (await _staff_out(db, user.id))[0]


@router.post("/users/{user_id}/reset-mfa", response_model=MessageResponse)
async def reset_staff_mfa(
    user_id: uuid.UUID, request: Request, current: AdminUser, db: Session
) -> MessageResponse:
    """Remove two step verification so the person enrols again at their next sign in."""
    user = await _staff_target(db, user_id, current)
    user.mfa_enabled = False
    user.mfa_secret_enc = None
    await db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    await _revoke_sessions(db, user.id)
    await _record(db, AuditAction.MFA_RESET, request, current, "user", user.id)
    await db.commit()
    return MessageResponse(message="Two step verification was reset. They will enrol again.")


# --- services and prices --------------------------------------------------------------------


async def _services_out(db: Session, service_id: uuid.UUID | None = None) -> list[ServiceAdminOut]:
    stmt = select(ServiceRow).order_by(ServiceRow.display_order, ServiceRow.name)
    if service_id is not None:
        stmt = stmt.where(ServiceRow.id == service_id)
    services = (await db.execute(stmt)).scalars().all()
    changes: dict[uuid.UUID, list[PriceChangeOut]] = {}
    for c in (
        await db.execute(
            select(ServicePriceChange).order_by(
                ServicePriceChange.effective_from.desc(), ServicePriceChange.created_at.desc()
            )
        )
    ).scalars():
        changes.setdefault(c.service_id, []).append(
            PriceChangeOut(
                id=c.id, price=c.price, effective_from=c.effective_from, applied_at=c.applied_at
            )
        )
    return [
        ServiceAdminOut(
            id=s.id,
            code=s.code,
            name=s.name,
            category=s.category,
            description=s.description,
            duration_min=s.duration_min,
            base_price=s.base_price,
            is_active=s.is_active,
            display_order=s.display_order,
            price_changes=changes.get(s.id, [])[:10],
        )
        for s in services
    ]


async def _service(db: Session, service_id: uuid.UUID) -> ServiceRow:
    row = (
        await db.execute(select(ServiceRow).where(ServiceRow.id == service_id))
    ).scalar_one_or_none()
    if row is None:
        raise AppError("not_found", "Service not found.", 404)
    return row


@router.get("/services", response_model=list[ServiceAdminOut])
async def list_services(_: AdminUser, db: Session, settings: AppSettings) -> list[ServiceAdminOut]:
    await apply_due_price_changes(db, _today(settings))
    return await _services_out(db)


@router.post("/services", response_model=ServiceAdminOut, status_code=201)
async def create_service(
    body: ServiceCreate, request: Request, current: AdminUser, db: Session
) -> ServiceAdminOut:
    row = ServiceRow(**body.model_dump())
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise AppError("conflict", "A service with that code already exists.", 409) from exc
    await _record(
        db, AuditAction.SERVICE_CHANGE, request, current, "service", row.id, {"create": True}
    )
    await db.commit()
    return (await _services_out(db, row.id))[0]


@router.patch("/services/{service_id}", response_model=ServiceAdminOut)
async def update_service(
    service_id: uuid.UUID,
    body: ServiceUpdate,
    request: Request,
    current: AdminUser,
    db: Session,
    settings: AppSettings,
    redis: RedisDep,
) -> ServiceAdminOut:
    row = await _service(db, service_id)
    changes = body.model_dump(exclude_unset=True)
    for name, value in changes.items():
        setattr(row, name, value)
    await _record(
        db,
        AuditAction.SERVICE_CHANGE,
        request,
        current,
        "service",
        row.id,
        {"fields": sorted(changes)},
    )
    await db.commit()
    if {"duration_min", "is_active"} & changes.keys():
        await AvailabilityService(db, settings, redis).invalidate_cache()
    return (await _services_out(db, row.id))[0]


@router.post(
    "/services/{service_id}/price-changes", response_model=ServiceAdminOut, status_code=201
)
async def schedule_price_change(
    service_id: uuid.UUID,
    body: PriceChangeCreate,
    request: Request,
    current: AdminUser,
    db: Session,
    settings: AppSettings,
) -> ServiceAdminOut:
    """Set a new price from a day. Today or earlier takes effect at once, later days wait."""
    row = await _service(db, service_id)
    db.add(
        ServicePriceChange(
            service_id=row.id,
            price=body.price,
            effective_from=body.effective_from,
            created_by=current.id,
        )
    )
    await _record(
        db,
        AuditAction.SERVICE_CHANGE,
        request,
        current,
        "service",
        row.id,
        {"price_from": body.effective_from.isoformat()},
    )
    await db.commit()
    await apply_due_price_changes(db, _today(settings))
    return (await _services_out(db, row.id))[0]


@router.delete("/services/{service_id}/price-changes/{change_id}", status_code=204)
async def cancel_price_change(
    service_id: uuid.UUID, change_id: uuid.UUID, current: AdminUser, db: Session
) -> None:
    change = (
        await db.execute(
            select(ServicePriceChange).where(
                ServicePriceChange.id == change_id, ServicePriceChange.service_id == service_id
            )
        )
    ).scalar_one_or_none()
    if change is None:
        raise AppError("not_found", "Price change not found.", 404)
    if change.applied_at is not None:
        raise AppError("conflict", "That price change has already taken effect.", 409)
    await db.delete(change)
    await db.commit()


# --- dentists, working hours and time off ------------------------------------------------------


async def _dentists_out(db: Session, dentist_id: uuid.UUID | None = None) -> list[DentistAdminOut]:
    stmt = select(Dentist).order_by(Dentist.full_name)
    if dentist_id is not None:
        stmt = stmt.where(Dentist.id == dentist_id)
    dentists = (await db.execute(stmt)).scalars().all()
    links: dict[uuid.UUID, list[uuid.UUID]] = {}
    for did, sid in await db.execute(select(DentistService.dentist_id, DentistService.service_id)):
        links.setdefault(did, []).append(sid)
    return [
        DentistAdminOut(
            id=d.id,
            full_name=d.full_name,
            specialty=d.specialty,
            color=d.color,
            is_active=d.is_active,
            user_id=d.user_id,
            service_ids=links.get(d.id, []),
        )
        for d in dentists
    ]


async def _dentist(db: Session, dentist_id: uuid.UUID) -> Dentist:
    row = (await db.execute(select(Dentist).where(Dentist.id == dentist_id))).scalar_one_or_none()
    if row is None:
        raise AppError("not_found", "Dentist not found.", 404)
    return row


@router.get("/dentists", response_model=list[DentistAdminOut])
async def list_dentists(_: AdminUser, db: Session) -> list[DentistAdminOut]:
    return await _dentists_out(db)


@router.patch("/dentists/{dentist_id}", response_model=DentistAdminOut)
async def update_dentist(
    dentist_id: uuid.UUID,
    body: DentistUpdate,
    request: Request,
    current: AdminUser,
    db: Session,
    settings: AppSettings,
    redis: RedisDep,
) -> DentistAdminOut:
    row = await _dentist(db, dentist_id)
    changes = body.model_dump(exclude_unset=True)
    service_ids = changes.pop("service_ids", None)
    for name, value in changes.items():
        setattr(row, name, value)
    if service_ids is not None:
        known = set(
            (
                await db.execute(select(ServiceRow.id).where(ServiceRow.id.in_(service_ids)))
            ).scalars()
        )
        if known != set(service_ids):
            raise AppError("validation_error", "One of the services does not exist.", 422)
        await db.execute(delete(DentistService).where(DentistService.dentist_id == row.id))
        db.add_all(DentistService(dentist_id=row.id, service_id=sid) for sid in known)
    await _record(
        db,
        AuditAction.DENTIST_CHANGE,
        request,
        current,
        "dentist",
        row.id,
        {"fields": sorted(body.model_fields_set)},
    )
    await db.commit()
    await AvailabilityService(db, settings, redis).invalidate_cache()
    return (await _dentists_out(db, row.id))[0]


@router.get("/dentists/{dentist_id}/schedule", response_model=list[ScheduleDay])
async def get_schedule(dentist_id: uuid.UUID, _: AdminUser, db: Session) -> list[ScheduleDay]:
    await _dentist(db, dentist_id)
    rows = (
        await db.execute(
            select(DentistSchedule)
            .where(DentistSchedule.dentist_id == dentist_id)
            .order_by(DentistSchedule.weekday)
        )
    ).scalars()
    return [
        ScheduleDay(
            weekday=r.weekday,
            start_time=r.start_time,
            end_time=r.end_time,
            break_start=r.break_start,
            break_end=r.break_end,
        )
        for r in rows
    ]


@router.put("/dentists/{dentist_id}/schedule", response_model=list[ScheduleDay])
async def replace_schedule(
    dentist_id: uuid.UUID,
    body: ScheduleReplace,
    request: Request,
    current: AdminUser,
    db: Session,
    settings: AppSettings,
    redis: RedisDep,
) -> list[ScheduleDay]:
    """Replace the weekly working hours. A weekday that is left out is a day off."""
    await _dentist(db, dentist_id)
    if len({d.weekday for d in body.days}) != len(body.days):
        raise AppError("validation_error", "Each weekday can appear only once.", 422)
    for day in body.days:
        if day.start_time >= day.end_time:
            raise AppError("validation_error", "Working hours must end after they start.", 422)
        if (day.break_start is None) != (day.break_end is None):
            raise AppError("validation_error", "Give both ends of the break, or neither.", 422)
        if (
            day.break_start is not None
            and day.break_end is not None
            and not (day.start_time <= day.break_start < day.break_end <= day.end_time)
        ):
            raise AppError("validation_error", "The break must fall within working hours.", 422)
    await db.execute(delete(DentistSchedule).where(DentistSchedule.dentist_id == dentist_id))
    db.add_all(DentistSchedule(dentist_id=dentist_id, **d.model_dump()) for d in body.days)
    await _record(
        db, AuditAction.DENTIST_CHANGE, request, current, "dentist", dentist_id, {"schedule": True}
    )
    await db.commit()
    await AvailabilityService(db, settings, redis).invalidate_cache()
    return sorted(body.days, key=lambda d: d.weekday)


def _off_out(row: ScheduleException) -> TimeOffOut:
    return TimeOffOut(
        id=row.id, starts_at=row.starts_at, ends_at=row.ends_at, reason=row.reason, note=row.note
    )


@router.get("/dentists/{dentist_id}/time-off", response_model=list[TimeOffOut])
async def list_time_off(
    dentist_id: uuid.UUID,
    _: AdminUser,
    db: Session,
    include_past: bool = False,
) -> list[TimeOffOut]:
    await _dentist(db, dentist_id)
    stmt = select(ScheduleException).where(ScheduleException.dentist_id == dentist_id)
    if not include_past:
        stmt = stmt.where(ScheduleException.ends_at >= datetime.now(UTC))
    rows = (await db.execute(stmt.order_by(ScheduleException.starts_at))).scalars()
    return [_off_out(r) for r in rows]


@router.post("/dentists/{dentist_id}/time-off", response_model=TimeOffCreated, status_code=201)
async def add_time_off(
    dentist_id: uuid.UUID,
    body: TimeOffCreate,
    request: Request,
    current: AdminUser,
    db: Session,
    settings: AppSettings,
    redis: RedisDep,
) -> TimeOffCreated:
    await _dentist(db, dentist_id)
    if body.starts_at.tzinfo is None or body.ends_at.tzinfo is None:
        raise AppError("validation_error", "Give the times with a time zone.", 422)
    if body.starts_at >= body.ends_at:
        raise AppError("validation_error", "Time off must end after it starts.", 422)
    row = ScheduleException(dentist_id=dentist_id, **body.model_dump())
    db.add(row)
    affected = (
        await db.execute(
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.dentist_id == dentist_id,
                Appointment.status.in_([AppointmentStatus.BOOKED, AppointmentStatus.CONFIRMED]),
                Appointment.slot.overlaps(Range(body.starts_at, body.ends_at, bounds="[)")),
            )
        )
    ).scalar_one()
    await db.flush()
    await _record(
        db, AuditAction.DENTIST_CHANGE, request, current, "dentist", dentist_id, {"time_off": True}
    )
    await db.commit()
    await AvailabilityService(db, settings, redis).invalidate_cache()
    return TimeOffCreated(**_off_out(row).model_dump(), affected_appointments=affected)


@router.delete("/time-off/{time_off_id}", status_code=204)
async def remove_time_off(
    time_off_id: uuid.UUID, _: AdminUser, db: Session, settings: AppSettings, redis: RedisDep
) -> None:
    row = (
        await db.execute(select(ScheduleException).where(ScheduleException.id == time_off_id))
    ).scalar_one_or_none()
    if row is None:
        raise AppError("not_found", "Time off not found.", 404)
    await db.delete(row)
    await db.commit()
    await AvailabilityService(db, settings, redis).invalidate_cache()


# --- assistant intent examples -----------------------------------------------------------------


@router.get("/kb/intents", response_model=list[IntentExampleOut])
async def list_intents(_: AdminUser, db: Session) -> list[IntentExampleOut]:
    rows = (
        await db.execute(select(IntentExample).order_by(IntentExample.intent, IntentExample.text))
    ).scalars()
    return [IntentExampleOut(id=r.id, intent=r.intent, text=r.text) for r in rows]


@router.post("/kb/intents", response_model=IntentExampleOut, status_code=201)
async def add_intent(
    body: IntentExampleCreate, request: Request, current: AdminUser, db: Session
) -> IntentExampleOut:
    embedder = request.app.state.embedder
    (vector,) = await embedder.embed_documents([body.text])
    row = IntentExample(intent=body.intent, text=body.text, embedding=vector)
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise AppError("conflict", "That example already exists for this intent.", 409) from exc
    await _record(db, AuditAction.KB_CHANGE, request, current, "intent_example", row.id)
    await db.commit()
    return IntentExampleOut(id=row.id, intent=row.intent, text=row.text)


@router.delete("/kb/intents/{example_id}", status_code=204)
async def delete_intent(
    example_id: uuid.UUID, request: Request, current: AdminUser, db: Session
) -> None:
    result = await db.execute(delete(IntentExample).where(IntentExample.id == example_id))
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise AppError("not_found", "Example not found.", 404)
    await _record(db, AuditAction.KB_CHANGE, request, current, "intent_example", example_id)
    await db.commit()


# --- chat transcripts, with personal details masked ----------------------------------------------


@router.get("/chat/sessions", response_model=list[ChatSessionRow])
async def list_chat_sessions(
    _: AdminUser,
    db: Session,
    feedback: Annotated[str, Query(pattern="^(any|positive|negative)$")] = "any",
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ChatSessionRow]:
    up = func.coalesce(func.sum(case((ChatMessage.feedback == 1, 1), else_=0)), 0)
    down = func.coalesce(func.sum(case((ChatMessage.feedback == -1, 1), else_=0)), 0)
    first = (
        select(ChatMessage.content)
        .where(ChatMessage.session_id == ChatSession.id, ChatMessage.role == "user")
        .order_by(ChatMessage.created_at)
        .limit(1)
        .correlate(ChatSession)
        .scalar_subquery()
    )
    stmt = (
        select(
            ChatSession.id,
            ChatSession.created_at,
            ChatSession.provider_last,
            func.count(ChatMessage.id),
            up,
            down,
            first,
        )
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .group_by(ChatSession.id)
        .order_by(ChatSession.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if feedback == "positive":
        stmt = stmt.having(up > 0)
    elif feedback == "negative":
        stmt = stmt.having(down > 0)
    return [
        ChatSessionRow(
            id=sid,
            created_at=created,
            provider_last=provider,
            messages=count,
            thumbs_up=int(ups),
            thumbs_down=int(downs),
            first_message=mask_text(text)[:160] if text else None,
        )
        for sid, created, provider, count, ups, downs, text in (await db.execute(stmt)).all()
    ]


@router.get("/chat/sessions/{session_id}", response_model=Transcript)
async def get_chat_transcript(
    session_id: uuid.UUID, request: Request, current: AdminUser, db: Session
) -> Transcript:
    session = (
        await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    ).scalar_one_or_none()
    if session is None:
        raise AppError("not_found", "Conversation not found.", 404)
    messages = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
    ).scalars()
    await _record(db, AuditAction.CHAT_REVIEW, request, current, "chat_session", session_id)
    await db.commit()
    return Transcript(
        id=session.id,
        created_at=session.created_at,
        ended_at=session.ended_at,
        provider_last=session.provider_last,
        masked=True,
        messages=[
            TranscriptMessage(
                id=m.id,
                role=m.role.value,
                content=mask_text(m.content),
                intent=m.intent,
                route=m.route.value if m.route else None,
                llm_calls=m.llm_calls,
                feedback=m.feedback,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


# --- settings ----------------------------------------------------------------------------------

KEYS = {
    "booking": {
        "min_notice_hours": "booking_min_notice_hours",
        "max_horizon_days": "booking_max_horizon_days",
        "same_day_enabled": "booking_same_day_enabled",
        "buffer_minutes": "booking_buffer_minutes",
        "slot_grid_minutes": "booking_slot_grid_minutes",
        "cancellation_free_hours": "cancellation_free_hours",
    },
    "reminders": {
        "hours_before": "reminder_hours_before",
        "followup_days": "reminder_followup_days",
        "recall_months": "reminder_recall_months",
    },
    "billing": {
        "tax_rate_percent": "billing_tax_rate_percent",
        "receptionist_max_discount_percent": "receptionist_max_discount_percent",
        "monthly_revenue_target": "revenue_target_monthly",
    },
    "retention": {
        "chat_retention_days": "chat_retention_days",
        "guest_anonymize_months": "guest_anonymize_months",
    },
}
DEFAULTS: dict[str, Any] = {
    "booking_min_notice_hours": 2,
    "booking_max_horizon_days": 90,
    "booking_same_day_enabled": True,
    "booking_buffer_minutes": 10,
    "booking_slot_grid_minutes": 15,
    "cancellation_free_hours": 24,
    "reminder_hours_before": [48, 24],
    "reminder_followup_days": 2,
    "reminder_recall_months": 6,
    "billing_tax_rate_percent": 0,
    "receptionist_max_discount_percent": 10,
    "revenue_target_monthly": 0,
    "chat_retention_days": 90,
    "guest_anonymize_months": 24,
}


async def _settings_out(db: Session, settings: AppSettings) -> SettingsOut:
    async def group(name: str) -> dict[str, Any]:
        return {
            field: await get_setting(db, key, DEFAULTS[key]) for field, key in KEYS[name].items()
        }

    return SettingsOut(
        clinic=ClinicInfo(
            name=settings.clinic_name,
            address=settings.clinic_address,
            phone=settings.clinic_phone,
            email=settings.clinic_email,
            timezone=settings.clinic_tz,
        ),
        booking=BookingSettings(**await group("booking")),
        reminders=ReminderSettings(**await group("reminders")),
        billing=BillingSettings(**await group("billing")),
        retention=RetentionSettings(**await group("retention")),
    )


@router.get("/settings", response_model=SettingsOut)
async def read_settings(_: AdminUser, db: Session, settings: AppSettings) -> SettingsOut:
    return await _settings_out(db, settings)


@router.put("/settings", response_model=SettingsOut)
async def update_settings(
    body: SettingsUpdate,
    request: Request,
    current: AdminUser,
    db: Session,
    settings: AppSettings,
    redis: RedisDep,
) -> SettingsOut:
    changed: list[str] = []
    for name in KEYS:
        section = getattr(body, name)
        if section is None:
            continue
        values = section.model_dump(mode="json")
        for field, key in KEYS[name].items():
            value = values[field]
            if name == "billing" and field != "monthly_revenue_target":
                value = float(value)
            statement = pg_insert(AppSetting).values(key=key, value=value, updated_by=current.id)
            await db.execute(
                statement.on_conflict_do_update(
                    index_elements=[AppSetting.key],
                    set_={
                        "value": statement.excluded.value,
                        "updated_by": current.id,
                        "updated_at": func.now(),
                    },
                )
            )
        changed.append(name)
    await _record(
        db, AuditAction.SETTINGS_CHANGE, request, current, "settings", None, {"sections": changed}
    )
    await db.commit()
    if "booking" in changed:
        await AvailabilityService(db, settings, redis).invalidate_cache()
    return await _settings_out(db, settings)


# --- audit log export ----------------------------------------------------------------------------

EXPORT_LIMIT = 50_000


def _safe_cell(value: object) -> str:
    """Stop a spreadsheet from running a cell as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/audit-logs/export.csv")
async def export_audit_logs(
    request: Request,
    current: AdminUser,
    db: Session,
    action: Annotated[str | None, Query(max_length=80)] = None,
    actor_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> StreamingResponse:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id).limit(EXPORT_LIMIT)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if since:
        stmt = stmt.where(AuditLog.created_at >= since)
    if until:
        stmt = stmt.where(AuditLog.created_at <= until)
    rows = (await db.execute(stmt)).scalars().all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["time", "actor_id", "role", "action", "entity", "entity_id", "ip", "details"])
    for r in rows:
        writer.writerow(
            [
                _safe_cell(r.created_at.isoformat()),
                _safe_cell(r.actor_id),
                _safe_cell(r.actor_role),
                _safe_cell(r.action),
                _safe_cell(r.entity),
                _safe_cell(r.entity_id),
                _safe_cell(r.ip),
                _safe_cell(r.metadata_ and str(r.metadata_)),
            ]
        )
    await _record(db, AuditAction.EXPORT, request, current, "audit_log", None, {"rows": len(rows)})
    await db.commit()
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'},
    )
