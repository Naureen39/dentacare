"""Unauthenticated endpoints used by the public website and the booking wizard."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.api.v1.booking_deps import (
    Appointments,
    Availability,
    Guests,
    load_active_service,
)
from app.core.deps import AppSettings, Session
from app.core.errors import AppError
from app.core.rate_limit import (
    action_link_rule,
    contact_rule,
    ip_rate_limit,
    public_booking_rule,
)
from app.db.enums import AppointmentChannel, InquirySource
from app.db.models import (
    Appointment,
    ContactInquiry,
    Dentist,
    DentistService,
    InsuranceProvider,
    NewsletterSubscriber,
    Service,
    Testimonial,
)
from app.schemas.auth import MessageResponse
from app.schemas.booking import (
    ActionPreviewOut,
    ActionResultOut,
    AppointmentOut,
    ContactRequest,
    DayAvailabilityOut,
    DentistOut,
    GuestBookingRequest,
    GuestVerificationRequest,
    GuestVerificationResponse,
    HoldRequest,
    HoldResponse,
    InsuranceProviderOut,
    LinkAppointmentOut,
    NewsletterRequest,
    ServiceOut,
    TestimonialOut,
)
from app.services import audit, holds
from app.services.appointment_links import AppointmentLinkService
from app.services.appointments import AppointmentService, slot_out
from app.services.console import apply_due_price_changes
from app.services.guest import OTP_TTL_MINUTES

router = APIRouter(prefix="/public", tags=["public"])

booking_limit = Depends(ip_rate_limit(public_booking_rule))
contact_limit = Depends(ip_rate_limit(contact_rule))


@router.get("/services", response_model=list[ServiceOut])
async def list_services(db: Session, settings: AppSettings) -> list[ServiceOut]:
    await apply_due_price_changes(db, datetime.now(ZoneInfo(settings.clinic_tz)).date())
    rows = (
        await db.execute(
            select(Service)
            .where(Service.is_active.is_(True))
            .order_by(Service.display_order, Service.name)
        )
    ).scalars()
    return [ServiceOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/dentists", response_model=list[DentistOut])
async def list_dentists(
    db: Session, service_id: Annotated[uuid.UUID | None, Query()] = None
) -> list[DentistOut]:
    stmt = select(Dentist).where(Dentist.is_active.is_(True)).order_by(Dentist.full_name)
    if service_id is not None:
        stmt = stmt.join(DentistService, DentistService.dentist_id == Dentist.id).where(
            DentistService.service_id == service_id
        )
    return [
        DentistOut.model_validate(r, from_attributes=True)
        for r in (await db.execute(stmt)).scalars()
    ]


@router.get("/insurance-providers", response_model=list[InsuranceProviderOut])
async def list_insurance_providers(db: Session) -> list[InsuranceProviderOut]:
    rows = (await db.execute(select(InsuranceProvider).order_by(InsuranceProvider.name))).scalars()
    return [InsuranceProviderOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/availability", response_model=list[DayAvailabilityOut])
async def availability(
    availability: Availability,
    service_id: uuid.UUID,
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    dentist_id: uuid.UUID | None = None,
) -> list[DayAvailabilityOut]:
    days = await availability.search(
        service_id, date_from, date_to, dentist_id=dentist_id, use_cache=True
    )
    return [DayAvailabilityOut(date=d.date, slots=[slot_out(s) for s in d.slots]) for d in days]


@router.post("/hold", response_model=HoldResponse, status_code=201, dependencies=[booking_limit])
async def hold_slot(
    body: HoldRequest, availability: Availability, appointments: Appointments
) -> HoldResponse:
    service = await load_active_service(appointments.db, body.service_id)
    start = body.start.astimezone(UTC)
    if not await availability.is_available(service.id, body.dentist_id, start):
        raise await appointments.conflict(service, start, "This time is not available.")
    token = await holds.acquire(availability.redis, body.dentist_id, start)
    if token is None:
        raise await appointments.conflict(
            service, start, "Someone else is booking this time right now.", "slot_held"
        )
    return HoldResponse(
        hold_token=token,
        expires_in=holds.HOLD_TTL_SECONDS,
        start=start,
        end=start + timedelta(minutes=service.duration_min),
        dentist_id=body.dentist_id,
    )


@router.post(
    "/appointments/verification",
    response_model=GuestVerificationResponse,
    status_code=202,
    dependencies=[booking_limit],
)
async def request_verification(
    body: GuestVerificationRequest, guests: Guests
) -> GuestVerificationResponse:
    verification = await guests.request_code(str(body.email).lower(), body.first_name)
    return GuestVerificationResponse(
        verification_id=verification.id,
        expires_in=OTP_TTL_MINUTES * 60,
        message="A verification code has been sent to your email address.",
    )


@router.post(
    "/appointments", response_model=AppointmentOut, status_code=201, dependencies=[booking_limit]
)
async def book_as_guest(
    body: GuestBookingRequest, appointments: Appointments, guests: Guests
) -> AppointmentOut:
    if not body.consent:
        raise AppError(
            "consent_required",
            "You must accept the privacy policy and appointment reminders to book.",
            422,
        )
    email = str(body.email).lower()
    service = await load_active_service(appointments.db, body.service_id)
    verification = await guests.verify_code(body.verification_id, email, body.otp)
    patient = await guests.patient_for_guest(
        email=email,
        first_name=body.first_name,
        last_name=body.last_name,
        phone=body.phone,
        marketing=body.marketing_consent,
        insurance_provider_id=body.insurance_provider_id,
        insurance_member_id=body.insurance_member_id,
    )
    verification.consumed_at = datetime.now(UTC)
    appointment = await appointments.book(
        patient=patient,
        service=service,
        dentist_id=body.dentist_id,
        start=body.start,
        channel=AppointmentChannel.WEB,
        actor=None,
        reason_note=body.reason_note,
        hold_token=body.hold_token,
        require_hold=True,
        enforce_rules=True,
    )
    return (await appointments.present([appointment]))[0]


@router.post(
    "/contact", response_model=MessageResponse, status_code=201, dependencies=[contact_limit]
)
async def contact(body: ContactRequest, db: Session, request: Request) -> MessageResponse:
    db.add(
        ContactInquiry(
            name=body.name,
            email=str(body.email).lower() if body.email else None,
            phone=body.phone,
            message=body.message,
            source=InquirySource.CONTACT_FORM,
        )
    )
    await audit.record(db, "inquiry.create", request=request, entity="contact_inquiry")
    await db.commit()
    return MessageResponse(message="Thank you. We will reply as soon as possible.")


@router.post(
    "/newsletter", response_model=MessageResponse, status_code=202, dependencies=[contact_limit]
)
async def subscribe(body: NewsletterRequest, db: Session, settings: AppSettings) -> MessageResponse:
    # Same response whether or not the address was already subscribed.
    statement = insert(NewsletterSubscriber).values(email=str(body.email).lower())
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[NewsletterSubscriber.email], set_={"unsubscribed_at": None}
        )
    )
    await db.commit()
    return MessageResponse(message="Thank you for subscribing.")


@router.get("/testimonials", response_model=list[TestimonialOut])
async def testimonials(db: Session) -> list[TestimonialOut]:
    rows = (
        await db.execute(
            select(Testimonial)
            .where(Testimonial.is_published.is_(True))
            .order_by(Testimonial.created_at.desc())
            .limit(50)
        )
    ).scalars()
    return [TestimonialOut.model_validate(r, from_attributes=True) for r in rows]


# --- one time links from reminder emails ---------------------------------------------------

link_limit = Depends(ip_rate_limit(action_link_rule))
ActionToken = Annotated[str, Path(min_length=20, max_length=200)]


async def _link_appointment(
    appointments: AppointmentService, appointment: Appointment
) -> LinkAppointmentOut:
    view = (await appointments.present([appointment]))[0]
    return LinkAppointmentOut(
        service_name=view.service_name,
        dentist_name=view.dentist_name,
        start=view.start,
        end=view.end,
        status=view.status,
        free_cancellation_until=view.free_cancellation_until,
    )


@router.get(
    "/appointment-actions/{token}", response_model=ActionPreviewOut, dependencies=[link_limit]
)
async def preview_action(
    token: ActionToken, appointments: Appointments, db: Session
) -> ActionPreviewOut:
    """Show what the link would do. Nothing changes until the page posts to this address."""
    preview = await AppointmentLinkService(db, appointments).preview(token)
    return ActionPreviewOut(
        action=preview.action.value,
        usable=preview.usable,
        reason=preview.reason,
        appointment=await _link_appointment(appointments, preview.appointment),
    )


@router.post(
    "/appointment-actions/{token}", response_model=ActionResultOut, dependencies=[link_limit]
)
async def run_action(
    token: ActionToken, appointments: Appointments, db: Session
) -> ActionResultOut:
    result = await AppointmentLinkService(db, appointments).execute(token)
    messages = {
        "confirmed": "Thank you. Your appointment is confirmed.",
        "already_confirmed": "Your appointment was already confirmed.",
        "cancelled": "Your appointment has been cancelled.",
    }
    message = messages[result.outcome]
    if result.late_cancel:
        message += (
            " Because this is inside the free cancellation period, it is noted as a late"
            " cancellation."
        )
    return ActionResultOut(
        action=result.action.value,
        outcome=result.outcome,
        late_cancel=result.late_cancel,
        message=message,
        appointment=await _link_appointment(appointments, result.appointment),
    )
