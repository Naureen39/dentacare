"""Request and response shapes for the staff and admin console."""

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field

from app.db.enums import ExceptionReason, UserRole
from app.schemas.auth import StrictModel
from app.schemas.billing import InvoiceListItem
from app.schemas.booking import AppointmentOut, StaffAppointmentOut
from app.schemas.patients import PatientSummary

Money = Annotated[Decimal, Field(ge=0, le=100000, max_digits=12, decimal_places=2)]

# --- people ---------------------------------------------------------------------------


class StaffUserOut(BaseModel):
    id: uuid.UUID
    email: str
    role: UserRole
    is_active: bool
    mfa_enabled: bool
    last_login_at: datetime | None
    dentist_id: uuid.UUID | None
    dentist_name: str | None


class StaffUserCreate(StrictModel):
    email: EmailStr
    role: Literal["admin", "receptionist", "dentist"]
    full_name: str | None = Field(default=None, max_length=200)
    specialty: str = Field(default="General dentistry", max_length=100)


class StaffUserUpdate(StrictModel):
    is_active: bool


# --- services and prices ---------------------------------------------------------------


class PriceChangeOut(BaseModel):
    id: uuid.UUID
    price: Decimal
    effective_from: date
    applied_at: datetime | None


class ServiceAdminOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    category: str
    description: str | None
    duration_min: int
    base_price: Decimal
    is_active: bool
    display_order: int
    price_changes: list[PriceChangeOut]


class ServiceCreate(StrictModel):
    code: str = Field(min_length=2, max_length=20, pattern=r"^[A-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=2000)
    duration_min: int = Field(ge=5, le=480)
    base_price: Money
    display_order: int = Field(default=0, ge=0, le=1000)


class ServiceUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=2000)
    duration_min: int | None = Field(default=None, ge=5, le=480)
    is_active: bool | None = None
    display_order: int | None = Field(default=None, ge=0, le=1000)


class PriceChangeCreate(StrictModel):
    price: Money
    effective_from: date


# --- dentists, schedules and time off ----------------------------------------------------


class DentistAdminOut(BaseModel):
    id: uuid.UUID
    full_name: str
    specialty: str
    color: str
    is_active: bool
    user_id: uuid.UUID | None
    service_ids: list[uuid.UUID]


class DentistUpdate(StrictModel):
    is_active: bool | None = None
    specialty: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    service_ids: list[uuid.UUID] | None = None


class ScheduleDay(StrictModel):
    weekday: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    break_start: time | None = None
    break_end: time | None = None


class ScheduleReplace(StrictModel):
    days: list[ScheduleDay] = Field(max_length=7)


class TimeOffOut(BaseModel):
    id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    reason: ExceptionReason
    note: str | None


class TimeOffCreate(StrictModel):
    starts_at: datetime
    ends_at: datetime
    reason: ExceptionReason
    note: str | None = Field(default=None, max_length=400)


class TimeOffCreated(TimeOffOut):
    #: Booked appointments inside the period. They are not moved: staff must handle them.
    affected_appointments: int


# --- knowledge base intents --------------------------------------------------------------


class IntentExampleOut(BaseModel):
    id: uuid.UUID
    intent: str
    text: str


class IntentExampleCreate(StrictModel):
    intent: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9_]+$")
    text: str = Field(min_length=3, max_length=300)


# --- chat transcripts --------------------------------------------------------------------


class ChatSessionRow(BaseModel):
    id: uuid.UUID
    created_at: datetime
    messages: int
    thumbs_up: int
    thumbs_down: int
    first_message: str | None
    provider_last: str | None


class TranscriptMessage(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    intent: str | None
    route: str | None
    llm_calls: int
    feedback: int | None
    created_at: datetime


class Transcript(BaseModel):
    id: uuid.UUID
    created_at: datetime
    ended_at: datetime | None
    provider_last: str | None
    masked: bool
    messages: list[TranscriptMessage]


# --- settings ----------------------------------------------------------------------------


class BookingSettings(StrictModel):
    min_notice_hours: int = Field(ge=0, le=168)
    max_horizon_days: int = Field(ge=1, le=365)
    same_day_enabled: bool
    buffer_minutes: int = Field(ge=0, le=120)
    slot_grid_minutes: int = Field(ge=5, le=60)
    cancellation_free_hours: int = Field(ge=0, le=168)


class ReminderSettings(StrictModel):
    hours_before: list[Annotated[int, Field(ge=1, le=336)]] = Field(min_length=1, max_length=4)
    followup_days: int = Field(ge=0, le=30)
    recall_months: int = Field(ge=1, le=36)


class BillingSettings(StrictModel):
    tax_rate_percent: Decimal = Field(ge=0, le=30, max_digits=5, decimal_places=2)
    receptionist_max_discount_percent: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    monthly_revenue_target: Money


class RetentionSettings(StrictModel):
    chat_retention_days: int = Field(ge=1, le=3650)
    guest_anonymize_months: int = Field(ge=1, le=120)


class ClinicInfo(BaseModel):
    name: str
    address: str
    phone: str
    email: str
    timezone: str


class SettingsOut(BaseModel):
    clinic: ClinicInfo
    booking: BookingSettings
    reminders: ReminderSettings
    billing: BillingSettings
    retention: RetentionSettings


class SettingsUpdate(StrictModel):
    booking: BookingSettings | None = None
    reminders: ReminderSettings | None = None
    billing: BillingSettings | None = None
    retention: RetentionSettings | None = None


# --- staff work screens ---------------------------------------------------------------------


class AppointmentDetail(StaffAppointmentOut):
    patient_email: str | None
    patient_phone: str | None
    #: The dentist's own note. Empty for everyone else, who never receive it.
    clinical_note: str | None
    recent_visits: list[AppointmentOut]


class ClinicalNote(StrictModel):
    note: str = Field(max_length=5000)


class CompleteRequest(StrictModel):
    #: Services performed besides the booked one. Each is added to the draft invoice.
    performed_service_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    clinical_note: str | None = Field(default=None, max_length=5000)


class StaffRescheduleRequest(StrictModel):
    start: datetime
    dentist_id: uuid.UUID | None = None


class PatientHistory(BaseModel):
    appointments: list[AppointmentOut]
    invoices: list[InvoiceListItem]


class PatientNoteOut(BaseModel):
    id: uuid.UUID
    body: str
    author: str | None
    created_at: datetime


class PatientNoteCreate(StrictModel):
    body: str = Field(min_length=1, max_length=2000)


class DuplicateCandidate(BaseModel):
    patient: PatientSummary
    score: float
    reasons: list[str]


class Performance(BaseModel):
    days: int
    visits: int
    revenue: Decimal
    no_shows: int
    no_show_rate: float


class Alerts(BaseModel):
    unconfirmed_soon: int
    new_inquiries: int
