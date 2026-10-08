import uuid
from datetime import UTC, datetime, timedelta

from httpx import Response
from sqlalchemy.dialects.postgresql import Range

from app.db.enums import AppointmentChannel, AppointmentStatus, UserRole
from app.db.models import Appointment
from tests.auth.conftest import unique_email
from tests.booking.conftest import Practice, future_date, local_utc

ME = "/api/v1/me/appointments"


async def book(practice: Practice, token: str, dentist, start, hold=None) -> Response:  # type: ignore[no-untyped-def]
    hold = hold or await practice.hold(dentist, start)
    return await practice.ctx.client.post(
        ME,
        headers=practice.ctx.auth(token),
        json={
            "service_id": str(practice.cleaning.id),
            "dentist_id": str(dentist.id),
            "start": start.isoformat(),
            "hold_token": hold,
            "reason_note": "Routine check",
        },
    )


async def test_patient_books_with_a_hold(practice: Practice) -> None:
    token = await practice.patient_token()
    start = local_utc(future_date(2), 10, 0)

    response = await book(practice, token, practice.dentist_a, start)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "booked" and body["channel"] == "web"
    assert body["service_name"] == "Routine Exam and Cleaning"
    assert body["dentist_name"] == "Dr. Priya Raman"
    assert datetime.fromisoformat(body["start"]) == start
    assert datetime.fromisoformat(body["end"]) == start + timedelta(minutes=45)
    assert datetime.fromisoformat(body["free_cancellation_until"]) == start - timedelta(hours=24)


async def test_booking_writes_status_history_and_an_audit_entry(practice: Practice) -> None:
    token = await practice.patient_token()
    response = await book(practice, token, practice.dentist_a, local_utc(future_date(2), 10, 0))
    appointment_id = response.json()["id"]

    history = await practice.ctx.fetch(
        "SELECT from_status::text, to_status::text FROM appointment_status_history "
        "WHERE appointment_id = :i",
        i=uuid.UUID(appointment_id),
    )
    assert history == [(None, "booked")]
    audit = await practice.ctx.fetch(
        "SELECT action, entity, actor_role FROM audit_logs WHERE action = 'appointment.create'"
    )
    assert audit == [("appointment.create", "appointment", "patient")]


async def test_the_hold_is_released_and_the_slot_disappears_after_booking(
    practice: Practice,
) -> None:
    token = await practice.patient_token()
    day = future_date(2)
    start = local_utc(day, 10, 0)
    await book(practice, token, practice.dentist_a, start)

    assert await practice.ctx.redis.zcard("holds:index") == 0
    response = await practice.ctx.client.get(
        "/api/v1/public/availability",
        params={
            "service_id": str(practice.cleaning.id),
            "from": day.isoformat(),
            "to": day.isoformat(),
            "dentist_id": str(practice.dentist_a.id),
        },
    )
    starts = [datetime.fromisoformat(s["start"]) for s in response.json()[0]["slots"]]
    assert start not in starts


