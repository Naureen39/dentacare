"""Local text embeddings with fastembed (ONNX, CPU only).

The model is loaded once and kept in memory. Encoding runs in a small thread pool so the
event loop is never blocked. Vectors are normalized to unit length, which makes cosine
distance (pgvector ``<=>``) and inner product equivalent.

BGE models are asymmetric: a search query gets an instruction prefix, a document does not.
Short utterances compared with other short utterances (intent matching) use no prefix on
either side.
"""

import asyncio
import hashlib
import json
import re
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

import numpy as np
import structlog
from redis.asyncio import Redis

from app.core.errors import AppError

logger = structlog.get_logger(__name__)

EMBEDDING_DIMENSIONS = 384
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
QUERY_CACHE_TTL_SECONDS = 24 * 3600
MAX_QUERY_CHARS = 1000


class Embedder(Protocol):
    """What the rest of the application needs from an embedding provider."""

    async def embed_query(self, text: str, *, instruction: bool = True) -> list[float]: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...


def normalize_text(text: str) -> str:
    """Canonical form used for cache keys: lower case, single spaces, trimmed."""
    return re.sub(r"\s+", " ", text).strip().lower()


def normalize_vector(vector: Sequence[float]) -> list[float]:
    array = np.asarray(vector, dtype=np.float64)
    norm = np.linalg.norm(array)
    if norm == 0:
        return [float(x) for x in array]
    return [float(x) for x in array / norm]


_models: dict[tuple[str, str], Any] = {}
_models_lock = threading.Lock()


def load_model(name: str, cache_dir: str | None) -> Any:
    """Return the process wide model instance, loading it on first use."""
    key = (name, cache_dir or "")
    with _models_lock:
        model = _models.get(key)
        if model is None:
            from fastembed import TextEmbedding

            logger.info("embedding_model_loading", model=name)
            model = TextEmbedding(name, cache_dir=cache_dir or None)
            _models[key] = model
            logger.info("embedding_model_ready", model=name)
        return model


class EmbeddingService:
    def __init__(self, model_name: str, cache_dir: str | None = None, redis: Redis | None = None):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.redis = redis
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="embed")
        self.ready = False

    # --- lifecycle ---

    async def warm_up(self) -> None:
        """Load the model and run one encoding so the first real request is fast."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._pool, self._encode_sync, ["warm up"])
        self.ready = True

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # --- encoding ---

    def _encode_sync(self, texts: Sequence[str]) -> list[list[float]]:
        model = load_model(self.model_name, self.cache_dir)
        return [normalize_vector(vector) for vector in model.embed(list(texts))]

    async def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(self._pool, self._encode_sync, list(texts))
        except Exception as exc:
            logger.error("embedding_failed", error=type(exc).__name__)
            raise AppError(
                "embeddings_unavailable", "The search service is temporarily unavailable.", 503
            ) from exc

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed passages. No instruction prefix."""
        if not texts:
            return []
        return await self._encode(texts)

    async def embed_query(self, text: str, *, instruction: bool = True) -> list[float]:
        """Embed a search query, cached in Redis for 24 hours by normalized text."""
        clean = normalize_text(text)[:MAX_QUERY_CHARS]
        key = None
        if self.redis is not None:
            digest = hashlib.sha256(
                f"{self.model_name}|{int(instruction)}|{clean}".encode()
            ).hexdigest()
            key = f"emb:q:{digest}"
            cached = await self.redis.get(key)
            if cached is not None:
                return [float(x) for x in json.loads(cached)]
        payload = f"{QUERY_INSTRUCTION}{clean}" if instruction else clean
        [vector] = await self._encode([payload])
        if key is not None and self.redis is not None:
            await self.redis.set(key, json.dumps(vector), ex=QUERY_CACHE_TTL_SECONDS)
        return vector
