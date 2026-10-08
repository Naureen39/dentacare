from typing import Any

import structlog
from arq import cron, func
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import create_engine, create_session_factory
from app.jobs.tasks import (
    dispatch_due_reminders,
    ping,
    refresh_analytics,
    retention_purge,
    score_no_show_risk,
    send_reminder,
)
from app.services.mailer import SmtpMailer
from app.services.notifications import MAX_TRIES

logger = structlog.get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    ctx["settings"] = settings
    ctx["engine"] = create_engine(settings)
    ctx["session_factory"] = create_session_factory(ctx["engine"])
    ctx["mailer"] = SmtpMailer(settings)
    logger.info("worker_started")


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()
    logger.info("worker_stopped")


class WorkerSettings:
    functions = [
        ping,
        # keep_result=0 releases the job id as soon as the job ends, so a reminder that is
        # still pending can be queued again by the next sweep. The job id is the reminder id,
        # which is what makes sending idempotent.
        func(send_reminder, name="send_reminder", max_tries=MAX_TRIES, keep_result=0, timeout=60),
        dispatch_due_reminders,
        refresh_analytics,
        score_no_show_risk,
        retention_purge,
    ]
    cron_jobs = [
        cron(dispatch_due_reminders, name="dispatch_due_reminders", run_at_startup=True),
        cron(refresh_analytics, name="refresh_analytics", hour=3, minute=0),
        cron(score_no_show_risk, name="score_no_show_risk", hour=3, minute=15),
        cron(retention_purge, name="retention_purge", hour=3, minute=30),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = MAX_TRIES