async def test_booking_without_a_hold_is_rejected(practice: Practice) -> None:
    token = await practice.patient_token()
    start = local_utc(future_date(2), 10, 0)
    response = await practice.ctx.client.post(
        ME,
        headers=practice.ctx.auth(token),
        json={
            "service_id": str(practice.cleaning.id),
            "dentist_id": str(practice.dentist_a.id),
            "start": start.isoformat(),
            "hold_token": "x" * 30,
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "hold_expired"
    assert "alternatives" in response.json()["details"]


async def test_hold_token_for_another_slot_cannot_be_reused(practice: Practice) -> None:
    token = await practice.patient_token()
    day = future_date(2)
    hold = await practice.hold(practice.dentist_a, local_utc(day, 10, 0))
    response = await book(practice, token, practice.dentist_a, local_utc(day, 11, 0), hold=hold)
    assert response.status_code == 409 and response.json()["code"] == "hold_expired"


async def test_expired_hold_is_rejected(practice: Practice) -> None:
    token = await practice.patient_token()
    start = local_utc(future_date(2), 10, 0)
    hold = await practice.hold(practice.dentist_a, start)
    await practice.ctx.redis.flushall()  # the five minute TTL elapsing
    response = await book(practice, token, practice.dentist_a, start, hold=hold)
    assert response.status_code == 409 and response.json()["code"] == "hold_expired"


async def test_a_second_hold_on_the_same_slot_is_refused(practice: Practice) -> None:
    start = local_utc(future_date(2), 10, 0)
    await practice.hold(practice.dentist_a, start)
    response = await practice.ctx.client.post(
        "/api/v1/public/hold",
        json={
            "service_id": str(practice.cleaning.id),
            "dentist_id": str(practice.dentist_a.id),
            "start": start.isoformat(),
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "slot_held"
    assert response.json()["details"]["alternatives"]


async def test_hold_has_a_five_minute_expiry(practice: Practice) -> None:
    start = local_utc(future_date(2), 10, 0)
    await practice.hold(practice.dentist_a, start)
    [key] = [k async for k in practice.ctx.redis.scan_iter("hold:*")]
    assert 290 < await practice.ctx.redis.ttl(key) <= 300


async def test_hold_on_an_unavailable_time_is_refused_with_alternatives(practice: Practice) -> None:
    day = future_date(2)
    await practice.book_direct(practice.dentist_a, local_utc(day, 10, 0))
    response = await practice.ctx.client.post(
        "/api/v1/public/hold",
        json={
            "service_id": str(practice.cleaning.id),
            "dentist_id": str(practice.dentist_a.id),
            "start": local_utc(day, 10, 0).isoformat(),
        },
    )
    assert response.status_code == 409 and response.json()["code"] == "slot_unavailable"
    assert len(response.json()["details"]["alternatives"]) == 5


async def test_hold_outside_working_hours_is_refused(practice: Practice) -> None:
    response = await practice.ctx.client.post(
        "/api/v1/public/hold",
        json={
            "service_id": str(practice.cleaning.id),
            "dentist_id": str(practice.dentist_a.id),
            "start": local_utc(future_date(2), 3, 0).isoformat(),
        },
    )
    assert response.status_code == 409


async def test_hold_requires_a_timezone_in_the_timestamp(practice: Practice) -> None:
    response = await practice.ctx.client.post(
        "/api/v1/public/hold",
        json={
            "service_id": str(practice.cleaning.id),
            "dentist_id": str(practice.dentist_a.id),
            "start": "2027-05-05T10:00:00",
        },
    )
    assert response.status_code == 422


async def test_slot_taken_between_hold_and_booking_returns_409_with_alternatives(
    practice: Practice,
) -> None:
    """The database exclusion constraint is the last line of defence."""
    token = await practice.patient_token()
    start = local_utc(future_date(2), 10, 0)
    hold = await practice.hold(practice.dentist_a, start)
    # Another booking sneaks in straight through the database, past the hold.
    await practice.book_direct(practice.dentist_a, start + timedelta(minutes=15))

    response = await book(practice, token, practice.dentist_a, start, hold=hold)
    assert response.status_code == 409
    assert response.json()["code"] == "slot_unavailable"
    alternatives = response.json()["details"]["alternatives"]
    assert alternatives
    taken_for_a = {
        (str(practice.dentist_a.id), start),
        (str(practice.dentist_a.id), start + timedelta(minutes=15)),
    }
    assert not any(
        (a["dentist_id"], datetime.fromisoformat(a["start"])) in taken_for_a for a in alternatives
    )


async def test_patient_cannot_hold_two_overlapping_appointments(practice: Practice) -> None:
    token = await practice.patient_token()
    day = future_date(2)
    first = await book(practice, token, practice.dentist_a, local_utc(day, 10, 0))
    assert first.status_code == 201
    second = await book(practice, token, practice.dentist_b, local_utc(day, 10, 15))
    assert second.status_code == 409
    assert second.json()["code"] == "patient_double_booked"


async def test_booking_requires_a_patient_account(practice: Practice) -> None:
    staff = await practice.staff_token(UserRole.RECEPTIONIST)
    start = local_utc(future_date(2), 10, 0)
    response = await book(practice, staff, practice.dentist_a, start)
    assert response.status_code == 403


async def test_booking_requires_authentication(practice: Practice) -> None:
    response = await practice.ctx.client.post(ME, json={})
    assert response.status_code == 401


async def test_booking_rejects_unknown_fields_and_inactive_services(practice: Practice) -> None:
    token = await practice.patient_token()
    start = local_utc(future_date(2), 10, 0)
    extra = await practice.ctx.client.post(
        ME,
        headers=practice.ctx.auth(token),
        json={
            "service_id": str(practice.cleaning.id),
            "dentist_id": str(practice.dentist_a.id),
            "start": start.isoformat(),
            "hold_token": "x" * 30,
            "patient_id": str(uuid.uuid4()),
            "status": "completed",
        },
    )
    assert extra.status_code == 422
    await practice.ctx.execute("UPDATE services SET is_active = false")
    inactive = await practice.ctx.client.post(
        ME,
        headers=practice.ctx.auth(token),
        json={
            "service_id": str(practice.cleaning.id),
            "dentist_id": str(practice.dentist_a.id),
            "start": start.isoformat(),
            "hold_token": "x" * 30,
        },
    )
    assert inactive.status_code == 404


# --- listing --------------------------------------------------------------------------------


async def test_listing_shows_only_my_appointments_split_by_time(practice: Practice) -> None:
    token = await practice.patient_token()
    day = future_date(2)
    await book(practice, token, practice.dentist_a, local_utc(day, 10, 0))
    past = datetime.now(UTC) - timedelta(days=30)
    await practice.book_direct(practice.dentist_b, past.replace(minute=0, second=0, microsecond=0))
    stranger_email = unique_email("stranger")
    stranger = await practice.ctx.create_user(stranger_email)
    async with practice.ctx.session_factory() as db:
        from sqlalchemy import select

        from app.db.models import Patient

        other = (
            await db.execute(select(Patient).where(Patient.user_id == stranger.id))
        ).scalar_one()
    await practice.book_direct(practice.dentist_a, local_utc(day, 14, 0), patient=other)

    headers = practice.ctx.auth(token)
    upcoming = (
        await practice.ctx.client.get(ME, params={"when": "upcoming"}, headers=headers)
    ).json()
    past_list = (await practice.ctx.client.get(ME, params={"when": "past"}, headers=headers)).json()
    everything = (await practice.ctx.client.get(ME, headers=headers)).json()

    assert len(upcoming) == 1 and len(past_list) == 1 and len(everything) == 2
    assert everything[0]["start"] > everything[1]["start"]


# --- cancellation policy ----------------------------------------------------------------------


async def make_own_appointment(practice: Practice, start: datetime) -> Appointment:
    return await practice.book_direct(practice.dentist_a, start)


async def test_cancelling_more_than_24_hours_ahead_is_free(practice: Practice) -> None:
    token = await practice.patient_token()
    appointment = await make_own_appointment(practice, datetime.now(UTC) + timedelta(hours=72))

    response = await practice.ctx.client.post(
        f"{ME}/{appointment.id}/cancel",
        headers=practice.ctx.auth(token),
        json={"reason": "Travelling"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled" and response.json()["late_cancel"] is False
    [(reason,)] = await practice.ctx.fetch(
        "SELECT cancel_reason FROM appointments WHERE id = :i", i=appointment.id
    )
    assert reason == "Travelling"


async def test_cancelling_within_24_hours_is_flagged_as_late(practice: Practice) -> None:
    token = await practice.patient_token()
    appointment = await make_own_appointment(practice, datetime.now(UTC) + timedelta(hours=5))
    response = await practice.ctx.client.post(
        f"{ME}/{appointment.id}/cancel", headers=practice.ctx.auth(token)
    )
    assert response.status_code == 200 and response.json()["late_cancel"] is True


async def test_cancelling_exactly_at_the_policy_boundary(practice: Practice) -> None:
    token = await practice.patient_token()
    ahead = await make_own_appointment(practice, datetime.now(UTC) + timedelta(hours=24, minutes=5))
    response = await practice.ctx.client.post(
        f"{ME}/{ahead.id}/cancel", headers=practice.ctx.auth(token)
    )
    assert response.json()["late_cancel"] is False


async def test_cancellation_frees_the_slot_and_is_recorded(practice: Practice) -> None:
    token = await practice.patient_token()
    day = future_date(2)
    start = local_utc(day, 10, 0)
    created = await book(practice, token, practice.dentist_a, start)
    await practice.ctx.client.post(
        f"{ME}/{created.json()['id']}/cancel", headers=practice.ctx.auth(token)
    )
    history = await practice.ctx.fetch(
        "SELECT to_status::text FROM appointment_status_history ORDER BY changed_at"
    )
    assert [h[0] for h in history] == ["booked", "cancelled"]
    again = await book(practice, token, practice.dentist_a, start)
    assert again.status_code == 201


async def test_a_cancelled_appointment_cannot_be_cancelled_again(practice: Practice) -> None:
    token = await practice.patient_token()
    appointment = await make_own_appointment(practice, datetime.now(UTC) + timedelta(hours=72))
    headers = practice.ctx.auth(token)
    await practice.ctx.client.post(f"{ME}/{appointment.id}/cancel", headers=headers)
    second = await practice.ctx.client.post(f"{ME}/{appointment.id}/cancel", headers=headers)
    assert second.status_code == 422 and second.json()["code"] == "invalid_transition"


async def test_a_past_appointment_cannot_be_cancelled(practice: Practice) -> None:
    token = await practice.patient_token()
    appointment = await make_own_appointment(practice, datetime.now(UTC) - timedelta(hours=3))
    response = await practice.ctx.client.post(
        f"{ME}/{appointment.id}/cancel", headers=practice.ctx.auth(token)
    )
    assert response.status_code == 422


async def test_patients_cannot_cancel_or_reschedule_someone_elses_appointment(
    practice: Practice,
) -> None:
    other_email = unique_email("intruder")
    await practice.ctx.create_user(other_email)
    intruder = await practice.ctx.access_token(other_email)
    appointment = await make_own_appointment(practice, datetime.now(UTC) + timedelta(hours=72))
    headers = practice.ctx.auth(intruder)

    cancel = await practice.ctx.client.post(f"{ME}/{appointment.id}/cancel", headers=headers)
    reschedule = await practice.ctx.client.post(
        f"{ME}/{appointment.id}/reschedule",
        headers=headers,
        json={"start": local_utc(future_date(2), 10).isoformat(), "hold_token": "x" * 30},
    )
    assert cancel.status_code == reschedule.status_code == 404
    [(status,)] = await practice.ctx.fetch(
        "SELECT status::text FROM appointments WHERE id = :i", i=appointment.id
    )
    assert status == "booked"


# --- rescheduling -----------------------------------------------------------------------------


async def test_reschedule_cancels_the_old_appointment_and_links_the_new_one(
    practice: Practice,
) -> None:
    token = await practice.patient_token()
    day = future_date(2)
    original = (await book(practice, token, practice.dentist_a, local_utc(day, 10, 0))).json()
    new_start = local_utc(day, 14, 0)
    hold = await practice.hold(practice.dentist_a, new_start)

    response = await practice.ctx.client.post(
        f"{ME}/{original['id']}/reschedule",
        headers=practice.ctx.auth(token),
        json={"start": new_start.isoformat(), "hold_token": hold},
    )
    assert response.status_code == 201, response.text
    new = response.json()
    assert new["rescheduled_from"] == original["id"] and new["status"] == "booked"
    assert datetime.fromisoformat(new["start"]) == new_start

    [(old_status, old_reason)] = await practice.ctx.fetch(
        "SELECT status::text, cancel_reason FROM appointments WHERE id = :i",
        i=uuid.UUID(original["id"]),
    )
    assert (old_status, old_reason) == ("cancelled", "Rescheduled by patient")
    actions = [
        r[0] for r in await practice.ctx.fetch("SELECT action FROM audit_logs ORDER BY created_at")
    ]
    assert "appointment.reschedule" in actions


async def test_reschedule_to_an_overlapping_time_with_another_dentist_frees_the_old_slot_first(
    practice: Practice,
) -> None:
    token = await practice.patient_token()
    day = future_date(2)
    original = (await book(practice, token, practice.dentist_a, local_utc(day, 10, 0))).json()
    later = local_utc(day, 10, 15)
    hold = await practice.hold(practice.dentist_b, later)
    response = await practice.ctx.client.post(
        f"{ME}/{original['id']}/reschedule",
        headers=practice.ctx.auth(token),
        json={
            "start": later.isoformat(),
            "hold_token": hold,
            "dentist_id": str(practice.dentist_b.id),
        },
    )
    # Without cancelling the old appointment first, the patient overlap guard would reject this.
    assert response.status_code == 201, response.text


async def test_the_patients_own_appointment_blocks_holding_an_overlapping_slot(
    practice: Practice,
) -> None:
    token = await practice.patient_token()
    day = future_date(2)
    await book(practice, token, practice.dentist_a, local_utc(day, 10, 0))
    response = await practice.ctx.client.post(
        "/api/v1/public/hold",
        json={
            "service_id": str(practice.cleaning.id),
            "dentist_id": str(practice.dentist_a.id),
            "start": local_utc(day, 10, 15).isoformat(),
        },
    )
    assert response.status_code == 409


async def test_failed_reschedule_leaves_the_original_appointment_untouched(
    practice: Practice,
) -> None:
    token = await practice.patient_token()
    day = future_date(2)
    original = (await book(practice, token, practice.dentist_a, local_utc(day, 10, 0))).json()
    taken = local_utc(day, 14, 0)
    hold = await practice.hold(practice.dentist_a, taken)
    await practice.book_direct(practice.dentist_a, taken)

    response = await practice.ctx.client.post(
        f"{ME}/{original['id']}/reschedule",
        headers=practice.ctx.auth(token),
        json={"start": taken.isoformat(), "hold_token": hold},
    )
    assert response.status_code == 409
    [(status,)] = await practice.ctx.fetch(
        "SELECT status::text FROM appointments WHERE id = :i", i=uuid.UUID(original["id"])
    )
    assert status == "booked"


async def test_reschedule_with_a_different_dentist(practice: Practice) -> None:
    token = await practice.patient_token()
    day = future_date(2)
    original = (await book(practice, token, practice.dentist_a, local_utc(day, 10, 0))).json()
    new_start = local_utc(day, 11, 0)
    hold = await practice.hold(practice.dentist_b, new_start)
    response = await practice.ctx.client.post(
        f"{ME}/{original['id']}/reschedule",
        headers=practice.ctx.auth(token),
        json={
            "start": new_start.isoformat(),
            "hold_token": hold,
            "dentist_id": str(practice.dentist_b.id),
        },
    )
    assert response.status_code == 201 and response.json()["dentist_id"] == str(
        practice.dentist_b.id
    )


async def test_only_active_appointments_can_be_rescheduled(practice: Practice) -> None:
    token = await practice.patient_token()
    appointment = await practice.book_direct(
        practice.dentist_a,
        datetime.now(UTC) + timedelta(days=5),
        status=AppointmentStatus.CANCELLED,
    )
    start = local_utc(future_date(2), 10, 0)
    hold = await practice.hold(practice.dentist_a, start)
    response = await practice.ctx.client.post(
        f"{ME}/{appointment.id}/reschedule",
        headers=practice.ctx.auth(token),
        json={"start": start.isoformat(), "hold_token": hold},
    )
    assert response.status_code == 422


# --- invoices ----------------------------------------------------------------------------------


async def test_patients_see_only_their_own_invoices(practice: Practice) -> None:
    from decimal import Decimal

    from app.db.enums import InvoiceStatus
    from app.db.models import Invoice

    mine = await practice.book_direct(practice.dentist_a, datetime.now(UTC) - timedelta(days=3))
    other_user = await practice.ctx.create_user(unique_email("other"))
    async with practice.ctx.session_factory() as db:
        from sqlalchemy import select

        from app.db.models import Patient

        other = (
            await db.execute(select(Patient).where(Patient.user_id == other_user.id))
        ).scalar_one()
    theirs = await practice.book_direct(
        practice.dentist_b, datetime.now(UTC) - timedelta(days=2), patient=other
    )
    async with practice.ctx.session_factory() as db:
        for appt in (mine, theirs):
            db.add(
                Invoice(
                    appointment_id=appt.id,
                    patient_id=appt.patient_id,
                    subtotal=Decimal("120.00"),
                    total=Decimal("120.00"),
                    status=InvoiceStatus.ISSUED,
                )
            )
        await db.commit()

    token = await practice.patient_token()
    response = await practice.ctx.client.get(
        "/api/v1/me/invoices", headers=practice.ctx.auth(token)
    )
    assert response.status_code == 200
    invoices = response.json()
    assert len(invoices) == 1 and invoices[0]["patient_id"] == str(mine.patient_id)
    assert invoices[0]["total"] == "120.00"


_ = (AppointmentChannel, Range)
