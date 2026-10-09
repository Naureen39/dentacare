"""Fakes for gateway tests: scripted providers, a movable clock and Redis in memory."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import fakeredis
import pytest

from app.chat.llm_gateway import LlmGateway
from app.chat.types import Message, ProviderError, ProviderErrorKind, ProviderResponse
from app.core.config import Settings


class FakeClock:
    """A clock tests can move forward. The gateway's counters and breaker read it."""

    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


Outcome = ProviderResponse | ProviderError | Exception | Callable[[], Awaitable[ProviderResponse]]


def ok(
    text: str = "We open at 8:00 AM.",
    *,
    prompt: int = 120,
    completion: int = 20,
    cached: int = 0,
    finish: str = "stop",
    headers: dict[str, str] | None = None,
) -> ProviderResponse:
    return ProviderResponse(text, prompt, completion, cached, finish, headers or {})


def fail(
    kind: ProviderErrorKind = ProviderErrorKind.SERVER_ERROR,
    *,
    status: int | None = None,
    retry_after: float | None = None,
    headers: dict[str, str] | None = None,
) -> ProviderError:
    return ProviderError(
        kind, "failure", status_code=status, retry_after=retry_after, headers=headers
    )


@dataclass
class Call:
    system: str
    messages: list[Message]
    max_tokens: int
    json_schema: dict[str, Any] | None
    schema_name: str
    timeout: float


@dataclass
class FakeProvider:
    """Answers from a script. After the script runs out it repeats the last outcome."""

    name: str
    model: str = "fake-model"
    reset_tz: str = "UTC"
    counts_output_tokens: bool = True
    script: list[Outcome] = field(default_factory=lambda: [ok()])
    calls: list[Call] = field(default_factory=list)

    async def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
        schema_name: str,
        timeout: float,  # noqa: ASYNC109
    ) -> ProviderResponse:
        self.calls.append(
            Call(system, list(messages), max_tokens, json_schema, schema_name, timeout)
        )
        index = min(len(self.calls) - 1, len(self.script) - 1)
        outcome = self.script[index]
        if isinstance(outcome, ProviderResponse):
            return outcome
        if isinstance(outcome, Exception):
            raise outcome
        return await outcome()


def settings_for_gateway(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "llm_primary": "groq",
        "llm_timeout_seconds": 0.2,
        "clinic_phone": "(555) 010-0199",
        "public_base_url": "https://clinic.example",
    }
    values.update(overrides)
    return Settings(**values)


@dataclass
class Rig:
    gateway: LlmGateway
    groq: FakeProvider
    gemini: FakeProvider
    clock: FakeClock
    redis: fakeredis.FakeAsyncRedis


RigFactory = Callable[..., Rig]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def redis() -> AsyncIterator[fakeredis.FakeAsyncRedis]:
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def make_rig(clock: FakeClock, redis: fakeredis.FakeAsyncRedis) -> RigFactory:
    def build(
        groq: list[Outcome] | None = None,
        gemini: list[Outcome] | None = None,
        *,
        session_factory: Any = None,
        providers: tuple[str, ...] = ("groq", "gemini"),
        **settings: Any,
    ) -> Rig:
        groq_provider = FakeProvider(
            "groq", "openai/gpt-oss-20b", script=groq or [ok("groq answer")]
        )
        gemini_provider = FakeProvider(
            "gemini",
            "gemini-test",
            "America/Los_Angeles",
            counts_output_tokens=False,
            script=gemini or [ok("gemini answer")],
        )
        available = {"groq": groq_provider, "gemini": gemini_provider}
        gateway = LlmGateway(
            settings=settings_for_gateway(**settings),
            redis=redis,
            session_factory=session_factory,
            providers={name: available[name] for name in providers},
            clock=clock,
        )
        return Rig(gateway, groq_provider, gemini_provider, clock, redis)

    return build


async def never_returns() -> ProviderResponse:
    await asyncio.sleep(30)
    return ok()
