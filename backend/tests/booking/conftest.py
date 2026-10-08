"""A small fully configured practice used by the booking tests."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.dialects.postgresql import Range

from app.db.enums import AppointmentChannel, AppointmentStatus, UserRole
from app.db.models import (
    Appointment,
    Dentist,
    DentistSchedule,
    DentistService,
    Patient,
    Service,
)
from tests.auth.conftest import Ctx, unique_email

NY = ZoneInfo("America/New_York")


def clinic_now() -> datetime:
    return datetime.now(UTC)


def future_date(weekday: int, min_days: int = 10) -> date:
    """The first date with the given ISO weekday (0 = Monday) at least ``min_days`` ahead."""
    day = datetime.now(NY).date() + timedelta(days=min_days)
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return day


def local_utc(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=NY).astimezone(UTC)


@dataclass
class Practice:
    ctx: Ctx
    cleaning: Service  # 45 minutes
    crown: Service  # 90 minutes
    dentist_a: Dentist  # offers both
    dentist_b: Dentist  # offers cleaning only
    patient_user_email: str
    patient: Patient

    async def book_direct(
        self,
        dentist: Dentist,
        start: datetime,
        *,
        patient: Patient | None = None,
        service: Service | None = None,
        status: AppointmentStatus = AppointmentStatus.BOOKED,
    ) -> Appointment:
        """Insert an appointment straight into the database, bypassing the rules."""
        service = service or self.cleaning
        async with self.ctx.session_factory() as db:
            appointment = Appointment(
                patient_id=(patient or self.patient).id,
                dentist_id=dentist.id,
                service_id=service.id,
                slot=Range(start, start + timedelta(minutes=service.duration_min), bounds="[)"),
                status=status,
                channel=AppointmentChannel.STAFF,
            )
            db.add(appointment)
            await db.commit()
            await db.refresh(appointment)
            return appointment

    async def hold(self, dentist: Dentist, start: datetime, service: Service | None = None) -> str:
        response = await self.ctx.client.post(
            "/api/v1/public/hold",
            json={
                "service_id": str((service or self.cleaning).id),
                "dentist_id": str(dentist.id),
                "start": start.isoformat(),
            },
        )
        assert response.status_code == 201, response.text
        return str(response.json()["hold_token"])

    async def patient_token(self) -> str:
        return await self.ctx.access_token(self.patient_user_email)

    async def staff_token(self, role: UserRole) -> str:
        email = unique_email(role.value)
        await self.ctx.create_user(email, role)
        return await self.ctx.access_token(email)


async def _make_dentist(ctx: Ctx, name: str, specialty: str, services: list[Service]) -> Dentist:
    async with ctx.session_factory() as db:
        dentist = Dentist(full_name=name, specialty=specialty)
        db.add(dentist)
        await db.flush()
        for weekday in range(5):  # Monday to Friday
            db.add(
                DentistSchedule(
                    dentist_id=dentist.id,
                    weekday=weekday,
                    start_time=time(8, 0),
                    end_time=time(18, 0),
                    break_start=time(12, 30),
                    break_end=time(13, 30),
                )
            )
        db.add(
            DentistSchedule(
                dentist_id=dentist.id, weekday=5, start_time=time(9, 0), end_time=time(14, 0)
            )
        )
        for service in services:
            db.add(DentistService(dentist_id=dentist.id, service_id=service.id))
        await db.commit()
        await db.refresh(dentist)
        return dentist


@pytest.fixture
async def practice(ctx: Ctx) -> Practice:
    async with ctx.session_factory() as db:
        cleaning = Service(
            code="SV02",
            name="Routine Exam and Cleaning",
            category="preventive",
            duration_min=45,
            base_price=Decimal("120.00"),
            display_order=2,
        )
        crown = Service(
            code="SV05",
            name="Porcelain Crown",
            category="restorative",
            duration_min=90,
            base_price=Decimal("1150.00"),
            display_order=5,
        )
        db.add_all([cleaning, crown])
        await db.commit()
        await db.refresh(cleaning)
        await db.refresh(crown)

    dentist_a = await _make_dentist(ctx, "Dr. Priya Raman", "general", [cleaning, crown])
    dentist_b = await _make_dentist(ctx, "Dr. Marcus Lindqvist", "general", [cleaning])

    email = unique_email("patient")
    user = await ctx.create_user(email, UserRole.PATIENT, first_name="Amelia", last_name="Hartwell")
    async with ctx.session_factory() as db:
        from sqlalchemy import select

        patient = (await db.execute(select(Patient).where(Patient.user_id == user.id))).scalar_one()
    return Practice(ctx, cleaning, crown, dentist_a, dentist_b, email, patient)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()
