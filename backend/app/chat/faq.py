"""Answering questions from the knowledge base: stored answers first, a model only when needed."""

import hashlib
import json
import re
import uuid
from urllib.parse import urlparse

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import replies
from app.chat.budget import PURPOSE_BUDGETS, Purpose, estimate_tokens, limit_to_tokens
from app.chat.context import SUMMARY_MAX_TOKENS, fit_history
from app.chat.llm_gateway import LlmGateway
from app.chat.replies import Link, Reply
from app.chat.safety import neutralize_delimiters
from app.chat.types import GatewayError, Message
from app.core.config import Settings
from app.db.enums import ChatRoute
from app.db.models import KbDocument
from app.services.knowledge.embeddings import Embedder
from app.services.knowledge.search import SearchHit, search_kb

DIRECT_SCORE = 0.82  # at or above: return the stored short answer, no model
ANSWER_MIN_SCORE = 0.65  # below: the knowledge base has nothing useful
CONTEXT_CHUNKS = 2
CONTEXT_TOKENS = 350
ANSWER_MAX_TOKENS = 160
ANSWER_MAX_SENTENCES = 3
ANSWER_MAX_CHARS = 600
CACHE_SECONDS = 24 * 3600
CLINICAL_CATEGORIES = frozenset(
    {"procedures", "aftercare", "oral-health", "pediatric-comfort", "emergency"}
)

_URL = re.compile(r"(?:https?://|www\.)[^\s)\]>]+", re.IGNORECASE)
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)")
_SHINGLE = 6


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)[-10:]


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def allowed_hosts(settings: Settings) -> set[str]:
    hosts = {urlparse(settings.public_base_url).hostname or ""}
    if "@" in settings.clinic_email:
        hosts.add(settings.clinic_email.split("@", 1)[1].lower())
    return {h.lower() for h in hosts if h}


