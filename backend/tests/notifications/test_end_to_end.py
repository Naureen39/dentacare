"""Phase 6 exit criterion: a booking produces a confirmation email, the reminder arrives, and
the confirm link in it works. The worker functions run in process with an in memory mailer;
the same flow is exercised against Mailpit and a live worker by the manual runbook check."""

import re
from datetime import UTC, datetime

from app.jobs.tasks import dispatch_due_reminders, send_reminder
from tests.auth.conftest import unique_email
from tests.booking.conftest import Practice, future_date, local_utc
from tests.notifications.helpers import book_via_api, links_in, reminders_of, worker_ctx

ACTIONS = "/api/v1/public/appointment-actions"


async def run_queued_jobs(practice: Practice, ctx: dict) -> int:  # type: ignore[type-arg]
    """Play the worker: execute every send job the dispatcher queued, then clear the queue."""
    ran = 0
    for function, args, job_id in list(ctx["redis"].queued):
        assert function == "send_reminder"
        await send_reminder(ctx, *args)
        ctx["redis"].finish(job_id)
        ran += 1
    ctx["redis"].queued.clear()
    return ran


async def test_booking_confirmation_reminder_and_confirm_link_end_to_end(
    practice: Practice,
) -> None:
    ctx = worker_ctx(practice)
    outbox = practice.ctx.mailer.outbox

    # 1. The patient books. The API hands the confirmation to the worker straight away.
    booked = await book_via_api(practice)
    assert [job[0] for job in practice.ctx.jobs.jobs] == ["send_reminder"]

    # 2. The worker's minute sweep finds the due confirmation and sends it.
    assert await dispatch_due_reminders(ctx) == 1
    assert await run_queued_jobs(practice, ctx) == 1
    [confirmation] = outbox
    assert confirmation.subject.startswith("Appointment booked: Routine Exam and Cleaning")
    assert confirmation.attachments and confirmation.attachments[0].filename == "appointment.ics"
    assert booked["status"] == "booked"

    # 3. Two days before the visit the first reminder falls due.
    await practice.ctx.execute(
        "UPDATE reminders SET scheduled_at = now() - interval '1 minute' WHERE kind = '48h'"
    )
    assert await dispatch_due_reminders(ctx) == 1
    assert await run_queued_jobs(practice, ctx) == 1
    reminder = outbox[-1]
    assert reminder.subject.startswith("Reminder: your appointment")
    links = links_in(reminder)
    assert set(links) == {"confirm", "cancel"}

    # 4. The patient opens the confirm link: a preview first, then the page posts to the API.
    preview = await practice.ctx.client.get(f"{ACTIONS}/{links['confirm']}")
    assert preview.status_code == 200 and preview.json()["usable"] is True
    assert (
        await practice.ctx.client.get(
            "/api/v1/me/appointments", headers=practice.ctx.auth(await practice.patient_token())
        )
    ).json()[0]["status"] == "booked"

    result = await practice.ctx.client.post(f"{ACTIONS}/{links['confirm']}")
    assert result.status_code == 200 and result.json()["outcome"] == "confirmed"
    mine = await practice.ctx.client.get(
        "/api/v1/me/appointments", headers=practice.ctx.auth(await practice.patient_token())
    )
    assert mine.json()[0]["status"] == "confirmed"

    # 5. Later sweeps do not repeat anything that already happened.
    assert await dispatch_due_reminders(ctx) == 0
    assert len(outbox) == 2

    # 6. The patient's notification history shows what was sent.
    notifications = await practice.ctx.client.get(
        "/api/v1/me/notifications", headers=practice.ctx.auth(await practice.patient_token())
    )
    assert [n["kind"] for n in notifications.json()] == ["48h", "confirmation"]
    assert notifications.json()[0]["title"] == "Appointment reminder"

    rows = await reminders_of(practice, booked["id"])
    assert rows["confirmation"][1] == rows["48h"][1] == "sent"
    # The 24 hour reminder is still pending and, because the visit is confirmed, will only offer cancel.
    assert rows["24h"][1] == "pending"


async def test_guest_booking_gets_the_same_confirmation_and_working_cancel_link(
    practice: Practice,
) -> None:
    ctx = worker_ctx(practice)
    email = unique_email("guest")
    start = local_utc(future_date(2, 14), 11, 0)

    request = await practice.ctx.client.post(
        "/api/v1/public/appointments/verification", json={"email": email, "first_name": "Jonas"}
    )
    code = re.search(r"code is (\d{6})", practice.ctx.mailer.outbox[-1].body)
    assert code
    hold = await practice.hold(practice.dentist_a, start)
    booked = await practice.ctx.client.post(
        "/api/v1/public/appointments",
        json={
            "verification_id": request.json()["verification_id"],
            "otp": code.group(1),
            "hold_token": hold,
            "service_id": str(practice.cleaning.id),
            "dentist_id": str(practice.dentist_a.id),
            "start": start.isoformat(),
            "first_name": "Jonas",
            "last_name": "Weber",
            "email": email,
            "consent": True,
        },
    )
    assert booked.status_code == 201

    await dispatch_due_reminders(ctx)
    await run_queued_jobs(practice, ctx)
    message = next(
        m for m in practice.ctx.mailer.outbox if m.subject.startswith("Appointment booked")
    )
    assert message.to == email
    cancel = links_in(message)["cancel"]

    result = await practice.ctx.client.post(f"{ACTIONS}/{cancel}")
    assert result.status_code == 200 and result.json()["outcome"] == "cancelled"
    rows = await practice.ctx.fetch(
        "SELECT status::text FROM appointments WHERE id = :i", i=booked.json()["id"]
    )
    assert rows == [("cancelled",)]
    _ = datetime.now(UTC)


async def test_cancelled_booking_never_sends_its_pending_reminders(practice: Practice) -> None:
    ctx = worker_ctx(practice)
    booked = await book_via_api(practice)
    await dispatch_due_reminders(ctx)
    await run_queued_jobs(practice, ctx)
    sent_before = len(practice.ctx.mailer.outbox)

    await practice.ctx.client.post(
        f"/api/v1/me/appointments/{booked['id']}/cancel",
        headers=practice.ctx.auth(await practice.patient_token()),
    )
    await practice.ctx.execute("UPDATE reminders SET scheduled_at = now() - interval '1 hour'")
    assert await dispatch_due_reminders(ctx) == 0
    assert len(practice.ctx.mailer.outbox) == sent_before
