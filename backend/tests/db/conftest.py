"""Fixtures for tests that need a real PostgreSQL server with the required extensions.

The server comes from TEST_DATABASE_URL (default: the Compose database). Tests create and
drop their own databases, so they never touch development data. When the server cannot be
reached the tests are skipped locally and fail when REQUIRE_DB=1 (used in CI).
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import make_url
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.enums import (
    AppointmentChannel,
    AppointmentStatus,
    InvoiceStatus,
    UserRole,
)
from app.db.models import Appointment, Dentist, Invoice, Patient, Service, User

SERVER_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://meridian:meridian@127.0.0.1:5432/postgres"
)
SCHEMA_DB = "meridian_schema_test"
MIGRATION_DB = "meridian_migration_test"


def _asyncpg_dsn(database: str) -> str:
    url = make_url(SERVER_URL).set(database=database, drivername="postgresql")
    return url.render_as_string(hide_password=False)


def sqlalchemy_url(database: str) -> str:
    return make_url(SERVER_URL).set(database=database).render_as_string(hide_password=False)


async def _admin_execute(statement: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn("postgres"), timeout=5)
    try:
        await conn.execute(statement)
    finally:
        await conn.close()


def recreate_database(name: str) -> None:
    asyncio.run(_admin_execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    asyncio.run(_admin_execute(f'CREATE DATABASE "{name}"'))


def drop_database(name: str) -> None:
    asyncio.run(_admin_execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def alembic_config(database: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", sqlalchemy_url(database).replace("%", "%%"))
    return config


@pytest.fixture(scope="session")
def postgres_available() -> None:
    try:
        asyncio.run(_admin_execute("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        message = f"PostgreSQL is not reachable for database tests: {exc}"
        if os.environ.get("REQUIRE_DB") == "1":
            pytest.fail(message)
        pytest.skip(message)


@pytest.fixture(scope="session")
def migrated_schema_db(postgres_available: None) -> Iterator[str]:
    """A database migrated to head once per test session."""
    recreate_database(SCHEMA_DB)
    command.upgrade(alembic_config(SCHEMA_DB), "head")
    yield SCHEMA_DB
    drop_database(SCHEMA_DB)


@pytest.fixture
def scratch_db(postgres_available: None) -> Iterator[str]:
    """An empty database for migration tests."""
    recreate_database(MIGRATION_DB)
    yield MIGRATION_DB
    drop_database(MIGRATION_DB)


@pytest.fixture
async def session(migrated_schema_db: str) -> AsyncIterator[AsyncSession]:
    """A session inside a transaction that is rolled back after the test."""
    engine = create_async_engine(sqlalchemy_url(migrated_schema_db), poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with factory() as db_session:
            yield db_session
        await transaction.rollback()
    await engine.dispose()


@dataclass
class Clinic:
    """A minimal set of related rows shared by scheduling and billing tests."""

    patient: Patient
    other_patient: Patient
    dentist: Dentist
    other_dentist: Dentist
    service: Service


@pytest.fixture
async def clinic(session: AsyncSession) -> Clinic:
    suffix = uuid.uuid4().hex[:8]
    patient = Patient(first_name="Amelia", last_name="Hartwell", email=f"a-{suffix}@example.com")
    other_patient = Patient(
        first_name="Daniel", last_name="Okafor", email=f"d-{suffix}@example.com"
    )
    dentist = Dentist(full_name="Dr. Priya Raman", specialty="general")
    other_dentist = Dentist(full_name="Dr. Marcus Lindqvist", specialty="orthodontics")
    service = Service(
        code=f"T{suffix}",
        name="Routine Exam and Cleaning",
        category="preventive",
        duration_min=45,
        base_price=Decimal("120.00"),
    )
    session.add_all([patient, other_patient, dentist, other_dentist, service])
    await session.flush()
    return Clinic(patient, other_patient, dentist, other_dentist, service)


BASE_START = datetime(2027, 3, 2, 14, 0, tzinfo=UTC)


def make_slot(offset_minutes: int = 0, length_minutes: int = 45) -> Range[datetime]:
    start = BASE_START + timedelta(minutes=offset_minutes)
    return Range(start, start + timedelta(minutes=length_minutes), bounds="[)")


def make_appointment(
    clinic: Clinic,
    *,
    offset_minutes: int = 0,
    length_minutes: int = 45,
    status: AppointmentStatus = AppointmentStatus.BOOKED,
    patient: Patient | None = None,
    dentist: Dentist | None = None,
) -> Appointment:
    return Appointment(
        patient_id=(patient or clinic.patient).id,
        dentist_id=(dentist or clinic.dentist).id,
        service_id=clinic.service.id,
        slot=make_slot(offset_minutes, length_minutes),
        status=status,
        channel=AppointmentChannel.WEB,
    )


def make_invoice(
    appointment: Appointment,
    *,
    subtotal: str = "120.00",
    discount: str = "0.00",
    tax: str = "0.00",
    total: str = "120.00",
    status: InvoiceStatus = InvoiceStatus.ISSUED,
) -> Invoice:
    return Invoice(
        appointment_id=appointment.id,
        patient_id=appointment.patient_id,
        subtotal=Decimal(subtotal),
        discount=Decimal(discount),
        discount_reason="Loyalty discount" if Decimal(discount) != 0 else None,
        tax=Decimal(tax),
        total=Decimal(total),
        status=status,
    )


def make_user(email: str, role: UserRole = UserRole.PATIENT) -> User:
    return User(email=email, password_hash="not-a-real-hash", role=role)
