"""Plain data types shared by the LLM gateway, its providers and the chat code."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


@dataclass(frozen=True)
class Message:
    """One chat message. The static system prompt is added by the gateway, never by callers."""

    role: Literal["user", "assistant"]
    content: str


class ProviderErrorKind(StrEnum):
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"
    CONNECTION = "connection_error"
    AUTH = "auth_error"
    BAD_REQUEST = "bad_request"
    UNKNOWN = "error"


class ProviderError(Exception):
    """A provider call failed. ``kind`` drives failover, the circuit breaker and the usage log."""

    def __init__(
        self,
        kind: ProviderErrorKind,
        message: str = "",
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message or kind.value)
        self.kind = kind
        self.status_code = status_code
        self.retry_after = retry_after
        self.headers: dict[str, str] = {k.lower(): v for k, v in (headers or {}).items()}


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    finish_reason: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class LlmResult:
    """What the gateway returns. ``degraded`` means no model answered and ``text`` is a fixed
    fallback, so callers must not treat it as model output."""

    text: str
    parsed: BaseModel | None = None
    provider: str | None = None
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    latency_ms: int = 0
    degraded: bool = False
    failover_from: str | None = None
    repaired: bool = False


class GatewayError(Exception):
    """A request the gateway refuses because the caller broke a rule (for example the prompt
    is larger than its purpose allows). Never raised for provider outages."""


class PromptTooLargeError(GatewayError):
    pass
