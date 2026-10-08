from datetime import UTC, datetime, timedelta

from app.db.enums import AppointmentStatus, UserRole
from app.services.reminders import ReminderScheduler
from tests.booking.conftest import Practice, future_date, local_utc
from tests.notifications.helpers import appointment_in, book_via_api, reminders_of

PATIENT_CANCEL = "/api/v1/me/appointments/{}/cancel"


async def test_booking_schedules_a_confirmation_and_the_two_visit_reminders(
    practice: Practice,
) -> None:
    booked = await book_via_api(practice)
    start = datetime.fromisoformat(booked["start"])
    rows = await reminders_of(practice, booked["id"])

    assert set(rows) == {"confirmation", "48h", "24h"}
    assert all(r[1] == "pending" for r in rows.values())
    assert rows["48h"][2] == start - timedelta(hours=48)
    assert rows["24h"][2] == start - timedelta(hours=24)
    assert abs((rows["confirmation"][2] - datetime.now(UTC)).total_seconds()) < 60


async def test_booking_hands_the_confirmation_to_the_worker_immediately(practice: Practice) -> None:
    booked = await book_via_api(practice)
    rows = await reminders_of(practice, booked["id"])
    confirmation_id = rows["confirmation"][6]
    assert practice.ctx.jobs.jobs == [
        ("send_reminder", (str(confirmation_id),), f"reminder:{confirmation_id}")
    ]


async def test_reminders_in_the_past_are_not_scheduled(practice: Practice) -> None:
    async with practice.ctx.session_factory() as db:
        scheduler = ReminderScheduler(db)
        thirty_hours = await appointment_in(practice, 30)
        created = await scheduler.schedule_booking(thirty_hours)
        assert sorted(kind.value for _, kind in created) == ["24h", "confirmation"]
        ten_hours = await appointment_in(practice, 10, patient=None)
    async with practice.ctx.session_factory() as db:
        created = await ReminderScheduler(db).schedule_booking(ten_hours)
        await db.commit()
    assert sorted(kind.value for _, kind in created) == ["confirmation"]


async def test_scheduling_twice_creates_no_duplicates(practice: Practice) -> None:
    appointment = await appointment_in(practice, 100)
    async with practice.ctx.session_factory() as db:
        scheduler = ReminderScheduler(db)
        first = await scheduler.schedule_booking(appointment)
        second = await scheduler.schedule_booking(appointment)
        await db.commit()
    assert len(first) == 3 and second == []
    assert len(await reminders_of(practice, appointment.id)) == 3


async def test_reminder_timing_comes_from_settings(practice: Practice) -> None:
    await practice.ctx.execute(
        "UPDATE app_settings SET value = '[72, 12]'::jsonb WHERE key = 'reminder_hours_before'"
    )
    try:
        appointment = await appointment_in(practice, 200)
        async with practice.ctx.session_factory() as db:
            await ReminderScheduler(db).schedule_booking(appointment)
            await db.commit()
        rows = await reminders_of(practice, appointment.id)
        start = appointment.slot.lower
        assert rows["48h"][2] == start - timedelta(hours=72)
        assert rows["24h"][2] == start - timedelta(hours=12)
    finally:
        await practice.ctx.execute(
            "UPDATE app_settings SET value = '[48, 24]'::jsonb WHERE key = 'reminder_hours_before'"
        )


async def test_cancelling_stops_the_pending_reminders(practice: Practice) -> None:
    booked = await book_via_api(practice)
    headers = practice.ctx.auth(await practice.patient_token())
    response = await practice.ctx.client.post(PATIENT_CANCEL.format(booked["id"]), headers=headers)
    assert response.status_code == 200

    rows = await reminders_of(practice, booked["id"])
    assert {r[1] for r in rows.values()} == {"cancelled"}
    assert all(r[5] == "appointment no longer active" for r in rows.values())


async def test_staff_cancellation_also_stops_reminders(practice: Practice) -> None:
    booked = await book_via_api(practice)
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    await practice.ctx.client.patch(
        f"/api/v1/staff/appointments/{booked['id']}/status",
        headers=practice.ctx.auth(token),
        json={"status": "cancelled"},
    )
    rows = await reminders_of(practice, booked["id"])
    assert {r[1] for r in rows.values()} == {"cancelled"}