def validate_answer(text: str, settings: Settings, system_prompt: str) -> str | None:
    """Check a model's reply. Returns the text to show, or None when it must not be shown.

    Rejects replies that repeat the system prompt or quote a phone number the clinic does not
    own. Removes web links outside the clinic's own site and email addresses other than its
    own, then limits the length.
    """
    cleaned = text.strip()
    if not cleaned:
        return None
    words = re.findall(r"[a-z0-9']+", cleaned.lower())
    prompt_words = re.findall(r"[a-z0-9']+", system_prompt.lower())
    prompt_shingles = {
        tuple(prompt_words[i : i + _SHINGLE]) for i in range(len(prompt_words) - _SHINGLE + 1)
    }
    if any(tuple(words[i : i + _SHINGLE]) in prompt_shingles for i in range(len(words))):
        return None
    own_numbers = {digits(settings.clinic_phone), digits(settings.clinic_emergency_phone)}
    if any(digits(m.group()) not in own_numbers for m in _PHONE.finditer(cleaned)):
        return None

    hosts = allowed_hosts(settings)

    def keep_link(match: re.Match[str]) -> str:
        url = match.group()
        host = urlparse(url if "//" in url else f"//{url}").hostname or ""
        return url if host.lower() in hosts else ""

    cleaned = _MARKDOWN_LINK.sub(lambda m: m.group(1), cleaned)
    cleaned = _URL.sub(keep_link, cleaned)
    cleaned = _EMAIL.sub(
        lambda m: m.group() if m.group().lower() == settings.clinic_email.lower() else "",
        cleaned,
    )
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    kept = sentences(cleaned)[:ANSWER_MAX_SENTENCES]
    cleaned = " ".join(kept)
    if len(cleaned) > ANSWER_MAX_CHARS:
        cleaned = cleaned[:ANSWER_MAX_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "."
    return cleaned or None


def cache_key(question: str, hits: list[SearchHit]) -> str:
    """The same question over the same stored text. Editing a document changes its chunks, so
    the cached answer stops being found without any explicit invalidation."""
    normal = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", question.lower())).strip()
    chunks = ",".join(str(h.chunk.id) for h in hits[:CONTEXT_CHUNKS])
    return "chat:faq:" + hashlib.sha256(f"{normal}|{chunks}".encode()).hexdigest()


def build_question_message(
    question: str, hits: list[SearchHit], summary: str | None
) -> tuple[str, str]:
    """The one user message carrying the context, the summary and the question, delimited."""
    context = limit_to_tokens(
        "\n\n".join(h.chunk.text for h in hits[:CONTEXT_CHUNKS]), CONTEXT_TOKENS
    )
    note = f"Earlier: {limit_to_tokens(summary, SUMMARY_MAX_TOKENS)}\n" if summary else ""
    body = (
        f"<context>\n{neutralize_delimiters(context)}\n</context>\n{note}"
        f"<question>\n{neutralize_delimiters(question)}\n</question>"
    )
    return body, context


class FaqAnswerer:
    def __init__(
        self,
        *,
        db: AsyncSession,
        embedder: Embedder,
        gateway: LlmGateway | None,
        redis: Redis,
        settings: Settings,
        session_id: uuid.UUID | None,
    ) -> None:
        self.db = db
        self.embedder = embedder
        self.gateway = gateway
        self.redis = redis
        self.settings = settings
        self.session_id = session_id

    async def search(self, question: str) -> list[SearchHit]:
        return await search_kb(self.db, self.embedder, question, 3)

    async def answer(
        self,
        question: str,
        *,
        history: list[Message] | None = None,
        summary: str | None = None,
        hits: list[SearchHit] | None = None,
        direct_score: float = DIRECT_SCORE,
    ) -> Reply:
        hits = hits if hits is not None else await self.search(question)
        if not hits or hits[0].score < ANSWER_MIN_SCORE:
            return replies.cannot_answer(self.settings)
        top = hits[0]
        document = await self.db.get(KbDocument, top.document_id)
        short = document.short_answer if document and document.short_answer else None
        link = [Link("Read more", f"/faq?topic={top.slug}")]
        clinical = top.category in CLINICAL_CATEGORIES

        if top.score >= direct_score and short:
            return Reply(
                self.with_note(short, clinical),
                route=ChatRoute.FAQ_DIRECT,
                intent="faq",
                links=link,
                quick_replies=[replies.BOOK_CHIP] if clinical else [],
            )

        key = cache_key(question, hits)
        cached = await self.redis.get(key)
        if cached:
            return Reply(
                self.with_note(str(json.loads(cached)["text"]), clinical),
                route=ChatRoute.CACHE,
                intent="faq",
                links=link,
                quick_replies=[replies.BOOK_CHIP] if clinical else [],
            )

        if self.gateway is None:
            return self.stored_answer(short, link, clinical)

        body, _ = build_question_message(question, hits, summary)
        final = Message("user", body)
        cap = PURPOSE_BUDGETS[Purpose.FAQ_ANSWER].max_prompt_tokens
        room = cap - estimate_tokens(body) - 10
        messages = [*fit_history(history or [], max(room, 0)), final]

        async def stored() -> str | None:
            return short

        try:
            result = await self.gateway.complete(
                messages,
                max_tokens=ANSWER_MAX_TOKENS,
                purpose=Purpose.FAQ_ANSWER,
                session_id=self.session_id,
                fallback=stored,
            )
        except GatewayError:
            return self.stored_answer(short, link, clinical)

        if result.degraded:
            return Reply(
                result.text,
                route=ChatRoute.RULE,
                intent="faq_degraded",
                links=link if short else [],
                degraded=True,
            )
        text = validate_answer(result.text, self.settings, self.gateway.system_prompt)
        if text is None:
            reply = self.stored_answer(short, link, clinical)
            reply.llm_calls = 1
            return reply
        await self.redis.set(key, json.dumps({"text": text, "slug": top.slug}), ex=CACHE_SECONDS)
        return Reply(
            self.with_note(text, clinical),
            route=ChatRoute.LLM,
            intent="faq",
            links=link,
            quick_replies=[replies.BOOK_CHIP] if clinical else [],
            llm_calls=1,
            provider=result.provider,
        )

    def stored_answer(self, short: str | None, link: list[Link], clinical: bool) -> Reply:
        if short is None:
            return replies.cannot_answer(self.settings)
        return Reply(
            self.with_note(short, clinical),
            route=ChatRoute.FAQ_DIRECT,
            intent="faq",
            links=link,
        )

    @staticmethod
    def with_note(text: str, clinical: bool) -> str:
        return f"{text} {replies.CLINICAL_NOTE}" if clinical else text
