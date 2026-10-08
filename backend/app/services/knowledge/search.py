"""Vector search over the knowledge base and intent examples."""

import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IntentExample, KbChunk, KbDocument
from app.services.knowledge.embeddings import Embedder

MAX_K = 20
OVERFETCH = 4  # chunks fetched per wanted result, so duplicates from one document can be dropped


async def tune_vector_search(db: AsyncSession) -> None:
    """Make HNSW index scans return enough rows, in exact order, even with filters.

    Without iterative scans an index scan stops after ``ef_search`` candidates and a
    category filter can leave fewer than ``k`` rows. Both settings last until the end of the
    current transaction.
    """
    await db.execute(text("SET LOCAL hnsw.ef_search = 100"))
    await db.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))


@dataclass(frozen=True)
class SearchHit:
    """One matching chunk. ``score`` is cosine similarity: 1.0 means identical direction."""

    chunk: KbChunk
    score: float
    document_id: uuid.UUID
    slug: str
    title: str
    category: str


async def search_kb(
    db: AsyncSession,
    embedder: Embedder,
    query: str,
    k: int = 3,
    *,
    category: str | None = None,
    distinct_documents: bool = True,
) -> list[SearchHit]:
    """The ``k`` most similar chunks, best first, optionally limited to one category.

    With ``distinct_documents`` (the default) each document appears at most once, represented
    by its best chunk, so three results are three different documents.
    """
    if not query.strip():
        return []
    k = max(1, min(k, MAX_K))
    vector = await embedder.embed_query(query)
    await tune_vector_search(db)
    distance = KbChunk.embedding.cosine_distance(vector)
    stmt = (
        select(KbChunk, KbDocument, distance.label("distance"))
        .join(KbDocument, KbDocument.id == KbChunk.document_id)
        .order_by(distance)
        .limit(k * OVERFETCH if distinct_documents else k)
    )
    if category is not None:
        stmt = stmt.where(KbDocument.category == category)

    hits: list[SearchHit] = []
    seen: set[uuid.UUID] = set()
    for chunk, document, dist in (await db.execute(stmt)).all():
        if distinct_documents and document.id in seen:
            continue
        seen.add(document.id)
        hits.append(
            SearchHit(
                chunk,
                1.0 - float(dist),
                document.id,
                document.slug,
                document.title,
                document.category,
            )
        )
        if len(hits) == k:
            break
    return hits


# --- intents -------------------------------------------------------------------------------


@dataclass(frozen=True)
class IntentMatch:
    intent: str
    score: float
    nearest_example: str
    runner_up: str | None
    runner_up_score: float | None


async def match_intent(
    db: AsyncSession, embedder: Embedder, message: str, neighbours: int = 8
) -> IntentMatch | None:
    """The intent whose examples are closest to the message, or None when none are indexed.

    Messages and examples are both short utterances, so neither side gets the retrieval
    instruction prefix.
    """
    if not message.strip():
        return None
    vector = await embedder.embed_query(message, instruction=False)
    await tune_vector_search(db)
    distance = IntentExample.embedding.cosine_distance(vector)
    rows = (
        await db.execute(
            select(IntentExample.intent, IntentExample.text, distance.label("distance"))
            .order_by(distance)
            .limit(neighbours)
        )
    ).all()
    if not rows:
        return None
    best: dict[str, tuple[float, str]] = {}
    for intent, example, dist in rows:
        score = 1.0 - float(dist)
        if intent not in best or score > best[intent][0]:
            best[intent] = (score, example)
    ranked = sorted(best.items(), key=lambda item: item[1][0], reverse=True)
    top_intent, (top_score, top_example) = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    return IntentMatch(
        top_intent,
        top_score,
        top_example,
        second[0] if second else None,
        second[1][0] if second else None,
    )


def load_intents(path: Path) -> dict[str, list[str]]:
    """Read ``intents.yaml``: a mapping of intent name to its example utterances."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    intents: dict[str, list[str]] = {}
    for name, examples in data.items():
        cleaned = list(dict.fromkeys(str(e).strip() for e in examples if str(e).strip()))
        intents[str(name)] = cleaned
    return intents


async def sync_intents(
    db: AsyncSession, embedder: Embedder, intents: dict[str, list[str]]
) -> dict[str, int]:
    """Embed new utterances once and drop removed ones. Returns counts of added and removed."""
    existing = {(i.intent, i.text) for i in (await db.execute(select(IntentExample))).scalars()}
    wanted = {(intent, text) for intent, examples in intents.items() for text in examples}

    to_add = sorted(wanted - existing)
    vectors = await embedder.embed_documents([example for _, example in to_add])
    for (intent, example), vector in zip(to_add, vectors, strict=True):
        db.add(IntentExample(intent=intent, text=example, embedding=vector))

    removed = 0
    for intent, example in sorted(existing - wanted):
        if intent in intents:  # only prune intents that the file still defines
            await db.execute(
                delete(IntentExample).where(
                    IntentExample.intent == intent, IntentExample.text == example
                )
            )
            removed += 1
    await db.commit()
    return {"added": len(to_add), "removed": removed, "total": len(wanted)}
