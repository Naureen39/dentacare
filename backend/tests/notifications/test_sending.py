import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from arq import Retry

from app.db.enums import AppointmentStatus, UserRole
from app.services.notifications import (
    NotificationService,
    backoff_seconds,
    format_when,
    relative_day,
)
from tests.auth.conftest import unique_email
from tests.booking.conftest import Practice
from tests.notifications.helpers import (
    appointment_in,
    book_via_api,
    events,
    links_in,
    reminder_id,
    reminders_of,
    send,
    worker_ctx,
)

NY = ZoneInfo("America/New_York")


async def schedule(practice: Practice, appointment) -> None:  # type: ignore[no-untyped-def]
    from app.services.reminders import ReminderScheduler

    async with practice.ctx.session_factory() as db:
        await ReminderScheduler(db).schedule_booking(appointment)
        await db.commit()


# --- the confirmation email -------------------------------------------------------------------


async def test_confirmation_email_has_details_calendar_file_and_cancel_link(
    practice: Practice,
) -> None:
    booked = await book_via_api(practice)
    rid = await reminder_id(practice, booked["id"], "confirmation")

    assert await send(practice, rid) == "sent"

    [message] = practice.ctx.mailer.outbox
    assert message.to == practice.patient.email
    assert message.subject.startswith("Appointment booked: Routine Exam and Cleaning on ")
    assert "Dr. Priya Raman" in message.body and "Amelia" in message.body
    assert message.html and "<strong>Routine Exam and Cleaning</strong>" in message.html
    [attachment] = message.attachments
    assert attachment.filename == "appointment.ics" and attachment.subtype == "calendar"
    [event] = events(attachment.content)
    assert event["dtstart"].dt == datetime.fromisoformat(booked["start"])
    assert set(links_in(message)) == {"cancel"}  # nothing to confirm yet


async def test_sending_marks_the_reminder_sent_exactly_once(practice: Practice) -> None:
    booked = await book_via_api(practice)
    rid = await reminder_id(practice, booked["id"], "confirmation")

    assert await send(practice, rid) == "sent"
    assert await send(practice, rid) == "skipped"
    assert await send(practice, rid) == "skipped"

    assert len(practice.ctx.mailer.outbox) == 1
    row = (await reminders_of(practice, booked["id"]))["confirmation"]
    assert row[1] == "sent" and row[3] is not None and row[4] == 1 and row[5] is None


async def test_concurrent_attempts_on_one_reminder_send_a_single_email(practice: Practice) -> None:
    booked = await book_via_api(practice)
    rid = await reminder_id(practice, booked["id"], "confirmation")
    results = await asyncio.gather(*(send(practice, rid) for _ in range(8)))
    assert results.count("sent") == 1
    assert len(practice.ctx.mailer.outbox) == 1


async def test_unknown_reminder_ids_are_skipped(practice: Practice) -> None:
    assert await send(practice, uuid.uuid4()) == "skipped"


async def test_action_tokens_are_stored_only_as_hashes(practice: Practice) -> None:
    booked = await book_via_api(practice)
    await send(practice, await reminder_id(practice, booked["id"], "confirmation"))
    token = links_in(practice.ctx.mailer.outbox[0])["cancel"]
    rows = await practice.ctx.fetch(
        "SELECT token_hash, action::text, used_at FROM appointment_action_tokens"
    )
    assert len(rows) == 1 and rows[0][0] != token and len(rows[0][0]) == 64
    assert rows[0][1:] == ("cancel", None)


# --- visit reminders ---------------------------------------------------------------------------


async def test_first_reminder_offers_confirm_and_cancel(practice: Practice) -> None:
    appointment = await appointment_in(practice, 50)
    await schedule(practice, appointment)
    rid = await reminder_id(practice, appointment.id, "48h")
    await practice.ctx.execute("UPDATE reminders SET scheduled_at = now() WHERE id = :i", i=rid)

    assert await send(practice, rid) == "sent"
    message = practice.ctx.mailer.outbox[0]
    assert set(links_in(message)) == {"confirm", "cancel"}
    assert message.subject.startswith("Reminder: your appointment in 2 days, ")
    assert "Confirm appointment" in (message.html or "")
    assert message.attachments == ()


async def test_first_reminder_is_skipped_once_the_appointment_is_confirmed(
    practice: Practice,
) -> None:
    appointment = await appointment_in(practice, 50, AppointmentStatus.CONFIRMED)
    await schedule(practice, appointment)
    rid = await reminder_id(practice, appointment.id, "48h")
    assert await send(practice, rid) == "cancelled"
    assert practice.ctx.mailer.outbox == []
    assert (await reminders_of(practice, appointment.id))["48h"][5] == "already confirmed"


async def test_second_reminder_for_a_confirmed_appointment_only_offers_cancel(
    practice: Practice,
) -> None:
    appointment = await appointment_in(practice, 26, AppointmentStatus.CONFIRMED)
    await schedule(practice, appointment)
    rid = await reminder_id(practice, appointment.id, "24h")
    assert await send(practice, rid) == "sent"
    message = practice.ctx.mailer.outbox[0]
    assert set(links_in(message)) == {"cancel"}
    assert "Your appointment is confirmed" in message.body


