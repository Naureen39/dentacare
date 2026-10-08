"""Redis backed fixed window rate limiting."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Request
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.errors import AppError


@dataclass(frozen=True)
class RateLimitRule:
    scope: str
    limit: int
    window_seconds: int


def login_rule(settings: Settings) -> RateLimitRule:
    return RateLimitRule("login", settings.rate_limit_login_per_minute, 60)


def public_booking_rule(settings: Settings) -> RateLimitRule:
    return RateLimitRule("public_booking", settings.rate_limit_public_booking_per_hour, 3600)


def chat_rule(settings: Settings) -> RateLimitRule:
    return RateLimitRule("chat", settings.rate_limit_chat_per_minute, 60)


def contact_rule(settings: Settings) -> RateLimitRule:
    return RateLimitRule("contact", settings.rate_limit_contact_per_hour, 3600)


def action_link_rule(settings: Settings) -> RateLimitRule:
    return RateLimitRule("action_link", settings.rate_limit_action_link_per_hour, 3600)


def account_email_rule(settings: Settings) -> RateLimitRule:
    """Limits emails sent per address (verification and password reset)."""
    return RateLimitRule("account_email", settings.rate_limit_account_email_per_hour, 3600)


async def enforce(redis: Redis, rule: RateLimitRule, identity: str) -> None:
    """Count one hit for ``identity`` and raise HTTP 429 once the limit is exceeded."""
    key = f"rl:{rule.scope}:{identity}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, rule.window_seconds)
    if count > rule.limit:
        ttl = await redis.ttl(key)
        if ttl < 0:  # the key lost its expiry: repair it so the client is not blocked forever
            await redis.expire(key, rule.window_seconds)
            ttl = rule.window_seconds
        raise AppError(
            "rate_limited",
            "Too many requests. Please wait a moment and try again.",
            429,
            headers={"Retry-After": str(ttl)},
        )


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def ip_rate_limit(
    rule_factory: Callable[[Settings], RateLimitRule],
) -> Callable[[Request], Awaitable[None]]:
    """Dependency factory that limits by client IP address."""

    async def dependency(request: Request) -> None:
        rule = rule_factory(request.app.state.settings)
        await enforce(request.app.state.redis, rule, client_ip(request))

    return dependency
