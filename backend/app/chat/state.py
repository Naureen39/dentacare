"""What the assistant remembers between messages, stored in ``chat_sessions.state``."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

IDENTITY_MINUTES = 20  # how long a mailbox verified in chat may manage appointments

FlowName = Literal["book", "reschedule", "cancel", "handoff"]


class FlowState(BaseModel):
    """An unfinished booking, reschedule, cancellation or callback request."""

    model_config = ConfigDict(extra="ignore")

    name: FlowName
    step: str
    service_id: str | None = None
    service_name: str | None = None
    dentist_id: str | None = None  # the dentist the visitor asked for, if any
    dentist_name: str | None = None
    dentist_decided: bool = False  # the visitor chose a dentist or said they have no preference
    day: str | None = None  # ISO local date
    time_pref: str | None = None
    # The chosen slot, with the dentist who offers it and the hold that keeps it for a while.
    start: str | None = None
    slot_dentist_id: str | None = None
    slot_dentist_name: str | None = None
    hold_token: str | None = None
    appointment_id: str | None = None  # the appointment being moved or cancelled
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    phone_done: bool = False  # the phone number was given or skipped
    consent: bool = False
    marketing: bool = False
    source: str | None = None  # "handoff" or "callback"
    note: str | None = None  # recent visitor messages for a callback request
    verification_id: str | None = None
    extraction_used: bool = False
    misses: int = 0  # inputs in a row that did not fit the current step
    shown: list[str] = Field(default_factory=list)  # ids offered as buttons on this step


class VerifiedIdentity(BaseModel):
    patient_id: str
    until: str

    def valid(self, now: datetime | None = None) -> bool:
        return datetime.fromisoformat(self.until) > (now or datetime.now(UTC))

    @classmethod
    def issue(cls, patient_id: str, now: datetime | None = None) -> "VerifiedIdentity":
        until = (now or datetime.now(UTC)) + timedelta(minutes=IDENTITY_MINUTES)
        return cls(patient_id=patient_id, until=until.isoformat())


class SessionState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    flow: FlowState | None = None
    verified: VerifiedIdentity | None = None
    # Counts of events used by analytics, for example how far booking conversations got.
    funnel: dict[str, bool] = Field(default_factory=dict)
    user_turns: int = 0

    @classmethod
    def load(cls, raw: dict[str, Any] | None) -> "SessionState":
        try:
            return cls.model_validate(raw or {})
        except ValueError:
            return cls()

    def dump(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=False)

    def mark(self, stage: str) -> None:
        self.funnel[stage] = True
