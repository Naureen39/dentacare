"""Enqueueing background jobs from the API.

Enqueueing is best effort: the database is the source of truth and the worker's dispatcher
sweeps due reminders every minute, so a failure here only delays delivery.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

logger = structlog.get_logger(__name__)


class JobQueue(Protocol):
    async def enqueue(self, function: str, *args: Any, job_id: str | None = None) -> None: ...

    async def close(self) -> None: ...


class ArqJobQueue:
    def __init__(self, redis_dsn: str) -> None:
        self._settings = RedisSettings.from_dsn(redis_dsn)
        self._pool: ArqRedis | None = None

    async def enqueue(self, function: str, *args: Any, job_id: str | None = None) -> None:
        try:
            if self._pool is None:
                self._pool = await create_pool(self._settings)
            await self._pool.enqueue_job(function, *args, _job_id=job_id)
        except Exception:  # noqa: BLE001
            logger.warning("job_enqueue_failed", function=function, job_id=job_id)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None


@dataclass
class RecordingJobQueue:
    """Remembers what was enqueued. Used by tests."""

    jobs: list[tuple[str, tuple[Any, ...], str | None]] = field(default_factory=list)

    async def enqueue(self, function: str, *args: Any, job_id: str | None = None) -> None:
        self.jobs.append((function, args, job_id))

    async def close(self) -> None:
        return None
