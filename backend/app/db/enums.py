from enum import StrEnum


class UserRole(StrEnum):
    PATIENT = "patient"
    RECEPTIONIST = "receptionist"
    DENTIST = "dentist"
    ADMIN = "admin"


class PatientSource(StrEnum):
    WEB = "web"
    CHATBOT = "chatbot"
    WALK_IN = "walk_in"
    REFERRAL = "referral"


class ExceptionReason(StrEnum):
    LEAVE = "leave"
    HOLIDAY = "holiday"
    TRAINING = "training"


class AppointmentStatus(StrEnum):
    BOOKED = "booked"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class AppointmentChannel(StrEnum):
    WEB = "web"
    CHATBOT = "chatbot"
    STAFF = "staff"


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    VOID = "void"


class PaymentMethod(StrEnum):
    CARD = "card"
    CASH = "cash"
    INSURANCE = "insurance"
    BANK_TRANSFER = "bank_transfer"


class PayerType(StrEnum):
    PATIENT = "patient"
    INSURER = "insurer"


class ReminderKind(StrEnum):
    CONFIRMATION = "confirmation"
    HOURS_48 = "48h"
    HOURS_24 = "24h"
    FOLLOWUP = "followup"
    RECALL = "recall"


class ReminderChannel(StrEnum):
    EMAIL = "email"


class ReminderStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatRoute(StrEnum):
    RULE = "rule"
    CACHE = "cache"
    FAQ_DIRECT = "faq_direct"
    LLM = "llm"
    HANDOFF = "handoff"


class InquirySource(StrEnum):
    CONTACT_FORM = "contact_form"
    CHATBOT_HANDOFF = "chatbot_handoff"
    CALLBACK_REQUEST = "callback_request"


class InquiryStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class AuthTokenPurpose(StrEnum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"


class AppointmentAction(StrEnum):
    CONFIRM = "confirm"
    CANCEL = "cancel"
