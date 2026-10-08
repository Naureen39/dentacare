import uuid
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, pg_enum, uuid_pk
from app.db.enums import ExceptionReason, PatientSource


class InsuranceProvider(Base):
    __tablename__ = "insurance_providers"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    plan_types: Mapped[list[str]] = mapped_column(
        ARRAY(String(60)), server_default=text("'{}'::varchar[]"), nullable=False
    )


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (
        Index("ix_patients_user_id", "user_id"),
        Index("ix_patients_email", "email"),
        Index(
            "ix_patients_first_name_trgm",
            "first_name",
            postgresql_using="gin",
            postgresql_ops={"first_name": "gin_trgm_ops"},
        ),
        Index(
            "ix_patients_last_name_trgm",
            "last_name",
            postgresql_using="gin",
            postgresql_ops={"last_name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    dob_enc: Mapped[str | None] = mapped_column(Text)
    phone_enc: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(320))
    address_enc: Mapped[str | None] = mapped_column(Text)
    insurance_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("insurance_providers.id", ondelete="SET NULL")
    )
    insurance_member_id_enc: Mapped[str | None] = mapped_column(Text)
    marketing_consent: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    source: Mapped[PatientSource] = mapped_column(
        pg_enum(PatientSource, "patient_source"), server_default=text("'web'"), nullable=False
    )
    created_at: Mapped[datetime] = created_at_column()
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Dentist(Base):
    __tablename__ = "dentists"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True
    )
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    specialty: Mapped[str] = mapped_column(String(100), nullable=False)
    bio: Mapped[str | None] = mapped_column(Text)
    photo_url: Mapped[str | None] = mapped_column(String(500))
    license_no: Mapped[str | None] = mapped_column(String(60), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    color: Mapped[str] = mapped_column(String(7), server_default=text("'#13A3A1'"), nullable=False)
    created_at: Mapped[datetime] = created_at_column()


class DentistSchedule(Base):
    """Weekly working template. Weekday follows ISO numbering: 0 is Monday."""

    __tablename__ = "dentist_schedules"
    __table_args__ = (
        UniqueConstraint("dentist_id", "weekday", name="uq_dentist_schedules_dentist_weekday"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("start_time < end_time", name="hours_order"),
        CheckConstraint("(break_start IS NULL) = (break_end IS NULL)", name="break_pair"),
        CheckConstraint(
            "break_start IS NULL OR (break_start < break_end"
            " AND break_start >= start_time AND break_end <= end_time)",
            name="break_within_hours",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    dentist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dentists.id", ondelete="CASCADE"), nullable=False
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    break_start: Mapped[time | None] = mapped_column(Time)
    break_end: Mapped[time | None] = mapped_column(Time)


class ScheduleException(Base):
    __tablename__ = "schedule_exceptions"
    __table_args__ = (
        CheckConstraint("starts_at < ends_at", name="range_order"),
        Index("ix_schedule_exceptions_dentist_id_starts_at", "dentist_id", "starts_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    dentist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dentists.id", ondelete="CASCADE"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[ExceptionReason] = mapped_column(
        pg_enum(ExceptionReason, "exception_reason"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(String(400))


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("duration_min > 0", name="duration_positive"),
        CheckConstraint("base_price >= 0", name="price_non_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    base_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)


class DentistService(Base):
    __tablename__ = "dentist_services"

    dentist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dentists.id", ondelete="CASCADE"), primary_key=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), primary_key=True
    )


__all__ = [
    "Dentist",
    "DentistSchedule",
    "DentistService",
    "InsuranceProvider",
    "Patient",
    "ScheduleException",
    "Service",
]
