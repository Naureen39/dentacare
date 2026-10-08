"""Tests of the embedding service. Those marked with the model fixture use the real BGE model."""

import asyncio
import json
import math
import time
from collections.abc import AsyncIterator

import fakeredis
import pytest

from app.core.errors import AppError
from app.services.knowledge import embeddings
from app.services.knowledge.embeddings import (
    EMBEDDING_DIMENSIONS,
    QUERY_INSTRUCTION,
    EmbeddingService,
    normalize_text,
    normalize_vector,
)
from tests.knowledge.conftest import MODEL_CACHE, MODEL_NAME, cosine


def test_normalize_text_is_case_and_space_insensitive() -> None:
    assert normalize_text("  What TIME\tdo you   open? \n") == "what time do you open?"


def test_normalize_vector_gives_unit_length_and_keeps_zero_vectors() -> None:
    vector = normalize_vector([3.0, 4.0])
    assert vector == pytest.approx([0.6, 0.8])
    assert normalize_vector([0.0, 0.0]) == [0.0, 0.0]


def test_the_bge_query_instruction_is_exactly_the_documented_text() -> None:
    assert QUERY_INSTRUCTION == "Represent this sentence for searching relevant passages: "


# --- with a stubbed encoder --------------------------------------------------------------------------


class Recorder:
    """Replaces the model so tests can see what would be encoded."""

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def encode(self, texts):  # type: ignore[no-untyped-def]
        self.batches.append(list(texts))
        return [normalize_vector([1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)) for _ in texts]


@pytest.fixture
async def stubbed() -> AsyncIterator[tuple[EmbeddingService, Recorder, fakeredis.FakeAsyncRedis]]:
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    service = EmbeddingService(MODEL_NAME, None, redis)
    recorder = Recorder()
    service._encode_sync = recorder.encode  # type: ignore[method-assign]
    yield service, recorder, redis
    service.close()
    await redis.aclose()


async def test_queries_get_the_instruction_prefix_and_documents_do_not(stubbed) -> None:  # type: ignore[no-untyped-def]
    service, recorder, _ = stubbed
    await service.embed_query("What time do you open")
    await service.embed_documents(["We open at eight."])
    await service.embed_query("hello there", instruction=False)

    assert recorder.batches[0] == [f"{QUERY_INSTRUCTION}what time do you open"]
    assert recorder.batches[1] == ["We open at eight."]
    assert recorder.batches[2] == ["hello there"]


async def test_query_embeddings_are_cached_for_24_hours_by_normalized_text(stubbed) -> None:  # type: ignore[no-untyped-def]
    service, recorder, redis = stubbed
    first = await service.embed_query("What time do you OPEN")
    second = await service.embed_query("  what time   do you open ")
    third = await service.embed_query("what time do you open")

    assert first == second == third
    assert len(recorder.batches) == 1
    [key] = [k async for k in redis.scan_iter("emb:q:*")]
    assert 23 * 3600 < await redis.ttl(key) <= 24 * 3600
    assert len(json.loads(await redis.get(key))) == EMBEDDING_DIMENSIONS


async def test_the_cache_separates_prefixed_and_plain_queries(stubbed) -> None:  # type: ignore[no-untyped-def]
    service, recorder, _ = stubbed
    await service.embed_query("hello")
    await service.embed_query("hello", instruction=False)
    await service.embed_query("hello")
    assert len(recorder.batches) == 2


async def test_different_queries_are_encoded_separately(stubbed) -> None:  # type: ignore[no-untyped-def]
    service, recorder, _ = stubbed
    await service.embed_query("parking")
    await service.embed_query("insurance")
    assert len(recorder.batches) == 2


async def test_an_empty_document_list_does_no_work(stubbed) -> None:  # type: ignore[no-untyped-def]
    service, recorder, _ = stubbed
    assert await service.embed_documents([]) == []
    assert recorder.batches == []


async def test_overlong_queries_are_truncated_before_encoding(stubbed) -> None:  # type: ignore[no-untyped-def]
    service, recorder, _ = stubbed
    await service.embed_query("word " * 2000)
    assert len(recorder.batches[0][0]) <= len(QUERY_INSTRUCTION) + 1000


async def test_a_model_failure_becomes_a_service_unavailable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(name: str, cache_dir: str | None) -> object:
        raise OSError("model files missing")

    monkeypatch.setattr(embeddings, "load_model", broken)
    service = EmbeddingService("some-model", None)
    with pytest.raises(AppError) as raised:
        await service.embed_query("hello")
    assert raised.value.status_code == 503 and raised.value.code == "embeddings_unavailable"
    service.close()


# --- with the real model ----------------------------------------------------------------------------


async def test_the_real_model_returns_384_unit_vectors(model_available: None) -> None:
    service = EmbeddingService(MODEL_NAME, MODEL_CACHE)
    vectors = await service.embed_documents(["We are open on weekdays.", "Parking is free."])
    assert len(vectors) == 2 and all(len(v) == EMBEDDING_DIMENSIONS for v in vectors)
    assert all(math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-6) for v in vectors)
    service.close()


async def test_related_text_is_closer_than_unrelated_text(model_available: None) -> None:
    service = EmbeddingService(MODEL_NAME, MODEL_CACHE)
    query = await service.embed_query("when does the clinic open")
    hours, tooth = await service.embed_documents(
        [
            "The clinic opens at eight in the morning on weekdays.",
            "A crown covers and protects a damaged tooth.",
        ]
    )
    assert cosine(query, hours) > cosine(query, tooth) + 0.05
    service.close()


async def test_the_instruction_changes_the_query_vector(model_available: None) -> None:
    service = EmbeddingService(MODEL_NAME, MODEL_CACHE)
    with_instruction = await service.embed_query("what are your hours", instruction=True)
    without = await service.embed_query("what are your hours", instruction=False)
    assert with_instruction != without and cosine(with_instruction, without) < 0.999
    service.close()


async def test_encoding_runs_off_the_event_loop(model_available: None) -> None:
    """While many passages are encoded in the pool, the event loop keeps ticking."""
    service = EmbeddingService(MODEL_NAME, MODEL_CACHE)
    await service.warm_up()
    gaps: list[float] = []
    stop = asyncio.Event()

    async def ticker() -> None:
        last = time.perf_counter()
        while not stop.is_set():
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    task = asyncio.create_task(ticker())
    await service.embed_documents(
        [f"Passage number {i} about dental care and appointments." * 5 for i in range(120)]
    )
    stop.set()
    await task
    assert (
        len(gaps) > 5 and max(gaps) < 0.25
    )  # a blocked loop would show one gap as long as the whole job
    service.close()


async def test_warm_up_marks_the_service_ready(model_available: None) -> None:
    service = EmbeddingService(MODEL_NAME, MODEL_CACHE)
    assert service.ready is False
    await service.warm_up()
    assert service.ready is True
    service.close()


def test_the_model_is_loaded_once_per_process(model_available: None) -> None:
    first = embeddings.load_model(MODEL_NAME, MODEL_CACHE)
    second = embeddings.load_model(MODEL_NAME, MODEL_CACHE)
    assert first is second
