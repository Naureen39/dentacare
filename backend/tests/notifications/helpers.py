"""Helpers for notification, reminder and worker tests."""

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db.enums import AppointmentStatus
from app.jobs.tasks import send_reminder
from app.services.mailer import SentMessage
from tests.booking.conftest import Practice, future_date, local_utc

LINK = re.compile(r"/appointments/(confirm|cancel)\?token=([\w-]+)")


@dataclass
class FakeArqRedis:
    """Stands in for ArqRedis: remembers queued jobs and refuses duplicate job ids."""

    queued: list[tuple[str, tuple[Any, ...], str | None]] = field(default_factory=list)
    _ids: set[str] = field(default_factory=set)
    counters: dict[str, int] = field(default_factory=dict)

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def enqueue_job(
        self, function: str, *args: Any, _job_id: str | None = None
    ) -> object | None:
        if _job_id is not None:
            if _job_id in self._ids:
                return None
            self._ids.add(_job_id)
        self.queued.append((function, args, _job_id))
        return object()

    def finish(self, job_id: str) -> None:
        self._ids.discard(job_id)


def worker_ctx(practice: Practice, **extra: Any) -> dict[str, Any]:
    ctx = practice.ctx
    return {
        "session_factory": ctx.session_factory,
        "settings": ctx.settings,
        "mailer": ctx.mailer,
        "engine": ctx.app.state.engine,
        "redis": FakeArqRedis(),
        "job_try": 1,
        **extra,
    }


def links_in(message: SentMessage) -> dict[str, str]:
    """Action links found in the plain text body, keyed by action name."""
    return {action: token for action, token in LINK.findall(message.body)}


async def reminders_of(practice: Practice, appointment_id: uuid.UUID) -> dict[str, tuple[Any, ...]]:
    rows = await practice.ctx.fetch(
        "SELECT kind::text, status::text, scheduled_at, sent_at, attempts, error, id "
        "FROM reminders WHERE appointment_id = :a",
        a=appointment_id,
    )
    return {row[0]: row for row in rows}


async def reminder_id(practice: Practice, appointment_id: uuid.UUID, kind: str) -> uuid.UUID:
    rows = await practice.ctx.fetch(
        "SELECT id FROM reminders WHERE appointment_id = :a AND kind::text = :k",
        a=appointment_id,
        k=kind,
    )
    assert rows, f"no {kind} reminder"
    return rows[0][0]  # type: ignore[no-any-return]


async def send(practice: Practice, reminder: uuid.UUID, **extra: Any) -> str:
    """Run the real send_reminder task for one reminder."""
    return await send_reminder(worker_ctx(practice, **extra), str(reminder))


async def book_via_api(practice: Practice, hour: int = 10, days_ahead: int = 10) -> dict[str, Any]:
    """A patient books through the public API, as the booking wizard would."""
    token = await practice.patient_token()
    start = local_utc(future_date(2, days_ahead), hour, 0)
    hold = await practice.hold(practice.dentist_a, start)
    response = await practice.ctx.client.post(
        "/api/v1/me/appointments",
        headers=practice.ctx.auth(token),
        json={
            "service_id": str(practice.cleaning.id),
            "dentist_id": str(practice.dentist_a.id),
            "start": start.isoformat(),
            "hold_token": hold,
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def appointment_in(
    practice: Practice,
    hours: float,
    status: AppointmentStatus = AppointmentStatus.BOOKED,
    **kw: Any,
) -> Any:
    """An appointment starting ``hours`` from now, inserted directly."""
    start = (datetime.now(UTC) + timedelta(hours=hours)).replace(second=0, microsecond=0)
    return await practice.book_direct(practice.dentist_a, start, status=status, **kw)


def calendar_of(content: bytes) -> Any:
    from icalendar import Calendar

    return Calendar.from_ical(content)


def events(content: bytes) -> list[Any]:
    """The VEVENT components of an iCalendar file."""
    return [c for c in calendar_of(content).walk() if c.name == "VEVENT"]
