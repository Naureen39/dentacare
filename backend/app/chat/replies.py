"""What a chat turn returns, and every fixed message the assistant can say without a model."""

from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings
from app.db.enums import ChatRoute


@dataclass(frozen=True)
class QuickReply:
    """A button. Clicking it sends ``kind`` and ``value`` back instead of typed text."""

    label: str
    kind: str
    value: str


@dataclass(frozen=True)
class Choice:
    """A button the visitor clicked, sent back by the interface."""

    kind: str
    value: str
    label: str = ""  # the button text, kept so the conversation reads naturally


@dataclass(frozen=True)
class Link:
    label: str
    url: str


@dataclass
class Reply:
    text: str
    route: ChatRoute = ChatRoute.RULE
    intent: str | None = None
    quick_replies: list[QuickReply] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    # What kind of input the interface should offer next: text, name, email, phone or code.
    input_hint: str | None = None
    # "date" or "slot" asks the interface for its date or time picker instead of plain chips.
    picker: str | None = None
    degraded: bool = False
    llm_calls: int = 0
    provider: str | None = None  # the model provider that answered, when one did

    def payload(self) -> dict[str, Any]:
        return {
            "quick_replies": [q.__dict__ for q in self.quick_replies],
            "links": [link.__dict__ for link in self.links],
            "input_hint": self.input_hint,
            "picker": self.picker,
            "degraded": self.degraded,
        }


# --- chips used in several places ---------------------------------------------------------------

BOOK_CHIP = QuickReply("Book an appointment", "action", "start_booking")
HOURS_CHIP = QuickReply("Opening hours", "action", "hours")
HANDOFF_CHIP = QuickReply("Talk to a person", "action", "handoff")
CALLBACK_CHIP = QuickReply("Request a callback", "action", "callback")
EXIT_CHIP = QuickReply("Never mind", "action", "exit_flow")


def menu_chips() -> list[QuickReply]:
    return [
        BOOK_CHIP,
        QuickReply("Change or cancel", "action", "manage"),
        HOURS_CHIP,
        QuickReply("Prices", "action", "prices"),
        HANDOFF_CHIP,
    ]


# --- fixed messages ---------------------------------------------------------------------------------


def greeting(settings: Settings) -> Reply:
    return Reply(
        f"Hello, and welcome to {settings.clinic_name}. I can answer questions about our "
        "services, hours and policies, and help you book, change or cancel an appointment. "
        "How can I help?",
        intent="greeting",
        quick_replies=menu_chips(),
    )


def thanks() -> Reply:
    return Reply(
        "You're welcome. Is there anything else I can help you with?",
        intent="thanks",
        quick_replies=[BOOK_CHIP, HANDOFF_CHIP],
    )


def emergency(settings: Settings) -> Reply:
    return Reply(
        "This may be an emergency. If you have trouble breathing or swallowing, swelling that "
        "is spreading to your face or neck, bleeding that will not stop, or a serious injury "
        "to your face or jaw, call 911 or go to the nearest emergency room now. "
        f"For urgent dental care you can also call our emergency line at "
        f"{settings.clinic_emergency_phone}.",
        intent="emergency",
        quick_replies=[HANDOFF_CHIP],
    )


def urgent(settings: Settings) -> Reply:
    """For a dental problem that needs prompt care but did not use words of a medical emergency."""
    return Reply(
        "That sounds like it needs attention soon. Please call our emergency line at "
        f"{settings.clinic_emergency_phone} and we will arrange the earliest visit. If you "
        "have trouble breathing, swelling that is spreading, or bleeding that will not stop, "
        "call 911 instead.",
        intent="urgent",
        quick_replies=[HANDOFF_CHIP, BOOK_CHIP],
    )


def blocked(settings: Settings) -> Reply:
    return Reply(
        f"I can only help with questions about {settings.clinic_name}: our services, hours, "
        "prices, policies and your appointments. What would you like to know?",
        intent="blocked",
        quick_replies=menu_chips(),
    )


def out_of_scope(settings: Settings) -> Reply:
    return Reply(
        f"That is outside what I can help with. I can answer questions about "
        f"{settings.clinic_name}, and help you book, change or cancel a visit.",
        intent="out_of_scope",
        quick_replies=menu_chips(),
    )


def too_long(limit: int) -> Reply:
    return Reply(
        f"Please keep your message under {limit} characters so I can help you properly.",
        intent="too_long",
    )


def empty_message() -> Reply:
    return Reply("Please type a message or choose one of the options.", intent="empty")


MEDICAL_DISCLAIMER = (
    "I can't give medical advice or diagnose problems. A dentist needs to examine you for that."
)


def medical_advice(settings: Settings) -> Reply:
    return Reply(
        f"{MEDICAL_DISCLAIMER} Please book a visit, or call us at {settings.clinic_phone}. "
        "If it is severe pain, swelling or bleeding, tell us when you call.",
        intent="medical_advice",
        quick_replies=[BOOK_CHIP, HANDOFF_CHIP],
    )


CLINICAL_NOTE = "This is general information, not a diagnosis. A dentist can advise you personally."


def cannot_answer(settings: Settings) -> Reply:
    return Reply(
        "I'm not sure about that one, and I would rather not guess. You can call us at "
        f"{settings.clinic_phone}, send a message through our contact form, or ask for a "
        "callback.",
        intent="unanswered",
        quick_replies=[CALLBACK_CHIP, BOOK_CHIP],
        links=[Link("Contact form", "/contact")],
    )


def technical_problem(settings: Settings) -> Reply:
    return Reply(
        "Sorry, I could not complete that just now. Please try again in a moment, or call us "
        f"at {settings.clinic_phone}.",
        intent="error",
        quick_replies=[HANDOFF_CHIP, BOOK_CHIP],
        degraded=True,
    )


def handoff_done(settings: Settings, name: str) -> Reply:
    return Reply(
        f"Thank you, {name}. A member of our team will contact you soon. If it is urgent, "
        f"please call {settings.clinic_phone}.",
        route=ChatRoute.HANDOFF,
        intent="human_handoff",
    )
