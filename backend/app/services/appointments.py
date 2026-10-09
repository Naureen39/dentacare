"""Booking, rescheduling, cancellation and the appointment state machine."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import CurrentUser
from app.core.errors import AppError
from app.db.enums import AppointmentChannel, AppointmentStatus, ReminderKind, UserRole
from app.db.models import Appointment, AppointmentStatusHistory, Dentist, Patient, Service
from app.schemas.booking import AppointmentOut, SlotOut, StaffAppointmentOut
from app.services import audit, holds
from app.services.app_settings import BookingRules
from app.services.audit import AuditAction
from app.services.availability import AvailabilityService, Slot
from app.services.billing import BillingService
from app.services.queue import JobQueue
from app.services.reminders import ReminderScheduler

S = AppointmentStatus
EXCLUSION_VIOLATION = "23P01"

# booked -> confirmed -> checked_in -> completed; booked or confirmed -> cancelled;
# booked or confirmed -> no_show once the start time has passed.
TRANSITIONS: dict[AppointmentStatus, frozenset[AppointmentStatus]] = {
    S.BOOKED: frozenset({S.CONFIRMED, S.CANCELLED, S.NO_SHOW}),
    S.CONFIRMED: frozenset({S.CHECKED_IN, S.CANCELLED, S.NO_SHOW}),
    S.CHECKED_IN: frozenset({S.COMPLETED}),
    S.COMPLETED: frozenset(),
    S.CANCELLED: frozenset(),
    S.NO_SHOW: frozenset(),
}
CANCELLABLE = frozenset({S.BOOKED, S.CONFIRMED})
DENTIST_ALLOWED_TARGETS = frozenset({S.COMPLETED, S.NO_SHOW})


def slot_out(slot: Slot) -> SlotOut:
    return SlotOut(
        start=slot.start, end=slot.end, dentist_id=slot.dentist_id, dentist_name=slot.dentist_name
    )


def bounds(appointment: Appointment) -> tuple[datetime, datetime]:
    """Start and end of the slot. The database check constraint guarantees both exist."""
    slot = appointment.slot
    if slot.lower is None or slot.upper is None:
        raise AppError("internal_error", "The appointment has no time range.", 500)
    return slot.lower, slot.upper


def not_found() -> AppError:
    return AppError("not_found", "Appointment not found.", 404)


class AppointmentService:
    def __init__(
        self,
        *,
        db: AsyncSession,
        settings: Settings,
        redis: Redis,
        request: Request | None = None,
        jobs: JobQueue | None = None,
    ) -> None:
        self.jobs = jobs
        self.db = db
        self.settings = settings
        self.redis = redis
        self.request = request
        self.availability = AvailabilityService(db, settings, redis)

    # --- loading and presentation ---------------------------------------------------

    async def get(self, appointment_id: uuid.UUID, *, lock: bool = False) -> Appointment:
        stmt = select(Appointment).where(Appointment.id == appointment_id)
        if lock:
            stmt = stmt.with_for_update()
        appointment = (await self.db.execute(stmt)).scalar_one_or_none()
        if appointment is None:
            raise not_found()
        return appointment

    async def present(
        self, appointments: list[Appointment], *, with_patient: bool = False
    ) -> list[AppointmentOut] | list[StaffAppointmentOut]:
        if not appointments:
            return []
        rules = await BookingRules.load(self.db)
        services = {
            s.id: s
            for s in (
                await self.db.execute(
                    select(Service).where(Service.id.in_({a.service_id for a in appointments}))
                )
            ).scalars()
        }
        dentists = {
            d.id: d
            for d in (
                await self.db.execute(
                    select(Dentist).where(Dentist.id.in_({a.dentist_id for a in appointments}))
                )
            ).scalars()
        }
        patients: dict[uuid.UUID, Patient] = {}
        if with_patient:
            patients = {
                p.id: p
                for p in (
                    await self.db.execute(
                        select(Patient).where(Patient.id.in_({a.patient_id for a in appointments}))
                    )
                ).scalars()
            }
        out: list[AppointmentOut] | list[StaffAppointmentOut] = []
        for a in appointments:
            base = {
                "id": a.id,
                "status": a.status,
                "channel": a.channel,
                "start": bounds(a)[0],
                "end": bounds(a)[1],
                "service_id": a.service_id,
                "service_name": services[a.service_id].name,
                "dentist_id": a.dentist_id,
                "dentist_name": dentists[a.dentist_id].full_name,
                "reason_note": a.reason_note,
                "late_cancel": a.late_cancel,
                "free_cancellation_until": bounds(a)[0]
                - timedelta(hours=rules.cancellation_free_hours),
                "rescheduled_from": a.rescheduled_from,
                "created_at": a.created_at,
            }
            if with_patient:
                patient = patients[a.patient_id]
                out.append(
                    StaffAppointmentOut(
                        **base,
                        patient_id=patient.id,
                        patient_name=f"{patient.first_name} {patient.last_name}",
                    )
                )
            else:
                out.append(AppointmentOut(**base))  # type: ignore[arg-type]
        return out

    # --- bookkeeping ----------------------------------------------------------------

    async def _record_history(
        self,
        appointment: Appointment,
        from_status: AppointmentStatus | None,
        actor: CurrentUser | None,
    ) -> None:
        self.db.add(
            AppointmentStatusHistory(
                appointment_id=appointment.id,
                from_status=from_status,
                to_status=appointment.status,
                changed_by=actor.id if actor else None,
            )
        )

    async def _audit(
        self,
        action: str,
        appointment: Appointment,
        actor: CurrentUser | None,
        metadata: dict[str, object],
    ) -> None:
        await audit.record(
            self.db,
            action,
            request=self.request,
            actor_id=actor.id if actor else None,
            actor_role=actor.role.value if actor else "guest",
            entity="appointment",
            entity_id=appointment.id,
            metadata=metadata,
        )

    async def conflict(
        self, service: Service, start: datetime, message: str, code: str = "slot_unavailable"
    ) -> AppError:
        nearby = await self.availability.alternatives(service.id, start)
        return AppError(
            code,
            message,
            409,
            {"alternatives": [slot_out(s).model_dump(mode="json") for s in nearby]},
        )

    # --- booking --------------------------------------------------------------------

    async def book(
        self,
        *,
        patient: Patient,
        service: Service,
        dentist_id: uuid.UUID,
        start: datetime,
        channel: AppointmentChannel,
        actor: CurrentUser | None,
        reason_note: str | None,
        hold_token: str | None,
        require_hold: bool,
        enforce_rules: bool,
        rescheduled_from: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> Appointment:
        start = start.astimezone(UTC)
        if require_hold and not (
            hold_token and await holds.is_valid(self.redis, dentist_id, start, hold_token)
        ):
            raise await self.conflict(
                service,
                start,
                "Your reservation for this time has expired. Please choose a time again.",
                "hold_expired",
            )
        if not await self.availability.is_available(
            service.id, dentist_id, start, enforce_rules=enforce_rules, now=now
        ):
            raise await self.conflict(service, start, "This time is no longer available.")

        appointment = Appointment(
            patient_id=patient.id,
            dentist_id=dentist_id,
            service_id=service.id,
            slot=Range(start, start + timedelta(minutes=service.duration_min), bounds="[)"),
            status=AppointmentStatus.BOOKED,
            channel=channel,
            reason_note=reason_note,
            created_by=actor.id if actor else None,
            rescheduled_from=rescheduled_from,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(appointment)
                await self.db.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) != EXCLUSION_VIOLATION:
                raise
            if "patient_no_overlap" in str(exc.orig):
                raise AppError(
                    "patient_double_booked",
                    "You already have an appointment that overlaps this time.",
                    409,
                ) from exc
            raise await self.conflict(
                service, start, "This time was just taken. Please choose another."
            ) from exc

        await self._record_history(appointment, None, actor)
        await self._audit(
            AuditAction.APPOINTMENT_CREATE,
            appointment,
            actor,
            {"channel": channel.value, "service": service.code},
        )
        scheduled = await ReminderScheduler(self.db).schedule_booking(appointment)
        await self.db.commit()
        await holds.release(self.redis, dentist_id, start)
        await self.availability.invalidate_cache()
        await self._enqueue_now(scheduled, ReminderKind.CONFIRMATION)
        return appointment

    async def _enqueue_now(
        self, scheduled: list[tuple[uuid.UUID, ReminderKind]], kind: ReminderKind
    ) -> None:
        """Hand a just created reminder to the worker without waiting for the sweep."""
        if self.jobs is None:
            return
        for reminder_id, reminder_kind in scheduled:
            if reminder_kind is kind:
                await self.jobs.enqueue(
                    "send_reminder", str(reminder_id), job_id=f"reminder:{reminder_id}"
                )

    # --- patient actions ------------------------------------------------------------

    def _late(self, appointment: Appointment, rules: BookingRules, now: datetime) -> bool:
        return bounds(appointment)[0] - now < timedelta(hours=rules.cancellation_free_hours)

    async def cancel(
        self, appointment: Appointment, actor: CurrentUser | None, reason: str | None
    ) -> Appointment:
        """Cancel on the patient's behalf, from the portal or an email link.

        Free until the policy window, then flagged as late.
        """
        now = datetime.now(UTC)
        self._require_future_and_cancellable(appointment, now)
        rules = await BookingRules.load(self.db)
        previous = appointment.status
        appointment.status = AppointmentStatus.CANCELLED
        appointment.cancel_reason = reason or "Cancelled by patient"
        appointment.late_cancel = self._late(appointment, rules, now)
        await self._record_history(appointment, previous, actor)
        await self._audit(
            AuditAction.APPOINTMENT_STATUS,
            appointment,
            actor,
            {"from": previous.value, "to": "cancelled", "late": appointment.late_cancel},
        )
        await ReminderScheduler(self.db).cancel_pending(appointment.id)
        await self.db.commit()
        await self.availability.invalidate_cache()
        return appointment

    async def reschedule_own(
        self,
        appointment: Appointment,
        patient: Patient,
        actor: CurrentUser | None,
        *,
        start: datetime,
        dentist_id: uuid.UUID | None,
        hold_token: str,
    ) -> Appointment:
        now = datetime.now(UTC)
        self._require_future_and_cancellable(appointment, now)
        rules = await BookingRules.load(self.db)
        service = (
            await self.db.execute(select(Service).where(Service.id == appointment.service_id))
        ).scalar_one()

        previous = appointment.status
        appointment.status = AppointmentStatus.CANCELLED
        appointment.cancel_reason = "Rescheduled by patient"
        appointment.late_cancel = self._late(appointment, rules, now)
        await self._record_history(appointment, previous, actor)
        await self._audit(
            AuditAction.APPOINTMENT_RESCHEDULE,
            appointment,
            actor,
            {"from": previous.value, "late": appointment.late_cancel},
        )
        await ReminderScheduler(self.db).cancel_pending(appointment.id)
        await self.db.flush()  # frees the old slot for the new booking inside this transaction

        new = await self.book(
            patient=patient,
            service=service,
            dentist_id=dentist_id or appointment.dentist_id,
            start=start,
            channel=appointment.channel,
            actor=actor,
            reason_note=appointment.reason_note,
            hold_token=hold_token,
            require_hold=True,
            enforce_rules=True,
            rescheduled_from=appointment.id,
        )
        return new

    async def reschedule_staff(
        self,
        appointment: Appointment,
        actor: CurrentUser,
        *,
        start: datetime,
        dentist_id: uuid.UUID | None,
    ) -> Appointment:
        """Move a visit for the patient, from the schedule. Booking rules are not applied.

        The old visit is cancelled without a late flag (the clinic chose the move) and the new one
        is booked in the same transaction, so a clash leaves the original untouched.
        """
        now = datetime.now(UTC)
        self._require_future_and_cancellable(appointment, now)
        patient = (
            await self.db.execute(select(Patient).where(Patient.id == appointment.patient_id))
        ).scalar_one()
        service = (
            await self.db.execute(select(Service).where(Service.id == appointment.service_id))
        ).scalar_one()
        previous = appointment.status
        appointment.status = AppointmentStatus.CANCELLED
        appointment.cancel_reason = "Rescheduled by staff"
        await self._record_history(appointment, previous, actor)
        await self._audit(
            AuditAction.APPOINTMENT_RESCHEDULE,
            appointment,
            actor,
            {"from": previous.value, "by": "staff"},
        )
        await ReminderScheduler(self.db).cancel_pending(appointment.id)
        await self.db.flush()
        return await self.book(
            patient=patient,
            service=service,
            dentist_id=dentist_id or appointment.dentist_id,
            start=start,
            channel=appointment.channel,
            actor=actor,
            reason_note=appointment.reason_note,
            hold_token=None,
            require_hold=False,
            enforce_rules=False,
            rescheduled_from=appointment.id,
        )

    def _require_future_and_cancellable(self, appointment: Appointment, now: datetime) -> None:
        if appointment.status not in CANCELLABLE:
            raise AppError(
                "invalid_transition",
                f"An appointment with status '{appointment.status.value}' cannot be changed.",
                422,
            )
        if bounds(appointment)[0] <= now:
            raise AppError(
                "invalid_transition", "This appointment has already started or passed.", 422
            )

    async def confirm(self, appointment: Appointment, actor: CurrentUser | None) -> Appointment:
        """Booked to confirmed. Used by the reminder email link and by staff."""
        previous = appointment.status
        if AppointmentStatus.CONFIRMED not in TRANSITIONS[previous]:
            raise AppError(
                "invalid_transition",
                f"An appointment cannot move from '{previous.value}' to 'confirmed'.",
                422,
            )
        appointment.status = AppointmentStatus.CONFIRMED
        await self._record_history(appointment, previous, actor)
        await self._audit(
            AuditAction.APPOINTMENT_STATUS,
            appointment,
            actor,
            {"from": previous.value, "to": "confirmed"},
        )
        await self.db.flush()
        return appointment

    # --- staff actions --------------------------------------------------------------

    async def change_status(
        self,
        appointment: Appointment,
        target: AppointmentStatus,
        actor: CurrentUser,
        reason: str | None,
    ) -> Appointment:
        if actor.role is UserRole.DENTIST and target not in DENTIST_ALLOWED_TARGETS:
            raise AppError(
                "forbidden", "Dentists can only mark visits completed or as no shows.", 403
            )
        previous = appointment.status
        if target not in TRANSITIONS[previous]:
            raise AppError(
                "invalid_transition",
                f"An appointment cannot move from '{previous.value}' to '{target.value}'.",
                422,
            )
        if target is AppointmentStatus.NO_SHOW and bounds(appointment)[0] > datetime.now(UTC):
            raise AppError(
                "invalid_transition",
                "An appointment can be marked as a no show only after its start time.",
                422,
            )
        appointment.status = target
        if target is AppointmentStatus.CANCELLED:
            appointment.cancel_reason = reason or "Cancelled by staff"
        await self._record_history(appointment, previous, actor)
        await self._audit(
            AuditAction.APPOINTMENT_STATUS,
            appointment,
            actor,
            {"from": previous.value, "to": target.value},
        )
        if target is AppointmentStatus.COMPLETED:
            # A completed visit always gets a draft invoice built from the service price.
            await BillingService(self.db, self.settings, self.request).create_for_appointment(
                appointment, actor
            )
            await ReminderScheduler(self.db).schedule_completion(appointment)
        elif target in (AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW):
            await ReminderScheduler(self.db).cancel_pending(appointment.id)
        await self.db.commit()
        if target in (AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW):
            await self.availability.invalidate_cache()
        return appointment
