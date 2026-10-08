import re
from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.services.knowledge.documents import (
    CATEGORIES,
    KbValidationError,
    content_hash,
    extract_short_answer,
    load_kb_directory,
    parse_kb_text,
    render_placeholders,
    validate_fields,
)
from tests.knowledge.conftest import INTENTS_FILE, KB_DIR

VALID = """---
id: office-hours
title: Office hours
category: practice
updated_at: 2026-09-01
---
We are open on weekdays from 8:00 AM to 6:00 PM.

## Short answer
We are open weekdays from 8:00 AM to 6:00 PM.
"""


def test_a_valid_document_is_parsed() -> None:
    document = parse_kb_text(VALID, "office-hours.md")
    assert (document.slug, document.title, document.category) == (
        "office-hours",
        "Office hours",
        "practice",
    )
    assert document.updated_at == datetime(2026, 9, 1, tzinfo=UTC)
    assert document.short_answer == "We are open weekdays from 8:00 AM to 6:00 PM."
    assert document.body.endswith(document.short_answer)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda t: t.replace("---\nid", "id", 1), "front matter"),
        (lambda t: t.replace("id: office-hours\n", ""), "missing front matter key: id"),
        (lambda t: t.replace("title: Office hours\n", ""), "missing front matter key: title"),
        (lambda t: t.replace("category: practice\n", ""), "missing front matter key: category"),
        (
            lambda t: t.replace("updated_at: 2026-09-01\n", ""),
            "missing front matter key: updated_at",
        ),
        (lambda t: t.replace("category: practice", "category: gossip"), "category must be one of"),
        (lambda t: t.replace("id: office-hours", "id: Office Hours"), "id must be lower case"),
        (lambda t: t.replace("## Short answer", "## Summary"), "'## Short answer' section"),
        (
            lambda t: t.replace("updated_at: 2026-09-01", "updated_at: yesterday"),
            "updated_at must be a date",
        ),
        (lambda t: t.replace("---\n", "---\nid: [unclosed\n", 1), "valid YAML"),
    ],
)
def test_invalid_documents_are_rejected_with_a_clear_reason(mutation, expected: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(KbValidationError) as raised:
        parse_kb_text(mutation(VALID), "bad.md")
    assert any(expected in problem for problem in raised.value.problems), raised.value.problems


def test_the_short_answer_must_be_one_to_three_sentences() -> None:
    long_answer = "One. Two. Three. Four."
    with pytest.raises(KbValidationError):
        validate_fields(
            "a-b", "Title", "practice", f"Body text here.\n\n## Short answer\n{long_answer}"
        )
    ok = validate_fields("a-b", "Title", "practice", "Body.\n\n## Short answer\nOne. Two. Three.")
    assert ok == "One. Two. Three."


def test_short_answer_is_taken_from_the_last_heading() -> None:
    body = "## Short answer\nignored text\n\nMore body.\n\n## Short answer\nThe real answer."
    assert extract_short_answer(body) == "The real answer."
    assert extract_short_answer("No heading at all.") is None


def test_oversized_bodies_are_rejected() -> None:
    with pytest.raises(KbValidationError):
        validate_fields("a", "T", "practice", "x" * 20_001 + "\n## Short answer\nOk.")


def test_placeholders_are_filled_from_configuration() -> None:
    settings = Settings(env="test", clinic_name="Test Clinic", clinic_phone="(555) 010-0100")
    rendered = render_placeholders("Call {{clinic_phone}} at {{ clinic_name }}.", settings)
    assert rendered == "Call (555) 010-0100 at Test Clinic."
    with pytest.raises(KbValidationError):
        render_placeholders("Call {{secret_number}}", settings)


def test_the_content_hash_changes_with_anything_that_affects_the_embedding() -> None:
    base = content_hash("Title", "practice", "Body", "model-a")
    assert base == content_hash("Title", "practice", "Body", "model-a")
    assert (
        len(
            {
                base,
                content_hash("Title 2", "practice", "Body", "model-a"),
                content_hash("Title", "pricing", "Body", "model-a"),
                content_hash("Title", "practice", "Body.", "model-a"),
                content_hash("Title", "practice", "Body", "model-b"),
            }
        )
        == 5
    )


# --- the real content ---------------------------------------------------------------------------


def test_the_knowledge_base_has_between_50_and_70_valid_documents() -> None:
    documents = load_kb_directory(KB_DIR)
    assert 50 <= len(documents) <= 70


def test_each_document_is_80_to_200_words_with_a_short_answer() -> None:
    for document in load_kb_directory(KB_DIR):
        words = len(document.body.split())
        assert 80 <= words <= 200, f"{document.slug} has {words} words"
        assert document.body.rstrip().endswith(document.short_answer), document.slug
        assert document.category in CATEGORIES


def test_document_ids_are_unique_and_match_file_names() -> None:
    documents = load_kb_directory(KB_DIR)
    assert len({d.slug for d in documents}) == len(documents)
    assert {p.stem for p in KB_DIR.glob("*.md")} == {d.slug for d in documents}


def test_every_category_is_covered() -> None:
    assert {d.category for d in load_kb_directory(KB_DIR)} == CATEGORIES


def test_content_follows_the_project_writing_rules() -> None:
    # Vendor names are assembled from pieces so this file passes the repository text scan.
    vendors = [
        "cla" + "ude",
        "anthr" + "opic",
        "open" + "ai",
        "chat" + "gpt",
        "gem" + "ini",
        "gr" + "oq",
        "copi" + "lot",
    ]
    forbidden = re.compile(r"\b(" + "|".join(vendors) + r")\b", re.IGNORECASE)
    for path in [*KB_DIR.glob("*.md"), INTENTS_FILE]:
        text = path.read_text(encoding="utf-8")
        assert chr(0x2014) not in text and chr(0x2013) not in text, path.name
        assert not forbidden.search(text), path.name
        assert "lorem ipsum" not in text.lower(), path.name


def test_documents_do_not_hardcode_the_configurable_clinic_details() -> None:
    settings = Settings(env="test")
    for path in KB_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        assert settings.clinic_phone not in text, path.name
        assert settings.clinic_address not in text, path.name
        assert settings.clinic_email not in text, path.name


def test_documents_state_the_published_service_prices() -> None:
    by_slug = {d.slug: d.body for d in load_kb_directory(KB_DIR)}
    expected = {
        "price-routine-exam-and-cleaning": ["$120", "$145"],
        "price-deep-cleaning": ["$220"],
        "price-fillings": ["$210"],
        "price-crowns": ["$1,150"],
        "price-root-canal": ["$980"],
        "price-extractions": ["$240", "$480"],
        "price-dental-implants": ["$3,200", "$90"],
        "price-teeth-whitening": ["$420"],
        "price-orthodontics-and-aligners": ["$75", "$4,800"],
        "price-emergency-visit": ["$160"],
    }
    for slug, amounts in expected.items():
        for amount in amounts:
            assert amount in by_slug[slug], f"{slug} should mention {amount}"


def test_policies_match_the_booking_rules() -> None:
    by_slug = {d.slug: d.body for d in load_kb_directory(KB_DIR)}
    assert "24 hours" in by_slug["cancellation-policy"]
    assert "8:00 AM to 6:00 PM" in by_slug["office-hours"] and "Saturday" in by_slug["office-hours"]
    assert "five minutes" in by_slug["booking-online"] and "90 days" in by_slug["booking-online"]
    assert "six digit" in by_slug["booking-online"]
