"""Fixtures for knowledge base tests.

Most tests use ``FakeEmbedder``: a deterministic bag of words embedder that needs no model
download, where texts sharing words are close together. The retrieval quality tests use the
real BGE model against a separate database that is indexed once per session.
"""

import asyncio
import hashlib
import math
import os
import re
from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.services.knowledge.documents import load_kb_directory
from app.services.knowledge.embeddings import (
    EMBEDDING_DIMENSIONS,
    EmbeddingService,
    load_model,
    normalize_text,
    normalize_vector,
)
from app.services.knowledge.indexer import sync_sources
from app.services.knowledge.search import load_intents, sync_intents
from tests.db.conftest import alembic_config, drop_database, recreate_database, sqlalchemy_url

REPO_ROOT = Path(__file__).resolve().parents[3]
KB_DIR = REPO_ROOT / "data" / "kb"
INTENTS_FILE = REPO_ROOT / "data" / "intents.yaml"
MODEL_CACHE = str(Path(__file__).resolve().parents[2] / "models")
KB_DB = "meridian_kb_test"
MODEL_NAME = "BAAI/bge-small-en-v1.5"


class FakeEmbedder:
    """Bag of words embedder: each word adds weight to a hashed dimension."""

    def __init__(self) -> None:
        self.query_calls = 0
        self.document_calls = 0
        self.documents_embedded = 0

    @staticmethod
    def vector(text: str) -> list[float]:
        values = [0.0] * EMBEDDING_DIMENSIONS
        for word in re.findall(r"[a-z0-9]+", normalize_text(text)):
            digest = hashlib.sha256(word.encode()).digest()
            values[int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS] += 1.0
        if not any(values):
            values[0] = 1.0
        return normalize_vector(values)

    async def embed_query(self, text: str, *, instruction: bool = True) -> list[float]:
        self.query_calls += 1
        return self.vector(text)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_calls += 1
        self.documents_embedded += len(texts)
        return [self.vector(t) for t in texts]


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def settings_for_kb() -> Settings:
    return Settings(env="test")


@pytest.fixture(scope="session")
def model_available() -> None:
    """Skip the model based tests when the model cannot be loaded, unless REQUIRE_MODEL=1."""
    try:
        load_model(MODEL_NAME, MODEL_CACHE)
    except Exception as exc:  # noqa: BLE001
        message = f"embedding model is not available: {exc}"
        if os.environ.get("REQUIRE_MODEL") == "1":
            pytest.fail(message)
        pytest.skip(message)


@pytest.fixture(scope="session")
def indexed_kb_database(postgres_available: None, model_available: None) -> Iterator[str]:
    """A migrated database holding the real knowledge base, embedded with the real model."""
    recreate_database(KB_DB)
    command.upgrade(alembic_config(KB_DB), "head")

    async def index() -> None:
        engine = create_async_engine(sqlalchemy_url(KB_DB), poolclass=NullPool)
        embedder = EmbeddingService(MODEL_NAME, MODEL_CACHE)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                await sync_sources(
                    db,
                    embedder,
                    load_kb_directory(KB_DIR),
                    Settings(env="test"),
                    model_name=MODEL_NAME,
                )
                await sync_intents(db, embedder, load_intents(INTENTS_FILE))
        finally:
            embedder.close()
            await engine.dispose()

    asyncio.run(index())
    yield KB_DB
    drop_database(KB_DB)


@pytest.fixture
async def kb_session(
    indexed_kb_database: str,
) -> AsyncIterator[tuple[AsyncSession, EmbeddingService]]:
    engine = create_async_engine(sqlalchemy_url(indexed_kb_database), poolclass=NullPool)
    embedder = EmbeddingService(MODEL_NAME, MODEL_CACHE)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session, embedder
    embedder.close()
    await engine.dispose()


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    )
