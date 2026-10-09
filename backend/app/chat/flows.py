"""The booking, rescheduling, cancellation and callback conversations.

Each is a small state machine. The interface shows buttons and pickers for every step, so most
input is a click. Times always come from the availability service and confirmations always use
fixed wording: no model is involved here, except for one optional extraction call made by the
router before a booking starts.
"""

import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import entities
from app.chat.entities import DentistInfo, Parsed, ServiceInfo
from app.chat.replies import (
    EXIT_CHIP,
    HANDOFF_CHIP,
    Choice,
    Link,
    QuickReply,
    Reply,
    handoff_done,
    menu_chips,
)
from app.chat.safety import wants_to_exit, wants_to_restart
from app.chat.state import FlowName, FlowState, SessionState, VerifiedIdentity
from app.core.config import Settings
from app.core.deps import CurrentUser
from app.core.errors import AppError
from app.db.enums import AppointmentChannel, InquirySource
from app.db.models import (
    Appointment,
    ContactInquiry,
    Dentist,
    DentistService,
    Patient,
    Service,
)
from app.services import holds
from app.services.appointments import CANCELLABLE, AppointmentService
from app.services.availability import AvailabilityService, Slot
from app.services.guest import GuestService
from app.services.notifications import format_when

MAX_CHIPS = 8
DAY_CHIPS = 7
SEARCH_DAYS = 28  # the availability service accepts at most 31 days at a time
MISSES_BEFORE_HELP = 3

Interrupt = Callable[[str], Awaitable[Reply | None]]

_YES = re.compile(
    r"^\s*(yes|yeah|yep|yup|sure|ok|okay|confirm|confirmed|correct|right|go ahead|do it|"
    r"book it|that'?s right|looks good|sounds good|please do|i agree|agree|i do|absolutely)\b",
    re.IGNORECASE,
)
_NO = re.compile(r"^\s*(no|nope|nah|don'?t|do not|not really|i disagree|disagree)\b", re.I)
_EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
_NAME_PREFIX = re.compile(
    r"^\s*(?:my name is|my name'?s|name is|name:|i am|i'm|im|it'?s|this is|call me)\s+", re.I
)
_NAME_PART = re.compile(r"^[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’.\-]*$")
_PHONE = re.compile(r"^[\d\s().+\-]{7,20}$")
_CODE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def is_yes(text: str) -> bool:
    return bool(_YES.match(text))


def is_no(text: str) -> bool:
    return bool(_NO.match(text))


def money(amount: Decimal) -> str:
    return f"${amount:,.0f}" if amount == amount.to_integral() else f"${amount:,.2f}"


def clock(moment: datetime, tz: ZoneInfo) -> str:
    local = moment.astimezone(tz)
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def day_label(day: date) -> str:
    return f"{day:%a}, {day:%b} {day.day}"


def long_day(day: date) -> str:
    return f"{day:%A}, {day:%B} {day.day}"


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


