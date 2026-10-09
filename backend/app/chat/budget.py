"""Token budgets per purpose and local rate limit accounting per provider.

Providers publish limits (requests and tokens per minute and per day). The gateway keeps its
own counters in Redis, shared by all API processes, so it can move to the other provider
before the first provider starts refusing requests.
"""

import math
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast
from zoneinfo import ZoneInfo

from redis.asyncio import Redis


class Purpose(StrEnum):
    ENTITY_EXTRACTION = "entity_extraction"
    FAQ_ANSWER = "faq_answer"
    FALLBACK_REPHRASE = "fallback_rephrase"


@dataclass(frozen=True)
class PurposeBudget:
    max_prompt_tokens: int
    max_completion_tokens: int
    max_calls: int


# The token budget table of the chatbot design. Enforced by the gateway and covered by tests.
PURPOSE_BUDGETS: dict[Purpose, PurposeBudget] = {
    Purpose.ENTITY_EXTRACTION: PurposeBudget(350, 80, 1),
    Purpose.FAQ_ANSWER: PurposeBudget(700, 160, 1),
    Purpose.FALLBACK_REPHRASE: PurposeBudget(300, 100, 1),
}
SYSTEM_PROMPT_MAX_TOKENS = 250

_TOKEN = re.compile(r"\w+|[^\w\s]")


def estimate_tokens(text: str) -> int:
    """A cheap upper leaning estimate of the token count, without loading a tokenizer."""
    return max(len(_TOKEN.findall(text)), math.ceil(len(text) / 4))


def limit_to_tokens(text: str, limit: int) -> str:
    """Cut text down to roughly ``limit`` tokens, ending on a sentence boundary when possible."""
    if estimate_tokens(text) <= limit:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept: list[str] = []
    for sentence in sentences:
        if estimate_tokens(" ".join([*kept, sentence])) > limit:
            break
        kept.append(sentence)
    if kept:
        return " ".join(kept)
    words = text.split()
    while words and estimate_tokens(" ".join(words)) > limit:
        words.pop()
    return " ".join(words)


@dataclass(frozen=True)
class ProviderLimits:
    """Published limits. ``None`` means the limit is unknown and is not enforced locally."""

    rpm: int | None = None
    rpd: int | None = None
    tpm: int | None = None
    tpd: int | None = None


@dataclass(frozen=True)
class Usage:
    rpm: int
    tpm: int
    rpd: int
    tpd: int


@dataclass(frozen=True)
class Utilization:
    """The worst case share of any limit this call would use, and which limit it is."""

    ratio: float
    limit: str | None


def parse_duration(value: str | None) -> float | None:
    """Parse durations such as ``7.66s``, ``2m59.56s`` or ``1h2m3s`` into seconds."""
    if not value:
        return None
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", value.strip())
    if not parts or "".join(f"{n}{u}" for n, u in parts) != value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    factors = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}
    return sum(float(n) * factors[u] for n, u in parts)


class BudgetTracker:
    """Sliding minute window and per day counters, plus corrections from provider headers."""

    WINDOW_SECONDS = 60

    def __init__(self, redis: Redis, clock: Callable[[], float] = time.time) -> None:
        self.redis = redis
        self.clock = clock

    # --- keys ---

    @staticmethod
    def _minute_key(provider: str) -> str:
        return f"llm:b:{provider}:minute"

    def _day_key(self, provider: str, tz: str) -> str:
        local = datetime.fromtimestamp(self.clock(), UTC).astimezone(ZoneInfo(tz))
        return f"llm:b:{provider}:day:{local:%Y%m%d}"

    # --- reading ---

    async def usage(self, provider: str, tz: str) -> Usage:
        now = self.clock()
        minute_key = self._minute_key(provider)
        await self.redis.zremrangebyscore(minute_key, "-inf", now - self.WINDOW_SECONDS)
        members = await self.redis.zrange(minute_key, 0, -1)
        rpm = len(members)
        tpm = sum(int(str(m).rsplit(":", 1)[1]) for m in members)
        day: dict[str, str] = await cast(
            "Awaitable[dict[str, str]]", self.redis.hgetall(self._day_key(provider, tz))
        )
        rpd, tpd = int(day.get("req", 0)), int(day.get("tok", 0))

        # The provider's own numbers win when they are higher than ours: other processes or
        # other applications may share the same key.
        server_tpm = await self.redis.get(f"llm:b:{provider}:srv_tpm")
        server_rpd = await self.redis.get(f"llm:b:{provider}:srv_rpd")
        if server_tpm is not None:
            tpm = max(tpm, int(float(server_tpm)))
        if server_rpd is not None:
            rpd = max(rpd, int(float(server_rpd)))
        return Usage(rpm, tpm, rpd, tpd)

    async def utilization(
        self, provider: str, limits: ProviderLimits, tz: str, estimated_tokens: int
    ) -> Utilization:
        """The highest share of any limit that would be used once this call is counted."""
        usage = await self.usage(provider, tz)
        candidates = [
            ("rpm", usage.rpm + 1, limits.rpm),
            ("rpd", usage.rpd + 1, limits.rpd),
            ("tpm", usage.tpm + estimated_tokens, limits.tpm),
            ("tpd", usage.tpd + estimated_tokens, limits.tpd),
        ]
        worst = Utilization(0.0, None)
        for name, used, limit in candidates:
            if limit:
                ratio = used / limit
                if ratio > worst.ratio:
                    worst = Utilization(ratio, name)
        return worst

    # --- writing ---

    async def record(self, provider: str, tz: str, tokens: int) -> None:
        """Count one finished request and the tokens it used against all windows."""
        now = self.clock()
        minute_key = self._minute_key(provider)
        await self.redis.zadd(minute_key, {f"{uuid.uuid4().hex}:{max(tokens, 0)}": now})
        await self.redis.zremrangebyscore(minute_key, "-inf", now - self.WINDOW_SECONDS)
        await self.redis.expire(minute_key, self.WINDOW_SECONDS * 2)
        day_key = self._day_key(provider, tz)
        pipe = self.redis.pipeline()
        pipe.hincrby(day_key, "req", 1)
        pipe.hincrby(day_key, "tok", max(tokens, 0))
        pipe.expire(day_key, 48 * 3600)
        await pipe.execute()

    async def apply_server_hints(
        self,
        provider: str,
        *,
        limit_tokens: int | None,
        remaining_tokens: int | None,
        reset_tokens_seconds: float | None,
        limit_requests: int | None,
        remaining_requests: int | None,
        reset_requests_seconds: float | None,
    ) -> None:
        """Correct our counters with what the provider says is used (from response headers)."""
        if None not in (limit_tokens, remaining_tokens):
            used = max(int(limit_tokens or 0) - int(remaining_tokens or 0), 0)
            ttl = max(1, math.ceil(reset_tokens_seconds or self.WINDOW_SECONDS))
            await self.redis.set(f"llm:b:{provider}:srv_tpm", used, ex=ttl)
        if None not in (limit_requests, remaining_requests):
            used = max(int(limit_requests or 0) - int(remaining_requests or 0), 0)
            ttl = max(1, math.ceil(reset_requests_seconds or 3600))
            await self.redis.set(f"llm:b:{provider}:srv_rpd", used, ex=min(ttl, 48 * 3600))
