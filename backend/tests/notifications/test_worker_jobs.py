import pytest
from arq import Retry

from app.jobs.tasks import (
    dispatch_due_reminders,
    ping,
    refresh_analytics,
    retention_purge,
    score_no_show_risk,
    send_reminder,
)
from app.jobs.worker import WorkerSettings
from app.services.reminders import ReminderScheduler
from tests.booking.conftest import Practice
from tests.notifications.helpers import appointment_in, reminder_id, worker_ctx


async def schedule(practice: Practice, appointment) -> None:  # type: ignore[no-untyped-def]
    async with practice.ctx.session_factory() as db:
        await ReminderScheduler(db).schedule_booking(appointment)
        await db.commit()


# --- the dispatcher --------------------------------------------------------------------------


async def test_dispatcher_queues_only_reminders_that_are_due(practice: Practice) -> None:
    appointment = await appointment_in(practice, 100)
    await schedule(practice, appointment)  # confirmation due now, 48h and 24h later
    ctx = worker_ctx(practice)

    assert await dispatch_due_reminders(ctx) == 1
    [(function, args, job_id)] = ctx["redis"].queued
    confirmation = await reminder_id(practice, appointment.id, "confirmation")
    assert (function, args, job_id) == (
        "send_reminder",
        (str(confirmation),),
        f"reminder:{confirmation}",
    )


async def test_dispatcher_never_queues_the_same_reminder_twice(practice: Practice) -> None:
    appointment = await appointment_in(practice, 100)
    await schedule(practice, appointment)
    ctx = worker_ctx(practice)

    assert await dispatch_due_reminders(ctx) == 1
    assert await dispatch_due_reminders(ctx) == 0  # still queued, deduplicated by job id
    assert len(ctx["redis"].queued) == 1

    ctx["redis"].finish(
        ctx["redis"].queued[0][2]
    )  # the job ended without sending (for example a crash)
    assert await dispatch_due_reminders(ctx) == 1


async def test_dispatcher_ignores_sent_cancelled_and_future_reminders(practice: Practice) -> None:
    appointment = await appointment_in(practice, 100)
    await schedule(practice, appointment)
    await practice.ctx.execute("UPDATE reminders SET status = 'sent' WHERE kind = 'confirmation'")
    ctx = worker_ctx(practice)
    assert await dispatch_due_reminders(ctx) == 0

    await practice.ctx.execute(
        "UPDATE reminders SET scheduled_at = now() - interval '1 minute', status = 'cancelled' WHERE kind = '48h'"
    )
    assert await dispatch_due_reminders(ctx) == 0


async def test_dispatcher_picks_up_reminders_when_their_time_arrives(practice: Practice) -> None:
    appointment = await appointment_in(practice, 100)
    await schedule(practice, appointment)
    await practice.ctx.execute("UPDATE reminders SET status = 'sent' WHERE kind = 'confirmation'")
    ctx = worker_ctx(practice)
    assert await dispatch_due_reminders(ctx) == 0

    await practice.ctx.execute(
        "UPDATE reminders SET scheduled_at = now() - interval '1 second' WHERE kind = '48h'"
    )
    assert await dispatch_due_reminders(ctx) == 1


# --- the send task ---------------------------------------------------------------------------


async def test_send_task_returns_the_outcome_and_sends_through_the_mailer(
    practice: Practice,
) -> None:
    appointment = await appointment_in(practice, 100)
    await schedule(practice, appointment)
    rid = str(await reminder_id(practice, appointment.id, "confirmation"))
    ctx = worker_ctx(practice)
    assert await send_reminder(ctx, rid) == "sent"
    assert await send_reminder(ctx, rid) == "skipped"
    assert len(practice.ctx.mailer.outbox) == 1


async def test_send_task_requests_an_arq_retry_when_delivery_fails(practice: Practice) -> None:
    appointment = await appointment_in(practice, 100)
    await schedule(practice, appointment)
    rid = str(await reminder_id(practice, appointment.id, "confirmation"))
    practice.ctx.mailer.failures = 1
    with pytest.raises(Retry) as raised:
        await send_reminder(worker_ctx(practice), rid)
    assert raised.value.defer_score == 30_000  # milliseconds


