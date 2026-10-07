"""The database must be the final guard against double booking."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import AppointmentStatus
from tests.db.conftest import Clinic, make_appointment

EXCLUSION_VIOLATION = "23P01"


async def _insert_expecting_conflict(session: AsyncSession, appointment, constraint: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(IntegrityError) as raised:
        async with session.begin_nested():
            session.add(appointment)
            await session.flush()
    assert raised.value.orig.sqlstate == EXCLUSION_VIOLATION  # type: ignore[union-attr]
    assert constraint in str(raised.value.orig)


async def test_overlapping_booking_for_same_dentist_is_rejected(
    session: AsyncSession, clinic: Clinic
) -> None:
    session.add(make_appointment(clinic))
    await session.flush()

    clash = make_appointment(clinic, offset_minutes=30, patient=clinic.other_patient)
    await _insert_expecting_conflict(session, clash, "ex_appointments_dentist_no_overlap")


async def test_identical_slot_for_same_dentist_is_rejected(
    session: AsyncSession, clinic: Clinic
) -> None:
    session.add(make_appointment(clinic))
    await session.flush()

    clash = make_appointment(clinic, patient=clinic.other_patient)
    await _insert_expecting_conflict(session, clash, "ex_appointments_dentist_no_overlap")


async def test_back_to_back_bookings_are_allowed(session: AsyncSession, clinic: Clinic) -> None:
    session.add(make_appointment(clinic, length_minutes=45))
    session.add(make_appointment(clinic, offset_minutes=45, patient=clinic.other_patient))
    await session.flush()


async def test_same_slot_with_different_dentists_and_patients_is_allowed(
    session: AsyncSession, clinic: Clinic
) -> None:
    session.add(make_appointment(clinic))
    session.add(
        make_appointment(clinic, patient=clinic.other_patient, dentist=clinic.other_dentist)
    )
    await session.flush()


async def test_patient_cannot_hold_overlapping_appointments_with_different_dentists(
    session: AsyncSession, clinic: Clinic
) -> None:
    session.add(make_appointment(clinic))
    await session.flush()

    clash = make_appointment(clinic, offset_minutes=15, dentist=clinic.other_dentist)
    await _insert_expecting_conflict(session, clash, "ex_appointments_patient_no_overlap")


@pytest.mark.parametrize("released", [AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW])
async def test_cancelled_and_no_show_appointments_release_the_slot(
    session: AsyncSession, clinic: Clinic, released: AppointmentStatus
) -> None:
    session.add(make_appointment(clinic, status=released))
    session.add(make_appointment(clinic, patient=clinic.other_patient))
    await session.flush()


@pytest.mark.parametrize(
    "occupying",
    [
        AppointmentStatus.BOOKED,
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.CHECKED_IN,
        AppointmentStatus.COMPLETED,
    ],
)
async def test_every_active_status_blocks_the_slot(
    session: AsyncSession, clinic: Clinic, occupying: AppointmentStatus
) -> None:
    session.add(make_appointment(clinic, status=occupying))
    await session.flush()

    clash = make_appointment(clinic, patient=clinic.other_patient)
    await _insert_expecting_conflict(session, clash, "ex_appointments_dentist_no_overlap")


async def test_reactivating_a_cancelled_appointment_into_a_taken_slot_is_rejected(
    session: AsyncSession, clinic: Clinic
) -> None:
    session.add(make_appointment(clinic))
    cancelled = make_appointment(
        clinic, patient=clinic.other_patient, status=AppointmentStatus.CANCELLED
    )
    session.add(cancelled)
    await session.flush()

    with pytest.raises(IntegrityError) as raised:
        async with session.begin_nested():
            cancelled.status = AppointmentStatus.BOOKED
            await session.flush()
    assert raised.value.orig.sqlstate == EXCLUSION_VIOLATION  # type: ignore[union-attr]