@pytest.mark.parametrize("status", [AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW])
async def test_nothing_is_sent_for_an_inactive_appointment(
    practice: Practice, status: AppointmentStatus
) -> None:
    appointment = await appointment_in(practice, 100)
    await schedule(practice, appointment)
    await practice.ctx.execute(
        "UPDATE appointments SET status = :s WHERE id = :i", s=status.value, i=appointment.id
    )
    rid = await reminder_id(practice, appointment.id, "confirmation")
    assert await send(practice, rid) == "cancelled"
    assert practice.ctx.mailer.outbox == []


async def test_nothing_is_sent_once_the_appointment_has_started(practice: Practice) -> None:
    appointment = await appointment_in(practice, -1)
    await schedule(practice, appointment)
    rid = await reminder_id(practice, appointment.id, "confirmation")
    assert await send(practice, rid) == "cancelled"
    assert (await reminders_of(practice, appointment.id))["confirmation"][
        5
    ] == "appointment already started"


async def test_patients_without_an_email_address_are_skipped(practice: Practice) -> None:
    appointment = await appointment_in(practice, 100)
    await schedule(practice, appointment)
    await practice.ctx.execute(
        "UPDATE patients SET email = NULL WHERE id = :p", p=practice.patient.id
    )
    assert (
        await send(practice, await reminder_id(practice, appointment.id, "confirmation"))
        == "cancelled"
    )
    assert practice.ctx.mailer.outbox == []


async def test_anonymized_patients_are_never_emailed(practice: Practice) -> None:
    appointment = await appointment_in(practice, 100)
    await schedule(practice, appointment)
    await practice.ctx.execute(
        "UPDATE patients SET anonymized_at = now() WHERE id = :p", p=practice.patient.id
    )
    assert (
        await send(practice, await reminder_id(practice, appointment.id, "confirmation"))
        == "cancelled"
    )


# --- follow up and recall --------------------------------------------------------------------


async def completed_with_reminders(practice: Practice) -> uuid.UUID:
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    appointment = await appointment_in(practice, -3, AppointmentStatus.CHECKED_IN)
    await practice.ctx.client.patch(
        f"/api/v1/staff/appointments/{appointment.id}/status",
        headers=practice.ctx.auth(token),
        json={"status": "completed"},
    )
    return appointment.id  # type: ignore[no-any-return]


async def test_followup_thanks_the_patient_after_a_completed_visit(practice: Practice) -> None:
    appointment_id = await completed_with_reminders(practice)
    assert await send(practice, await reminder_id(practice, appointment_id, "followup")) == "sent"
    message = practice.ctx.mailer.outbox[0]
    assert message.subject == "Thank you for visiting Meridian Dental Care"
    assert "Routine Exam and Cleaning" in message.body and links_in(message) == {}


async def test_recall_invites_the_patient_back_when_no_visit_is_booked(practice: Practice) -> None:
    appointment_id = await completed_with_reminders(practice)
    assert await send(practice, await reminder_id(practice, appointment_id, "recall")) == "sent"
    message = practice.ctx.mailer.outbox[0]
    assert message.subject == "Time for your next check-up at Meridian Dental Care"
    assert "/book" in message.body


async def test_recall_is_dropped_when_the_next_visit_is_already_booked(practice: Practice) -> None:
    appointment_id = await completed_with_reminders(practice)
    await appointment_in(practice, 24 * 20)
    rid = await reminder_id(practice, appointment_id, "recall")
    assert await send(practice, rid) == "cancelled"
    assert practice.ctx.mailer.outbox == []
    assert (await reminders_of(practice, appointment_id))["recall"][
        5
    ] == "next visit already booked"


async def test_followup_is_dropped_if_the_visit_is_no_longer_completed(practice: Practice) -> None:
    appointment_id = await completed_with_reminders(practice)
    await practice.ctx.execute(
        "UPDATE appointments SET status = 'cancelled' WHERE id = :i", i=appointment_id
    )
    assert (
        await send(practice, await reminder_id(practice, appointment_id, "followup")) == "cancelled"
    )


# --- failures, retries and the dead letter --------------------------------------------------------


async def test_delivery_failure_asks_for_a_retry_with_exponential_backoff(
    practice: Practice,
) -> None:
    booked = await book_via_api(practice)
    rid = await reminder_id(practice, booked["id"], "confirmation")
    practice.ctx.mailer.failures = 4

    delays = []
    for attempt in range(1, 5):
        with pytest.raises(Retry) as raised:
            await send(practice, rid, job_try=attempt)
        assert raised.value.defer_score is not None
        delays.append(raised.value.defer_score / 1000)
        row = (await reminders_of(practice, booked["id"]))["confirmation"]
        assert (
            row[1] == "pending" and row[4] == attempt and "simulated mail server outage" in row[5]
        )

    assert delays == [30, 60, 120, 240]
    assert await send(practice, rid, job_try=5) == "sent"  # the server recovered
    final = (await reminders_of(practice, booked["id"]))["confirmation"]
    assert final[1] == "sent" and final[4] == 5 and final[5] is None


