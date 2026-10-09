"""Fixtures for chat orchestration tests.

The knowledge base and the intent examples are embedded once with the real BGE model, so
thresholds such as 0.80 and 0.82 are exercised against real similarity scores. The language
model providers are scripted: every call is counted, so a test can say how many a turn cost.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import fakeredis
import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text

from app.chat.llm_gateway import LlmGateway
from app.chat.types import ProviderErrorKind
from app.main import create_app
from app.services.knowledge.embeddings import EmbeddingService
from app.services.mailer import InMemoryMailer
from app.services.queue import RecordingJobQueue
from tests.auth.conftest import CLEANUP_ORDER, Ctx, make_settings
from tests.booking.conftest import Practice
from tests.chat.conftest import FakeProvider, Outcome, fail, ok, settings_for_gateway
from tests.knowledge.conftest import MODEL_CACHE, MODEL_NAME

KEEP = {"kb_chunks", "kb_documents", "intent_examples"}
BASE = "/api/v1/chat"
PHONE = "(555) 010-0199"


async def _cleanup(ctx_session_factory: Any) -> None:
    async with ctx_session_factory() as db:
        for table in CLEANUP_ORDER:
            if table not in KEEP:
                await db.execute(text(f"DELETE FROM {table}"))  # noqa: S608
        await db.commit()


@pytest.fixture
async def ctx(indexed_kb_database: str) -> AsyncIterator[Ctx]:
    """Replaces the shared ``ctx`` for these tests: same wiring, but on the database that holds
    the real embedded knowledge base, which must survive between tests."""
    settings = make_settings(
        indexed_kb_database,
        rate_limit_chat_per_minute=1000,
        clinic_phone=PHONE,
        public_base_url="https://clinic.example",
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        redis = fakeredis.FakeAsyncRedis(decode_responses=True)
        mailer = InMemoryMailer()
        jobs = RecordingJobQueue()
        embedder = EmbeddingService(MODEL_NAME, MODEL_CACHE, redis)
        app.state.redis = redis
        app.state.mailer = mailer
        app.state.jobs = jobs
        app.state.embedder = embedder
        from httpx import ASGITransport

        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            context = Ctx(
                app=app,
                client=client,
                mailer=mailer,
                jobs=jobs,
                redis=redis,
                settings=settings,
                session_factory=app.state.session_factory,
                passwords=app.state.passwords,
            )
            context.totp_secrets = {}
            await _cleanup(context.session_factory)
            yield context
            await _cleanup(context.session_factory)
        embedder.close()
        await redis.aclose()


def reply_named(reply: dict[str, Any], label: str) -> dict[str, str]:
    """The quick reply whose label contains ``label``."""
    for option in reply["quick_replies"]:
        if label.lower() in option["label"].lower():
            return dict(option)
    labels = [q["label"] for q in reply["quick_replies"]]
    raise AssertionError(f"no button containing {label!r}; buttons: {labels}")


@dataclass
class Conversation:
    bot: "Bot"
    headers: dict[str, str]
    session_id: str = ""
    token: str = ""
    last: dict[str, Any] = field(default_factory=dict)
    replies: list[dict[str, Any]] = field(default_factory=list)

    @property
    def client(self) -> AsyncClient:
        return self.bot.ctx.client

    @property
    def auth(self) -> dict[str, str]:
        return {**self.headers, "X-Chat-Token": self.token}

    async def open(self) -> "Conversation":
        response = await self.client.post(f"{BASE}/sessions", headers=self.headers)
        assert response.status_code == 201, response.text
        body = response.json()
        self.session_id, self.token = body["session_id"], body["session_token"]
        self.last = body["greeting"]
        self.replies.append(self.last)
        return self

    async def post(self, payload: dict[str, Any], **headers: str) -> Response:
        return await self.client.post(
            f"{BASE}/sessions/{self.session_id}/messages",
            json=payload,
            headers={**self.auth, **headers},
        )

    async def say(self, text: str) -> dict[str, Any]:
        response = await self.post({"text": text})
        assert response.status_code == 200, response.text
        self.last = response.json()
        self.replies.append(self.last)
        return self.last

    async def click(self, kind: str, value: str, label: str = "") -> dict[str, Any]:
        response = await self.post({"choice": {"kind": kind, "value": value, "label": label}})
        assert response.status_code == 200, response.text
        self.last = response.json()
        self.replies.append(self.last)
        return self.last

    async def press(self, label: str, reply: dict[str, Any] | None = None) -> dict[str, Any]:
        """Click the button of the latest reply whose label contains ``label``."""
        option = reply_named(reply or self.last, label)
        return await self.click(option["kind"], option["value"], option["label"])

    async def history(self) -> dict[str, Any]:
        response = await self.client.get(f"{BASE}/sessions/{self.session_id}", headers=self.auth)
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body


@dataclass
class Bot:
    ctx: Ctx
    practice: Practice
    groq: FakeProvider
    gemini: FakeProvider
    gateway: LlmGateway

    @property
    def llm_calls(self) -> int:
        return len(self.groq.calls) + len(self.gemini.calls)

    async def conversation(self, token: str | None = None) -> Conversation:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return await Conversation(self, headers).open()

    async def patient_conversation(self) -> Conversation:
        return await self.conversation(await self.practice.patient_token())

    def script(
        self, groq: list[Outcome] | None = None, gemini: list[Outcome] | None = None
    ) -> None:
        """Replace what the providers will answer, and forget earlier calls."""
        self.groq.script = groq or [ok("Our team is happy to help with that.")]
        self.gemini.script = gemini or [ok("Our team is happy to help with that.")]
        self.groq.calls.clear()
        self.gemini.calls.clear()

    def outage(self) -> None:
        self.script([fail(ProviderErrorKind.SERVER_ERROR)], [fail(ProviderErrorKind.SERVER_ERROR)])


@pytest.fixture
async def bot(ctx: Ctx, practice: Practice) -> Bot:
    groq = FakeProvider("groq", "openai/gpt-oss-20b", script=[ok("Our team is happy to help.")])
    gemini = FakeProvider(
        "gemini", "gemini-test", "America/Los_Angeles", False, script=[ok("Gemini answer.")]
    )
    gateway = LlmGateway(
        settings=settings_for_gateway(),
        redis=ctx.redis,
        session_factory=ctx.session_factory,
        providers={"groq": groq, "gemini": gemini},
    )
    ctx.app.state.llm = gateway
    return Bot(ctx, practice, groq, gemini, gateway)
