"""Knowledge base documents: file format, validation, hashing and placeholders."""

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from app.core.config import Settings
from app.services.knowledge.chunking import CHUNKING_VERSION

CATEGORIES = frozenset(
    {
        "practice",
        "new-patients",
        "policies",
        "insurance-payment",
        "pricing",
        "procedures",
        "aftercare",
        "pediatric-comfort",
        "emergency",
        "oral-health",
    }
)
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SHORT_ANSWER_HEADING = re.compile(r"^##\s+Short answer\s*$", re.IGNORECASE | re.MULTILINE)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
MAX_BODY_CHARS = 20_000
REQUIRED_KEYS = ("id", "title", "category", "updated_at")


class KbValidationError(ValueError):
    """A document is malformed. ``problems`` lists every issue found."""

    def __init__(self, problems: list[str], source: str = "") -> None:
        super().__init__("; ".join(problems))
        self.problems = problems
        self.source = source


@dataclass(frozen=True)
class KbSource:
    slug: str
    title: str
    category: str
    updated_at: datetime
    body: str
    short_answer: str
    source: str = ""


def extract_short_answer(body: str) -> str | None:
    """The text under the final ``## Short answer`` heading, if any."""
    matches = list(SHORT_ANSWER_HEADING.finditer(body))
    if not matches:
        return None
    return body[matches[-1].end() :].strip() or None


def validate_fields(slug: str, title: str, category: str, body: str, *, source: str = "") -> str:
    """Check the parts of a document and return its short answer."""
    problems: list[str] = []
    if not SLUG_PATTERN.fullmatch(slug) or len(slug) > 120:
        problems.append("id must be lower case words joined by hyphens")
    if not title.strip() or len(title) > 200:
        problems.append("title must be 1 to 200 characters")
    if category not in CATEGORIES:
        problems.append(f"category must be one of: {', '.join(sorted(CATEGORIES))}")
    if not body.strip():
        problems.append("body must not be empty")
    if len(body) > MAX_BODY_CHARS:
        problems.append(f"body must be at most {MAX_BODY_CHARS} characters")
    answer = extract_short_answer(body)
    if answer is None:
        problems.append("body must end with a '## Short answer' section")
    else:
        sentences = [s for s in SENTENCE_END.split(answer) if s.strip()]
        if not 1 <= len(sentences) <= 3:
            problems.append("the short answer must be one to three sentences")
    if problems:
        raise KbValidationError(problems, source)
    return answer or ""


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    stripped = text.lstrip(chr(0xFEFF))
    if not stripped.startswith("---"):
        raise KbValidationError(["file must start with a front matter block"])
    parts = stripped.split("---", 2)
    if len(parts) < 3:
        raise KbValidationError(["front matter block is not closed"])
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        raise KbValidationError([f"front matter is not valid YAML: {exc}"]) from exc
    if not isinstance(meta, dict):
        raise KbValidationError(["front matter must be a mapping"])
    return meta, parts[2].strip()


def parse_kb_text(text: str, source: str = "") -> KbSource:
    meta, body = split_front_matter(text)
    problems = [f"missing front matter key: {key}" for key in REQUIRED_KEYS if key not in meta]
    if problems:
        raise KbValidationError(problems, source)
    updated = meta["updated_at"]
    if isinstance(updated, datetime):
        moment = updated if updated.tzinfo else updated.replace(tzinfo=UTC)
    elif isinstance(updated, date):
        moment = datetime(updated.year, updated.month, updated.day, tzinfo=UTC)
    else:
        raise KbValidationError(["updated_at must be a date such as 2026-09-01"], source)
    slug, title, category = str(meta["id"]), str(meta["title"]), str(meta["category"])
    answer = validate_fields(slug, title, category, body, source=source)
    return KbSource(slug, title, category, moment, body, answer, source)


def load_kb_directory(directory: Path) -> list[KbSource]:
    """Read and validate every markdown file. Raises one error listing every problem."""
    sources: list[KbSource] = []
    problems: list[str] = []
    seen: dict[str, str] = {}
    for path in sorted(directory.glob("*.md")):
        try:
            document = parse_kb_text(path.read_text(encoding="utf-8"), path.name)
        except KbValidationError as exc:
            problems.extend(f"{path.name}: {p}" for p in exc.problems)
            continue
        if document.slug != path.stem:
            problems.append(f"{path.name}: id '{document.slug}' must match the file name")
        if document.slug in seen:
            problems.append(f"{path.name}: duplicate id (also used by {seen[document.slug]})")
        seen[document.slug] = path.name
        sources.append(document)
    if problems:
        raise KbValidationError(problems)
    return sources


def render_placeholders(text: str, settings: Settings) -> str:
    """Fill {{clinic_name}} style placeholders so clinic details stay configuration."""
    values = {
        "clinic_name": settings.clinic_name,
        "clinic_phone": settings.clinic_phone,
        "clinic_address": settings.clinic_address,
        "clinic_email": settings.clinic_email,
    }

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise KbValidationError([f"unknown placeholder: {{{{{name}}}}}"])
        return values[name]

    return PLACEHOLDER.sub(replace, text)


def content_hash(title: str, category: str, body: str, model_name: str) -> str:
    """Identity of a document's embedded content, including how it is embedded."""
    payload = "\x1f".join([model_name, CHUNKING_VERSION, title, category, body])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
