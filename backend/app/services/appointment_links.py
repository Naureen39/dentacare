"""One time confirm and cancel links carried by reminder emails.

The email holds a random 256 bit token. Only its SHA-256 hash is stored, the token stops
working when the appointment starts, and it can be used once. Opening the link in a browser
shows a summary; the change itself happens only when the page posts to the API, so mail
scanners that pre-fetch links cannot confirm or cancel anything.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import generate_token, hash_token
from app.db.enums import AppointmentAction, AppointmentStatus
from app.db.models import Appointment, AppointmentActionToken
from app.services.appointments import AppointmentService, bounds

ACTIVE = (AppointmentStatus.BOOKED, AppointmentStatus.CONFIRMED)


async def issue_links(
    db: AsyncSession,
    appointment: Appointment,
    reminder_id: uuid.UUID | None,
    actions: list[AppointmentAction],
) -> dict[AppointmentAction, str]:
    """Create fresh tokens. Earlier unused tokens of the same reminder stop working."""
    expires = bounds(appointment)[0]
    now = datetime.now(UTC)
    if reminder_id is not None:
        await db.execute(
            update(AppointmentActionToken)
            .where(
                AppointmentActionToken.reminder_id == reminder_id,
                AppointmentActionToken.used_at.is_(None),
                AppointmentActionToken.action.in_(actions),
            )
            .values(expires_at=now)
        )
    issued: dict[AppointmentAction, str] = {}
    for action in actions:
        raw = generate_token()
        db.add(
            AppointmentActionToken(
                appointment_id=appointment.id,
                reminder_id=reminder_id,
                action=action,
                token_hash=hash_token(raw),
                expires_at=expires,
            )
        )
        issued[action] = raw
    await db.flush()
    return issued


@dataclass(frozen=True)
class LinkPreview:
    action: AppointmentAction
    appointment: Appointment
    usable: bool
    reason: str | None


@dataclass(frozen=True)
class LinkResult:
    action: AppointmentAction
    appointment: Appointment
    outcome: str  # "confirmed", "already_confirmed" or "cancelled"
    late_cancel: bool


def invalid_link() -> AppError:
    return AppError("invalid_link", "This link is not valid.", 404)


class AppointmentLinkService:
    def __init__(self, db: AsyncSession, appointments: AppointmentService) -> None:
        self.db = db
        self.appointments = appointments

    async def _load(self, raw: str, *, lock: bool) -> tuple[AppointmentActionToken, Appointment]:
        stmt = select(AppointmentActionToken).where(
            AppointmentActionToken.token_hash == hash_token(raw)
        )
        if lock:
            stmt = stmt.with_for_update()
        token = (await self.db.execute(stmt)).scalar_one_or_none()
        if token is None:
            raise invalid_link()
        appointment = await self.appointments.get(token.appointment_id, lock=lock)
        return token, appointment

    @staticmethod
    def _problem(token: AppointmentActionToken, appointment: Appointment) -> AppError | None:
        if token.used_at is not None:
            return AppError("link_used", "This link has already been used.", 409)
        if token.expires_at <= datetime.now(UTC):
            return AppError("link_expired", "This link has expired.", 410)
        if appointment.status not in (*ACTIVE, AppointmentStatus.CHECKED_IN):
            return AppError(
                "appointment_not_active",
                "This appointment can no longer be changed with this link.",
                409,
            )
        return None

    async def preview(self, raw: str) -> LinkPreview:
        token, appointment = await self._load(raw, lock=False)
        problem = self._problem(token, appointment)
        return LinkPreview(
            token.action, appointment, problem is None, problem.message if problem else None
        )

    async def execute(self, raw: str) -> LinkResult:
        token, appointment = await self._load(raw, lock=True)
        problem = self._problem(token, appointment)
        if problem is not None:
            raise problem

        if token.action is AppointmentAction.CONFIRM:
            if appointment.status is AppointmentStatus.BOOKED:
                await self.appointments.confirm(appointment, None)
                outcome = "confirmed"
            else:
                outcome = "already_confirmed"
            late = False
        else:
            if appointment.status is AppointmentStatus.CHECKED_IN:
                raise AppError("appointment_not_active", "The visit has already started.", 409)
            await self.appointments.cancel(appointment, None, "Cancelled from email link")
            outcome = "cancelled"
            late = appointment.late_cancel

        token.used_at = datetime.now(UTC)
        await self.db.commit()
        return LinkResult(token.action, appointment, outcome, late)
