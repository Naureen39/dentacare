"""The fallback used when no language model can answer: the best matching FAQ answer."""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import KbDocument
from app.services.knowledge.embeddings import Embedder
from app.services.knowledge.search import search_kb

FAQ_MIN_SCORE = 0.65  # below this the knowledge base has nothing relevant to offer


async def faq_short_answer(
    db: AsyncSession, embedder: Embedder, query: str, min_score: float = FAQ_MIN_SCORE
) -> str | None:
    """The short answer of the best matching document, or None when nothing matches well."""
    hits = await search_kb(db, embedder, query, 1)
    if not hits or hits[0].score < min_score:
        return None
    document = await db.get(KbDocument, hits[0].document_id)
    return document.short_answer if document and document.short_answer else None


def faq_fallback(
    session_factory: async_sessionmaker[AsyncSession], embedder: Embedder, query: str
) -> Callable[[], Awaitable[str | None]]:
    """A callable for ``LlmGateway.complete(fallback=...)``. It uses its own database session."""

    async def run() -> str | None:
        async with session_factory() as db:
            return await faq_short_answer(db, embedder, query)

    return run
