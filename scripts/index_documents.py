"""Backfill pgvector chunks for documents already stored in Postgres."""

import argparse
import asyncio
import logging

from pensionpal.config import get_settings
from pensionpal.db.session import make_engine, make_sessionmaker
from pensionpal.ingest.indexing import index_all_documents
from pensionpal.llm.embeddings import GeminiEmbedder

logger = logging.getLogger("pensionpal.index_documents")


async def run(limit: int) -> int:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise SystemExit("Set GEMINI_API_KEY in .env to generate document embeddings.")
    engine = make_engine(settings)
    sessions = make_sessionmaker(engine)
    embedder = GeminiEmbedder(
        settings.gemini_api_key,
        model=settings.embedding_model,
        batch_size=settings.embedding_batch_size,
    )
    try:
        counts = await index_all_documents(sessions, embedder, settings, limit=limit)
    finally:
        await embedder.aclose()
        await engine.dispose()
    logger.info(
        "Indexing complete: indexed=%s unchanged=%s chunks=%s",
        counts["indexed"],
        counts["unchanged"],
        counts["chunks"],
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=0, help="maximum documents (0 = all)"
    )
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit cannot be negative")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return asyncio.run(run(args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
