import re

from app.services.knowledge.chunking import (
    OVERLAP_TOKENS,
    TARGET_TOKENS,
    chunk_document,
    count_tokens,
)
from app.services.knowledge.documents import load_kb_directory
from tests.knowledge.conftest import KB_DIR

SENTENCE = "The dentist explains every step of the treatment in plain and friendly language."


def long_body(sentences: int) -> str:
    return " ".join(f"{SENTENCE[:-1]} number {i}." for i in range(sentences))


def test_token_count_counts_words_and_punctuation() -> None:
    assert count_tokens("Hello, world!") == 4
    assert count_tokens("") == 0
    assert count_tokens("don't stop") >= 3


def test_a_short_document_is_one_chunk_that_starts_with_its_title() -> None:
    chunks = chunk_document("Office hours", "We are open on weekdays. Closed on Sunday.")
    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].text == "Office hours\nWe are open on weekdays. Closed on Sunday."
    assert chunks[0].token_count == count_tokens(chunks[0].text)


def test_headings_are_kept_as_a_path_in_front_of_their_section() -> None:
    body = "Intro text about the clinic.\n\n## Parking\nFree parking is beside the building.\n\n## Short answer\nParking is free."
    chunks = chunk_document("Getting here", body)
    assert [c.text.split("\n")[0] for c in chunks] == [
        "Getting here",
        "Getting here > Parking",
        "Getting here > Short answer",
    ]
    assert "Free parking is beside the building." in chunks[1].text
    assert [c.index for c in chunks] == [0, 1, 2]


def test_a_repeated_title_heading_is_not_duplicated() -> None:
    chunks = chunk_document("Office hours", "# Office hours\nOpen weekdays.")
    assert chunks[0].text.splitlines()[0] == "Office hours"
    assert "Office hours > Office hours" not in chunks[0].text


def test_long_sections_split_into_chunks_near_the_target_size() -> None:
    chunks = chunk_document("Long guide", long_body(60))
    assert len(chunks) > 2
    sizes = [c.token_count for c in chunks]
    assert all(size <= TARGET_TOKENS + 25 for size in sizes)  # path line plus one sentence of slack
    assert all(size >= 60 for size in sizes[:-1])


def test_consecutive_chunks_overlap_by_about_thirty_tokens() -> None:
    chunks = chunk_document("Long guide", long_body(60))
    for earlier, later in zip(chunks, chunks[1:], strict=False):
        body_earlier = earlier.text.split("\n", 1)[1]
        body_later = later.text.split("\n", 1)[1]
        first_sentence_later = re.split(r"(?<=\.)\s", body_later)[0]
        assert (
            first_sentence_later in body_earlier
        )  # the overlap is real text from the previous chunk
        carried = 0
        for sentence in reversed(re.split(r"(?<=\.)\s", body_earlier)):
            if sentence in body_later:
                carried += count_tokens(sentence)
        assert OVERLAP_TOKENS - 20 <= carried <= OVERLAP_TOKENS + 25


def test_every_sentence_is_present_in_some_chunk() -> None:
    body = long_body(45)
    joined = " ".join(c.text for c in chunk_document("Guide", body))
    for i in range(45):
        assert f"number {i}." in joined


def test_chunking_is_deterministic_and_handles_empty_bodies() -> None:
    assert chunk_document("Guide", long_body(30)) == chunk_document("Guide", long_body(30))
    assert chunk_document("Guide", "") == []
    assert chunk_document("Guide", "\n\n  \n") == []


def test_a_single_very_long_sentence_still_becomes_a_chunk() -> None:
    chunks = chunk_document("Guide", "word " * 400 + ".")
    assert len(chunks) == 1


def test_real_documents_chunk_into_a_small_number_of_reasonable_pieces() -> None:
    for document in load_kb_directory(KB_DIR):
        chunks = chunk_document(document.title, document.body)
        assert 1 <= len(chunks) <= 4, document.slug
        assert all(c.token_count <= 300 for c in chunks), document.slug
        assert chunks[-1].text.splitlines()[0].endswith("Short answer"), document.slug
