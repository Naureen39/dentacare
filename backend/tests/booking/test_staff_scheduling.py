import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.enums import AppointmentStatus, UserRole
from tests.auth.conftest import unique_email
from tests.booking.conftest import Practice, future_date, local_utc

S = AppointmentStatus


def status_url(appointment_id: uuid.UUID | str) -> str:
    return f"/api/v1/staff/appointments/{appointment_id}/status"


async def change(practice: Practice, token: str, appointment_id, target: str):  # type: ignore[no-untyped-def]
    return await practice.ctx.client.patch(
        status_url(appointment_id), headers=practice.ctx.auth(token), json={"status": target}
    )


async def dentist_token(practice: Practice, dentist) -> str:  # type: ignore[no-untyped-def]
    """Sign in as the dentist that owns the given dentist profile."""
    email = unique_email("dentist")
    user = await practice.ctx.create_user(email, UserRole.DENTIST)
    await practice.ctx.execute("UPDATE dentists SET user_id = NULL WHERE user_id = :u", u=user.id)
    await practice.ctx.execute(
        "DELETE FROM dentists WHERE user_id IS NULL AND full_name LIKE 'Dr. Person'"
    )
    await practice.ctx.execute(
        "UPDATE dentists SET user_id = :u WHERE id = :d", u=user.id, d=dentist.id
    )
    return await practice.ctx.access_token(email)


# --- state machine -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start_status", "target", "allowed"),
    [
        (S.BOOKED, S.CONFIRMED, True),
        (S.BOOKED, S.CANCELLED, True),
        (S.BOOKED, S.CHECKED_IN, False),
        (S.BOOKED, S.COMPLETED, False),
        (S.CONFIRMED, S.CHECKED_IN, True),
        (S.CONFIRMED, S.CANCELLED, True),
        (S.CONFIRMED, S.COMPLETED, False),
        (S.CONFIRMED, S.BOOKED, False),
        (S.CHECKED_IN, S.COMPLETED, True),
        (S.CHECKED_IN, S.CANCELLED, False),
        (S.CHECKED_IN, S.NO_SHOW, False),
        (S.COMPLETED, S.CANCELLED, False),
        (S.COMPLETED, S.BOOKED, False),
        (S.CANCELLED, S.BOOKED, False),
        (S.CANCELLED, S.CONFIRMED, False),
        (S.NO_SHOW, S.COMPLETED, False),
    ],
)
async def test_status_transitions(
    practice: Practice, start_status: S, target: S, allowed: bool
) -> None:
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    appointment = await practice.book_direct(
        practice.dentist_a, datetime.now(UTC) + timedelta(days=3), status=start_status
    )
    response = await change(practice, token, appointment.id, target.value)
    if allowed:
        assert response.status_code == 200, response.text
        assert response.json()["status"] == target.value
    else:
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_transition"


async def test_no_show_is_allowed_only_after_the_start_time(practice: Practice) -> None:
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    future = await practice.book_direct(practice.dentist_a, datetime.now(UTC) + timedelta(hours=5))
    past = await practice.book_direct(practice.dentist_a, datetime.now(UTC) - timedelta(hours=5))

    early = await change(practice, token, future.id, "no_show")
    late = await change(practice, token, past.id, "no_show")
    assert early.status_code == 422 and "after its start time" in early.json()["message"]
    assert late.status_code == 200 and late.json()["status"] == "no_show"


async def test_full_visit_lifecycle_writes_history_and_audit_for_every_change(
    practice: Practice,
) -> None:
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    appointment = await practice.book_direct(
        practice.dentist_a, datetime.now(UTC) + timedelta(days=2)
    )
    for target in ("confirmed", "checked_in", "completed"):
        assert (await change(practice, token, appointment.id, target)).status_code == 200

    history = await practice.ctx.fetch(
        "SELECT from_status::text, to_status::text, changed_by IS NOT NULL "
        "FROM appointment_status_history WHERE appointment_id = :i ORDER BY changed_at",
        i=appointment.id,
    )
    assert history == [
        ("booked", "confirmed", True),
        ("confirmed", "checked_in", True),
        ("checked_in", "completed", True),
    ]
    audits = await practice.ctx.fetch(
        "SELECT count(*) FROM audit_logs WHERE action = 'appointment.status'"
    )
    assert audits == [(3,)]


