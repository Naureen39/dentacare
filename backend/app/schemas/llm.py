from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.auth import StrictModel


class PrimaryRequest(StrictModel):
    provider: Literal["groq", "gemini"]


class LimitsRequest(StrictModel):
    """Provider limits. ``null`` means unknown: no local limit is enforced for that window."""

    rpm: int | None = Field(default=None, ge=1, le=10_000_000)
    rpd: int | None = Field(default=None, ge=1, le=100_000_000)
    tpm: int | None = Field(default=None, ge=1, le=1_000_000_000)
    tpd: int | None = Field(default=None, ge=1, le=10_000_000_000)


class ProviderUsageRow(BaseModel):
    provider: str
    status: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    average_latency_ms: int
    failovers: int


class UsageSummary(BaseModel):
    hours: int
    rows: list[ProviderUsageRow]
