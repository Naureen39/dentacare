import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, EmailStr, Field

from app.db.enums import AppointmentChannel, AppointmentStatus
from app.schemas.auth import StrictModel

# --- catalogue and availability ------------------------------------------------------


class ServiceOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    category: str
    description: str | None
    duration_min: int
    base_price: Decimal


class DentistOut(BaseModel):
    id: uuid.UUID
    full_name: str
    specialty: str
    bio: str | None
    photo_url: str | None
    color: str


class InsuranceProviderOut(BaseModel):
    id: uuid.UUID
    name: str
    plan_types: list[str]


class SlotOut(BaseModel):
    start: datetime
    end: datetime
    dentist_id: uuid.UUID
    dentist_name: str


class DayAvailabilityOut(BaseModel):
    date: date
    slots: list[SlotOut]


class HoldRequest(StrictModel):
    service_id: uuid.UUID
    dentist_id: uuid.UUID
    start: AwareDatetime


class HoldResponse(BaseModel):
    hold_token: str
    expires_in: int
    start: datetime
    end: datetime
    dentist_id: uuid.UUID


# --- appointments --------------------------------------------------------------------


class AppointmentOut(BaseModel):
    id: uuid.UUID
    status: AppointmentStatus
    channel: AppointmentChannel
    start: datetime
    end: datetime
    service_id: uuid.UUID
    service_name: str
    dentist_id: uuid.UUID
    dentist_name: str
    reason_note: str | None
    late_cancel: bool
    free_cancellation_until: datetime
    rescheduled_from: uuid.UUID | None
    created_at: datetime


class StaffAppointmentOut(AppointmentOut):
    patient_id: uuid.UUID
    patient_name: str


class BookingRequest(StrictModel):
    service_id: uuid.UUID
    dentist_id: uuid.UUID
    start: AwareDatetime
    hold_token: str = Field(min_length=20, max_length=200)
    reason_note: str | None = Field(default=None, max_length=500)


class RescheduleRequest(StrictModel):
    start: AwareDatetime
    dentist_id: uuid.UUID | None = None
    hold_token: str = Field(min_length=20, max_length=200)


class CancelRequest(StrictModel):
    reason: str | None = Field(default=None, max_length=300)


class StaffBookingRequest(StrictModel):
    patient_id: uuid.UUID
    service_id: uuid.UUID
    dentist_id: uuid.UUID
    start: AwareDatetime
    reason_note: str | None = Field(default=None, max_length=500)


class StatusChangeRequest(StrictModel):
    status: AppointmentStatus
    reason: str | None = Field(default=None, max_length=300)


class ScheduleResponse(BaseModel):
    view: Literal["day", "week"]
    start: date
    end: date
    appointments: list[StaffAppointmentOut]


# --- guest booking -------------------------------------------------------------------


class GuestVerificationRequest(StrictModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=100)


class GuestVerificationResponse(BaseModel):
    verification_id: uuid.UUID
    expires_in: int
    message: str


class GuestBookingRequest(BookingRequest):
    verification_id: uuid.UUID
    otp: str = Field(pattern=r"^\d{6}$")
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    consent: bool
    marketing_consent: bool = False
    # Optional. Kept only for a patient record created by this booking, never written over an
    # existing record, because the caller has proved control of the address and nothing more.
    insurance_provider_id: uuid.UUID | None = None
    insurance_member_id: str | None = Field(default=None, max_length=60)


# --- public site ---------------------------------------------------------------------


class ContactRequest(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    message: str = Field(min_length=5, max_length=2000)


class NewsletterRequest(StrictModel):
    email: EmailStr


class TestimonialOut(BaseModel):
    id: uuid.UUID
    first_name: str
    last_initial: str
    treatment: str | None
    rating: int
    body: str


# --- reminder links and notifications --------------------------------------------------


class LinkAppointmentOut(BaseModel):
    """The few appointment details shown to the holder of an email link."""

    service_name: str
    dentist_name: str
    start: datetime
    end: datetime
    status: AppointmentStatus
    free_cancellation_until: datetime


class ActionPreviewOut(BaseModel):
    action: Literal["confirm", "cancel"]
    usable: bool
    reason: str | None
    appointment: LinkAppointmentOut


class ActionResultOut(BaseModel):
    action: Literal["confirm", "cancel"]
    outcome: Literal["confirmed", "already_confirmed", "cancelled"]
    late_cancel: bool
    message: str
    appointment: LinkAppointmentOut


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    sent_at: datetime
    appointment_id: uuid.UUID


class ReminderOut(BaseModel):
    id: uuid.UUID
    appointment_id: uuid.UUID
    kind: str
    status: str
    scheduled_at: datetime
    sent_at: datetime | None
    attempts: int
    error: str | None