async def test_cancelling_as_staff_frees_the_slot_and_records_the_reason(
    practice: Practice,
) -> None:
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    day = future_date(2)
    appointment = await practice.book_direct(practice.dentist_a, local_utc(day, 10, 0))
    response = await practice.ctx.client.patch(
        status_url(appointment.id),
        headers=practice.ctx.auth(token),
        json={"status": "cancelled", "reason": "Dentist unavailable"},
    )
    assert response.status_code == 200
    [(reason,)] = await practice.ctx.fetch(
        "SELECT cancel_reason FROM appointments WHERE id = :i", i=appointment.id
    )
    assert reason == "Dentist unavailable"
    again = await practice.ctx.client.get(
        "/api/v1/public/availability",
        params={
            "service_id": str(practice.cleaning.id),
            "from": day.isoformat(),
            "to": day.isoformat(),
            "dentist_id": str(practice.dentist_a.id),
        },
    )
    assert local_utc(day, 10, 0).isoformat().replace("+00:00", "Z") in [
        s["start"] for s in again.json()[0]["slots"]
    ]


async def test_unknown_appointment_status_and_missing_appointment(practice: Practice) -> None:
    token = await practice.staff_token(UserRole.ADMIN)
    appointment = await practice.book_direct(
        practice.dentist_a, datetime.now(UTC) + timedelta(days=2)
    )
    assert (await change(practice, token, appointment.id, "teleported")).status_code == 422
    assert (await change(practice, token, uuid.uuid4(), "confirmed")).status_code == 404


# --- who may change what ------------------------------------------------------------------------


async def test_patients_cannot_change_status_through_the_staff_route(practice: Practice) -> None:
    token = await practice.patient_token()
    appointment = await practice.book_direct(
        practice.dentist_a, datetime.now(UTC) + timedelta(days=2)
    )
    response = await change(practice, token, appointment.id, "confirmed")
    assert response.status_code == 403


async def test_anonymous_callers_cannot_use_staff_routes(practice: Practice) -> None:
    for method, path in [
        ("GET", "/api/v1/staff/schedule"),
        ("POST", "/api/v1/staff/appointments"),
        ("PATCH", status_url(uuid.uuid4())),
        ("POST", "/api/v1/patients"),
    ]:
        assert (await practice.ctx.client.request(method, path, json={})).status_code == 401


async def test_dentist_can_complete_and_mark_no_show_only_for_own_appointments(
    practice: Practice,
) -> None:
    token = await dentist_token(practice, practice.dentist_a)
    own = await practice.book_direct(
        practice.dentist_a, datetime.now(UTC) - timedelta(hours=4), status=S.CHECKED_IN
    )
    other_user = await practice.ctx.create_user(unique_email("other"))
    async with practice.ctx.session_factory() as db:
        from sqlalchemy import select

        from app.db.models import Patient

        other = (
            await db.execute(select(Patient).where(Patient.user_id == other_user.id))
        ).scalar_one()
    foreign = await practice.book_direct(
        practice.dentist_b,
        datetime.now(UTC) - timedelta(hours=4),
        status=S.CHECKED_IN,
        patient=other,
    )

    assert (await change(practice, token, own.id, "completed")).status_code == 200
    assert (await change(practice, token, foreign.id, "completed")).status_code == 404


async def test_dentist_cannot_cancel_or_confirm(practice: Practice) -> None:
    token = await dentist_token(practice, practice.dentist_a)
    appointment = await practice.book_direct(
        practice.dentist_a, datetime.now(UTC) + timedelta(days=2)
    )
    for target in ("cancelled", "confirmed", "checked_in"):
        assert (await change(practice, token, appointment.id, target)).status_code == 403


# --- staff booking -------------------------------------------------------------------------------