async def test_already_sent_reminders_are_left_alone_when_cancelling(practice: Practice) -> None:
    booked = await book_via_api(practice)
    await practice.ctx.execute(
        "UPDATE reminders SET status = 'sent', sent_at = now() WHERE kind = 'confirmation'"
    )
    headers = practice.ctx.auth(await practice.patient_token())
    await practice.ctx.client.post(PATIENT_CANCEL.format(booked["id"]), headers=headers)
    rows = await reminders_of(practice, booked["id"])
    assert rows["confirmation"][1] == "sent" and rows["48h"][1] == "cancelled"


async def test_rescheduling_cancels_old_reminders_and_schedules_new_ones(
    practice: Practice,
) -> None:
    booked = await book_via_api(practice, hour=10)
    new_start = local_utc(future_date(2, 12), 14, 0)
    hold = await practice.hold(practice.dentist_a, new_start)
    response = await practice.ctx.client.post(
        f"/api/v1/me/appointments/{booked['id']}/reschedule",
        headers=practice.ctx.auth(await practice.patient_token()),
        json={"start": new_start.isoformat(), "hold_token": hold},
    )
    assert response.status_code == 201
    old = await reminders_of(practice, booked["id"])
    new = await reminders_of(practice, response.json()["id"])
    assert {r[1] for r in old.values()} == {"cancelled"}
    assert set(new) == {"confirmation", "48h", "24h"} and {r[1] for r in new.values()} == {
        "pending"
    }


async def test_completing_a_visit_schedules_the_followup_and_the_recall(practice: Practice) -> None:
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    appointment = await appointment_in(practice, -3, AppointmentStatus.CHECKED_IN)
    before = datetime.now(UTC)
    response = await practice.ctx.client.patch(
        f"/api/v1/staff/appointments/{appointment.id}/status",
        headers=practice.ctx.auth(token),
        json={"status": "completed"},
    )
    assert response.status_code == 200
    rows = await reminders_of(practice, appointment.id)

    assert set(rows) == {"followup", "recall"}
    assert (
        timedelta(days=2) - timedelta(minutes=1)
        < rows["followup"][2] - before
        < timedelta(days=2, minutes=1)
    )
    recall_days = (rows["recall"][2] - before).total_seconds() / 86400
    assert 182.5 <= recall_days <= 183.1  # about six months (183 days)


async def test_followup_and_recall_timing_come_from_settings(practice: Practice) -> None:
    await practice.ctx.execute(
        "UPDATE app_settings SET value = '5'::jsonb WHERE key = 'reminder_followup_days'"
    )
    await practice.ctx.execute(
        "UPDATE app_settings SET value = '3'::jsonb WHERE key = 'reminder_recall_months'"
    )
    try:
        appointment = await appointment_in(practice, -3, AppointmentStatus.CHECKED_IN)
        token = await practice.staff_token(UserRole.RECEPTIONIST)
        await practice.ctx.client.patch(
            f"/api/v1/staff/appointments/{appointment.id}/status",
            headers=practice.ctx.auth(token),
            json={"status": "completed"},
        )
        rows = await reminders_of(practice, appointment.id)
        now = datetime.now(UTC)
        assert 4.9 < (rows["followup"][2] - now).total_seconds() / 86400 < 5.1
        assert 90.9 < (rows["recall"][2] - now).total_seconds() / 86400 < 91.1
    finally:
        await practice.ctx.execute(
            "UPDATE app_settings SET value = '2'::jsonb WHERE key = 'reminder_followup_days'"
        )
        await practice.ctx.execute(
            "UPDATE app_settings SET value = '6'::jsonb WHERE key = 'reminder_recall_months'"
        )


async def test_due_selection_returns_only_pending_reminders_whose_time_has_come(
    practice: Practice,
) -> None:
    appointment = await appointment_in(practice, 100)
    async with practice.ctx.session_factory() as db:
        await ReminderScheduler(db).schedule_booking(appointment)
        await db.commit()
    async with practice.ctx.session_factory() as db:
        scheduler = ReminderScheduler(db)
        assert len(await scheduler.due()) == 1  # only the confirmation is due now
        assert len(await scheduler.due(now=datetime.now(UTC) + timedelta(days=3))) == 2
        assert len(await scheduler.due(now=datetime.now(UTC) + timedelta(days=5))) == 3
