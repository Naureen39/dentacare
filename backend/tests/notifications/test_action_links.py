from datetime import UTC, datetime, timedelta

from app.db.enums import AppointmentStatus
from app.db.models import Appointment
from tests.booking.conftest import Practice
from tests.notifications.helpers import (
    appointment_in,
    links_in,
    reminder_id,
    reminders_of,
    send,
)

BASE = "/api/v1/public/appointment-actions"


async def reminder_links(
    practice: Practice, hours: float, status: AppointmentStatus = AppointmentStatus.BOOKED
) -> tuple[Appointment, dict[str, str]]:
    """Create an appointment and the links its first reminder email would carry."""
    from app.services.reminders import ReminderScheduler

    appointment = await appointment_in(practice, hours, status)
    async with practice.ctx.session_factory() as db:
        await ReminderScheduler(db).schedule_booking(appointment)
        await db.commit()
    kind = "48h" if hours > 48 else "24h"
    await send(practice, await reminder_id(practice, appointment.id, kind))
    return appointment, links_in(practice.ctx.mailer.outbox[-1])


async def status_of(practice: Practice, appointment_id) -> str:  # type: ignore[no-untyped-def]
    rows = await practice.ctx.fetch(
        "SELECT status::text FROM appointments WHERE id = :i", i=appointment_id
    )
    return str(rows[0][0])


async def test_opening_a_link_only_previews_and_changes_nothing(practice: Practice) -> None:
    appointment, links = await reminder_links(practice, 60)
    client = practice.ctx.client

    for action in ("confirm", "cancel"):
        response = await client.get(f"{BASE}/{links[action]}")
        assert response.status_code == 200
        body = response.json()
        assert body["action"] == action and body["usable"] is True and body["reason"] is None
        assert body["appointment"]["service_name"] == "Routine Exam and Cleaning"
        assert body["appointment"]["dentist_name"] == "Dr. Priya Raman"
    assert await status_of(practice, appointment.id) == "booked"
    assert await practice.ctx.fetch(
        "SELECT count(*) FROM appointment_action_tokens WHERE used_at IS NOT NULL"
    ) == [(0,)]


async def test_preview_exposes_no_personal_details(practice: Practice) -> None:
    _, links = await reminder_links(practice, 60)
    body = (await practice.ctx.client.get(f"{BASE}/{links['confirm']}")).json()
    assert set(body["appointment"]) == {
        "service_name",
        "dentist_name",
        "start",
        "end",
        "status",
        "free_cancellation_until",
    }


