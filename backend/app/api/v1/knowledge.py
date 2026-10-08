"""Administration of the chatbot knowledge base."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.core.deps import AppSettings, CurrentUser, Session, require_roles
from app.core.errors import AppError
from app.db.enums import UserRole
from app.db.models import KbChunk, KbDocument
from app.schemas.knowledge import (
    KbDocumentCreate,
    KbDocumentOut,
    KbDocumentSummary,
    KbDocumentUpdate,
    ReindexResult,
    SearchHitOut,
)
from app.services import audit
from app.services.knowledge.documents import (
    KbValidationError,
    content_hash,
    render_placeholders,
    validate_fields,
)
from app.services.knowledge.embeddings import Embedder
from app.services.knowledge.indexer import chunk_counts, embed_document, stale_documents
from app.services.knowledge.search import search_kb

router = APIRouter(prefix="/admin/kb", tags=["knowledge-base"])

AdminUser = Annotated[CurrentUser, Depends(require_roles(UserRole.ADMIN))]


def get_embedder(request: Request) -> Embedder:
    embedder: Embedder | None = getattr(request.app.state, "embedder", None)
    if embedder is None:
        raise AppError("embeddings_unavailable", "The search service is not configured.", 503)
    return embedder


EmbedderDep = Annotated[Embedder, Depends(get_embedder)]


def _invalid(exc: KbValidationError) -> AppError:
    return AppError("validation_error", "The document is not valid.", 422, exc.problems)


async def _get(db: Session, slug: str) -> KbDocument:
    document = (
        await db.execute(select(KbDocument).where(KbDocument.slug == slug))
    ).scalar_one_or_none()
    if document is None:
        raise AppError("not_found", "Document not found.", 404)
    return document


async def _summary(db: Session, document: KbDocument) -> KbDocumentSummary:
    count = (
        await db.execute(
            select(func.count()).select_from(KbChunk).where(KbChunk.document_id == document.id)
        )
    ).scalar_one()
    return KbDocumentSummary(
        slug=document.slug,
        title=document.title,
        category=document.category,
        updated_at=document.updated_at,
        managed_by=document.managed_by,
        stale=document.embedded_hash != document.content_hash,
        chunks=int(count),
    )


async def _full(db: Session, document: KbDocument) -> KbDocumentOut:
    summary = await _summary(db, document)
    return KbDocumentOut(
        **summary.model_dump(),
        id=document.id,
        body=document.body,
        short_answer=document.short_answer,
        embedded_at=document.embedded_at,
    )


@router.get("/documents", response_model=list[KbDocumentSummary])
async def list_documents(
    db: Session,
    _: AdminUser,
    category: str | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    stale_only: bool = False,
) -> list[KbDocumentSummary]:
    stmt = select(KbDocument).order_by(KbDocument.category, KbDocument.slug)
    if category:
        stmt = stmt.where(KbDocument.category == category)
    if q:
        stmt = stmt.where(
            KbDocument.title.ilike(f"%{q.strip()}%") | KbDocument.slug.ilike(f"%{q.strip()}%")
        )
    documents = (await db.execute(stmt)).scalars().all()
    counts = await chunk_counts(db)
    rows = [
        KbDocumentSummary(
            slug=d.slug,
            title=d.title,
            category=d.category,
            updated_at=d.updated_at,
            managed_by=d.managed_by,
            stale=d.embedded_hash != d.content_hash,
            chunks=counts.get(d.id, 0),
        )
        for d in documents
    ]
    return [r for r in rows if r.stale] if stale_only else rows


@router.get("/documents/{slug}", response_model=KbDocumentOut)
async def get_document(slug: str, db: Session, _: AdminUser) -> KbDocumentOut:
    return await _full(db, await _get(db, slug))


@router.post("/documents", response_model=KbDocumentOut, status_code=201)
async def create_document(
    body: KbDocumentCreate,
    request: Request,
    db: Session,
    current: AdminUser,
    embedder: EmbedderDep,
    settings: AppSettings,
) -> KbDocumentOut:
    try:
        answer = validate_fields(body.slug, body.title, body.category, body.body)
        rendered = render_placeholders(body.body, settings)
    except KbValidationError as exc:
        raise _invalid(exc) from exc
    if (await db.execute(select(KbDocument.id).where(KbDocument.slug == body.slug))).first():
        raise AppError("conflict", "A document with this id already exists.", 409)

    document = KbDocument(
        slug=body.slug,
        title=body.title,
        category=body.category,
        body=rendered,
        short_answer=render_placeholders(answer, settings),
        content_hash=content_hash(body.title, body.category, rendered, settings.embed_model),
        updated_at=datetime.now(UTC),
        managed_by="admin",
    )
    db.add(document)
    await db.flush()
    if body.reembed:
        await embed_document(db, embedder, document)
    await audit.record(
        db,
        "kb.create",
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity="kb_document",
        entity_id=document.id,
        metadata={"slug": body.slug, "embedded": body.reembed},
    )
    await db.commit()
    return await _full(db, document)


@router.put("/documents/{slug}", response_model=KbDocumentOut)
async def update_document(
    slug: str,
    body: KbDocumentUpdate,
    request: Request,
    db: Session,
    current: AdminUser,
    embedder: EmbedderDep,
    settings: AppSettings,
) -> KbDocumentOut:
    document = await _get(db, slug)
    title = body.title if body.title is not None else document.title
    category = body.category if body.category is not None else document.category
    text = body.body if body.body is not None else document.body
    try:
        answer = validate_fields(slug, title, category, text)
        rendered = render_placeholders(text, settings)
    except KbValidationError as exc:
        raise _invalid(exc) from exc

    document.title, document.category, document.body = title, category, rendered
    document.short_answer = render_placeholders(answer, settings)
    document.content_hash = content_hash(title, category, rendered, settings.embed_model)
    document.updated_at = datetime.now(UTC)
    document.managed_by = "admin"  # the file sync no longer overwrites this document
    await db.flush()
    if body.reembed:
        await embed_document(db, embedder, document)
    await audit.record(
        db,
        "kb.update",
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity="kb_document",
        entity_id=document.id,
        metadata={"slug": slug, "embedded": body.reembed},
    )
    await db.commit()
    return await _full(db, document)


@router.post("/documents/{slug}/reembed", response_model=KbDocumentOut)
async def reembed_document(
    slug: str, request: Request, db: Session, current: AdminUser, embedder: EmbedderDep
) -> KbDocumentOut:
    document = await _get(db, slug)
    await embed_document(db, embedder, document)
    await audit.record(
        db,
        "kb.reembed",
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity="kb_document",
        entity_id=document.id,
        metadata={"slug": slug},
    )
    await db.commit()
    return await _full(db, document)


@router.post("/reindex", response_model=ReindexResult)
async def reindex(
    request: Request,
    db: Session,
    current: AdminUser,
    embedder: EmbedderDep,
    force: bool = False,
) -> ReindexResult:
    """Re-embed documents whose chunks are out of date, or every document with ``force``."""
    documents = (
        list((await db.execute(select(KbDocument).order_by(KbDocument.slug))).scalars().all())
        if force
        else await stale_documents(db)
    )
    chunks = 0
    for document in documents:
        chunks += await embed_document(db, embedder, document)
    await audit.record(
        db,
        "kb.reindex",
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity="kb_document",
        metadata={"documents": len(documents), "force": force},
    )
    await db.commit()
    return ReindexResult(reembedded=[d.slug for d in documents], chunks_written=chunks)


@router.get("/search", response_model=list[SearchHitOut])
async def preview_search(
    db: Session,
    _: AdminUser,
    embedder: EmbedderDep,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    k: Annotated[int, Query(ge=1, le=10)] = 3,
    category: str | None = None,
) -> list[SearchHitOut]:
    """What the assistant would retrieve for a question, with similarity scores."""
    hits = await search_kb(db, embedder, q, k, category=category)
    return [
        SearchHitOut(
            slug=h.slug,
            title=h.title,
            category=h.category,
            score=round(h.score, 4),
            chunk_index=h.chunk.chunk_index,
            text=h.chunk.text,
        )
        for h in hits
    ]
