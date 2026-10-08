"""Sending reminder emails, one reminder row at a time.

``send`` is idempotent: it locks the reminder row, does nothing unless the row is still
pending, and commits the new status in the same transaction that records the outcome. A job
that runs twice, or is retried after a crash, never sends a second email for a reminder that
is already marked sent. Delivery is at least once: a crash between the mail server accepting
a message and the commit can cause one duplicate, which is the usual trade off for email.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.enums import (
    AppointmentAction,
    AppointmentStatus,
    ReminderKind,
    ReminderStatus,
)
from app.db.models import Appointment, Dentist, Patient, Reminder, Service
from app.services import audit
from app.services.app_settings import BookingRules
from app.services.appointment_links import issue_links
from app.services.appointments import bounds
from app.services.calendar_ics import build_ics
from app.services.email_templates import render_email
from app.services.mailer import Attachment, EmailContent, MailDeliveryError, Mailer

logger = structlog.get_logger(__name__)

MAX_TRIES = 5
BASE_BACKOFF_SECONDS = 30
MAX_BACKOFF_SECONDS = 3600
ACTIVE = (AppointmentStatus.BOOKED, AppointmentStatus.CONFIRMED)


def backoff_seconds(attempt: int) -> int:
    """Exponential backoff: 30 s, 1 min, 2 min, 4 min ... capped at one hour."""
    return int(min(BASE_BACKOFF_SECONDS * 2 ** (max(attempt, 1) - 1), MAX_BACKOFF_SECONDS))


@dataclass(frozen=True)
class SendOutcome:
    status: str  # "sent", "skipped", "cancelled", "retry", "failed"
    detail: str | None = None
    retry_in: int | None = None


def format_when(moment: datetime, tz: ZoneInfo) -> str:
    local = moment.astimezone(tz)
    hour = local.hour % 12 or 12
    suffix = "AM" if local.hour < 12 else "PM"
    return (
        f"{local:%A}, {local:%B} {local.day}, {local.year} at {hour}:{local.minute:02d} "
        f"{suffix} {local:%Z}"
    )


def format_date(moment: datetime, tz: ZoneInfo) -> str:
    local = moment.astimezone(tz)
    return f"{local:%B} {local.day}"


def format_day(moment: datetime, tz: ZoneInfo) -> str:
    local = moment.astimezone(tz)
    return f"{local:%B} {local.day}, {local.year}"


def relative_day(start: datetime, now: datetime, tz: ZoneInfo) -> str:
    days = (start.astimezone(tz).date() - now.astimezone(tz).date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days} days"


class NotificationService:
    def __init__(self, db: AsyncSession, settings: Settings, mailer: Mailer) -> None:
        self.db = db
        self.settings = settings
        self.mailer = mailer
        self.tz = ZoneInfo(settings.clinic_tz)

    async def send(
        self,
        reminder_id: uuid.UUID,
        *,
        job_try: int = 1,
        max_tries: int = MAX_TRIES,
        now: datetime | None = None,
    ) -> SendOutcome:
        current = now or datetime.now(UTC)
        reminder = (
            await self.db.execute(
                select(Reminder).where(Reminder.id == reminder_id).with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if reminder is None:
            return SendOutcome("skipped", "missing or being processed")
        if reminder.status is not ReminderStatus.PENDING:
            return SendOutcome("skipped", f"already {reminder.status.value}")

        appointment = (
            await self.db.execute(
                select(Appointment).where(Appointment.id == reminder.appointment_id)
            )
        ).scalar_one()
        patient = (
            await self.db.execute(select(Patient).where(Patient.id == appointment.patient_id))
        ).scalar_one()

        reason = await self._skip_reason(reminder.kind, appointment, patient, current)
        if reason is not None:
            reminder.status = ReminderStatus.CANCELLED
            reminder.error = reason
            await self.db.commit()
            logger.info("reminder_cancelled", reminder_id=str(reminder.id), reason=reason)
            return SendOutcome("cancelled", reason)

        content = await self._build(reminder, appointment, patient, current)
        reminder.attempts += 1
        reminder.last_attempt_at = current
        try:
            await self.mailer.deliver(content)
        except MailDeliveryError as exc:
            reminder.error = str(exc)[:400]
            if reminder.attempts >= max_tries or job_try >= max_tries:
                reminder.status = ReminderStatus.FAILED
                await audit.record(
                    self.db,
                    "job.dead_letter",
                    entity="reminder",
                    entity_id=reminder.id,
                    metadata={"kind": reminder.kind.value, "attempts": reminder.attempts},
                )
                await self.db.commit()
                logger.error(
                    "reminder_dead_letter",
                    reminder_id=str(reminder.id),
                    kind=reminder.kind.value,
                    attempts=reminder.attempts,
                    error=reminder.error,
                )
                return SendOutcome("failed", reminder.error)
            await self.db.commit()
            delay = backoff_seconds(reminder.attempts)
            logger.warning(
                "reminder_retry",
                reminder_id=str(reminder.id),
                attempt=reminder.attempts,
                retry_in=delay,
            )
            return SendOutcome("retry", reminder.error, delay)

        reminder.status = ReminderStatus.SENT
        reminder.sent_at = current
        reminder.error = None
        await self.db.commit()
        logger.info("reminder_sent", reminder_id=str(reminder.id), kind=reminder.kind.value)
        return SendOutcome("sent")

    # --- eligibility -----------------------------------------------------------------

    async def _skip_reason(
        self, kind: ReminderKind, appointment: Appointment, patient: Patient, now: datetime
    ) -> str | None:
        if patient.anonymized_at is not None or not patient.email:
            return "no email address on file"
        status = appointment.status
        start = bounds(appointment)[0]
        pre_visit = kind in (
            ReminderKind.CONFIRMATION,
            ReminderKind.HOURS_48,
            ReminderKind.HOURS_24,
        )
        if pre_visit:
            if status not in ACTIVE:
                return "appointment no longer active"
            if start <= now:
                return "appointment already started"
            if kind is ReminderKind.HOURS_48 and status is AppointmentStatus.CONFIRMED:
                return "already confirmed"
        elif status is not AppointmentStatus.COMPLETED:
            return "visit was not completed"
        elif kind is ReminderKind.RECALL and await self._has_upcoming_visit(patient.id, now):
            return "next visit already booked"  # do not nag someone who has booked
        return None

    # --- content ---------------------------------------------------------------------

    async def _has_upcoming_visit(self, patient_id: uuid.UUID, now: datetime) -> bool:
        rows = (
            await self.db.execute(
                select(Appointment).where(
                    Appointment.patient_id == patient_id, Appointment.status.in_(ACTIVE)
                )
            )
        ).scalars()
        return any(bounds(a)[0] > now for a in rows)

    async def _build(
        self, reminder: Reminder, appointment: Appointment, patient: Patient, now: datetime
    ) -> EmailContent:
        service = (
            await self.db.execute(select(Service).where(Service.id == appointment.service_id))
        ).scalar_one()
        dentist = (
            await self.db.execute(select(Dentist).where(Dentist.id == appointment.dentist_id))
        ).scalar_one()
        start, end = bounds(appointment)
        rules = await BookingRules.load(self.db)
        base = self.settings.public_base_url
        context: dict[str, Any] = {
            "first_name": patient.first_name,
            "service": service.name,
            "dentist": dentist.full_name,
            "when": format_when(start, self.tz),
            "manage_url": f"{base}/portal/appointments",
            "book_url": f"{base}/book",
        }

        free_until = start - timedelta(hours=rules.cancellation_free_hours)
        if free_until > now:
            context["cancel_policy"] = (
                f"You can cancel free of charge until {format_when(free_until, self.tz)}. "
                "After that, a late cancellation may be noted on your record."
            )
        else:
            context["cancel_policy"] = (
                "The free cancellation period has ended. Cancelling now will be noted as a "
                "late cancellation."
            )

        kind = reminder.kind
        if kind is ReminderKind.CONFIRMATION:
            links = await issue_links(self.db, appointment, reminder.id, [AppointmentAction.CANCEL])
            context["cancel_url"] = self._link("cancel", links[AppointmentAction.CANCEL])
            ics = build_ics(
                appointment_id=appointment.id,
                start=start,
                end=end,
                service_name=service.name,
                dentist_name=dentist.full_name,
                settings=self.settings,
            )
            attachment = Attachment(
                "appointment.ics",
                ics,
                "text",
                "calendar",
                {"method": "PUBLISH", "charset": "utf-8"},
            )
            return render_email(
                "confirmation",
                to=str(patient.email),
                settings=self.settings,
                attachments=(attachment,),
                short_date=format_date(start, self.tz),
                **context,
            )

        if kind in (ReminderKind.HOURS_48, ReminderKind.HOURS_24):
            wanted = [AppointmentAction.CANCEL]
            if appointment.status is AppointmentStatus.BOOKED:
                wanted.insert(0, AppointmentAction.CONFIRM)
            links = await issue_links(self.db, appointment, reminder.id, wanted)
            context["cancel_url"] = self._link("cancel", links[AppointmentAction.CANCEL])
            context["confirm_url"] = (
                self._link("confirm", links[AppointmentAction.CONFIRM])
                if AppointmentAction.CONFIRM in links
                else None
            )
            relative = relative_day(start, now, self.tz)
            context["headline"] = f"Your appointment is {relative}"
            context["subject_hint"] = (
                f"Reminder: your appointment {relative}, {format_date(start, self.tz)}"
            )
            return render_email(
                "reminder", to=str(patient.email), settings=self.settings, **context
            )

        if kind is ReminderKind.FOLLOWUP:
            context["when"] = format_day(start, self.tz)
            return render_email(
                "followup", to=str(patient.email), settings=self.settings, **context
            )

        context["when"] = format_day(start, self.tz)
        return render_email("recall", to=str(patient.email), settings=self.settings, **context)

    def _link(self, action: str, token: str) -> str:
        return f"{self.settings.public_base_url}/appointments/{action}?token={token}"
