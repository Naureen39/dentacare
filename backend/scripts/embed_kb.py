"""Index the knowledge base and the intent examples.

Usage (from the backend directory):

    uv run python -m scripts.embed_kb              # sync documents and intents
    uv run python -m scripts.embed_kb --check      # validate the files only, no database
    uv run python -m scripts.embed_kb --force      # re-embed everything, including admin edits
    uv run python -m scripts.embed_kb --prune      # also delete file managed documents that were removed

Only documents whose content changed are embedded again. Documents edited in the admin
console are left alone unless --force is given.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from app.core.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.services.knowledge.documents import KbValidationError, load_kb_directory
from app.services.knowledge.embeddings import EmbeddingService
from app.services.knowledge.indexer import sync_sources
from app.services.knowledge.search import load_intents, sync_intents


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--dir", type=Path, default=Path(settings.kb_dir), help="markdown directory"
    )
    parser.add_argument(
        "--intents", type=Path, default=Path(settings.intents_file), help="intents file"
    )
    parser.add_argument("--check", action="store_true", help="validate the files and exit")
    parser.add_argument("--force", action="store_true", help="re-embed every document")
    parser.add_argument(
        "--prune", action="store_true", help="delete documents no longer in the directory"
    )
    parser.add_argument("--skip-intents", action="store_true", help="do not touch intent examples")
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        sources = load_kb_directory(args.dir)
    except KbValidationError as exc:
        print("Knowledge base files are not valid:")
        for problem in exc.problems:
            print(f"  - {problem}")
        return 1
    print(f"{len(sources)} documents are valid in {args.dir}")
    if args.check:
        return 0

    engine = create_engine(settings)
    factory = create_session_factory(engine)
    embedder = EmbeddingService(settings.embed_model, settings.embed_cache_dir)
    try:
        async with factory() as db:
            report = await sync_sources(
                db,
                embedder,
                sources,
                settings,
                model_name=settings.embed_model,
                force=args.force,
                prune=args.prune,
            )
            print(
                f"documents: {len(report.added)} added, {len(report.updated)} updated, "
                f"{len(report.unchanged)} unchanged, {len(report.skipped_admin)} kept (edited in console), "
                f"{len(report.removed)} removed; {report.chunks_written} chunks written"
            )
            if not args.skip_intents:
                counts = await sync_intents(db, embedder, load_intents(args.intents))
                print(
                    f"intents: {counts['added']} added, {counts['removed']} removed, {counts['total']} total"
                )
    finally:
        embedder.close()
        await engine.dispose()
    return 0


def main() -> None:
    sys.exit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
