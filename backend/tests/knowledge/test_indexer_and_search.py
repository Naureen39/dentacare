from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from app.core.config import Settings
from app.db.models import IntentExample, KbChunk, KbDocument
from app.services.knowledge.documents import KbSource, load_kb_directory
from app.services.knowledge.indexer import SyncReport, stale_documents, sync_sources
from app.services.knowledge.search import (
    load_intents,
    match_intent,
    search_kb,
    sync_intents,
)
from tests.auth.conftest import Ctx
from tests.knowledge.conftest import INTENTS_FILE, KB_DIR, FakeEmbedder

MODEL = "test-model"
WHEN = datetime(2026, 9, 1, tzinfo=UTC)


def source(
    slug: str, body: str = "Open on weekdays.", title: str = "Title", category: str = "practice"
) -> KbSource:
    return KbSource(slug, title, category, WHEN, f"{body}\n\n## Short answer\n{body}", body)


async def sync(
    ctx: Ctx, embedder: FakeEmbedder, sources: list[KbSource], **kwargs: Any
) -> SyncReport:
    settings = kwargs.pop("settings", Settings(env="test"))
    async with ctx.session_factory() as db:
        return await sync_sources(
            db, embedder, sources, settings, model_name=kwargs.pop("model", MODEL), **kwargs
        )


async def rows(ctx: Ctx, query: str) -> list[tuple]:  # type: ignore[type-arg]
    return await ctx.fetch(query)


# --- incremental indexing ----------------------------------------------------------------------


