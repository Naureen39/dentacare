"""Keeping ``kb_documents`` and ``kb_chunks`` in step with the source documents."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import KbChunk, KbDocument
from app.services.knowledge.chunking import chunk_document
from app.services.knowledge.documents import KbSource, content_hash, render_placeholders
from app.services.knowledge.embeddings import Embedder


@dataclass
class SyncReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped_admin: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    chunks_written: int = 0

    @property
    def embedded(self) -> list[str]:
        return [*self.added, *self.updated]


async def embed_document(db: AsyncSession, embedder: Embedder, document: KbDocument) -> int:
    """Replace the chunks of one document with freshly embedded ones. Returns the chunk count."""
    chunks = chunk_document(document.title, document.body)
    vectors = await embedder.embed_documents([c.text for c in chunks])
    await db.execute(delete(KbChunk).where(KbChunk.document_id == document.id))
    for chunk, vector in zip(chunks, vectors, strict=True):
        db.add(
            KbChunk(
                document_id=document.id,
                chunk_index=chunk.index,
                text=chunk.text,
                token_count=chunk.token_count,
                embedding=vector,
            )
        )
    document.embedded_hash = document.content_hash
    document.embedded_at = datetime.now(UTC)
    await db.flush()
    return len(chunks)


async def sync_sources(
    db: AsyncSession,
    embedder: Embedder,
    sources: list[KbSource],
    settings: Settings,
    *,
    model_name: str,
    force: bool = False,
    prune: bool = False,
) -> SyncReport:
    """Make the database match the source files.

    Only documents whose content (or embedding settings) changed are embedded again.
    Documents edited in the admin console are left alone unless ``force`` is set.
    """
    report = SyncReport()
    existing = {d.slug: d for d in (await db.execute(select(KbDocument))).scalars()}

    for source in sources:
        body = render_placeholders(source.body, settings)
        digest = content_hash(source.title, source.category, body, model_name)
        document = existing.get(source.slug)

        if document is None:
            document = KbDocument(
                slug=source.slug,
                title=source.title,
                category=source.category,
                body=body,
                short_answer=render_placeholders(source.short_answer, settings),
                content_hash=digest,
                updated_at=source.updated_at,
                managed_by="file",
            )
            db.add(document)
            await db.flush()
            report.chunks_written += await embed_document(db, embedder, document)
            report.added.append(source.slug)
            continue

        if document.managed_by == "admin" and not force:
            report.skipped_admin.append(source.slug)
            continue
        if document.content_hash == digest and document.embedded_hash == digest and not force:
            report.unchanged.append(source.slug)
            continue

        document.title, document.category, document.body = source.title, source.category, body
        document.short_answer = render_placeholders(source.short_answer, settings)
        document.content_hash = digest
        document.updated_at = source.updated_at
        document.managed_by = "file"
        report.chunks_written += await embed_document(db, embedder, document)
        report.updated.append(source.slug)

    if prune:
        wanted = {s.slug for s in sources}
        for slug, document in existing.items():
            if slug not in wanted and document.managed_by == "file":
                await db.delete(document)
                report.removed.append(slug)
    await db.commit()
    return report


async def stale_documents(db: AsyncSession) -> list[KbDocument]:
    rows = await db.execute(
        select(KbDocument)
        .where(
            (KbDocument.embedded_hash.is_(None))
            | (KbDocument.embedded_hash != KbDocument.content_hash)
        )
        .order_by(KbDocument.slug)
    )
    return list(rows.scalars().all())


async def chunk_counts(db: AsyncSession) -> dict[object, int]:
    rows = await db.execute(select(KbChunk.document_id, func.count()).group_by(KbChunk.document_id))
    return {document_id: int(count) for document_id, count in rows.all()}
