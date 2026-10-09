"""Reading booking details out of free text.

A rule based parser runs first and costs nothing. A model is asked only when the text carries
several words the rules could not place, and the model's answer is resolved by the same code
(dates are never computed by the model).
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import dateparser
from pydantic import BaseModel, ConfigDict

from app.chat.budget import Purpose, estimate_tokens, limit_to_tokens
from app.chat.llm_gateway import LlmGateway
from app.chat.safety import neutralize_delimiters
from app.chat.types import GatewayError, Message

NO_PREFERENCE = "any"
TimePref = str  # "morning", "afternoon", "evening" or a 24 hour "HH:MM"

# --- vocabulary ----------------------------------------------------------------------------------

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "for",
        "to",
        "with",
        "on",
        "in",
        "at",
        "by",
        "my",
        "me",
        "i",
        "we",
        "us",
        "you",
        "your",
        "our",
        "is",
        "are",
        "am",
        "be",
        "been",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "there",
        "here",
        "please",
        "can",
        "could",
        "would",
        "will",
        "shall",
        "may",
        "might",
        "should",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "want",
        "wanna",
        "need",
        "like",
        "looking",
        "hoping",
        "trying",
        "try",
        "get",
        "make",
        "set",
        "schedule",
        "book",
        "booking",
        "appointment",
        "appointments",
        "visit",
        "slot",
        "time",
        "date",
        "day",
        "sometime",
        "some",
        "any",
        "something",
        "someone",
        "anyone",
        "anything",
        "would",
        "love",
        "prefer",
        "preferably",
        "possible",
        "possibly",
        "if",
        "when",
        "what",
        "which",
        "who",
        "how",
        "about",
        "around",
        "after",
        "before",
        "next",
        "coming",
        "also",
        "then",
        "so",
        "just",
        "only",
        "really",
        "very",
        "much",
        "as",
        "from",
        "up",
        "out",
        "into",
        "over",
        "under",
        "again",
        "still",
        "yes",
        "yeah",
        "ok",
        "okay",
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank",
        "dr",
        "doctor",
        "dentist",
        "see",
        "seeing",
        "see",
        "me",
        "morning",
        "afternoon",
        "evening",
        "noon",
        "am",
        "pm",
        "o'clock",
        "oclock",
        "at",
    ]
)

# Words patients use, mapped to one canonical word so "cleaning" finds "Hygiene Visit".
SYNONYMS: dict[str, str] = {
    "clean": "cleaning",
    "cleanings": "cleaning",
    "scale": "cleaning",
    "scaling": "cleaning",
    "polish": "cleaning",
    "polishing": "cleaning",
    "hygiene": "cleaning",
    "hygienist": "cleaning",
    "prophylaxis": "cleaning",
    "checkup": "routine",
    "check-up": "routine",
    "check": "routine",
    "examination": "exam",
    "exams": "exam",
    "checkups": "routine",
    "whiten": "whitening",
    "whitened": "whitening",
    "bleach": "whitening",
    "bleaching": "whitening",
    "crowns": "crown",
    "cap": "crown",
    "caps": "crown",
    "fillings": "filling",
    "cavity": "filling",
    "cavities": "filling",
    "endodontic": "canal",
    "endodontics": "canal",
    "extract": "extraction",
    "extractions": "extraction",
    "pulled": "extraction",
    "implants": "implant",
    "xray": "x-ray",
    "xrays": "x-ray",
    "x-rays": "x-ray",
    "radiograph": "x-ray",
    "aligners": "aligner",
    "invisalign": "aligner",
    "braces": "aligner",
    "consult": "consultation",
    "consultations": "consultation",
    "emergencies": "emergency",
    "urgent": "emergency",
    "kids": "child",
    "kid": "child",
    "children": "child",
    "childs": "child",
    "pediatric": "child",
    "paediatric": "child",
}
WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}  # fmt: skip
MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
]
_MONTH = "(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + ")"
_WEEKDAY = "(?:" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + ")"

_WORD = re.compile(r"[a-z0-9][a-z0-9'\-]*")
_NO_PREFERENCE = re.compile(
    r"\b(any ?(one|dentist|doctor)?|no preference|doesn'?t matter|don'?t mind|whoever|"
    r"anyone|first available|no one in particular|either)\b",
    re.IGNORECASE,
)


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def canon(word: str) -> str:
    return SYNONYMS.get(word, word)


# --- services and dentists -----------------------------------------------------------------------


@dataclass(frozen=True)
class ServiceInfo:
    id: uuid.UUID
    name: str
    code: str
    category: str
    duration_min: int
    price: Any
    order: int = 0


@dataclass(frozen=True)
class DentistInfo:
    id: uuid.UUID
    full_name: str


def _service_tokens(service: ServiceInfo) -> set[str]:
    return {canon(w) for w in words(service.name) if w not in STOPWORDS}


def rank_services(text: str, services: list[ServiceInfo]) -> list[tuple[ServiceInfo, int]]:
    """Services sharing words with the text, best first, with how many words they share."""
    query = {canon(w) for w in words(text) if w not in STOPWORDS}
    scored = []
    for service in services:
        shared = len(query & _service_tokens(service))
        if shared:
            scored.append((service, shared))
    scored.sort(key=lambda item: (-item[1], item[0].order, item[0].name))
    return scored


def match_service(text: str, services: list[ServiceInfo]) -> tuple[ServiceInfo | None, set[str]]:
    """The service the text is about, and the words that identified it."""
    ranked = rank_services(text, services)
    if not ranked:
        return None, set()
    # A tie between different services is settled by the clinic's own display order, which
    # puts the common ones first. The booking summary shows the choice and lets it change.
    best = ranked[0][0]
    used = {w for w in words(text) if canon(w) in _service_tokens(best)}
    return best, used


def match_dentist(text: str, dentists: list[DentistInfo]) -> tuple[DentistInfo | None, set[str]]:
    query = set(words(text))
    best: DentistInfo | None = None
    best_hits: set[str] = set()
    for dentist in dentists:
        names = {w for w in words(dentist.full_name) if w not in {"dr", "doctor"} and len(w) >= 3}
        hits = query & names
        if hits and len(hits) > len(best_hits):
            best, best_hits = dentist, hits
    return best, best_hits | ({"dr", "doctor"} & query if best else set())


def wants_any_dentist(text: str) -> bool:
    return bool(_NO_PREFERENCE.search(text))


# --- time of day -----------------------------------------------------------------------------------

_CLOCK_AMPM = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?![a-z])", re.I)
_CLOCK_24 = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_AT_HOUR = re.compile(r"\bat (\d{1,2})(?![\d:])(?!\s*(?:st|nd|rd|th)\b)", re.I)


def parse_time_pref(text: str) -> tuple[TimePref | None, set[str]]:
    lowered = text.lower()
    match = _CLOCK_AMPM.search(lowered)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2) or 0)
        if 1 <= hour <= 12:
            pm = match.group(3).startswith("p")
            hour = hour % 12 + (12 if pm else 0)
            return f"{hour:02d}:{minute:02d}", {"am", "pm", "a.m.", "p.m."}
    match = _CLOCK_24.search(lowered)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}", set()
    if re.search(r"\bnoon\b|\bmidday\b|\blunch ?time\b", lowered):
        return "12:00", {"noon", "midday"}
    if re.search(r"\b(morning|early|first thing|before work|a\.?m\.?)\b", lowered):
        return "morning", {"morning", "early"}
    if re.search(r"\bafternoon\b|\bafter lunch\b", lowered):
        return "afternoon", {"afternoon"}
    if re.search(r"\b(evening|late|after work|after 5|night)\b", lowered):
        return "evening", {"evening", "late"}
    match = _AT_HOUR.search(lowered)
    if match and 1 <= int(match.group(1)) <= 12:
        # "at 3" with no am or pm: a dental clinic is not open at 3 in the morning.
        hour = int(match.group(1))
        return f"{hour + 12 if hour < 8 else hour:02d}:00", set()
    return None, set()


def slot_matches_pref(local_hour: int, local_minute: int, pref: TimePref | None) -> bool:
    if pref is None:
        return True
    if pref == "morning":
        return local_hour < 12
    if pref == "afternoon":
        return 12 <= local_hour < 17
    if pref == "evening":
        return local_hour >= 17
    return True  # an exact time is handled by distance, not by a filter


def minutes_of(pref: TimePref) -> int | None:
    match = re.fullmatch(r"(\d{2}):(\d{2})", pref)
    return int(match.group(1)) * 60 + int(match.group(2)) if match else None


# --- dates ------------------------------------------------------------------------------------------


def _next_weekday(today: date, weekday: int, *, strictly_after: bool) -> date:
    delta = (weekday - today.weekday()) % 7
    if delta == 0 and strictly_after:
        delta = 7
    return today + timedelta(days=delta)


def parse_date(text: str, today: date, tz: ZoneInfo) -> tuple[date | None, set[str], bool]:
    """A calendar date from words like "next Tuesday", "tomorrow" or "Oct 20".

    Returns the date, the words used, and whether the date lies in the past.
    """
    lowered = text.lower()
    found: date | None = None
    used: set[str] = set()

    if re.search(r"\bday after tomorrow\b", lowered):
        found, used = today + timedelta(days=2), {"day", "after", "tomorrow"}
    elif re.search(r"\btomorrow\b|\btmrw\b|\btmr\b", lowered):
        found, used = today + timedelta(days=1), {"tomorrow", "tmrw", "tmr"}
    elif re.search(r"\btoday\b|\btonight\b|\bthis (morning|afternoon|evening)\b", lowered):
        found, used = today, {"today", "tonight", "this"}
    elif m := re.search(r"\bin (\d{1,3}|a|an|one|two|three|four|five|six) (day|week)s?\b", lowered):
        count = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
        number = int(m.group(1)) if m.group(1).isdigit() else count[m.group(1)]
        found = today + timedelta(days=number * (7 if m.group(2) == "week" else 1))
        used = set(words(m.group(0)))
    elif re.search(r"\bnext week\b", lowered):
        found, used = _next_weekday(today, 0, strictly_after=True), {"next", "week"}
    elif re.search(r"\bthis weekend\b|\bweekend\b", lowered):
        found, used = _next_weekday(today, 5, strictly_after=False), {"this", "weekend"}
    elif m := re.search(rf"\b(?:(next|this|coming|on|by|for)\s+)?({_WEEKDAY})\b", lowered):
        # "sat" and "sun" are also ordinary words; require a clear cue for the short forms.
        name = m.group(2)
        if len(name) > 3 or m.group(1) or name in {"mon", "tue", "wed", "thu", "fri"}:
            found = _next_weekday(today, WEEKDAYS[name], strictly_after=m.group(1) != "this")
            used = {name, "next", "this", "coming", "on", "by", "for"} & set(words(m.group(0)))
            used.add(name)
    if found is None:
        candidates = re.findall(
            rf"\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?\b"
            rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\b(?:,?\s+\d{{4}})?"
            r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b\d{4}-\d{2}-\d{2}\b",
            lowered,
        )
        for candidate in candidates:
            parsed = _dateparser(candidate, today, tz)
            if parsed is not None:
                found, used = parsed, set(words(candidate))
                break
    if found is None:
        return None, set(), False
    return found, used, found < today


def _dateparser(text: str, today: date, tz: ZoneInfo) -> date | None:
    base = datetime(today.year, today.month, today.day, 9, 0)
    parsed = dateparser.parse(
        text,
        languages=["en"],
        settings={
            "TIMEZONE": str(tz),
            "RETURN_AS_TIMEZONE_AWARE": False,
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": base,
            "DATE_ORDER": "MDY",
        },
    )
    return parsed.date() if parsed else None


# --- one parser for a message ------------------------------------------------------------------------


@dataclass
class Parsed:
    service: ServiceInfo | None = None
    dentist: DentistInfo | None = None
    any_dentist: bool = False
    day: date | None = None
    past_date: bool = False
    time_pref: TimePref | None = None
    unplaced: int = 0
    used: set[str] = field(default_factory=set)

    @property
    def found(self) -> int:
        return sum(
            1
            for item in (
                self.service,
                self.dentist or self.any_dentist or None,
                self.day,
                self.time_pref,
            )
            if item
        )


def parse_message(
    text: str,
    services: list[ServiceInfo],
    dentists: list[DentistInfo],
    today: date,
    tz: ZoneInfo,
) -> Parsed:
    """Everything the rules can place in the text, and how many words were left unexplained."""
    parsed = Parsed()
    service, used_service = match_service(text, services)
    dentist, used_dentist = match_dentist(text, dentists)
    day, used_day, past = parse_date(text, today, tz)
    pref, used_pref = parse_time_pref(text)
    parsed.service, parsed.dentist, parsed.day, parsed.past_date = service, dentist, day, past
    parsed.time_pref = pref
    parsed.any_dentist = wants_any_dentist(text) and dentist is None
    parsed.used = used_service | used_dentist | used_day | used_pref
    leftover = [
        w
        for w in words(text)
        if w not in STOPWORDS and w not in parsed.used and not w.isdigit() and len(w) > 2
    ]
    parsed.unplaced = len(leftover)
    return parsed


def needs_model(parsed: Parsed) -> bool:
    """Ask the model only when several words stayed unexplained and the rules found little."""
    return parsed.unplaced >= 3 and parsed.found <= 1


# --- the model, for the hard cases --------------------------------------------------------------------


class BookingExtraction(BaseModel):
    """What the model must return. An empty string means the text did not say."""

    model_config = ConfigDict(extra="forbid")

    service: str
    dentist: str
    date_expr: str
    time_pref: Literal["", "morning", "afternoon", "evening"]


EXTRACTION_PROMPT = (
    "Read the visitor's booking request in the question block and fill the JSON fields. "
    "service: the closest name from the list, else empty. dentist: the dentist named, else "
    "empty. date_expr: the date words exactly as written, else empty. time_pref: morning, "
    "afternoon, evening or empty. Do not invent values."
)


def build_extraction_messages(text: str, services: list[ServiceInfo]) -> list[Message]:
    question = neutralize_delimiters(text)
    names = "; ".join(s.name for s in services)
    head = f"{EXTRACTION_PROMPT}\nServices: {names}\n<question>\n"
    tail = "\n</question>"
    room = 330 - estimate_tokens(head) - estimate_tokens(tail)
    if room < 40:  # a very long service list: keep the question and trim the list
        names = limit_to_tokens(names, 120)
        head = f"{EXTRACTION_PROMPT}\nServices: {names}\n<question>\n"
        room = 330 - estimate_tokens(head) - estimate_tokens(tail)
    return [Message("user", head + limit_to_tokens(question, max(room, 40)) + tail)]


async def extract_with_model(
    gateway: LlmGateway,
    text: str,
    services: list[ServiceInfo],
    *,
    session_id: uuid.UUID | None,
) -> tuple[BookingExtraction | None, int]:
    """One extraction call. Returns the result (None when degraded) and the calls made."""
    try:
        result = await gateway.complete(
            build_extraction_messages(text, services),
            max_tokens=80,
            json_schema=BookingExtraction,
            purpose=Purpose.ENTITY_EXTRACTION,
            session_id=session_id,
            fallback=_no_fallback,
        )
    except GatewayError:
        return None, 0
    if result.degraded or not isinstance(result.parsed, BookingExtraction):
        return None, 0
    return result.parsed, 1


async def _no_fallback() -> str | None:
    return None


def apply_extraction(
    parsed: Parsed,
    extraction: BookingExtraction,
    services: list[ServiceInfo],
    dentists: list[DentistInfo],
    today: date,
    tz: ZoneInfo,
) -> Parsed:
    """Merge the model's fields into what the rules found. The rules win where they found."""
    if parsed.service is None and extraction.service:
        parsed.service = (
            next(
                (s for s in services if s.name.lower() == extraction.service.strip().lower()), None
            )
            or match_service(extraction.service, services)[0]
        )
    if parsed.dentist is None and extraction.dentist:
        parsed.dentist = match_dentist(extraction.dentist, dentists)[0]
    if parsed.day is None and extraction.date_expr:
        day, _, past = parse_date(extraction.date_expr, today, tz)
        parsed.day, parsed.past_date = day, past
    if parsed.time_pref is None and extraction.time_pref:
        parsed.time_pref = extraction.time_pref
    return parsed