class ChatFlows:
    def __init__(
        self,
        *,
        db: AsyncSession,
        settings: Settings,
        redis: Redis,
        session_id: uuid.UUID,
        state: SessionState,
        appointments: AppointmentService,
        availability: AvailabilityService,
        guests: GuestService,
        patient: Patient | None,
        user: CurrentUser | None,
        interrupt: Interrupt | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.redis = redis
        self.session_id = session_id
        self.state = state
        self.appointments = appointments
        self.availability = availability
        self.guests = guests
        self.patient = patient
        self.user = user
        self.interrupt = interrupt
        self.tz = ZoneInfo(settings.clinic_tz)
        self._services: list[ServiceInfo] | None = None
        self._dentists: list[DentistInfo] | None = None

    # --- reference data -----------------------------------------------------------------------

    @property
    def today(self) -> date:
        return datetime.now(UTC).astimezone(self.tz).date()

    async def services(self) -> list[ServiceInfo]:
        if self._services is None:
            rows = (
                await self.db.execute(
                    select(Service)
                    .where(Service.is_active.is_(True))
                    .order_by(Service.display_order, Service.name)
                )
            ).scalars()
            self._services = [
                ServiceInfo(
                    s.id, s.name, s.code, s.category, s.duration_min, s.base_price, s.display_order
                )
                for s in rows
            ]
        return self._services

    async def dentists(self) -> list[DentistInfo]:
        if self._dentists is None:
            rows = (
                await self.db.execute(
                    select(Dentist).where(Dentist.is_active.is_(True)).order_by(Dentist.full_name)
                )
            ).scalars()
            self._dentists = [DentistInfo(d.id, d.full_name) for d in rows]
        return self._dentists

    async def dentists_for(self, service_id: str) -> list[DentistInfo]:
        ids = set(
            (
                await self.db.execute(
                    select(DentistService.dentist_id).where(
                        DentistService.service_id == uuid.UUID(service_id)
                    )
                )
            ).scalars()
        )
        return [d for d in await self.dentists() if d.id in ids]

    async def service(self, service_id: str) -> ServiceInfo | None:
        return next((s for s in await self.services() if str(s.id) == service_id), None)

    @property
    def signed_in(self) -> bool:
        return self.user is not None and self.patient is not None

    # --- entering and leaving -------------------------------------------------------------------

    async def start(
        self,
        name: FlowName,
        parsed: Parsed | None = None,
        *,
        source: str | None = None,
        note: str | None = None,
        notice: str | None = None,
    ) -> Reply:
        await self.release_hold()
        flow = FlowState(name=name, step="start", source=source, note=note)
        self.state.flow = flow
        if name == "book":
            self.state.mark("started")
            if parsed is not None:
                await self.apply_parsed(flow, parsed)
                notice = notice or self.understood(flow, parsed)
        return await self.advance(flow, notice)

    def understood(self, flow: FlowState, parsed: Parsed) -> str | None:
        """Say back what was picked up from the visitor's sentence, so a mistake is visible."""
        parts = []
        if flow.service_name:
            parts.append(flow.service_name)
        if flow.dentist_name:
            parts.append(f"with {flow.dentist_name}")
        if flow.day:
            parts.append(f"on {long_day(date.fromisoformat(flow.day))}")
        if flow.time_pref:
            parts.append(
                {
                    "morning": "in the morning",
                    "afternoon": "in the afternoon",
                    "evening": "in the evening",
                }.get(flow.time_pref, f"around {flow.time_pref}")
            )
        text = f"Got it: {' '.join(parts)}." if parts else ""
        if parsed.past_date:
            text = f"{text} That date has already passed.".strip()
        return text or None

    async def exit(self, message: str = "No problem, I have stopped that. Anything else?") -> Reply:
        await self.release_hold()
        self.state.flow = None
        return Reply(message, intent="flow_exit", quick_replies=menu_chips())

    async def release_hold(self) -> None:
        flow = self.state.flow
        if flow and flow.hold_token and flow.start and flow.slot_dentist_id:
            await holds.release(
                self.redis, uuid.UUID(flow.slot_dentist_id), datetime.fromisoformat(flow.start)
            )
            flow.hold_token = None

    async def apply_parsed(self, flow: FlowState, parsed: Parsed) -> None:
        """Fill the flow with whatever the rules or the model found in the visitor's text."""
        if parsed.service:
            flow.service_id, flow.service_name = str(parsed.service.id), parsed.service.name
        if parsed.dentist and flow.service_id:
            eligible = {d.id for d in await self.dentists_for(flow.service_id)}
            if parsed.dentist.id in eligible:
                flow.dentist_id = str(parsed.dentist.id)
                flow.dentist_name = parsed.dentist.full_name
                flow.dentist_decided = True
        elif parsed.any_dentist:
            flow.dentist_decided = True
        if parsed.day and not parsed.past_date:
            flow.day = parsed.day.isoformat()
        if parsed.time_pref:
            flow.time_pref = parsed.time_pref

    # --- the common entry for a visitor's input ----------------------------------------------------

    async def handle(self, text: str, choice: Choice | None) -> Reply:
        flow = self.state.flow
        if flow is None:
            return await self.exit("There is nothing in progress. How can I help?")
        try:
            return await self._dispatch(flow, text, choice)
        except AppError as error:
            return await self._on_error(flow, error)

    async def _dispatch(self, flow: FlowState, text: str, choice: Choice | None) -> Reply:
        if choice is not None:
            if choice.kind == "action":
                reply = await self._on_action(flow, choice.value)
                if reply is not None:
                    return reply
            return await self._on_choice(flow, choice)
        if wants_to_exit(text):
            return await self.exit()
        if wants_to_restart(text):
            return await self.start(flow.name, source=flow.source, note=flow.note)
        return await self._on_text(flow, text)

    async def _on_action(self, flow: FlowState, value: str) -> Reply | None:
        if value == "exit_flow":
            return await self.exit()
        if value == "restart":
            return await self.start(flow.name, source=flow.source, note=flow.note)
        if value in ("callback", "handoff"):
            await self.release_hold()
            return await self.start("handoff", source=value, note=flow.note)
        if value == "start_booking":
            return await self.start("book")
        if value == "skip" and flow.step == "phone":
            flow.phone_done = True
            return await self.advance(flow)
        if value == "change_day":
            await self.release_hold()
            flow.day, flow.start, flow.slot_dentist_id = None, None, None
            return await self.advance(flow)
        if value == "change_time":
            await self.release_hold()
            flow.start, flow.slot_dentist_id = None, None
            return await self.advance(flow)
        if value == "change_service" and flow.name == "book":
            await self.release_hold()
            flow.service_id = flow.service_name = flow.dentist_id = flow.dentist_name = None
            flow.dentist_decided, flow.day, flow.start, flow.slot_dentist_id = (
                False,
                None,
                None,
                None,
            )
            return await self.advance(flow)
        if value == "resend_code" and flow.step in ("otp", "verify_code"):
            return await self._send_code(flow)
        return None

    async def _on_choice(self, flow: FlowState, choice: Choice) -> Reply:
        kind, value = choice.kind, choice.value
        if kind == "service" and flow.step == "service":
            service = await self.service(value)
            if service is None:
                return await self._miss(flow, "Please choose one of the services shown.")
            flow.service_id, flow.service_name = str(service.id), service.name
            return await self.advance(flow)
        if kind == "dentist" and flow.step == "dentist":
            if value == "any":
                flow.dentist_id = flow.dentist_name = None
            else:
                dentist = next((d for d in await self.dentists() if str(d.id) == value), None)
                if dentist is None:
                    return await self._miss(flow, "Please choose one of the dentists shown.")
                flow.dentist_id, flow.dentist_name = str(dentist.id), dentist.full_name
            flow.dentist_decided = True
            return await self.advance(flow)
        if kind == "date" and flow.step == "day":
            try:
                chosen = date.fromisoformat(value)
            except ValueError:
                return await self._miss(flow, "Please choose one of the days shown.")
            flow.day = chosen.isoformat()
            return await self.advance(flow)
        if kind == "time_pref" and flow.step == "time":
            flow.time_pref = value
            return await self.advance(flow)
        if kind == "slot" and flow.step == "time":
            return await self._choose_slot(flow, value)
        if kind == "appointment" and flow.step == "pick":
            return await self._choose_appointment(flow, value)
        if kind == "consent" and flow.step == "consent":
            if value == "yes":
                flow.consent = True
                return await self.advance(flow)
            return await self.exit(
                "I can't book without your consent to the privacy policy and appointment "
                f"reminders. You can also book by phone at {self.settings.clinic_phone}."
            )
        if kind == "confirm" and flow.step in ("confirm", "confirm_cancel"):
            if value == "yes":
                return await self._confirmed(flow)
            return await self.exit()
        return await self._miss(flow, None)

    async def _on_text(self, flow: FlowState, text: str) -> Reply:
        step = flow.step
        if step in ("service", "dentist", "day", "time"):
            return await self._on_search_text(flow, text)
        if step == "name":
            return await self._on_name(flow, text)
        if step == "email" or step == "verify_email":
            return await self._on_email(flow, text)
        if step == "phone":
            return await self._on_phone(flow, text)
        if step == "contact":
            return await self._on_contact(flow, text)
        if step in ("otp", "verify_code"):
            return await self._on_code(flow, text)
        if step == "consent":
            if is_yes(text):
                flow.consent = True
                return await self.advance(flow)
            if is_no(text):
                return await self._on_choice(flow, Choice("consent", "no"))
            return await self._miss(flow, "Please choose I agree, or say no.")
        if step in ("confirm", "confirm_cancel"):
            if is_yes(text):
                return await self._confirmed(flow)
            if is_no(text):
                return await self.exit()
            return await self._miss(flow, "Please choose one of the options below.")
        return await self._miss(flow, None)

    # --- search steps: service, dentist, day, time ---------------------------------------------------

    async def _on_search_text(self, flow: FlowState, text: str) -> Reply:
        services, dentists = await self.services(), await self.dentists()
        parsed = entities.parse_message(text, services, dentists, self.today, self.tz)
        step = flow.step
        changed = False
        if step == "service" and parsed.service:
            await self.apply_parsed(flow, parsed)
            changed = True
        elif step == "dentist":
            if parsed.dentist or parsed.any_dentist:
                await self.apply_parsed(flow, parsed)
                changed = flow.dentist_decided
            elif is_no(text):
                flow.dentist_decided = True
                changed = True
        elif step == "day" and (parsed.day or parsed.time_pref):
            if parsed.past_date:
                return await self._miss(flow, "That date has already passed.", count=False)
            await self.apply_parsed(flow, parsed)
            changed = bool(flow.day)
        elif step == "time" and (parsed.time_pref or parsed.day):
            if parsed.past_date:
                return await self._miss(flow, "That date has already passed.", count=False)
            if parsed.day:
                await self.release_hold()
                flow.day = parsed.day.isoformat()
            if parsed.time_pref:
                flow.time_pref = parsed.time_pref
            changed = True
        if changed:
            flow.misses = 0
            return await self.advance(flow)
        return await self._try_interrupt(flow, text, "")

    async def _miss(self, flow: FlowState, hint: str | None, *, count: bool = True) -> Reply:
        """The input did not fit. Try answering it as a general question, then ask again."""
        if count:
            flow.misses += 1
        if flow.misses >= MISSES_BEFORE_HELP:
            reply = await self.render(flow)
            reply.text = (
                "I'm having trouble understanding. Please use the options shown, or I can "
                f"pass you to our team.\n\n{reply.text}"
            )
            reply.quick_replies = [*reply.quick_replies, HANDOFF_CHIP]
            return reply
        reply = await self.render(flow)
        if hint:
            reply.text = f"{hint} {reply.text}"
        return reply

    async def interrupted(self, flow: FlowState, text: str) -> Reply | None:
        """A question asked in the middle of a flow: answer it, then repeat the step."""
        if self.interrupt is None:
            return None
        answer = await self.interrupt(text)
        if answer is None:
            return None
        if answer.intent in ("flow_switch", "emergency"):  # the conversation changed course
            return answer
        prompt = await self.render(flow)
        answer.text = f"{answer.text}\n\nBack to your request: {prompt.text}"
        answer.quick_replies = prompt.quick_replies
        answer.picker, answer.input_hint = prompt.picker, prompt.input_hint
        return answer

    # --- the next step ---------------------------------------------------------------------------------

    def next_step(self, flow: FlowState) -> str:
        if flow.name == "handoff":
            if self.patient is not None:
                return "done"
            if not flow.first_name:
                return "name"
            return "contact" if not (flow.email or flow.phone) else "done"
        if flow.name in ("reschedule", "cancel"):
            if self.patient is None:
                return "verify_code" if flow.verification_id else "verify_email"
            if not flow.appointment_id:
                return "pick"
            if flow.name == "cancel":
                return "confirm_cancel"
        if flow.name == "book" and not flow.service_id:
            return "service"
        if flow.name == "book" and not flow.dentist_decided:
            return "dentist"
        if not flow.day:
            return "day"
        if not flow.start:
            return "time"
        if flow.name == "book" and self.patient is None:
            if not (flow.first_name and flow.last_name):
                return "name"
            if not flow.email:
                return "email"
            if not flow.phone_done:
                return "phone"
            if not flow.consent:
                return "consent"
        return "otp" if flow.verification_id else "confirm"

    async def advance(self, flow: FlowState, notice: str | None = None) -> Reply:
        """Move to the first step that still lacks information and show it."""
        flow.misses = 0
        flow.step = self.next_step(flow)
        if flow.step == "done":
            return await self._finish_handoff(flow)
        if flow.step == "dentist" and flow.service_id:
            eligible = await self.dentists_for(flow.service_id)
            if len(eligible) <= 1:  # nothing to choose
                flow.dentist_decided = True
                if eligible:
                    flow.dentist_id, flow.dentist_name = str(eligible[0].id), eligible[0].full_name
                return await self.advance(flow, notice)
        reply = await self.render(flow)
        if notice:
            reply.text = f"{notice} {reply.text}"
        return reply

    # --- prompts ---------------------------------------------------------------------------------------

    async def render(self, flow: FlowState) -> Reply:
        step = flow.step
        chips: list[QuickReply]
        if step == "service":
            services = (await self.services())[:MAX_CHIPS]
            return Reply(
                "Which service would you like to book?",
                intent="book",
                quick_replies=[
                    *(QuickReply(s.name, "service", str(s.id)) for s in services),
                    EXIT_CHIP,
                ],
            )
        if step == "dentist":
            eligible = await self.dentists_for(flow.service_id or "") if flow.service_id else []
            return Reply(
                f"{flow.service_name}, good choice. Do you have a preferred dentist?",
                intent="book",
                quick_replies=[
                    QuickReply("No preference", "dentist", "any"),
                    *(QuickReply(d.full_name, "dentist", str(d.id)) for d in eligible[:6]),
                    QuickReply("Change service", "action", "change_service"),
                ],
            )
        if step == "day":
            return await self._render_days(flow)
        if step == "time":
            return await self._render_times(flow)
        if step == "pick":
            return await self._render_pick(flow)
        if step == "name":
            first = f"Thanks, {flow.first_name}. And your last name?" if flow.first_name else None
            return Reply(
                first or "To book, I need a few details. What is your first and last name?",
                intent="book",
                input_hint="name",
                quick_replies=[EXIT_CHIP],
            )
        if step == "email":
            return Reply(
                "What email address should we send the confirmation to?",
                intent="book",
                input_hint="email",
                quick_replies=[EXIT_CHIP],
            )
        if step == "phone":
            return Reply(
                "What phone number can we reach you on? This is optional.",
                intent="book",
                input_hint="phone",
                quick_replies=[QuickReply("Skip", "action", "skip"), EXIT_CHIP],
            )
        if step == "consent":
            return Reply(
                "To book, please confirm that you accept our privacy policy and that we may "
                "send you appointment reminders by email.",
                intent="book",
                links=[Link("Privacy policy", "/privacy")],
                quick_replies=[
                    QuickReply("I agree", "consent", "yes"),
                    QuickReply("No thanks", "consent", "no"),
                ],
            )
        if step == "confirm":
            return await self._render_confirm(flow)
        if step == "confirm_cancel":
            return await self._render_confirm_cancel(flow)
        if step == "otp":
            return Reply(
                f"I sent a 6 digit code to {mask_email(flow.email or '')}. Please type it here "
                "to confirm your booking. The code is valid for 10 minutes.",
                intent="book",
                input_hint="code",
                quick_replies=[QuickReply("Send a new code", "action", "resend_code"), EXIT_CHIP],
            )
        if step == "verify_email":
            return Reply(
                "To protect your privacy I need to check it is you. What email address is your "
                "appointment booked under? I will send a code to it. If you have an account you "
                "can also sign in first.",
                intent=flow.name,
                input_hint="email",
                quick_replies=[EXIT_CHIP],
            )
        if step == "verify_code":
            return Reply(
                f"I sent a 6 digit code to {mask_email(flow.email or '')}. Please type it here.",
                intent=flow.name,
                input_hint="code",
                quick_replies=[QuickReply("Send a new code", "action", "resend_code"), EXIT_CHIP],
            )
        if step == "contact":
            return Reply(
                "What is the best email address or phone number to reach you on?",
                intent="human_handoff",
                input_hint="contact",
                quick_replies=[EXIT_CHIP],
            )
        chips = [EXIT_CHIP]
        return Reply("How can I help?", quick_replies=chips)

    async def _search_days(self, flow: FlowState) -> list[tuple[date, list[Slot]]]:
        dentist = uuid.UUID(flow.dentist_id) if flow.dentist_id else None
        days = await self.availability.search(
            uuid.UUID(flow.service_id or ""),
            self.today,
            self.today + timedelta(days=SEARCH_DAYS - 1),
            dentist_id=dentist,
            use_cache=True,
        )
        return [(d.date, d.slots) for d in days if d.slots]

    async def _render_days(self, flow: FlowState) -> Reply:
        days = await self._search_days(flow)
        if not days:
            return Reply(
                "I can't see any openings in the next four weeks for that. I can pass your "
                "request to our team, or you can call "
                f"{self.settings.clinic_phone}.",
                intent="book",
                quick_replies=[
                    QuickReply("Request a callback", "action", "callback"),
                    QuickReply("Change service", "action", "change_service"),
                    EXIT_CHIP,
                ],
            )
        chips = [
            QuickReply(f"{day_label(d)} ({len(slots)} open)", "date", d.isoformat())
            for d, slots in days[:DAY_CHIPS]
        ]
        return Reply(
            "Which day suits you? Pick one, or type a date such as 'next Tuesday'.",
            intent="book",
            picker="date",
            quick_replies=[*chips, EXIT_CHIP],
        )

    def _choose_times(self, slots: list[Slot], pref: str | None) -> list[Slot]:
        """Up to ``MAX_CHIPS`` slots, filtered or ordered by the visitor's time preference."""
        wanted = slots
        target = entities.minutes_of(pref) if pref else None
        if pref and target is None:
            matching = [
                s
                for s in slots
                if entities.slot_matches_pref(
                    s.start.astimezone(self.tz).hour, s.start.astimezone(self.tz).minute, pref
                )
            ]
            wanted = matching or slots
        unique: dict[datetime, Slot] = {}
        for slot in wanted:
            unique.setdefault(slot.start, slot)  # one dentist per time when it is left open
        ordered = sorted(unique.values(), key=lambda s: s.start)
        if target is not None:

            def distance(slot: Slot) -> int:
                local = slot.start.astimezone(self.tz)
                return abs(local.hour * 60 + local.minute - target)

            ordered = sorted(sorted(ordered, key=distance)[:MAX_CHIPS], key=lambda s: s.start)
        elif len(ordered) > MAX_CHIPS:
            step = len(ordered) / MAX_CHIPS
            ordered = [ordered[int(i * step)] for i in range(MAX_CHIPS)]
        return ordered[:MAX_CHIPS]

    async def _render_times(self, flow: FlowState) -> Reply:
        day = date.fromisoformat(flow.day or "")
        dentist = uuid.UUID(flow.dentist_id) if flow.dentist_id else None
        found = await self.availability.search(
            uuid.UUID(flow.service_id or ""), day, day, dentist_id=dentist, use_cache=True
        )
        slots = [s for d in found for s in d.slots]
        if not slots:
            flow.day = None
            flow.step = "day"
            reply = await self._render_days(flow)
            reply.text = f"There are no openings on {long_day(day)}. {reply.text}"
            return reply
        pref = flow.time_pref
        chosen = self._choose_times(slots, pref)
        multiple = len({s.dentist_id for s in slots}) > 1 and dentist is None
        chips = [
            QuickReply(
                f"{clock(s.start, self.tz)}" + (f" with {s.dentist_name}" if multiple else ""),
                "slot",
                f"{s.start.isoformat()}|{s.dentist_id}",
            )
            for s in chosen
        ]
        extra: list[QuickReply] = []
        if pref is None and len(slots) > MAX_CHIPS:
            extra = [
                QuickReply("Mornings", "time_pref", "morning"),
                QuickReply("Afternoons", "time_pref", "afternoon"),
            ]
            if any(s.start.astimezone(self.tz).hour >= 17 for s in slots):
                extra.append(QuickReply("Evenings", "time_pref", "evening"))
        elif pref is not None:
            extra = [QuickReply("Show all times", "time_pref", "")]
        return Reply(
            f"Here are some available times on {long_day(day)}. Pick one, or type a time.",
            intent=flow.name if flow.name != "book" else "book",
            picker="slot",
            quick_replies=[
                *chips,
                *extra,
                QuickReply("Another day", "action", "change_day"),
                EXIT_CHIP,
            ],
        )

    async def _render_confirm(self, flow: FlowState) -> Reply:
        start = datetime.fromisoformat(flow.start or "")
        service = await self.service(flow.service_id or "")
        when = format_when(start, self.tz)
        who = f" with {flow.slot_dentist_name}" if flow.slot_dentist_name else ""
        detail = ""
        if service is not None:
            detail = f" ({service.duration_min} minutes, {money(Decimal(service.price))})"
        verb = "Move your appointment to" if flow.name == "reschedule" else "Book"
        return Reply(
            f"{verb} {flow.service_name}{who} on {when}{detail}? "
            + (
                "I will email you a code to confirm."
                if flow.name == "book" and not (self.patient or self.state.verified)
                else ""
            ),
            intent=flow.name,
            quick_replies=[
                QuickReply("Confirm", "confirm", "yes"),
                QuickReply("Change time", "action", "change_time"),
                EXIT_CHIP,
            ],
        )

    async def _render_confirm_cancel(self, flow: FlowState) -> Reply:
        appointment = await self._load_appointment(flow)
        view = (await self.appointments.present([appointment]))[0]
        note = (
            f"It is free to cancel until {format_when(view.free_cancellation_until, self.tz)}."
            if view.free_cancellation_until > datetime.now(UTC)
            else "This is inside our free cancellation period, so it will be noted as a late "
            "cancellation."
        )
        return Reply(
            f"Cancel your {view.service_name} with {view.dentist_name} on "
            f"{format_when(view.start, self.tz)}? {note}",
            intent="cancel",
            quick_replies=[
                QuickReply("Yes, cancel it", "confirm", "yes"),
                QuickReply("Keep it", "action", "exit_flow"),
            ],
        )

    async def _render_pick(self, flow: FlowState) -> Reply:
        appointments = await self._upcoming(self.patient)
        if not appointments:
            self.state.flow = None
            return Reply(
                "I could not find an upcoming appointment to change. You can book a new one, or "
                f"call us at {self.settings.clinic_phone}.",
                intent=flow.name,
                quick_replies=menu_chips(),
            )
        views = await self.appointments.present(appointments)
        flow.shown = [str(a.id) for a in appointments]
        verb = "move" if flow.name == "reschedule" else "cancel"
        return Reply(
            f"Which appointment would you like to {verb}?",
            intent=flow.name,
            quick_replies=[
                *(
                    QuickReply(
                        f"{v.service_name}, {format_when(v.start, self.tz).rsplit(' ', 1)[0]}",
                        "appointment",
                        str(v.id),
                    )
                    for v in views
                ),
                EXIT_CHIP,
            ],
        )

    # --- choosing a time ---------------------------------------------------------------------------------

    async def _choose_slot(self, flow: FlowState, value: str) -> Reply:
        try:
            raw_start, raw_dentist = value.split("|", 1)
            start = datetime.fromisoformat(raw_start).astimezone(UTC)
            dentist_id = uuid.UUID(raw_dentist)
        except ValueError:
            return await self._miss(flow, "Please choose one of the times shown.")
        service_id = uuid.UUID(flow.service_id or "")
        if flow.hold_token and flow.start and flow.slot_dentist_id:
            same = (
                datetime.fromisoformat(flow.start) == start
                and flow.slot_dentist_id == str(dentist_id)
                and await holds.is_valid(self.redis, dentist_id, start, flow.hold_token)
            )
            if same:
                return await self.advance(flow)
            await self.release_hold()
        if not await self.availability.is_available(service_id, dentist_id, start):
            return await self.advance(flow, "Sorry, that time has just gone.")
        token = await holds.acquire(self.redis, dentist_id, start)
        if token is None:
            return await self.advance(flow, "Someone else is booking that time right now.")
        dentist = next((d for d in await self.dentists() if d.id == dentist_id), None)
        flow.start = start.isoformat()
        flow.slot_dentist_id = str(dentist_id)
        flow.slot_dentist_name = dentist.full_name if dentist else None
        flow.hold_token = token
        self.state.mark("slot_chosen")
        return await self.advance(flow)

    async def _ensure_hold(self, flow: FlowState) -> bool:
        """Keep the chosen time reserved. The hold lasts five minutes, typing a form can take
        longer, so take it again if it lapsed and the time is still free."""
        dentist_id = uuid.UUID(flow.slot_dentist_id or "")
        start = datetime.fromisoformat(flow.start or "")
        if flow.hold_token and await holds.is_valid(self.redis, dentist_id, start, flow.hold_token):
            return True
        if not await self.availability.is_available(
            uuid.UUID(flow.service_id or ""), dentist_id, start
        ):
            return False
        token = await holds.acquire(self.redis, dentist_id, start)
        flow.hold_token = token
        return token is not None

    # --- text steps ----------------------------------------------------------------------------------------

    async def _on_name(self, flow: FlowState, text: str) -> Reply:
        cleaned = _NAME_PREFIX.sub("", text).strip(" .,!")
        parts = cleaned.split()
        if not 1 <= len(parts) <= 5 or not all(_NAME_PART.match(p) for p in parts):
            return await self._try_interrupt(
                flow, text, "Please type your name using letters only."
            )
        if flow.first_name and len(parts) == 1:
            flow.last_name = parts[0].title()
        elif len(parts) == 1:
            flow.first_name = parts[0].title()
            flow.last_name = None
        else:
            flow.first_name = parts[0].title()
            flow.last_name = " ".join(parts[1:]).title()
        return await self.advance(flow)

    async def _on_email(self, flow: FlowState, text: str) -> Reply:
        match = _EMAIL.search(text)
        if not match:
            return await self._try_interrupt(
                flow, text, "That does not look like an email address."
            )
        flow.email = match.group().lower()
        if flow.step == "verify_email":
            return await self._send_code(flow)
        return await self.advance(flow)

    async def _on_phone(self, flow: FlowState, text: str) -> Reply:
        if re.match(r"^\s*(skip|no|none|n/?a|no thanks)\s*$", text, re.I):
            flow.phone_done = True
            return await self.advance(flow)
        if not _PHONE.match(text.strip()) or len(re.sub(r"\D", "", text)) < 7:
            return await self._try_interrupt(
                flow, text, "That does not look like a phone number. You can also skip this."
            )
        flow.phone = text.strip()
        flow.phone_done = True
        return await self.advance(flow)

    async def _on_contact(self, flow: FlowState, text: str) -> Reply:
        email = _EMAIL.search(text)
        if email:
            flow.email = email.group().lower()
        elif _PHONE.match(text.strip()) and len(re.sub(r"\D", "", text)) >= 7:
            flow.phone = text.strip()
        else:
            return await self._try_interrupt(
                flow, text, "Please give an email address or phone number."
            )
        return await self.advance(flow)

    async def _try_interrupt(self, flow: FlowState, text: str, hint: str) -> Reply:
        flow.misses += 1
        answered = await self.interrupted(flow, text)
        if answered is not None:
            return answered
        return await self._miss(flow, hint, count=False)

    # --- one time codes -----------------------------------------------------------------------------------------

    async def _send_code(self, flow: FlowState) -> Reply:
        verification = await self.guests.request_code(flow.email or "", flow.first_name or "there")
        flow.verification_id = str(verification.id)
        flow.step = "verify_code" if flow.name != "book" else "otp"
        return await self.render(flow)

    async def _on_code(self, flow: FlowState, text: str) -> Reply:
        match = _CODE.search(text)
        if not match:
            return await self._try_interrupt(flow, text, "The code has 6 digits.")
        verification = await self.guests.verify_code(
            uuid.UUID(flow.verification_id or ""), flow.email or "", match.group(1)
        )
        verification.consumed_at = datetime.now(UTC)
        if flow.name == "book":
            return await self._book(flow)
        patient = await self._patient_by_email(flow.email or "")
        await self.db.commit()
        flow.verification_id = None
        if patient is None:
            self.state.flow = None
            return Reply(
                "Thank you. I could not find any appointments under that address. You can book "
                f"a new visit, or call us at {self.settings.clinic_phone}.",
                intent=flow.name,
                quick_replies=menu_chips(),
            )
        self.patient = patient
        self.state.verified = VerifiedIdentity.issue(str(patient.id))
        flow.step = "pick"
        return await self.advance(flow, "Thank you, you are verified.")

    async def _patient_by_email(self, email: str) -> Patient | None:
        return (
            await self.db.execute(
                select(Patient)
                .where(func.lower(Patient.email) == email.lower())
                .order_by(Patient.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()

    # --- acting on the patient's behalf ----------------------------------------------------------------------------

    async def _upcoming(self, patient: Patient | None) -> list[Appointment]:
        if patient is None:
            return []
        starts_at = func.lower(Appointment.slot)
        return list(
            (
                await self.db.execute(
                    select(Appointment)
                    .where(
                        Appointment.patient_id == patient.id,
                        Appointment.status.in_(CANCELLABLE),
                        starts_at > datetime.now(UTC),
                    )
                    .order_by(starts_at)
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )

    async def _load_appointment(self, flow: FlowState) -> Appointment:
        appointment = await self.appointments.get(uuid.UUID(flow.appointment_id or ""), lock=True)
        if self.patient is None or appointment.patient_id != self.patient.id:
            raise AppError("not_found", "Appointment not found.", 404)
        return appointment

    async def _choose_appointment(self, flow: FlowState, value: str) -> Reply:
        if value not in flow.shown:
            return await self._miss(flow, "Please choose one of the appointments shown.")
        flow.appointment_id = value
        appointment = await self._load_appointment(flow)
        if flow.name == "reschedule":
            flow.service_id = str(appointment.service_id)
            service = await self.service(flow.service_id)
            flow.service_name = service.name if service else "your appointment"
            flow.dentist_id = str(appointment.dentist_id)
            dentist = next(
                (d for d in await self.dentists() if d.id == appointment.dentist_id), None
            )
            flow.dentist_name = dentist.full_name if dentist else None
            flow.dentist_decided = True
        return await self.advance(flow)

    async def _confirmed(self, flow: FlowState) -> Reply:
        if flow.name == "cancel":
            return await self._cancel(flow)
        if not await self._ensure_hold(flow):
            flow.start, flow.slot_dentist_id, flow.hold_token = None, None, None
            return await self.advance(flow, "Sorry, that time is no longer available.")
        if flow.name == "book" and not (self.patient or self.state.verified):
            return await self._send_code(flow)
        if flow.name == "reschedule":
            return await self._reschedule(flow)
        return await self._book(flow)

    async def _book(self, flow: FlowState) -> Reply:
        if not await self._ensure_hold(flow):
            flow.start, flow.slot_dentist_id, flow.hold_token = None, None, None
            flow.verification_id = None
            return await self.advance(flow, "Sorry, that time is no longer available.")
        service = (
            await self.db.execute(
                select(Service).where(Service.id == uuid.UUID(flow.service_id or ""))
            )
        ).scalar_one()
        patient = self.patient
        if patient is None:
            patient = await self.guests.patient_for_guest(
                email=flow.email or "",
                first_name=flow.first_name or "",
                last_name=flow.last_name or "",
                phone=flow.phone,
                marketing=flow.marketing,
            )
        appointment = await self.appointments.book(
            patient=patient,
            service=service,
            dentist_id=uuid.UUID(flow.slot_dentist_id or ""),
            start=datetime.fromisoformat(flow.start or ""),
            channel=AppointmentChannel.CHATBOT,
            actor=self.user,
            reason_note=None,
            hold_token=flow.hold_token,
            require_hold=True,
            enforce_rules=True,
        )
        self.state.mark("confirmed")
        self.state.flow = None
        view = (await self.appointments.present([appointment]))[0]
        return Reply(
            f"You are booked: {view.service_name} with {view.dentist_name} on "
            f"{format_when(view.start, self.tz)}. A confirmation is on its way to your email. "
            f"If you need to change anything, ask me or call {self.settings.clinic_phone}.",
            intent="book_done",
            quick_replies=[QuickReply("Done", "action", "exit_flow")],
        )

    async def _reschedule(self, flow: FlowState) -> Reply:
        appointment = await self._load_appointment(flow)
        patient = self.patient
        if patient is None:  # _load_appointment already refused this, kept as a plain check
            raise AppError("not_found", "Appointment not found.", 404)
        new = await self.appointments.reschedule_own(
            appointment,
            patient,
            self.user,
            start=datetime.fromisoformat(flow.start or ""),
            dentist_id=uuid.UUID(flow.slot_dentist_id or ""),
            hold_token=flow.hold_token or "",
        )
        self.state.flow = None
        view = (await self.appointments.present([new]))[0]
        return Reply(
            f"Done. Your {view.service_name} with {view.dentist_name} is now on "
            f"{format_when(view.start, self.tz)}.",
            intent="reschedule_done",
        )

    async def _cancel(self, flow: FlowState) -> Reply:
        appointment = await self._load_appointment(flow)
        cancelled = await self.appointments.cancel(appointment, self.user, "Cancelled in chat")
        self.state.flow = None
        view = (await self.appointments.present([cancelled]))[0]
        late = (
            " Because this was inside the free cancellation period, it is noted as a late "
            "cancellation."
            if cancelled.late_cancel
            else ""
        )
        return Reply(
            f"Your {view.service_name} on {format_when(view.start, self.tz)} has been "
            f"cancelled.{late} Would you like to book another time?",
            intent="cancel_done",
            quick_replies=[QuickReply("Book a new time", "action", "start_booking")],
        )

    async def _finish_handoff(self, flow: FlowState) -> Reply:
        patient = self.patient
        name = patient.first_name if patient else (flow.first_name or "there")
        full = (
            f"{patient.first_name} {patient.last_name}"
            if patient
            else (f"{flow.first_name or ''} {flow.last_name or ''}".strip() or "Chat visitor")
        )
        email = (patient.email if patient else flow.email) or None
        phone = flow.phone
        source = (
            InquirySource.CALLBACK_REQUEST
            if flow.source == "callback"
            else InquirySource.CHATBOT_HANDOFF
        )
        message = "Requested through the chat assistant."
        if flow.note:
            message += f" Recent messages: {flow.note}"
        self.db.add(
            ContactInquiry(
                name=full, email=email, phone=phone, message=message[:2000], source=source
            )
        )
        await self.db.commit()
        self.state.flow = None
        reply = handoff_done(self.settings, name)
        reply.links = [Link("Contact and hours", "/contact")]
        return reply

    # --- failures from the services --------------------------------------------------------------------------------

    async def _on_error(self, flow: FlowState, error: AppError) -> Reply:
        code = error.code
        if code in ("slot_unavailable", "hold_expired", "slot_held"):
            await self.release_hold()
            flow.start, flow.slot_dentist_id, flow.hold_token = None, None, None
            flow.verification_id = None
            return await self.advance(
                flow, "Sorry, that time was just taken. Here are the times that are still open."
            )
        if code == "patient_double_booked":
            self.state.flow = None
            return Reply(
                "You already have an appointment that overlaps that time. Please choose a "
                "different time.",
                intent=flow.name,
                quick_replies=menu_chips(),
            )
        if code == "otp_invalid":
            remaining = (error.details or {}).get("attempts_remaining")
            suffix = f" You have {remaining} tries left." if remaining is not None else ""
            reply = await self.render(flow)
            reply.text = f"That code is not right.{suffix} {reply.text}"
            return reply
        if code == "otp_locked":
            flow.verification_id = None
            flow.step = "verify_email" if flow.name != "book" else "confirm"
            return Reply(
                "Too many incorrect codes. I can send you a new one.",
                intent=flow.name,
                quick_replies=[QuickReply("Send a new code", "action", "resend_code"), EXIT_CHIP],
            )
        if error.status_code == 429:
            return Reply(
                "You have asked for a few codes already. Please wait a little before trying "
                f"again, or call us at {self.settings.clinic_phone}.",
                intent=flow.name,
                quick_replies=[EXIT_CHIP],
            )
        if code == "invalid_transition":
            self.state.flow = None
            return Reply(
                "That appointment can no longer be changed online. Please call "
                f"{self.settings.clinic_phone}.",
                intent=flow.name,
                quick_replies=menu_chips(),
            )
        if code == "not_found":
            self.state.flow = None
            return Reply(
                "I could not find that appointment.",
                intent=flow.name,
                quick_replies=menu_chips(),
            )
        raise error