# --- nightly jobs ------------------------------------------------------------------------------


async def test_analytics_refresh_updates_every_analytics_view(practice: Practice) -> None:
    ctx = practice.ctx
    assert await refresh_analytics(worker_ctx(practice)) == {"refreshed": 10, "failed": 0}
    before = await ctx.fetch("SELECT count(*) FROM mv_cohort_retention")
    assert before == [(0,)]
    await ctx.execute("DELETE FROM app_settings WHERE key = 'analytics_refreshed_at'")
    await refresh_analytics(worker_ctx(practice))
    stamp = await ctx.fetch(
        "SELECT value #>> '{}' FROM app_settings WHERE key = 'analytics_refreshed_at'"
    )
    assert stamp and stamp[0][0]  # dashboards use it to show how fresh the data is


async def test_analytics_refresh_falls_back_when_a_view_cannot_refresh_concurrently(
    practice: Practice,
) -> None:
    ctx = practice.ctx
    await ctx.execute("DROP INDEX uq_mv_ar_aging")  # concurrent refresh needs a unique index
    try:
        assert await refresh_analytics(worker_ctx(practice)) == {"refreshed": 10, "failed": 0}
    finally:
        await ctx.execute("CREATE UNIQUE INDEX uq_mv_ar_aging ON mv_ar_aging (invoice_id)")


async def test_analytics_refresh_counts_views_that_fail(practice: Practice) -> None:
    ctx = practice.ctx
    await ctx.execute(
        "CREATE OR REPLACE FUNCTION clinic_date(moment timestamptz) RETURNS date "
        "LANGUAGE plpgsql IMMUTABLE AS $$ BEGIN RAISE EXCEPTION 'simulated failure'; END $$"
    )
    try:
        result = await refresh_analytics(worker_ctx(practice))
        assert result["failed"] >= 1 and result["refreshed"] + result["failed"] == 10
    finally:
        await ctx.execute(
            "CREATE OR REPLACE FUNCTION clinic_date(moment timestamptz) RETURNS date "
            "LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT (moment AT TIME ZONE 'America/New_York')::date $$"
        )


async def test_no_show_scoring_waits_until_a_model_exists(practice: Practice) -> None:
    await appointment_in(practice, 30)
    result = await score_no_show_risk(worker_ctx(practice))
    assert result == {"scored": 0, "skipped": "no model registered"}


async def test_retention_task_uses_the_settings_in_the_context(practice: Practice) -> None:
    result = await retention_purge(worker_ctx(practice))
    assert result == {"chat_messages_purged": 0, "guests_anonymized": 0}


async def test_ping_task() -> None:
    assert await ping({}) == "pong"


# --- worker configuration -------------------------------------------------------------------------


def test_worker_registers_every_job_and_cron_entry() -> None:
    names = {getattr(f, "name", getattr(f, "__name__", "")) for f in WorkerSettings.functions}
    assert {
        "ping",
        "send_reminder",
        "dispatch_due_reminders",
        "refresh_analytics",
        "score_no_show_risk",
        "retention_purge",
    } <= names
    cron = {job.name: job for job in WorkerSettings.cron_jobs}
    assert set(cron) == {
        "dispatch_due_reminders",
        "refresh_analytics",
        "score_no_show_risk",
        "retention_purge",
    }
    assert cron["dispatch_due_reminders"].run_at_startup is True
    assert cron["dispatch_due_reminders"].minute is None  # every minute
    assert (cron["refresh_analytics"].hour, cron["refresh_analytics"].minute) == (3, 0)
    assert (cron["retention_purge"].hour, cron["retention_purge"].minute) == (3, 30)


def test_send_reminder_retries_five_times_and_releases_its_job_id() -> None:
    send_job = next(
        f for f in WorkerSettings.functions if getattr(f, "name", "") == "send_reminder"
    )
    assert (
        getattr(send_job, "max_tries", None) == 5 and getattr(send_job, "keep_result_s", None) == 0
    )
    assert WorkerSettings.max_tries == 5