async def test_exhausted_retries_become_a_dead_letter(practice: Practice) -> None:
    booked = await book_via_api(practice)
    rid = await reminder_id(practice, booked["id"], "confirmation")
    practice.ctx.mailer.failures = 99

    for attempt in range(1, 5):
        with pytest.raises(Retry):
            await send(practice, rid, job_try=attempt)
    assert await send(practice, rid, job_try=5) == "failed"

    row = (await reminders_of(practice, booked["id"]))["confirmation"]
    assert row[1] == "failed" and row[4] == 5
    audit = await practice.ctx.fetch(
        "SELECT entity, entity_id, metadata::text FROM audit_logs WHERE action = 'job.dead_letter'"
    )
    assert audit and audit[0][0] == "reminder" and audit[0][1] == str(rid)
    # A failed reminder is never retried by later sweeps or duplicate jobs.
    practice.ctx.mailer.failures = 0
    assert await send(practice, rid) == "skipped"
    assert practice.ctx.mailer.outbox == []


async def test_failed_reminders_are_listed_for_administrators(practice: Practice) -> None:
    booked = await book_via_api(practice)
    rid = await reminder_id(practice, booked["id"], "confirmation")
    practice.ctx.mailer.failures = 99
    for attempt in range(1, 5):
        with pytest.raises(Retry):
            await send(practice, rid, job_try=attempt)
    await send(practice, rid, job_try=5)

    email = unique_email("admin")
    await practice.ctx.create_user(email, UserRole.ADMIN)
    headers = practice.ctx.auth(await practice.ctx.access_token(email))
    failed = await practice.ctx.client.get(
        "/api/v1/admin/reminders", params={"status": "failed"}, headers=headers
    )
    assert [r["id"] for r in failed.json()] == [str(rid)]
    assert failed.json()[0]["attempts"] == 5 and "outage" in failed.json()[0]["error"]
    everything = await practice.ctx.client.get("/api/v1/admin/reminders", headers=headers)
    assert len(everything.json()) == 3

    patient_headers = practice.ctx.auth(await practice.patient_token())
    assert (
        await practice.ctx.client.get("/api/v1/admin/reminders", headers=patient_headers)
    ).status_code == 403


async def test_a_direct_service_call_reports_the_retry_without_arq(practice: Practice) -> None:
    booked = await book_via_api(practice)
    rid = await reminder_id(practice, booked["id"], "confirmation")
    practice.ctx.mailer.failures = 1
    async with practice.ctx.session_factory() as db:
        outcome = await NotificationService(db, practice.ctx.settings, practice.ctx.mailer).send(
            rid
        )
    assert (outcome.status, outcome.retry_in) == ("retry", 30)


# --- helpers ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(0, 30), (1, 30), (2, 60), (3, 120), (4, 240), (7, 1920), (8, 3600), (20, 3600)],
)
def test_backoff_doubles_and_is_capped_at_one_hour(attempt: int, expected: int) -> None:
    assert backoff_seconds(attempt) == expected


def test_times_are_written_in_the_clinic_time_zone() -> None:
    summer = datetime(2027, 5, 5, 14, 0, tzinfo=UTC)
    winter = datetime(2027, 12, 8, 14, 0, tzinfo=UTC)
    assert format_when(summer, NY) == "Wednesday, May 5, 2027 at 10:00 AM EDT"
    assert format_when(winter, NY) == "Wednesday, December 8, 2027 at 9:00 AM EST"
    assert format_when(datetime(2027, 5, 5, 16, 5, tzinfo=UTC), NY).endswith("12:05 PM EDT")


def test_relative_day_wording_uses_clinic_calendar_days() -> None:
    now = datetime(2027, 5, 4, 3, 30, tzinfo=UTC)  # still May 3 evening in New York
    assert relative_day(datetime(2027, 5, 4, 16, 0, tzinfo=UTC), now, NY) == "tomorrow"
    assert relative_day(datetime(2027, 5, 5, 16, 0, tzinfo=UTC), now, NY) == "in 2 days"
    assert relative_day(datetime(2027, 5, 3, 22, 0, tzinfo=UTC), now, NY) == "today"


async def test_cancellation_policy_sentence_reflects_the_window(practice: Practice) -> None:
    near = await appointment_in(practice, 10)
    await schedule(practice, near)
    await send(practice, await reminder_id(practice, near.id, "confirmation"))
    assert "free cancellation period has ended" in practice.ctx.mailer.outbox[0].body

    practice.ctx.mailer.outbox.clear()
    other_user = await practice.ctx.create_user(unique_email("later"))
    async with practice.ctx.session_factory() as db:
        from sqlalchemy import select

        from app.db.models import Patient

        other = (
            await db.execute(select(Patient).where(Patient.user_id == other_user.id))
        ).scalar_one()
    far = await appointment_in(practice, 96, patient=other)
    await schedule(practice, far)
    await send(practice, await reminder_id(practice, far.id, "confirmation"))
    assert "cancel free of charge until" in practice.ctx.mailer.outbox[0].body


def _unused() -> None:
    _ = (timedelta, worker_ctx)