async def test_receptionist_books_for_a_patient_without_a_hold(practice: Practice) -> None:
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    start = local_utc(future_date(2), 9, 0)
    response = await practice.ctx.client.post(
        "/api/v1/staff/appointments",
        headers=practice.ctx.auth(token),
        json={
            "patient_id": str(practice.patient.id),
            "service_id": str(practice.cleaning.id),
            "dentist_id": str(practice.dentist_a.id),
            "start": start.isoformat(),
            "reason_note": "Phone booking",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["channel"] == "staff"
    assert response.json()["patient_name"] == "Amelia Hartwell"
    [(created_by,)] = await practice.ctx.fetch("SELECT created_by IS NOT NULL FROM appointments")
    assert created_by is True


async def test_staff_can_book_inside_the_minimum_notice_window_but_not_outside_hours(
    practice: Practice,
) -> None:
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    day = future_date(2)
    body = {
        "patient_id": str(practice.patient.id),
        "service_id": str(practice.cleaning.id),
        "dentist_id": str(practice.dentist_a.id),
    }
    off_hours = await practice.ctx.client.post(
        "/api/v1/staff/appointments",
        headers=practice.ctx.auth(token),
        json={**body, "start": local_utc(day, 21, 0).isoformat()},
    )
    assert off_hours.status_code == 409


async def test_staff_booking_conflict_returns_409_with_alternatives(practice: Practice) -> None:
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    start = local_utc(future_date(2), 9, 0)
    await practice.book_direct(practice.dentist_a, start)
    other = await practice.ctx.create_user(unique_email("other"))
    async with practice.ctx.session_factory() as db:
        from sqlalchemy import select

        from app.db.models import Patient

        patient = (
            await db.execute(select(Patient).where(Patient.user_id == other.id))
        ).scalar_one()
    response = await practice.ctx.client.post(
        "/api/v1/staff/appointments",
        headers=practice.ctx.auth(token),
        json={
            "patient_id": str(patient.id),
            "service_id": str(practice.cleaning.id),
            "dentist_id": str(practice.dentist_a.id),
            "start": start.isoformat(),
        },
    )
    assert response.status_code == 409 and response.json()["details"]["alternatives"]


async def test_only_front_desk_roles_can_book_for_patients(practice: Practice) -> None:
    start = local_utc(future_date(2), 9, 0)
    body = {
        "patient_id": str(practice.patient.id),
        "service_id": str(practice.cleaning.id),
        "dentist_id": str(practice.dentist_a.id),
        "start": start.isoformat(),
    }
    for token in (
        await practice.patient_token(),
        await dentist_token(practice, practice.dentist_a),
    ):
        response = await practice.ctx.client.post(
            "/api/v1/staff/appointments", headers=practice.ctx.auth(token), json=body
        )
        assert response.status_code == 403


async def test_booking_for_an_unknown_patient_is_not_found(practice: Practice) -> None:
    token = await practice.staff_token(UserRole.ADMIN)
    response = await practice.ctx.client.post(
        "/api/v1/staff/appointments",
        headers=practice.ctx.auth(token),
        json={
            "patient_id": str(uuid.uuid4()),
            "service_id": str(practice.cleaning.id),
            "dentist_id": str(practice.dentist_a.id),
            "start": local_utc(future_date(2), 9, 0).isoformat(),
        },
    )
    assert response.status_code == 404


# --- schedule view -------------------------------------------------------------------------------


async def test_day_schedule_lists_appointments_with_patient_names(practice: Practice) -> None:
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    day = future_date(2)
    await practice.book_direct(practice.dentist_a, local_utc(day, 9, 0))
    await practice.book_direct(practice.dentist_b, local_utc(day, 11, 0))
    await practice.book_direct(practice.dentist_a, local_utc(day + timedelta(days=1), 9, 0))

    response = await practice.ctx.client.get(
        "/api/v1/staff/schedule",
        params={"view": "day", "on": day.isoformat()},
        headers=practice.ctx.auth(token),
    )
    body = response.json()
    assert response.status_code == 200
    assert body["start"] == body["end"] == day.isoformat()
    assert [a["dentist_name"] for a in body["appointments"]] == [
        "Dr. Priya Raman",
        "Dr. Marcus Lindqvist",
    ]
    assert body["appointments"][0]["patient_name"] == "Amelia Hartwell"


async def test_week_schedule_spans_monday_to_sunday(practice: Practice) -> None:
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    day = future_date(2)
    monday = day - timedelta(days=2)
    await practice.book_direct(practice.dentist_a, local_utc(monday, 9, 0))
    await practice.book_direct(practice.dentist_a, local_utc(day, 9, 0))
    await practice.book_direct(practice.dentist_a, local_utc(monday + timedelta(days=7), 9, 0))

    body = (
        await practice.ctx.client.get(
            "/api/v1/staff/schedule",
            params={"view": "week", "on": day.isoformat()},
            headers=practice.ctx.auth(token),
        )
    ).json()
    assert body["start"] == monday.isoformat()
    assert body["end"] == (monday + timedelta(days=6)).isoformat()
    assert len(body["appointments"]) == 2


async def test_schedule_can_be_filtered_by_dentist(practice: Practice) -> None:
    token = await practice.staff_token(UserRole.ADMIN)
    day = future_date(2)
    await practice.book_direct(practice.dentist_a, local_utc(day, 9, 0))
    await practice.book_direct(practice.dentist_b, local_utc(day, 11, 0))
    body = (
        await practice.ctx.client.get(
            "/api/v1/staff/schedule",
            params={"on": day.isoformat(), "dentist_id": str(practice.dentist_b.id)},
            headers=practice.ctx.auth(token),
        )
    ).json()
    assert [a["dentist_id"] for a in body["appointments"]] == [str(practice.dentist_b.id)]


async def test_dentist_schedule_is_limited_to_their_own_patients_and_chair(
    practice: Practice,
) -> None:
    token = await dentist_token(practice, practice.dentist_a)
    day = future_date(2)
    await practice.book_direct(practice.dentist_a, local_utc(day, 9, 0))
    await practice.book_direct(practice.dentist_b, local_utc(day, 11, 0))

    own = (
        await practice.ctx.client.get(
            "/api/v1/staff/schedule",
            params={"on": day.isoformat()},
            headers=practice.ctx.auth(token),
        )
    ).json()
    assert [a["dentist_id"] for a in own["appointments"]] == [str(practice.dentist_a.id)]

    other = await practice.ctx.client.get(
        "/api/v1/staff/schedule",
        params={"on": day.isoformat(), "dentist_id": str(practice.dentist_b.id)},
        headers=practice.ctx.auth(token),
    )
    assert other.status_code == 403


async def test_patients_cannot_view_the_staff_schedule_and_views_are_audited(
    practice: Practice,
) -> None:
    assert (
        await practice.ctx.client.get(
            "/api/v1/staff/schedule", headers=practice.ctx.auth(await practice.patient_token())
        )
    ).status_code == 403
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    await practice.ctx.client.get("/api/v1/staff/schedule", headers=practice.ctx.auth(token))
    assert await practice.ctx.fetch(
        "SELECT count(*) FROM audit_logs WHERE action = 'schedule.view'"
    ) == [(1,)]


# --- patient registration by staff ---------------------------------------------------------------


async def test_front_desk_registers_a_walk_in_patient_with_encrypted_details(
    practice: Practice,
) -> None:
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    response = await practice.ctx.client.post(
        "/api/v1/patients",
        headers=practice.ctx.auth(token),
        json={
            "first_name": "Walter",
            "last_name": "Brandt",
            "phone": "+1 555 0188",
            "date_of_birth": "1975-08-02",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "walk_in" and body["phone"] == "+1 555 0188"
    [(phone, dob, user_id)] = await practice.ctx.fetch(
        "SELECT phone_enc, dob_enc, user_id FROM patients WHERE id = :i", i=uuid.UUID(body["id"])
    )
    assert "555" not in phone and "1975" not in dob and user_id is None


async def test_patient_creation_is_restricted_and_validated(practice: Practice) -> None:
    patient_token = await practice.patient_token()
    assert (
        await practice.ctx.client.post(
            "/api/v1/patients",
            headers=practice.ctx.auth(patient_token),
            json={"first_name": "A", "last_name": "B"},
        )
    ).status_code == 403
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    assert (
        await practice.ctx.client.post(
            "/api/v1/patients", headers=practice.ctx.auth(token), json={"first_name": "Only"}
        )
    ).status_code == 422
