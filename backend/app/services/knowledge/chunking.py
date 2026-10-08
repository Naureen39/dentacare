"""Splitting a document into overlapping chunks that keep their headings.

Token counts are approximated with a word and punctuation count, which stays close to the
BERT word piece count for English prose and needs no model. Chunks target 180 tokens and
share 30 tokens with their neighbour. Every chunk starts with the document title and the
heading of its section, so a chunk is understandable on its own.
"""

import re
from dataclasses import dataclass

TARGET_TOKENS = 180
OVERLAP_TOKENS = 30
CHUNKING_VERSION = "1"  # bump to force re-embedding after changing the rules below

_TOKEN = re.compile(r"\w+|[^\w\s]")
_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def count_tokens(text: str) -> int:
    return len(_TOKEN.findall(text))


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str
    token_count: int


def _sections(title: str, body: str) -> list[tuple[str, str]]:
    """Split the body at headings. Returns (heading path, text) pairs."""
    sections: list[tuple[str, list[str]]] = [(title, [])]
    for line in body.splitlines():
        match = _HEADING.match(line)
        if match:
            level, heading = len(match.group(1)), match.group(2)
            if level == 1 and heading.strip().lower() == title.strip().lower():
                continue  # the title is already the root of every path
            sections.append((f"{title} > {heading}", []))
        else:
            sections[-1][1].append(line)
    result = []
    for path, lines in sections:
        text = " ".join(part.strip() for part in "\n".join(lines).split("\n\n") if part.strip())
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            result.append((path, text))
    return result


def _windows(sentences: list[str], budget: int, overlap: int) -> list[list[str]]:
    """Group sentences into windows of about ``budget`` tokens that overlap by ``overlap``."""
    windows: list[list[str]] = []
    current: list[str] = []
    used = 0
    for sentence in sentences:
        size = count_tokens(sentence)
        if current and used + size > budget:
            windows.append(current)
            # carry the tail of the previous window forward as overlap
            tail: list[str] = []
            carried = 0
            for previous in reversed(current):
                previous_size = count_tokens(previous)
                if carried + previous_size > overlap and tail:
                    break
                tail.insert(0, previous)
                carried += previous_size
                if carried >= overlap:
                    break
            current, used = tail, carried
        current.append(sentence)
        used += size
    if current:
        windows.append(current)
    return windows


def chunk_document(
    title: str, body: str, *, target: int = TARGET_TOKENS, overlap: int = OVERLAP_TOKENS
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path, text in _sections(title, body):
        sentences = [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]
        for window in _windows(sentences, target, overlap):
            content = f"{path}\n{' '.join(window)}"
            chunks.append(Chunk(len(chunks), content, count_tokens(content)))
    return chunks
