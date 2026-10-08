"""Background tasks run by the ARQ worker.

Every task takes the worker context as its first argument. The context holds the session
factory, settings, mailer and the ARQ Redis pool; tests pass their own.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from arq import Retry
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.enums import AppointmentStatus
from app.db.models import Appointment
from app.services.notifications import MAX_TRIES, NotificationService
from app.services.reminders import ReminderScheduler
from app.services.retention import run_retention

logger = structlog.get_logger(__name__)

MATERIALIZED_VIEW_NAME = re.compile(r"^mv_[a-z0-9_]+$")
SCORING_HORIZON_DAYS = 7


async def ping(ctx: dict[str, Any]) -> str:
    """Smoke test task confirming the worker can consume jobs."""
    logger.info("worker_ping")
    return "pong"


async def send_reminder(ctx: dict[str, Any], reminder_id: str) -> str:
    """Send one reminder. Safe to run any number of times for the same reminder id."""
    settings: Settings = ctx["settings"]
    async with ctx["session_factory"]() as db:
        outcome = await NotificationService(db, settings, ctx["mailer"]).send(
            uuid.UUID(reminder_id), job_try=int(ctx.get("job_try", 1)), max_tries=MAX_TRIES
        )
    if outcome.status == "retry":
        raise Retry(defer=outcome.retry_in or 30)
    return outcome.status


async def dispatch_due_reminders(ctx: dict[str, Any]) -> int:
    """Every minute: queue a send job for each pending reminder whose time has come.

    The job id is derived from the reminder id, so a reminder that is already queued, running
    or waiting for a retry is not queued twice.
    """
    async with ctx["session_factory"]() as db:
        due = await ReminderScheduler(db).due()
    queued = 0
    for reminder_id in due:
        job = await ctx["redis"].enqueue_job(
            "send_reminder", str(reminder_id), _job_id=f"reminder:{reminder_id}"
        )
        if job is not None:
            queued += 1
    if due:
        logger.info("reminders_dispatched", due=len(due), queued=queued)
    return queued


async def refresh_analytics(ctx: dict[str, Any]) -> dict[str, int]:
    """Nightly: refresh every materialized view whose name starts with ``mv_``.

    The analytics phase creates those views. Until then there is nothing to refresh. Views with
    a unique index are refreshed concurrently so dashboards keep working during the refresh.
    """
    engine: AsyncEngine = ctx["engine"]
    refreshed = failed = 0
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        names = (
            (
                await connection.execute(
                    text(
                        "SELECT matviewname FROM pg_matviews "
                        "WHERE schemaname = 'public' AND matviewname LIKE 'mv\\_%' ORDER BY matviewname"
                    )
                )
            )
            .scalars()
            .all()
        )
        for name in names:
            if not MATERIALIZED_VIEW_NAME.fullmatch(name):
                continue
            try:
                try:
                    await connection.execute(
                        text(f'REFRESH MATERIALIZED VIEW CONCURRENTLY "{name}"')  # noqa: S608
                    )
                except Exception:  # noqa: BLE001  (no unique index, or never populated)
                    await connection.execute(text(f'REFRESH MATERIALIZED VIEW "{name}"'))
                refreshed += 1
            except Exception:  # noqa: BLE001
                failed += 1
                logger.error("materialized_view_refresh_failed", view=name)
    logger.info("analytics_refreshed", refreshed=refreshed, failed=failed)
    return {"refreshed": refreshed, "failed": failed}


async def score_no_show_risk(ctx: dict[str, Any]) -> dict[str, object]:
    """Nightly: score appointments in the next seven days for no show risk.

    The model is trained and registered in the analytics phase. Until a model exists this job
    only reports how many appointments are waiting to be scored.
    """
    now = datetime.now(UTC)
    async with ctx["session_factory"]() as db:
        waiting = (
            await db.execute(
                select(func.count())
                .select_from(Appointment)
                .where(
                    Appointment.status.in_([AppointmentStatus.BOOKED, AppointmentStatus.CONFIRMED]),
                    Appointment.slot.overlaps(
                        Range(now, now + timedelta(days=SCORING_HORIZON_DAYS), bounds="[)")
                    ),
                )
            )
        ).scalar_one()
        model = (await db.execute(text("SELECT to_regclass('public.model_registry')"))).scalar_one()
    if model is None:
        logger.info("no_show_scoring_skipped", reason="no model registered", waiting=waiting)
        return {"scored": 0, "waiting": waiting, "skipped": "no model registered"}
    logger.info("no_show_scoring_skipped", reason="scoring arrives with the analytics phase")
    return {"scored": 0, "waiting": waiting, "skipped": "scoring not available yet"}


async def retention_purge(ctx: dict[str, Any]) -> dict[str, int]:
    """Nightly data retention: purge old chat messages and anonymize stale guest records."""
    settings: Settings = ctx["settings"]
    async with ctx["session_factory"]() as session:
        result = await run_retention(
            session, settings.chat_retention_days, settings.guest_anonymize_months
        )
    logger.info("retention_purge_completed", **result)
    return result
