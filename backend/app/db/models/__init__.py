"""Import every model so that Base.metadata is complete for Alembic and tests."""

from app.db.models.billing import Invoice, InvoiceItem, Payment
from app.db.models.chat import ChatMessage, ChatSession, LlmUsage
from app.db.models.clinic import (
    Dentist,
    DentistSchedule,
    DentistService,
    InsuranceProvider,
    Patient,
    ScheduleException,
    Service,
)
from app.db.models.identity import RefreshToken, User
from app.db.models.knowledge import IntentExample, KbChunk, KbDocument
from app.db.models.platform import (
    AppSetting,
    AuditLog,
    ContactInquiry,
    NewsletterSubscriber,
    Testimonial,
)
from app.db.models.scheduling import Appointment, AppointmentStatusHistory, Reminder

__all__ = [
    "Appointment",
    "AppointmentStatusHistory",
    "AppSetting",
    "AuditLog",
    "ChatMessage",
    "ChatSession",
    "ContactInquiry",
    "Dentist",
    "DentistSchedule",
    "DentistService",
    "InsuranceProvider",
    "IntentExample",
    "Invoice",
    "InvoiceItem",
    "KbChunk",
    "KbDocument",
    "LlmUsage",
    "NewsletterSubscriber",
    "Patient",
    "Payment",
    "RefreshToken",
    "Reminder",
    "ScheduleException",
    "Service",
    "Testimonial",
    "User",
]
