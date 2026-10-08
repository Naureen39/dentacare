"""Many people trying for the same slot at once: the database must let exactly one win."""

import asyncio
import uuid
from datetime import datetime

from httpx import Response

from app.db.enums import UserRole
from app.db.models import Patient
from tests.booking.conftest import Practice, future_date, local_utc

PARALLEL = 20


async def make_patients(practice: Practice, count: int) -> list[uuid.UUID]:
    async with practice.ctx.session_factory() as db:
        patients = [Patient(first_name=f"Racer{i}", last_name="Contender") for i in range(count)]
        db.add_all(patients)
        await db.commit()
        return [p.id for p in patients]


def staff_body(
    practice: Practice, patient_id: uuid.UUID, dentist_id: uuid.UUID, start: datetime
) -> dict[str, str]:
    return {
        "patient_id": str(patient_id),
        "service_id": str(practice.cleaning.id),
        "dentist_id": str(dentist_id),
        "start": start.isoformat(),
    }


async def count_active(practice: Practice) -> int:
    rows = await practice.ctx.fetch(
        "SELECT count(*) FROM appointments WHERE status IN ('booked','confirmed','checked_in','completed')"
    )
    return int(rows[0][0])


async def test_twenty_parallel_bookings_for_one_slot_yield_exactly_one_success(
    practice: Practice,
) -> None:
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    patients = await make_patients(practice, PARALLEL)
    start = local_utc(future_date(2), 10, 0)
    headers = practice.ctx.auth(token)

    async def attempt(patient_id: uuid.UUID) -> Response:
        return await practice.ctx.client.post(
            "/api/v1/staff/appointments",
            headers=headers,
            json=staff_body(practice, patient_id, practice.dentist_a.id, start),
        )

    responses = await asyncio.gather(*(attempt(p) for p in patients))
    statuses = sorted(r.status_code for r in responses)

    assert statuses == [201] + [409] * (PARALLEL - 1)
    assert await count_active(practice) == 1
    losers = [r.json() for r in responses if r.status_code == 409]
    assert all(body["code"] == "slot_unavailable" for body in losers)
    assert all(body["details"]["alternatives"] for body in losers)


async def test_twenty_parallel_holds_on_one_slot_yield_exactly_one_hold(practice: Practice) -> None:
    start = local_utc(future_date(2), 10, 0)
    body = {
        "service_id": str(practice.cleaning.id),
        "dentist_id": str(practice.dentist_a.id),
        "start": start.isoformat(),
    }
    responses = await asyncio.gather(
        *(practice.ctx.client.post("/api/v1/public/hold", json=body) for _ in range(PARALLEL))
    )
    assert sorted(r.status_code for r in responses) == [201] + [409] * (PARALLEL - 1)
    assert {r.json()["code"] for r in responses if r.status_code == 409} == {"slot_held"}


async def test_the_same_patient_cannot_win_overlapping_slots_in_parallel(
    practice: Practice,
) -> None:
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    day = future_date(2)
    headers = practice.ctx.auth(token)
    dentists = [practice.dentist_a, practice.dentist_b]

    async def attempt(index: int) -> Response:
        # Different dentists and start times, but every interval overlaps the others.
        dentist = dentists[index % 2]
        start = local_utc(day, 10, 0 if index % 2 == 0 else 15)
        return await practice.ctx.client.post(
            "/api/v1/staff/appointments",
            headers=headers,
            json=staff_body(practice, practice.patient.id, dentist.id, start),
        )

    responses = await asyncio.gather(*(attempt(i) for i in range(PARALLEL)))
    assert sum(r.status_code == 201 for r in responses) == 1
    assert await count_active(practice) == 1
    assert {r.json()["code"] for r in responses if r.status_code == 409} <= {
        "patient_double_booked",
        "slot_unavailable",
    }


async def test_parallel_bookings_of_different_slots_all_succeed(practice: Practice) -> None:
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    patients = await make_patients(practice, 10)
    day = future_date(2)
    headers = practice.ctx.auth(token)

    async def attempt(index: int, patient_id: uuid.UUID) -> Response:
        # One hour apart so neither the appointments nor their cleanup buffers collide.
        start = local_utc(day, 8 + (index % 4), 0)
        dentist = practice.dentist_a if index < 4 else practice.dentist_b
        if index >= 8:
            start = local_utc(day, 14 + (index - 8), 0)
        return await practice.ctx.client.post(
            "/api/v1/staff/appointments",
            headers=headers,
            json=staff_body(practice, patient_id, dentist.id, start),
        )

    responses = await asyncio.gather(*(attempt(i, p) for i, p in enumerate(patients)))
    assert [r.status_code for r in responses] == [201] * 10
    assert await count_active(practice) == 10


async def test_back_to_back_attempts_after_a_loss_are_offered_real_alternatives(
    practice: Practice,
) -> None:
    token = await practice.staff_token(UserRole.RECEPTIONIST)
    patients = await make_patients(practice, 2)
    start = local_utc(future_date(2), 10, 0)
    headers = practice.ctx.auth(token)
    first = await practice.ctx.client.post(
        "/api/v1/staff/appointments",
        headers=headers,
        json=staff_body(practice, patients[0], practice.dentist_a.id, start),
    )
    loser = await practice.ctx.client.post(
        "/api/v1/staff/appointments",
        headers=headers,
        json=staff_body(practice, patients[1], practice.dentist_a.id, start),
    )
    assert (first.status_code, loser.status_code) == (201, 409)

    alternative = loser.json()["details"]["alternatives"][0]
    retry = await practice.ctx.client.post(
        "/api/v1/staff/appointments",
        headers=headers,
        json={
            **staff_body(practice, patients[1], uuid.UUID(alternative["dentist_id"]), start),
            "start": alternative["start"],
        },
    )
    assert retry.status_code == 201
