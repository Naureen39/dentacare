"""Quality gates for retrieval, run against the real model and the real knowledge base.

Gate: at least 90 percent of the sample questions must find their document in the top three
results. A second gate keeps the median time for query embedding plus vector search under
80 milliseconds on CPU.
"""

import statistics
import time

from sqlalchemy import select

from app.db.models import IntentExample, KbDocument
from app.services.knowledge.search import match_intent, search_kb
from tests.knowledge.questions import INTENT_PHRASES, RETRIEVAL_QUESTIONS

TOP3_TARGET = 0.90
TOP1_FLOOR = 0.80
INTENT_TARGET = 0.85
MEDIAN_BUDGET_MS = 80


async def test_the_sample_set_is_large_enough_and_every_target_document_exists(kb_session) -> None:  # type: ignore[no-untyped-def]
    db, _ = kb_session
    slugs = set((await db.execute(select(KbDocument.slug))).scalars())
    assert len(RETRIEVAL_QUESTIONS) >= 60
    assert len({q for q, _ in RETRIEVAL_QUESTIONS}) == len(RETRIEVAL_QUESTIONS)
    assert {slug for _, slug in RETRIEVAL_QUESTIONS} <= slugs
    assert 50 <= len(slugs) <= 70


async def test_top_three_hit_rate_meets_the_90_percent_gate(kb_session) -> None:  # type: ignore[no-untyped-def]
    db, embedder = kb_session
    top1 = top3 = 0
    misses: list[str] = []
    for question, expected in RETRIEVAL_QUESTIONS:
        slugs = [hit.slug for hit in await search_kb(db, embedder, question, 3)]
        top1 += slugs[:1] == [expected]
        if expected in slugs:
            top3 += 1
        else:
            misses.append(f"{question!r}: expected {expected}, got {slugs}")

    total = len(RETRIEVAL_QUESTIONS)
    assert top3 / total >= TOP3_TARGET, f"top 3 hit rate {top3 / total:.1%}; misses: {misses}"
    assert top1 / total >= TOP1_FLOOR, f"top 1 hit rate {top1 / total:.1%}"


async def test_median_embedding_plus_search_time_is_under_80_milliseconds(kb_session) -> None:  # type: ignore[no-untyped-def]
    db, embedder = kb_session
    await embedder.warm_up()
    await search_kb(db, embedder, "warm the connection", 3)

    timings: list[float] = []
    for index, (question, _) in enumerate(RETRIEVAL_QUESTIONS):
        # A unique suffix per round keeps every query a cache miss, so the model really runs.
        started = time.perf_counter()
        await search_kb(db, embedder, f"{question} please {index}", 3)
        timings.append((time.perf_counter() - started) * 1000)

    median = statistics.median(timings)
    assert median < MEDIAN_BUDGET_MS, (
        f"median {median:.1f} ms (p90 {sorted(timings)[int(len(timings) * 0.9)]:.1f} ms)"
    )


async def test_category_filters_work_on_the_real_knowledge_base(kb_session) -> None:  # type: ignore[no-untyped-def]
    db, embedder = kb_session
    hits = await search_kb(db, embedder, "how much does it cost", 5, category="pricing")
    assert len(hits) == 5 and {h.category for h in hits} == {"pricing"}
    emergency = await search_kb(db, embedder, "my tooth was knocked out", 3, category="emergency")
    assert emergency[0].slug == "knocked-out-tooth"


async def test_irrelevant_questions_score_clearly_lower_than_relevant_ones(kb_session) -> None:  # type: ignore[no-untyped-def]
    """Phase 9 relies on score thresholds to decide when to answer and when to hand off."""
    db, embedder = kb_session
    relevant = [(await search_kb(db, embedder, q, 1))[0].score for q, _ in RETRIEVAL_QUESTIONS[:20]]
    unrelated = [
        (await search_kb(db, embedder, q, 1))[0].score
        for q in (
            "who won the football game",
            "recipe for chocolate cake",
            "capital of france",
            "write me a poem about dragons",
        )
    ]
    assert statistics.mean(relevant) > statistics.mean(unrelated) + 0.15
    assert max(unrelated) < statistics.mean(relevant)


async def test_the_best_chunk_for_a_question_contains_the_answer_text(kb_session) -> None:  # type: ignore[no-untyped-def]
    db, embedder = kb_session
    [hit] = await search_kb(db, embedder, "how much does a porcelain crown cost", 1)
    assert hit.slug == "price-crowns" and "$1,150" in hit.chunk.text


async def test_intent_examples_are_indexed_for_every_intent(kb_session) -> None:  # type: ignore[no-untyped-def]
    db, _ = kb_session
    counts: dict[str, int] = {}
    for intent in (await db.execute(select(IntentExample.intent))).scalars():
        counts[intent] = counts.get(intent, 0) + 1
    assert len(counts) == 13 and all(15 <= n <= 25 for n in counts.values())


async def test_held_out_phrases_are_routed_to_the_right_intent(kb_session) -> None:  # type: ignore[no-untyped-def]
    db, embedder = kb_session
    wrong: list[str] = []
    for phrase, expected in INTENT_PHRASES:
        match = await match_intent(db, embedder, phrase)
        if match is None or match.intent != expected:
            wrong.append(f"{phrase!r}: expected {expected}, got {match.intent if match else None}")
    accuracy = 1 - len(wrong) / len(INTENT_PHRASES)
    assert accuracy >= INTENT_TARGET, f"intent accuracy {accuracy:.1%}; wrong: {wrong}"


async def test_exact_example_phrases_match_with_a_very_high_score(kb_session) -> None:  # type: ignore[no-untyped-def]
    db, embedder = kb_session
    for phrase, intent in (
        ("what are your opening hours", "hours"),
        ("I want to cancel my appointment", "cancel"),
        ("thank you", "thanks"),
        ("I have a terrible toothache", "emergency"),
    ):
        match = await match_intent(db, embedder, phrase)
        assert match is not None and match.intent == intent and match.score > 0.95
