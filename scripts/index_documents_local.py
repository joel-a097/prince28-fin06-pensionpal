"""Build the separate local-model index from corpus pages already in Postgres."""

import argparse
import asyncio
import logging

from pensionpal.config import get_settings
from pensionpal.db.session import make_engine, make_sessionmaker
from pensionpal.ingest.local_indexing import index_all_local_documents
from pensionpal.llm.local_embeddings import LocalFastEmbedder

logger = logging.getLogger("pensionpal.index_documents_local")


async def run(limit: int) -> int:
    settings = get_settings()
    engine = make_engine(settings)
    sessions = make_sessionmaker(engine)
    embedder = LocalFastEmbedder(
        model=settings.local_embedding_model,
        cache_dir=settings.local_embedding_cache_dir,
        threads=settings.local_embedding_threads,
    )
    try:
        counts = await index_all_local_documents(
            sessions, embedder, settings, limit=limit
        )
    finally:
        await embedder.aclose()
        await engine.dispose()
    logger.info(
        "Local indexing complete: indexed=%s unchanged=%s failed=%s chunks=%s",
        counts["indexed"],
        counts["unchanged"],
        counts["failed"],
        counts["chunks"],
    )
    return int(counts["failed"] > 0)


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
