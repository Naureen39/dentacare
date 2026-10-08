from app.db.enums import UserRole
from tests.auth.conftest import unique_email
from tests.booking.conftest import Practice
from tests.notifications.helpers import appointment_in, reminder_id, send

URL = "/api/v1/me/notifications"


async def test_history_lists_only_sent_messages_of_the_signed_in_patient(
    practice: Practice,
) -> None:
    from app.services.reminders import ReminderScheduler

    mine = await appointment_in(practice, 100)
    stranger_email = unique_email("stranger")
    stranger_user = await practice.ctx.create_user(stranger_email)
    async with practice.ctx.session_factory() as db:
        from sqlalchemy import select

        from app.db.models import Patient

        other = (
            await db.execute(select(Patient).where(Patient.user_id == stranger_user.id))
        ).scalar_one()
    theirs = await appointment_in(practice, 120, patient=other)
    async with practice.ctx.session_factory() as db:
        scheduler = ReminderScheduler(db)
        await scheduler.schedule_booking(mine)
        await scheduler.schedule_booking(theirs)
        await db.commit()

    await send(practice, await reminder_id(practice, mine.id, "confirmation"))
    await send(practice, await reminder_id(practice, theirs.id, "confirmation"))

    headers = practice.ctx.auth(await practice.patient_token())
    body = (await practice.ctx.client.get(URL, headers=headers)).json()
    assert [(n["kind"], n["appointment_id"]) for n in body] == [("confirmation", str(mine.id))]
    assert body[0]["title"] == "Appointment booked"


async def test_pending_failed_and_cancelled_reminders_are_not_shown(practice: Practice) -> None:
    from app.services.reminders import ReminderScheduler

    appointment = await appointment_in(practice, 100)
    async with practice.ctx.session_factory() as db:
        await ReminderScheduler(db).schedule_booking(appointment)
        await db.commit()
    await practice.ctx.execute("UPDATE reminders SET status = 'failed' WHERE kind = 'confirmation'")
    await practice.ctx.execute("UPDATE reminders SET status = 'cancelled' WHERE kind = '48h'")
    headers = practice.ctx.auth(await practice.patient_token())
    assert (await practice.ctx.client.get(URL, headers=headers)).json() == []


async def test_history_requires_a_patient_account(practice: Practice) -> None:
    assert (await practice.ctx.client.get(URL)).status_code == 401
    staff = await practice.staff_token(UserRole.RECEPTIONIST)
    assert (await practice.ctx.client.get(URL, headers=practice.ctx.auth(staff))).status_code == 403
