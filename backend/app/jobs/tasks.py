"""Background tasks run by the ARQ worker.

Every task takes the worker context as its first argument. The context holds the session
factory, settings, mailer and the ARQ Redis pool; tests pass their own.
"""

import uuid
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from arq import Retry

from app.analytics.noshow import model as noshow
from app.analytics.refresh import refresh_views
from app.core.config import Settings
from app.core.crypto import FieldCipher
from app.services.notifications import MAX_TRIES, NotificationService
from app.services.reminders import ReminderScheduler
from app.services.retention import run_retention

logger = structlog.get_logger(__name__)


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
    """Nightly: refresh the analytics materialized views, concurrently where possible."""
    result = await refresh_views(ctx["engine"])
    redis = ctx.get("redis")
    if redis is not None:
        await redis.incr("analytics:version")  # stored responses were built from the old figures
    return result


async def score_no_show_risk(ctx: dict[str, Any]) -> dict[str, object]:
    """Nightly: score appointments in the next seven days for no show risk."""
    settings: Settings = ctx["settings"]
    cipher = FieldCipher.from_settings(
        settings.field_encryption_key, settings.field_encryption_old_keys, settings.jwt_secret
    )
    async with ctx["session_factory"]() as db:
        result = await noshow.score_upcoming(
            db, cipher, Path(settings.model_dir), ZoneInfo(settings.clinic_tz)
        )
    logger.info("no_show_scoring_done", **result)
    return result


async def retention_purge(ctx: dict[str, Any]) -> dict[str, int]:
    """Nightly data retention: purge old chat messages and anonymize stale guest records."""
    settings: Settings = ctx["settings"]
    async with ctx["session_factory"]() as session:
        result = await run_retention(
            session, settings.chat_retention_days, settings.guest_anonymize_months
        )
    logger.info("retention_purge_completed", **result)
    return result