async def test_new_documents_are_stored_with_chunks_and_embedding_state(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    report = await sync(ctx, fake_embedder, [source("hours"), source("parking", "Free parking.")])

    assert sorted(report.added) == ["hours", "parking"]
    docs = await rows(
        ctx,
        "SELECT slug, managed_by, embedded_hash = content_hash, short_answer, updated_at FROM kb_documents ORDER BY slug",
    )
    assert [(d[0], d[1], d[2]) for d in docs] == [
        ("hours", "file", True),
        ("parking", "file", True),
    ]
    assert docs[0][3] == "Open on weekdays." and docs[0][4] == WHEN
    assert (await rows(ctx, "SELECT count(*) FROM kb_chunks"))[0][0] >= 2


async def test_unchanged_documents_are_not_embedded_again(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    sources = [source("hours"), source("parking", "Free parking.")]
    await sync(ctx, fake_embedder, sources)
    embedded_before = fake_embedder.documents_embedded

    report = await sync(ctx, fake_embedder, sources)

    assert sorted(report.unchanged) == ["hours", "parking"] and report.embedded == []
    assert fake_embedder.documents_embedded == embedded_before
    assert report.chunks_written == 0


async def test_only_the_changed_document_is_re_embedded(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    await sync(ctx, fake_embedder, [source("hours"), source("parking", "Free parking.")])
    before = {r[0]: r[1] for r in await rows(ctx, "SELECT slug, embedded_at FROM kb_documents")}

    report = await sync(
        ctx, fake_embedder, [source("hours"), source("parking", "Free parking and a garage.")]
    )

    assert report.updated == ["parking"] and report.unchanged == ["hours"]
    after = {r[0]: r[1] for r in await rows(ctx, "SELECT slug, embedded_at FROM kb_documents")}
    assert after["hours"] == before["hours"] and after["parking"] > before["parking"]
    texts = [
        r[0]
        for r in await rows(
            ctx,
            "SELECT c.text FROM kb_chunks c JOIN kb_documents d ON d.id = c.document_id WHERE d.slug = 'parking'",
        )
    ]
    assert any("garage" in t for t in texts) and not any("Free parking.\n" in t for t in texts)


async def test_old_chunks_are_replaced_not_accumulated(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    await sync(ctx, fake_embedder, [source("hours", "Version one.")])
    count_one = (await rows(ctx, "SELECT count(*) FROM kb_chunks"))[0][0]
    await sync(ctx, fake_embedder, [source("hours", "Version two.")])
    await sync(ctx, fake_embedder, [source("hours", "Version three.")])
    assert (await rows(ctx, "SELECT count(*) FROM kb_chunks"))[0][0] == count_one


async def test_title_category_and_embedding_model_changes_trigger_re_embedding(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    await sync(ctx, fake_embedder, [source("hours")])
    assert (await sync(ctx, fake_embedder, [source("hours", title="New title")])).updated == [
        "hours"
    ]
    assert (
        await sync(ctx, fake_embedder, [source("hours", title="New title", category="policies")])
    ).updated == ["hours"]
    swapped = await sync(
        ctx,
        fake_embedder,
        [source("hours", title="New title", category="policies")],
        model="other-model",
    )
    assert swapped.updated == ["hours"]


async def test_changing_clinic_details_re_embeds_documents_that_use_placeholders(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    doc = source("contact", "Call {{clinic_phone}} to book.")
    await sync(
        ctx, fake_embedder, [doc], settings=Settings(env="test", clinic_phone="(555) 010-0100")
    )
    again = await sync(
        ctx, fake_embedder, [doc], settings=Settings(env="test", clinic_phone="(555) 010-0100")
    )
    changed = await sync(
        ctx, fake_embedder, [doc], settings=Settings(env="test", clinic_phone="(555) 010-0200")
    )

    assert again.unchanged == ["contact"] and changed.updated == ["contact"]
    [(body,)] = await rows(ctx, "SELECT body FROM kb_documents")
    assert "(555) 010-0200" in body and "{{" not in body


async def test_documents_edited_in_the_console_are_left_alone_unless_forced(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    await sync(ctx, fake_embedder, [source("hours")])
    await ctx.execute("UPDATE kb_documents SET managed_by = 'admin', body = 'Edited in console'")

    skipped = await sync(ctx, fake_embedder, [source("hours", "Different file text.")])
    assert skipped.skipped_admin == ["hours"] and skipped.updated == []
    assert (await rows(ctx, "SELECT body FROM kb_documents"))[0][0] == "Edited in console"

    forced = await sync(ctx, fake_embedder, [source("hours", "Different file text.")], force=True)
    assert forced.updated == ["hours"]
    assert (await rows(ctx, "SELECT managed_by FROM kb_documents"))[0][0] == "file"


async def test_force_re_embeds_everything(ctx: Ctx, fake_embedder: FakeEmbedder) -> None:
    sources = [source("hours"), source("parking", "Free parking.")]
    await sync(ctx, fake_embedder, sources)
    report = await sync(ctx, fake_embedder, sources, force=True)
    assert sorted(report.updated) == ["hours", "parking"]


async def test_prune_removes_only_file_managed_documents_that_disappeared(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    await sync(
        ctx,
        fake_embedder,
        [source("hours"), source("old-page", "Old."), source("console-page", "Console.")],
    )
    await ctx.execute("UPDATE kb_documents SET managed_by = 'admin' WHERE slug = 'console-page'")

    kept = await sync(ctx, fake_embedder, [source("hours")])
    assert kept.removed == []
    report = await sync(ctx, fake_embedder, [source("hours")], prune=True)

    assert report.removed == ["old-page"]
    assert [r[0] for r in await rows(ctx, "SELECT slug FROM kb_documents ORDER BY slug")] == [
        "console-page",
        "hours",
    ]
    assert (
        await rows(
            ctx,
            "SELECT count(*) FROM kb_chunks c LEFT JOIN kb_documents d ON d.id = c.document_id WHERE d.id IS NULL",
        )
    )[0][0] == 0


async def test_stale_documents_are_those_whose_chunks_do_not_match_their_content(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    await sync(ctx, fake_embedder, [source("hours"), source("parking", "Free parking.")])
    async with ctx.session_factory() as db:
        assert await stale_documents(db) == []
    await ctx.execute("UPDATE kb_documents SET content_hash = 'changed' WHERE slug = 'hours'")
    await ctx.execute("UPDATE kb_documents SET embedded_hash = NULL WHERE slug = 'parking'")
    async with ctx.session_factory() as db:
        assert [d.slug for d in await stale_documents(db)] == ["hours", "parking"]


async def test_the_real_knowledge_base_files_index_cleanly_with_the_fake_embedder(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    sources = load_kb_directory(KB_DIR)
    report = await sync(ctx, fake_embedder, sources)
    assert len(report.added) == len(sources)
    chunk_rows = await rows(ctx, "SELECT count(*) FROM kb_chunks")
    assert len(sources) <= chunk_rows[0][0] <= len(sources) * 4
    again = await sync(ctx, fake_embedder, sources)
    assert len(again.unchanged) == len(sources)


# --- search ------------------------------------------------------------------------------------------


async def seeded(ctx: Ctx, fake_embedder: FakeEmbedder) -> None:
    await sync(
        ctx,
        fake_embedder,
        [
            source(
                "parking",
                "Free patient parking is in the lot beside the building.",
                "Parking",
                "practice",
            ),
            source(
                "hours",
                "We are open Monday to Friday and closed on Sunday.",
                "Office hours",
                "practice",
            ),
            source(
                "price-filling",
                "A tooth colored filling starts at 210 dollars.",
                "Filling price",
                "pricing",
            ),
            source(
                "price-crown", "A porcelain crown starts at 1150 dollars.", "Crown price", "pricing"
            ),
        ],
    )


async def test_search_returns_the_most_similar_chunks_best_first(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    await seeded(ctx, fake_embedder)
    async with ctx.session_factory() as db:
        hits = await search_kb(db, fake_embedder, "where can I park my car in the lot", 3)
    assert hits[0].slug == "parking"
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True) and all(-1.0 <= s <= 1.0 for s in scores)
    assert hits[0].document_id and hits[0].chunk.text.startswith("Parking")
    assert hits[0].title == "Parking" and hits[0].category == "practice"


async def test_search_respects_k_and_returns_distinct_documents(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    await seeded(ctx, fake_embedder)
    async with ctx.session_factory() as db:
        three = await search_kb(db, fake_embedder, "starts at dollars", 3)
        one = await search_kb(db, fake_embedder, "starts at dollars", 1)
        duplicates_allowed = await search_kb(
            db, fake_embedder, "starts at dollars", 8, distinct_documents=False
        )
    assert len(three) == 3 and len({h.document_id for h in three}) == 3
    assert len(one) == 1
    assert len(duplicates_allowed) == 8 and len({h.document_id for h in duplicates_allowed}) < 8


async def test_search_can_be_limited_to_a_category(ctx: Ctx, fake_embedder: FakeEmbedder) -> None:
    await seeded(ctx, fake_embedder)
    async with ctx.session_factory() as db:
        hits = await search_kb(db, fake_embedder, "open on Sunday parking", 5, category="pricing")
        nothing = await search_kb(db, fake_embedder, "parking", 5, category="emergency")
    assert {h.category for h in hits} == {"pricing"} and len(hits) == 2
    assert nothing == []


async def test_blank_queries_and_extreme_k_values_are_safe(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    await seeded(ctx, fake_embedder)
    async with ctx.session_factory() as db:
        assert await search_kb(db, fake_embedder, "   ", 3) == []
        assert len(await search_kb(db, fake_embedder, "parking", 0)) == 1
        assert len(await search_kb(db, fake_embedder, "parking", 1000)) <= 4


async def test_search_on_an_empty_knowledge_base_returns_nothing(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    async with ctx.session_factory() as db:
        assert await search_kb(db, fake_embedder, "anything", 3) == []


async def test_vector_search_uses_the_cosine_hnsw_index(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    await seeded(ctx, fake_embedder)
    vector = str(FakeEmbedder.vector("parking"))
    async with ctx.session_factory() as db:
        await db.execute(text("SET LOCAL enable_seqscan = off"))
        plan = (
            (
                await db.execute(
                    text(  # noqa: S608
                        f"EXPLAIN SELECT id FROM kb_chunks ORDER BY embedding <=> '{vector}' LIMIT 3"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert any("ix_kb_chunks_embedding_hnsw" in line for line in plan), plan


async def test_stored_vectors_are_unit_length(ctx: Ctx, fake_embedder: FakeEmbedder) -> None:
    await seeded(ctx, fake_embedder)
    async with ctx.session_factory() as db:
        chunks = (await db.execute(select(KbChunk))).scalars().all()
    assert chunks
    for chunk in chunks:
        assert abs(sum(float(x) ** 2 for x in chunk.embedding) - 1.0) < 1e-4


# --- intents ------------------------------------------------------------------------------------------


def test_the_intent_file_has_every_intent_with_15_to_25_examples() -> None:
    intents = load_intents(INTENTS_FILE)
    assert set(intents) == {
        "greeting",
        "hours",
        "location",
        "pricing",
        "insurance",
        "book",
        "reschedule",
        "cancel",
        "faq_procedure",
        "emergency",
        "human_handoff",
        "thanks",
        "out_of_scope",
    }
    for name, examples in intents.items():
        assert 15 <= len(examples) <= 25, name
        assert len(set(examples)) == len(examples), name


def test_intent_examples_do_not_overlap_between_intents() -> None:
    seen: dict[str, str] = {}
    for intent, examples in load_intents(INTENTS_FILE).items():
        for example in examples:
            assert seen.setdefault(example.lower(), intent) == intent, example


async def test_intent_examples_are_embedded_once_and_synced_idempotently(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    intents = {
        "hours": ["when are you open", "opening times"],
        "thanks": ["thank you", "thanks a lot"],
    }
    async with ctx.session_factory() as db:
        first = await sync_intents(db, fake_embedder, intents)
        second = await sync_intents(db, fake_embedder, intents)
    assert first == {"added": 4, "removed": 0, "total": 4} and second == {
        "added": 0,
        "removed": 0,
        "total": 4,
    }
    assert fake_embedder.documents_embedded == 4


async def test_removed_examples_are_deleted_but_other_intents_are_untouched(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    async with ctx.session_factory() as db:
        await sync_intents(db, fake_embedder, {"hours": ["a b", "c d"], "thanks": ["thanks"]})
        result = await sync_intents(db, fake_embedder, {"hours": ["a b"]})
        rest = (
            await db.execute(
                select(IntentExample.intent, IntentExample.text).order_by(IntentExample.text)
            )
        ).all()
    assert result["removed"] == 1
    assert [tuple(r) for r in rest] == [("hours", "a b"), ("thanks", "thanks")]


async def test_match_intent_finds_the_nearest_example_and_a_runner_up(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    async with ctx.session_factory() as db:
        await sync_intents(
            db,
            fake_embedder,
            {
                "hours": ["what time do you open", "when do you close"],
                "cancel": ["cancel my appointment", "please cancel my visit"],
                "thanks": ["thank you very much"],
            },
        )
        match = await match_intent(db, fake_embedder, "please cancel my appointment today")
        empty = await match_intent(db, fake_embedder, "   ")
    assert match is not None and match.intent == "cancel" and match.score > 0.6
    assert match.nearest_example in {"cancel my appointment", "please cancel my visit"}
    assert (
        match.runner_up is not None
        and match.runner_up_score is not None
        and match.runner_up_score < match.score
    )
    assert empty is None


async def test_match_intent_without_examples_returns_none(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    async with ctx.session_factory() as db:
        assert await match_intent(db, fake_embedder, "hello") is None


async def test_duplicate_examples_violate_the_unique_constraint(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    from sqlalchemy.exc import IntegrityError

    async with ctx.session_factory() as db:
        await sync_intents(db, fake_embedder, {"hours": ["when open"]})
        db.add(IntentExample(intent="hours", text="when open", embedding=FakeEmbedder.vector("x")))
        try:
            await db.commit()
            raised = False
        except IntegrityError:
            raised = True
    assert raised


def test_settings_default_paths_point_at_the_repository_data() -> None:
    assert Path(Settings().kb_dir).parts[-2:] == ("data", "kb")
    _ = KbDocument


async def test_filtered_search_still_returns_k_results_when_enough_documents_match(
    ctx: Ctx, fake_embedder: FakeEmbedder
) -> None:
    """Regression: an index scan stopped at its candidate limit and filters hid the rest."""
    sources = [
        source(
            f"doc-{i:02d}",
            f"Topic number {i} about {'pricing' if i % 2 else 'parking'} details.",
            f"Doc {i}",
            "pricing" if i % 2 else "practice",
        )
        for i in range(40)
    ]
    await sync(ctx, fake_embedder, sources)
    async with ctx.session_factory() as db:
        for _ in range(5):
            hits = await search_kb(db, fake_embedder, "parking details", 5, category="pricing")
            assert len(hits) == 5 and {h.category for h in hits} == {"pricing"}
            ordered = await search_kb(db, fake_embedder, "parking details", 10)
            assert [h.score for h in ordered] == sorted((h.score for h in ordered), reverse=True)
