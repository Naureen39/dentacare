import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSTZRANGE, ExcludeConstraint, Range
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, pg_enum, uuid_pk
from app.db.enums import (
    AppointmentAction,
    AppointmentChannel,
    AppointmentStatus,
    ReminderChannel,
    ReminderKind,
    ReminderStatus,
)

# Statuses that occupy the chair and the patient's time. Cancelled and no-show
# appointments release the slot.
ACTIVE_STATUS_PREDICATE = "status IN ('booked', 'confirmed', 'checked_in', 'completed')"


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint(
            "NOT isempty(slot) AND NOT lower_inf(slot) AND NOT upper_inf(slot)",
            name="slot_bounded",
        ),
        ExcludeConstraint(
            ("dentist_id", "="),
            ("slot", "&&"),
            using="gist",
            where=ACTIVE_STATUS_PREDICATE,
            name="ex_appointments_dentist_no_overlap",
        ),
        ExcludeConstraint(
            ("patient_id", "="),
            ("slot", "&&"),
            using="gist",
            where=ACTIVE_STATUS_PREDICATE,
            name="ex_appointments_patient_no_overlap",
        ),
        Index("ix_appointments_dentist_slot_start", "dentist_id", text("lower(slot)")),
        Index("ix_appointments_patient_id", "patient_id"),
        Index("ix_appointments_status", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False
    )
    dentist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dentists.id", ondelete="RESTRICT"), nullable=False
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
    )
    slot: Mapped[Range[datetime]] = mapped_column(TSTZRANGE, nullable=False)
    status: Mapped[AppointmentStatus] = mapped_column(
        pg_enum(AppointmentStatus, "appointment_status"), nullable=False
    )
    channel: Mapped[AppointmentChannel] = mapped_column(
        pg_enum(AppointmentChannel, "appointment_channel"), nullable=False
    )
    reason_note: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at_column()
    rescheduled_from: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL")
    )
    late_cancel: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)


class AppointmentStatusHistory(Base):
    __tablename__ = "appointment_status_history"
    __table_args__ = (Index("ix_appointment_status_history_appointment_id", "appointment_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[AppointmentStatus | None] = mapped_column(
        pg_enum(AppointmentStatus, "appointment_status")
    )
    to_status: Mapped[AppointmentStatus] = mapped_column(
        pg_enum(AppointmentStatus, "appointment_status"), nullable=False
    )
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (
        UniqueConstraint("appointment_id", "kind", name="uq_reminders_appointment_kind"),
        Index("ix_reminders_status_scheduled_at", "status", "scheduled_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[ReminderKind] = mapped_column(
        pg_enum(ReminderKind, "reminder_kind"), nullable=False
    )
    channel: Mapped[ReminderChannel] = mapped_column(
        pg_enum(ReminderChannel, "reminder_channel"), nullable=False
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[ReminderStatus] = mapped_column(
        pg_enum(ReminderStatus, "reminder_status"), nullable=False
    )
    error: Mapped[str | None] = mapped_column(String(400))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppointmentActionToken(Base):
    """One time link that lets the recipient of a reminder confirm or cancel an appointment.

    Only the hash of the token is stored. A token is valid until the appointment starts.
    """

    __tablename__ = "appointment_action_tokens"
    __table_args__ = (Index("ix_appointment_action_tokens_appointment_id", "appointment_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False
    )
    reminder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reminders.id", ondelete="SET NULL")
    )
    action: Mapped[AppointmentAction] = mapped_column(
        pg_enum(AppointmentAction, "appointment_action"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
