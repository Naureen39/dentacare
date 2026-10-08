import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.auth import StrictModel


class KbDocumentSummary(BaseModel):
    slug: str
    title: str
    category: str
    updated_at: datetime
    managed_by: str
    stale: bool
    chunks: int


class KbDocumentOut(KbDocumentSummary):
    id: uuid.UUID
    body: str
    short_answer: str | None
    embedded_at: datetime | None


class KbDocumentCreate(StrictModel):
    slug: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=60)
    body: str = Field(min_length=1, max_length=20_000)
    reembed: bool = True


class KbDocumentUpdate(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=60)
    body: str | None = Field(default=None, min_length=1, max_length=20_000)
    reembed: bool = True


class ReindexResult(BaseModel):
    reembedded: list[str]
    chunks_written: int


class SearchHitOut(BaseModel):
    slug: str
    title: str
    category: str
    score: float
    chunk_index: int
    text: str
