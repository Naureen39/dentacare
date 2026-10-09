"""Circuit breaker per provider, shared between processes through Redis.

After ``threshold`` consecutive failures the provider is treated as unhealthy for
``open_seconds``. When that time has passed the breaker is half open: exactly one request
is let through as a probe. A success closes the breaker, a failure opens it again.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from redis.asyncio import Redis

PROBE_TIMEOUT_SECONDS = 30.0


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class Permit:
    allowed: bool
    probe: bool = False
    state: BreakerState = BreakerState.CLOSED


class CircuitBreaker:
    def __init__(
        self,
        redis: Redis,
        threshold: int = 3,
        open_seconds: int = 60,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.redis = redis
        self.threshold = threshold
        self.open_seconds = open_seconds
        self.clock = clock

    @staticmethod
    def _key(provider: str, name: str) -> str:
        return f"llm:cb:{provider}:{name}"

    async def _read(self, provider: str) -> tuple[int, float | None, float | None]:
        failures = int(await self.redis.get(self._key(provider, "fails")) or 0)
        until = await self.redis.get(self._key(provider, "until"))
        probe = await self.redis.get(self._key(provider, "probe"))
        return failures, float(until) if until else None, float(probe) if probe else None

    async def state(self, provider: str) -> BreakerState:
        failures, until, _ = await self._read(provider)
        if failures < self.threshold or until is None:
            return BreakerState.CLOSED
        return BreakerState.OPEN if self.clock() < until else BreakerState.HALF_OPEN

    async def allow(self, provider: str) -> Permit:
        """May a request go to this provider now? At most one probe runs while half open."""
        failures, until, probe_started = await self._read(provider)
        now = self.clock()
        if failures < self.threshold or until is None:
            return Permit(True, False, BreakerState.CLOSED)
        if now < until:
            return Permit(False, False, BreakerState.OPEN)
        # Half open: let one probe through, and recover if a probe never reported back.
        if probe_started is None or now - probe_started > PROBE_TIMEOUT_SECONDS:
            await self.redis.set(self._key(provider, "probe"), now)
            return Permit(True, True, BreakerState.HALF_OPEN)
        return Permit(False, False, BreakerState.HALF_OPEN)

    async def record_success(self, provider: str) -> None:
        await self.redis.delete(
            self._key(provider, "fails"), self._key(provider, "until"), self._key(provider, "probe")
        )

    async def record_failure(self, provider: str) -> int:
        failures = int(await self.redis.incr(self._key(provider, "fails")))
        await self.redis.expire(self._key(provider, "fails"), 24 * 3600)
        if failures >= self.threshold:
            await self.redis.set(
                self._key(provider, "until"), self.clock() + self.open_seconds, ex=24 * 3600
            )
            await self.redis.delete(self._key(provider, "probe"))
        return failures

    async def snapshot(self, provider: str) -> dict[str, object]:
        failures, until, _ = await self._read(provider)
        state = await self.state(provider)
        remaining = max(0.0, until - self.clock()) if until and state is BreakerState.OPEN else 0.0
        return {
            "state": state.value,
            "consecutive_failures": failures,
            "open_for_seconds": round(remaining, 1),
        }
