"""Creating and cancelling reminder rows.

A reminder is one row per appointment and kind. Rows are created with
``ON CONFLICT DO NOTHING`` so scheduling can safely run twice. The worker sends them.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import AppointmentStatus, ReminderChannel, ReminderKind, ReminderStatus
from app.db.models import Appointment, Reminder
from app.services.app_settings import get_setting

PRE_VISIT_KINDS = (ReminderKind.CONFIRMATION, ReminderKind.HOURS_48, ReminderKind.HOURS_24)
DEFAULT_HOURS_BEFORE = (48, 24)
DAYS_PER_MONTH = 30.4375


class ReminderScheduler:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _add(
        self, appointment_id: uuid.UUID, kind: ReminderKind, scheduled_at: datetime
    ) -> uuid.UUID | None:
        statement = (
            insert(Reminder)
            .values(
                appointment_id=appointment_id,
                kind=kind,
                channel=ReminderChannel.EMAIL,
                scheduled_at=scheduled_at,
                status=ReminderStatus.PENDING,
            )
            .on_conflict_do_nothing(constraint="uq_reminders_appointment_kind")
            .returning(Reminder.id)
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def schedule_booking(
        self, appointment: Appointment, now: datetime | None = None
    ) -> list[tuple[uuid.UUID, ReminderKind]]:
        """Confirmation now, plus the visit reminders that still lie in the future."""
        current = now or datetime.now(UTC)
        start = appointment.slot.lower
        if start is None:
            return []
        hours = await get_setting(self.db, "reminder_hours_before", list(DEFAULT_HOURS_BEFORE))
        first_hours, second_hours = (list(hours) + list(DEFAULT_HOURS_BEFORE))[:2]

        created: list[tuple[uuid.UUID, ReminderKind]] = []
        plan = [
            (ReminderKind.CONFIRMATION, current),
            (ReminderKind.HOURS_48, start - timedelta(hours=int(first_hours))),
            (ReminderKind.HOURS_24, start - timedelta(hours=int(second_hours))),
        ]
        for kind, when in plan:
            if kind is not ReminderKind.CONFIRMATION and when <= current:
                continue  # that moment has already passed
            reminder_id = await self._add(appointment.id, kind, when)
            if reminder_id is not None:
                created.append((reminder_id, kind))
        return created

    async def schedule_completion(
        self, appointment: Appointment, completed_at: datetime | None = None
    ) -> list[tuple[uuid.UUID, ReminderKind]]:
        """Follow up two days after the visit and a recall about six months after it."""
        moment = completed_at or datetime.now(UTC)
        followup_days = int(await get_setting(self.db, "reminder_followup_days", 2))
        recall_months = int(await get_setting(self.db, "reminder_recall_months", 6))
        created: list[tuple[uuid.UUID, ReminderKind]] = []
        for kind, when in (
            (ReminderKind.FOLLOWUP, moment + timedelta(days=followup_days)),
            (ReminderKind.RECALL, moment + timedelta(days=round(recall_months * DAYS_PER_MONTH))),
        ):
            reminder_id = await self._add(appointment.id, kind, when)
            if reminder_id is not None:
                created.append((reminder_id, kind))
        return created

    async def cancel_pending(self, appointment_id: uuid.UUID) -> int:
        """Stop any visit reminders that have not gone out yet."""
        result = await self.db.execute(
            update(Reminder)
            .where(
                Reminder.appointment_id == appointment_id,
                Reminder.status == ReminderStatus.PENDING,
                Reminder.kind.in_(PRE_VISIT_KINDS),
            )
            .values(status=ReminderStatus.CANCELLED, error="appointment no longer active")
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def due(self, now: datetime | None = None, limit: int = 100) -> list[uuid.UUID]:
        current = now or datetime.now(UTC)
        rows = await self.db.execute(
            select(Reminder.id)
            .where(Reminder.status == ReminderStatus.PENDING, Reminder.scheduled_at <= current)
            .order_by(Reminder.scheduled_at)
            .limit(limit)
        )
        return list(rows.scalars().all())


INACTIVE_STATUSES = (AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW)