async def test_confirm_link_confirms_the_appointment_once(practice: Practice) -> None:
    appointment, links = await reminder_links(practice, 60)
    client = practice.ctx.client

    response = await client.post(f"{BASE}/{links['confirm']}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["outcome"], body["late_cancel"]) == ("confirmed", False)
    assert body["message"] == "Thank you. Your appointment is confirmed."
    assert body["appointment"]["status"] == "confirmed"
    assert await status_of(practice, appointment.id) == "confirmed"

    history = await practice.ctx.fetch(
        "SELECT from_status::text, to_status::text, changed_by FROM appointment_status_history "
        "WHERE appointment_id = :i ORDER BY changed_at",
        i=appointment.id,
    )
    assert history[-1] == ("booked", "confirmed", None)
    audit = await practice.ctx.fetch(
        "SELECT actor_role, actor_id FROM audit_logs WHERE action = 'appointment.status'"
    )
    assert audit == [("guest", None)]

    again = await client.post(f"{BASE}/{links['confirm']}")
    assert again.status_code == 409 and again.json()["code"] == "link_used"
    preview = (await client.get(f"{BASE}/{links['confirm']}")).json()
    assert preview["usable"] is False and "already been used" in preview["reason"]


async def test_cancel_link_cancels_frees_the_slot_and_stops_reminders(practice: Practice) -> None:
    appointment, links = await reminder_links(practice, 90)
    response = await practice.ctx.client.post(f"{BASE}/{links['cancel']}")

    assert response.status_code == 200
    body = response.json()
    assert (body["outcome"], body["late_cancel"]) == ("cancelled", False)
    assert body["appointment"]["status"] == "cancelled"
    assert await status_of(practice, appointment.id) == "cancelled"
    [(reason, late)] = await practice.ctx.fetch(
        "SELECT cancel_reason, late_cancel FROM appointments WHERE id = :i", i=appointment.id
    )
    assert (reason, late) == ("Cancelled from email link", False)
    pending = [
        r for r in (await reminders_of(practice, appointment.id)).values() if r[1] == "pending"
    ]
    assert pending == []


async def test_cancelling_inside_the_free_window_is_flagged_late(practice: Practice) -> None:
    appointment, links = await reminder_links(practice, 26)
    # The reminder email arrives when the visit is less than a day away.
    await practice.ctx.execute(
        "UPDATE appointments SET slot = tstzrange(:s, :e) WHERE id = :i",
        s=datetime.now(UTC) + timedelta(hours=10),
        e=datetime.now(UTC) + timedelta(hours=11),
        i=appointment.id,
    )
    body = (await practice.ctx.client.post(f"{BASE}/{links['cancel']}")).json()
    assert body["late_cancel"] is True and "late cancellation" in body["message"]
    [(late,)] = await practice.ctx.fetch(
        "SELECT late_cancel FROM appointments WHERE id = :i", i=appointment.id
    )
    assert late is True


async def test_confirm_link_on_an_already_confirmed_appointment_is_harmless(
    practice: Practice,
) -> None:
    appointment, links = await reminder_links(practice, 60)
    await practice.ctx.execute(
        "UPDATE appointments SET status = 'confirmed' WHERE id = :i", i=appointment.id
    )
    body = (await practice.ctx.client.post(f"{BASE}/{links['confirm']}")).json()
    assert body["outcome"] == "already_confirmed" and "already confirmed" in body["message"]


async def test_links_stop_working_once_the_appointment_is_cancelled(practice: Practice) -> None:
    appointment, links = await reminder_links(practice, 60)
    await practice.ctx.client.post(f"{BASE}/{links['cancel']}")
    response = await practice.ctx.client.post(f"{BASE}/{links['confirm']}")
    assert response.status_code == 409 and response.json()["code"] == "appointment_not_active"
    assert await status_of(practice, appointment.id) == "cancelled"


async def test_links_expire_when_the_appointment_starts(practice: Practice) -> None:
    appointment, links = await reminder_links(practice, 60)
    await practice.ctx.execute(
        "UPDATE appointment_action_tokens SET expires_at = now() - interval '1 second'"
    )
    response = await practice.ctx.client.post(f"{BASE}/{links['confirm']}")
    assert response.status_code == 410 and response.json()["code"] == "link_expired"
    preview = (await practice.ctx.client.get(f"{BASE}/{links['confirm']}")).json()
    assert preview["usable"] is False and "expired" in preview["reason"]
    assert await status_of(practice, appointment.id) == "booked"


async def test_token_lifetime_is_the_appointment_start_time(practice: Practice) -> None:
    appointment, _ = await reminder_links(practice, 60)
    rows = await practice.ctx.fetch(
        "SELECT t.expires_at = lower(a.slot) FROM appointment_action_tokens t JOIN appointments a ON a.id = t.appointment_id"
    )
    assert rows and all(r[0] for r in rows)
    _ = appointment


async def test_a_visit_that_has_started_cannot_be_cancelled_by_link(practice: Practice) -> None:
    appointment, links = await reminder_links(practice, 60)
    await practice.ctx.execute(
        "UPDATE appointments SET status = 'checked_in' WHERE id = :i", i=appointment.id
    )
    response = await practice.ctx.client.post(f"{BASE}/{links['cancel']}")
    assert response.status_code == 409
    assert await status_of(practice, appointment.id) == "checked_in"


async def test_unknown_malformed_and_foreign_tokens_are_rejected(practice: Practice) -> None:
    client = practice.ctx.client
    unknown = await client.post(f"{BASE}/{'x' * 43}")
    assert unknown.status_code == 404 and unknown.json()["code"] == "invalid_link"
    assert (await client.get(f"{BASE}/{'x' * 43}")).status_code == 404
    assert (await client.get(f"{BASE}/short")).status_code == 422
    assert (await client.post(f"{BASE}/{'y' * 300}")).status_code == 422


async def test_a_resent_reminder_invalidates_the_links_of_the_earlier_attempt(
    practice: Practice,
) -> None:
    from app.services.reminders import ReminderScheduler

    appointment = await appointment_in(practice, 60)
    async with practice.ctx.session_factory() as db:
        await ReminderScheduler(db).schedule_booking(appointment)
        await db.commit()
    rid = await reminder_id(practice, appointment.id, "48h")

    practice.ctx.mailer.failures = 1
    import pytest
    from arq import Retry

    with pytest.raises(Retry):
        await send(practice, rid)
    assert practice.ctx.mailer.outbox == []
    assert await send(practice, rid, job_try=2) == "sent"

    # Two attempts built links, but only the delivered ones can be used.
    usable = await practice.ctx.fetch(
        "SELECT count(*) FROM appointment_action_tokens WHERE expires_at > now()"
    )
    assert usable == [(2,)]
    delivered = links_in(practice.ctx.mailer.outbox[0])
    assert (await practice.ctx.client.post(f"{BASE}/{delivered['confirm']}")).status_code == 200


async def test_action_links_are_rate_limited_per_address(practice: Practice) -> None:
    practice.ctx.set_settings(rate_limit_action_link_per_hour=3)
    statuses = [(await practice.ctx.client.get(f"{BASE}/{'z' * 43}")).status_code for _ in range(5)]
    assert statuses == [404, 404, 404, 429, 429]


async def test_the_guest_who_booked_can_use_a_link_without_an_account(practice: Practice) -> None:
    appointment, links = await reminder_links(practice, 60)
    assert (
        await practice.ctx.client.post(f"{BASE}/{links['confirm']}")
    ).status_code == 200  # no auth header
    assert await status_of(practice, appointment.id) == "confirmed"
