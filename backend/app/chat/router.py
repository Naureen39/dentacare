"""One chat turn from the visitor's message to the assistant's reply.

The order is the cheapest first: safety rules, an active conversation flow, intent matching by
vector similarity, stored answers, and only then a model. Most turns end before the model.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import entities, replies, safety
from app.chat.context import (
    HISTORY_TURNS,
    SUMMARY_AFTER_TURNS,
    recent_history,
    rolling_summary,
)
from app.chat.faq import DIRECT_SCORE, FaqAnswerer
from app.chat.flows import ChatFlows, money
from app.chat.llm_gateway import LlmGateway
from app.chat.replies import Choice, QuickReply, Reply
from app.chat.state import SessionState
from app.chat.types import Message
from app.core.config import Settings
from app.core.deps import CurrentUser
from app.core.errors import AppError
from app.db.enums import ChatRole, ChatRoute, UserRole
from app.db.models import ChatMessage, ChatSession, KbDocument, Patient
from app.services.appointments import AppointmentService
from app.services.availability import AvailabilityService
from app.services.guest import GuestService
from app.services.knowledge.embeddings import Embedder
from app.services.knowledge.search import match_intent

logger = structlog.get_logger(__name__)

INTENT_SCORE = 0.80  # at or above: the intent is accepted
INTENT_LOW_SCORE = 0.65  # between this and INTENT_SCORE: treat as a knowledge base question
HISTORY_ROWS = 24
NOTE_MESSAGES = 3  # recent visitor messages attached to a callback request
PRICE_LIST_SIZE = 6
OPTION_PREFIX = "[option] "

QUESTION_WORDS = re.compile(
    r"^(what|when|where|which|who|whom|whose|why|how|do|does|did|can|could|is|are|am|was|were|"
    r"will|would|should|may|might|have|has|tell|explain|i'?d like to know|i want to know)\b",
    re.IGNORECASE,
)
FLOW_STARTERS = {"start_booking", "start_reschedule", "start_cancel", "handoff", "callback"}
KB_TEMPLATES = {"hours": "office-hours", "location": "location-and-directions"}
TEMPLATE_OVERRIDE_SCORE = 0.70  # another document this close beats the generic template
# Questions about a policy or a price mention the same words as the action ("cancel", "book")
# but want an answer, not a conversation flow.
POLICY_QUESTION = re.compile(
    r"\b(policy|policies|fees?|charges?|charged|rules?|terms|penalt\w+|refund\w*|deadline|"
    r"notice|how (much|long|early|far|soon)|what happens|what if|cost|costs|price|prices|"
    r"pricing|insurance|cover(ed|age)?|allowed|window)\b",
    re.IGNORECASE,
)
BOOKING_WORDS = re.compile(
    r"\b(book|booking|schedule|appointment|appt|reserve|come in|see (a|the|dr)|visit)\b",
    re.IGNORECASE,
)
OTHER_ACTIONS = re.compile(
    r"\b(resched\w*|cancel\w*|move|change|postpone|push back|delay|running late)\b",
    re.IGNORECASE,
)
INTERRUPTIBLE = {"greeting", "thanks", "hours", "location", "pricing", "insurance", "faq_procedure"}


def looks_like_booking(text: str, parsed: entities.Parsed) -> bool:
    """A request to book that already names what it wants, without needing the vector match."""
    if POLICY_QUESTION.search(text) or OTHER_ACTIONS.search(text):
        return False
    if parsed.service is not None and parsed.found >= 2:
        return True
    return bool(BOOKING_WORDS.search(text)) and parsed.found >= 1


def looks_like_question(text: str) -> bool:
    return "?" in text or bool(QUESTION_WORDS.match(text.strip())) or len(text.split()) >= 3


@dataclass
class TurnResult:
    reply: Reply
    user_message_id: uuid.UUID
    assistant_message_id: uuid.UUID
    flow: str | None
    step: str | None


class ChatRouter:
    def __init__(
        self,
        *,
        db: AsyncSession,
        settings: Settings,
        redis: Redis,
        embedder: Embedder,
        gateway: LlmGateway | None,
        appointments: AppointmentService,
        availability: AvailabilityService,
        guests: GuestService,
    ) -> None:
        self.db = db
        self.settings = settings
        self.redis = redis
        self.embedder = embedder
        self.gateway = gateway
        self.appointments = appointments
        self.availability = availability
        self.guests = guests

    # --- starting a conversation ----------------------------------------------------------------

    async def open_session(self, session: ChatSession) -> TurnResult:
        reply = replies.greeting(self.settings)
        reply.intent = "session_open"
        assistant = self._store(
            session.id, ChatRole.ASSISTANT, reply.text, reply, datetime.now(UTC)
        )
        self.db.add(assistant)
        await self.db.commit()
        return TurnResult(reply, assistant.id, assistant.id, None, None)

    # --- one turn -----------------------------------------------------------------------------------

    async def handle(
        self,
        session: ChatSession,
        text: str,
        choice: Choice | None,
        current_user: CurrentUser | None,
    ) -> TurnResult:
        state = SessionState.load(session.state)
        before = state.dump()
        patient = await self._identify(session, state, current_user)
        flows = ChatFlows(
            db=self.db,
            settings=self.settings,
            redis=self.redis,
            session_id=session.id,
            state=state,
            appointments=self.appointments,
            availability=self.availability,
            guests=self.guests,
            patient=patient,
            user=current_user if patient is not None and current_user else None,
        )
        history_rows = await self._history_rows(session.id)
        stored_text, reply = await self._reply(session, state, flows, history_rows, text, choice)
        if reply.intent == "error":  # the turn failed part way: keep the state as it was
            state = SessionState.load(before)
        state.user_turns += 1
        return await self._finish(session, state, stored_text, reply, history_rows)

    async def _reply(
        self,
        session: ChatSession,
        state: SessionState,
        flows: ChatFlows,
        history_rows: list[tuple[str, str]],
        raw: str,
        choice: Choice | None,
    ) -> tuple[str, Reply]:
        """The text to store for the visitor's message, and the assistant's reply."""
        if choice is None and len(raw) > self.settings_message_limit:
            return "[message too long]", replies.too_long(self.settings_message_limit)
        text = safety.clean_text(raw)
        if choice is None and not text:
            return "", replies.empty_message()
        text, _ = safety.mask_pii(text)
        in_code_step = state.flow is not None and state.flow.step in ("otp", "verify_code")
        stored = "[code]" if in_code_step else text
        if choice is not None:
            label, _ = safety.mask_pii(safety.clean_text(choice.label))
            shown = label or f"{choice.kind}:{choice.value}"
            return f"{OPTION_PREFIX}{shown}"[:200], await self._guarded(
                session, state, flows, history_rows, "", choice
            )
        if safety.is_emergency(text):
            return stored, replies.emergency(self.settings)
        if safety.looks_like_injection(text):
            return stored, replies.blocked(self.settings)
        return stored, await self._guarded(session, state, flows, history_rows, text, None)

    @property
    def settings_message_limit(self) -> int:
        return safety.MAX_MESSAGE_CHARS

    async def _guarded(
        self,
        session: ChatSession,
        state: SessionState,
        flows: ChatFlows,
        history_rows: list[tuple[str, str]],
        text: str,
        choice: Choice | None,
    ) -> Reply:
        """Route the turn. A failure anywhere becomes a polite message, never an error."""
        try:
            return await self._route(session, state, flows, history_rows, text, choice)
        except AppError as error:
            if error.status_code in (429, 503) or error.code == "embeddings_unavailable":
                await self._recover(session)
                return replies.technical_problem(self.settings)
            raise
        except Exception:
            logger.exception("chat_turn_failed", session=str(session.id))
            await self._recover(session)
            return replies.technical_problem(self.settings)

    async def _recover(self, session: ChatSession) -> None:
        await self.db.rollback()
        await self.db.refresh(session)

    async def _route(
        self,
        session: ChatSession,
        state: SessionState,
        flows: ChatFlows,
        history_rows: list[tuple[str, str]],
        text: str,
        choice: Choice | None,
    ) -> Reply:
        answerer = FaqAnswerer(
            db=self.db,
            embedder=self.embedder,
            gateway=self.gateway,
            redis=self.redis,
            settings=self.settings,
            session_id=session.id,
        )
        history = recent_history(
            [(r, c) for r, c in history_rows if not c.startswith(OPTION_PREFIX)], HISTORY_TURNS
        )

        async def interrupt(message: str) -> Reply | None:
            return await self._interruption(message, flows, answerer, history, session)

        flows.interrupt = interrupt
        note = self._note(history_rows, text)

        if choice is not None:
            return await self._on_choice(state, flows, answerer, history, session, choice, note)
        if state.flow is not None:
            return await flows.handle(text, None)
        return await self._on_text(state, flows, answerer, history, session, text, note)

    # --- choices ----------------------------------------------------------------------------------------

    async def _on_choice(
        self,
        state: SessionState,
        flows: ChatFlows,
        answerer: FaqAnswerer,
        history: list[Message],
        session: ChatSession,
        choice: Choice,
        note: str,
    ) -> Reply:
        if choice.kind == "action":
            value = choice.value
            if value == "start_booking":
                return await flows.start("book")
            if value == "start_reschedule":
                return await flows.start("reschedule")
            if value == "start_cancel":
                return await flows.start("cancel")
            if value in ("handoff", "callback"):
                return await flows.start("handoff", source=value, note=note)
            if value == "manage":
                return Reply(
                    "What would you like to do with your appointment?",
                    intent="manage",
                    quick_replies=[
                        QuickReply("Reschedule", "action", "start_reschedule"),
                        QuickReply("Cancel it", "action", "start_cancel"),
                    ],
                )
            if state.flow is None and value in ("hours", "prices"):
                question = (
                    "What are your opening hours?" if value == "hours" else "What are your prices?"
                )
                return await self._on_text(state, flows, answerer, history, session, question, note)
            if state.flow is None and value in ("exit_flow", "restart"):
                return replies.greeting(self.settings)
        if state.flow is not None:
            return await flows.handle("", choice)
        return replies.greeting(self.settings)

    # --- free text ----------------------------------------------------------------------------------------

    async def _on_text(
        self,
        state: SessionState,
        flows: ChatFlows,
        answerer: FaqAnswerer,
        history: list[Message],
        session: ChatSession,
        text: str,
        note: str,
    ) -> Reply:
        if safety.asks_for_medical_advice(text):
            return replies.medical_advice(self.settings)
        services, dentists = await flows.services(), await flows.dentists()
        parsed = entities.parse_message(text, services, dentists, flows.today, flows.tz)
        if looks_like_booking(text, parsed):
            return await self._start_booking(
                text, flows, state, session_id=answerer.session_id, parsed=parsed
            )
        match = await match_intent(self.db, self.embedder, text)
        summary = session.summary
        if match is not None and match.score >= INTENT_SCORE:
            return await self._dispatch(
                match.intent, text, state, flows, answerer, history, summary, note
            )
        if looks_like_question(text):
            # Not a known intent with confidence: ask the knowledge base. If it has nothing
            # relevant, the fallback answer says so and offers a person.
            return await answerer.answer(text, history=history, summary=summary)
        return replies.cannot_answer(self.settings)

    async def _dispatch(
        self,
        intent: str,
        text: str,
        state: SessionState,
        flows: ChatFlows,
        answerer: FaqAnswerer,
        history: list[Message],
        summary: str | None,
        note: str,
    ) -> Reply:
        if intent == "greeting":
            return replies.greeting(self.settings)
        if intent == "thanks":
            return replies.thanks()
        if intent == "emergency":
            return replies.urgent(self.settings)
        if intent == "out_of_scope":
            return replies.out_of_scope(self.settings)
        if intent in KB_TEMPLATES:
            return await self._from_document(intent, KB_TEMPLATES[intent], text, answerer)
        if intent == "pricing":
            return await self._pricing(text, flows, answerer, history, summary)
        if intent in ("book", "reschedule", "cancel") and POLICY_QUESTION.search(text):
            return await answerer.answer(text, history=history, summary=summary)
        if intent == "book":
            return await self._start_booking(text, flows, state, session_id=answerer.session_id)
        if intent == "reschedule":
            return await flows.start("reschedule")
        if intent == "cancel":
            return await flows.start("cancel")
        if intent == "human_handoff":
            return await flows.start("handoff", source="handoff", note=note)
        return await answerer.answer(text, history=history, summary=summary)

    async def _interruption(
        self,
        text: str,
        flows: ChatFlows,
        answerer: FaqAnswerer,
        history: list[Message],
        session: ChatSession,
    ) -> Reply | None:
        """A question typed in the middle of a flow. Returns None when it is not one."""
        if safety.asks_for_medical_advice(text):
            return replies.medical_advice(self.settings)
        match = await match_intent(self.db, self.embedder, text)
        if match is None or match.score < INTENT_SCORE:
            return None
        if match.intent == "emergency":
            return replies.urgent(self.settings)
        if match.intent == "human_handoff":
            reply = await flows.start("handoff", source="handoff")
            reply.intent = "flow_switch"
            return reply
        if match.intent not in INTERRUPTIBLE:
            return None
        if match.intent == "greeting":
            return None
        return await self._dispatch(
            match.intent, text, flows.state, flows, answerer, history, session.summary, ""
        )

    async def _start_booking(
        self,
        text: str,
        flows: ChatFlows,
        state: SessionState,
        *,
        session_id: uuid.UUID | None,
        parsed: entities.Parsed | None = None,
    ) -> Reply:
        services, dentists = await flows.services(), await flows.dentists()
        if parsed is None:
            parsed = entities.parse_message(text, services, dentists, flows.today, flows.tz)
        calls = 0
        if entities.needs_model(parsed) and self.gateway is not None:
            extraction, calls = await entities.extract_with_model(
                self.gateway, text, services, session_id=session_id
            )
            if extraction is not None:
                parsed = entities.apply_extraction(
                    parsed, extraction, services, dentists, flows.today, flows.tz
                )
        reply = await flows.start("book", parsed)
        if state.flow is not None:
            state.flow.extraction_used = calls > 0
        reply.llm_calls += calls
        return reply

    # --- templates filled from the database --------------------------------------------------------------

    async def _from_document(
        self, intent: str, slug: str, text: str, answerer: FaqAnswerer
    ) -> Reply:
        hits = await answerer.search(text)
        if hits and hits[0].slug != slug and hits[0].score >= TEMPLATE_OVERRIDE_SCORE:
            # The question is really about something more specific, such as parking.
            return await answerer.answer(text, hits=hits, direct_score=TEMPLATE_OVERRIDE_SCORE)
        document = (
            await self.db.execute(select(KbDocument).where(KbDocument.slug == slug))
        ).scalar_one_or_none()
        if document is None or not document.short_answer:
            return await answerer.answer(text, hits=hits)
        return Reply(
            document.short_answer,
            route=ChatRoute.RULE,
            intent=intent,
            links=[replies.Link("Contact and hours", "/contact")],
            quick_replies=[replies.BOOK_CHIP],
        )

    async def _pricing(
        self,
        text: str,
        flows: ChatFlows,
        answerer: FaqAnswerer,
        history: list[Message],
        summary: str | None,
    ) -> Reply:
        services = await flows.services()
        service, _ = entities.match_service(text, services)
        if service is not None:
            return Reply(
                f"{service.name} is {money(service.price)} and takes about "
                f"{service.duration_min} minutes. The final cost depends on your exam and on "
                "your insurance.",
                route=ChatRoute.RULE,
                intent="pricing",
                links=[replies.Link("Pricing", "/pricing")],
                quick_replies=[replies.BOOK_CHIP],
            )
        hits = await answerer.search(text)
        if hits and hits[0].score >= DIRECT_SCORE:  # a stored price page answers it exactly
            return await answerer.answer(text, history=history, summary=summary, hits=hits)
        listed = ", ".join(f"{s.name} {money(s.price)}" for s in services[:PRICE_LIST_SIZE])
        return Reply(
            f"Here are some of our usual prices: {listed}. The final cost depends on your exam "
            "and your insurance.",
            route=ChatRoute.RULE,
            intent="pricing",
            links=[replies.Link("Full price list", "/pricing")],
            quick_replies=[replies.BOOK_CHIP],
        )

    # --- who is chatting -----------------------------------------------------------------------------------

    async def _identify(
        self, session: ChatSession, state: SessionState, current_user: CurrentUser | None
    ) -> Patient | None:
        """The patient this conversation may act for: the signed in one, or a mailbox that
        was just verified with a one time code."""
        if (
            current_user is not None
            and session.user_id == current_user.id
            and current_user.role is UserRole.PATIENT
        ):
            return (
                await self.db.execute(select(Patient).where(Patient.user_id == current_user.id))
            ).scalar_one_or_none()
        if state.verified is not None:
            if state.verified.valid():
                return await self.db.get(Patient, uuid.UUID(state.verified.patient_id))
            state.verified = None
        return None

    # --- storing the turn ---------------------------------------------------------------------------------------

    async def _history_rows(self, session_id: uuid.UUID) -> list[tuple[str, str]]:
        rows = (
            await self.db.execute(
                select(ChatMessage.role, ChatMessage.content)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.desc())
                .limit(HISTORY_ROWS)
            )
        ).all()
        return [(role.value, content) for role, content in reversed(rows)]

    @staticmethod
    def _note(history_rows: list[tuple[str, str]], text: str) -> str:
        said = [c for r, c in history_rows if r == "user" and not c.startswith(OPTION_PREFIX)]
        said = [*said, text][-NOTE_MESSAGES:]
        return " | ".join(m[:200] for m in said if m)

    def _store(
        self,
        session_id: uuid.UUID,
        role: ChatRole,
        content: str,
        reply: Reply | None,
        when: datetime,
    ) -> ChatMessage:
        return ChatMessage(
            id=uuid.uuid4(),
            session_id=session_id,
            role=role,
            content=content,
            intent=reply.intent if reply else None,
            route=reply.route if reply and role is ChatRole.ASSISTANT else None,
            llm_calls=reply.llm_calls if reply and role is ChatRole.ASSISTANT else 0,
            payload=reply.payload() if reply and role is ChatRole.ASSISTANT else None,
            created_at=when,
        )

    async def _finish(
        self,
        session: ChatSession,
        state: SessionState,
        stored_text: str,
        reply: Reply,
        history_rows: list[tuple[str, str]],
    ) -> TurnResult:
        now = datetime.now(UTC)
        user_message = self._store(session.id, ChatRole.USER, stored_text, reply, now)
        user_message.intent = reply.intent
        assistant = self._store(
            session.id, ChatRole.ASSISTANT, reply.text, reply, now + timedelta(milliseconds=1)
        )
        self.db.add_all([user_message, assistant])

        if state.user_turns > SUMMARY_AFTER_TURNS:
            older = [
                c
                for r, c in history_rows
                if r == "user" and not c.startswith(OPTION_PREFIX) and not c.startswith("[")
            ][: -HISTORY_TURNS or None]
            session.summary = rolling_summary(older)
        if reply.provider:
            session.provider_last = reply.provider
        session.state = state.dump()
        await self.db.commit()
        flow = state.flow
        return TurnResult(
            reply,
            user_message.id,
            assistant.id,
            flow.name if flow else None,
            flow.step if flow else None,
        )
