"""Short lived slot holds kept in Redis while a person completes the booking form.

A hold is a key ``hold:<dentist>:<start>`` created with SET NX and a five minute TTL whose
value is a secret token. Booking must present the token. An index sorted set lets the
availability search hide held slots without scanning keys. The database exclusion
constraint remains the final guard against double booking.
"""

import hmac
import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis

from app.core.security import generate_token

HOLD_TTL_SECONDS = 300
HOLD_INDEX = "holds:index"


def hold_key(dentist_id: uuid.UUID, start: datetime) -> str:
    return f"hold:{dentist_id}:{start.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}"


async def acquire(redis: Redis, dentist_id: uuid.UUID, start: datetime) -> str | None:
    """Return a hold token, or None when someone else already holds the slot."""
    key = hold_key(dentist_id, start)
    token = generate_token()
    if not await redis.set(key, token, nx=True, ex=HOLD_TTL_SECONDS):
        return None
    expires = datetime.now(UTC) + timedelta(seconds=HOLD_TTL_SECONDS)
    await redis.zadd(HOLD_INDEX, {key: expires.timestamp()})
    return token


async def is_valid(redis: Redis, dentist_id: uuid.UUID, start: datetime, token: str) -> bool:
    stored = await redis.get(hold_key(dentist_id, start))
    return stored is not None and hmac.compare_digest(str(stored), token)


async def release(redis: Redis, dentist_id: uuid.UUID, start: datetime) -> None:
    key = hold_key(dentist_id, start)
    await redis.delete(key)
    await redis.zrem(HOLD_INDEX, key)


async def active_keys(redis: Redis) -> set[str]:
    now = datetime.now(UTC).timestamp()
    await redis.zremrangebyscore(HOLD_INDEX, "-inf", now)
    return {str(k) for k in await redis.zrangebyscore(HOLD_INDEX, now, "+inf")}
