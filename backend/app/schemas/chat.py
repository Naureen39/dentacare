import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.db.enums import ChatRole, ChatRoute
from app.schemas.auth import StrictModel


class ChoiceIn(StrictModel):
    """A button the visitor clicked: what kind of choice it was, and its value."""

    kind: str = Field(min_length=1, max_length=30)
    value: str = Field(max_length=300)
    label: str = Field(default="", max_length=100)


class SendMessageRequest(StrictModel):
    # Longer text is accepted here and answered politely by the assistant, instead of failing
    # with a validation error in the middle of a chat.
    text: str = Field(default="", max_length=4000)
    choice: ChoiceIn | None = None

    @model_validator(mode="after")
    def need_something(self) -> "SendMessageRequest":
        if not self.text and self.choice is None:
            raise ValueError("Send text or a choice.")
        return self


class QuickReplyOut(StrictModel):
    label: str
    kind: str
    value: str


class LinkOut(StrictModel):
    label: str
    url: str


class ChatReplyOut(StrictModel):
    message_id: uuid.UUID
    text: str
    route: ChatRoute
    intent: str | None
    quick_replies: list[QuickReplyOut]
    links: list[LinkOut]
    input_hint: str | None
    picker: str | None
    degraded: bool
    flow: str | None
    step: str | None


class CreateSessionResponse(StrictModel):
    session_id: uuid.UUID
    # Shown once. Send it as X-Chat-Token with every later request for this conversation.
    session_token: str
    greeting: ChatReplyOut


class ChatMessageOut(StrictModel):
    id: uuid.UUID
    role: ChatRole
    content: str
    intent: str | None
    route: ChatRoute | None
    quick_replies: list[QuickReplyOut]
    links: list[LinkOut]
    input_hint: str | None
    picker: str | None
    feedback: Literal["up", "down"] | None
    created_at: datetime


class SessionOut(StrictModel):
    id: uuid.UUID
    created_at: datetime
    flow: str | None
    step: str | None
    messages: list[ChatMessageOut]


class FeedbackRequest(StrictModel):
    message_id: uuid.UUID
    rating: Literal["up", "down"]


class ProviderShare(StrictModel):
    provider: str
    calls: int
    tokens: int


class UnansweredQuestion(StrictModel):
    question: str
    count: int


class ChatMetrics(StrictModel):
    days: int
    conversations: int
    turns: int
    zero_llm_turns: int
    zero_llm_share: float | None
    llm_calls: int
    tokens: int
    tokens_per_conversation: float | None
    tokens_per_booking: float | None
    funnel_started: int
    funnel_slot_chosen: int
    funnel_confirmed: int
    handoffs: int
    feedback_up: int
    feedback_down: int
    providers: list[ProviderShare]
    unanswered: list[UnansweredQuestion]
