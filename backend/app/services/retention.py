"""Data retention: purge old chat messages and anonymize stale cancelled guest records."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import AppointmentStatus
from app.db.models import Appointment, ChatMessage, ChatSession, Patient
from app.services.app_settings import get_setting

ANONYMIZED_FIRST_NAME = "Anonymized"
ANONYMIZED_LAST_NAME = "Guest"


async def purge_chat_messages(
    session: AsyncSession, retention_days: int, now: datetime | None = None
) -> int:
    """Delete chat messages older than the retention period, then empty ended sessions."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    result = await session.execute(delete(ChatMessage).where(ChatMessage.created_at < cutoff))
    await session.execute(
        delete(ChatSession).where(
            ChatSession.created_at < cutoff,
            ~select(ChatMessage.id).where(ChatMessage.session_id == ChatSession.id).exists(),
        )
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def anonymize_cancelled_guests(
    session: AsyncSession, months: int, now: datetime | None = None
) -> int:
    """Strip personal data from guest patients whose appointments were all cancelled.

    A guest is a patient without a user account. Records are kept for statistics but can no
    longer identify the person.
    """
    reference = now or datetime.now(UTC)
    cutoff = reference - timedelta(days=30 * months)

    last_slot = func.max(func.upper(Appointment.slot))
    non_cancelled = func.count().filter(Appointment.status != AppointmentStatus.CANCELLED)
    candidates = (
        select(Appointment.patient_id)
        .group_by(Appointment.patient_id)
        .having(non_cancelled == 0, last_slot < cutoff)
    )
    result = await session.execute(
        update(Patient)
        .where(
            Patient.user_id.is_(None),
            Patient.anonymized_at.is_(None),
            Patient.id.in_(candidates),
        )
        .values(
            first_name=ANONYMIZED_FIRST_NAME,
            last_name=ANONYMIZED_LAST_NAME,
            email=None,
            dob_enc=None,
            phone_enc=None,
            address_enc=None,
            insurance_member_id_enc=None,
            marketing_consent=False,
            anonymized_at=reference,
        )
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def run_retention(
    session: AsyncSession, defaults_days: int = 90, defaults_months: int = 12
) -> dict[str, int]:
    days = int(await get_setting(session, "chat_retention_days", defaults_days))
    months = int(await get_setting(session, "guest_anonymize_months", defaults_months))
    purged = await purge_chat_messages(session, days)
    anonymized = await anonymize_cancelled_guests(session, months)
    await session.commit()
    return {"chat_messages_purged": purged, "guests_anonymized": anonymized}
