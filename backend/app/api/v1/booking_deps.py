"""Dependencies that assemble the booking services for a request."""

import uuid
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select

from app.core.deps import AppSettings, Cipher, MailerDep, RedisDep, Session
from app.core.errors import AppError
from app.db.models import Service
from app.services.appointments import AppointmentService
from app.services.availability import AvailabilityService
from app.services.guest import GuestService


def get_appointment_service(
    request: Request, db: Session, settings: AppSettings, redis: RedisDep
) -> AppointmentService:
    return AppointmentService(
        db=db,
        settings=settings,
        redis=redis,
        request=request,
        jobs=getattr(request.app.state, "jobs", None),
    )


def get_availability_service(
    db: Session, settings: AppSettings, redis: RedisDep
) -> AvailabilityService:
    return AvailabilityService(db, settings, redis)


def get_guest_service(
    db: Session, settings: AppSettings, redis: RedisDep, cipher: Cipher, mailer: MailerDep
) -> GuestService:
    return GuestService(db=db, settings=settings, redis=redis, cipher=cipher, mailer=mailer)


Appointments = Annotated[AppointmentService, Depends(get_appointment_service)]
Availability = Annotated[AvailabilityService, Depends(get_availability_service)]
Guests = Annotated[GuestService, Depends(get_guest_service)]


async def load_active_service(db: Session, service_id: uuid.UUID) -> Service:
    service = (
        await db.execute(
            select(Service).where(Service.id == service_id, Service.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if service is None:
        raise AppError("not_found", "Service not found.", 404)
    return service
