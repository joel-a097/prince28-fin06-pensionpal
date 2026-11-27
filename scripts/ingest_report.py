"""Refresh the database-backed Day 10 report while preserving personal notes."""

import asyncio
from pathlib import Path

from pensionpal.config import get_settings
from pensionpal.db.ingest_jobs import IngestRepository
from pensionpal.db.session import make_engine, make_sessionmaker

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "INGEST_REPORT.md"
START, END = "<!-- ingest-report:start -->", "<!-- ingest-report:end -->"


async def main() -> None:
    engine = make_engine(get_settings())
    try:
        async with make_sessionmaker(engine)() as session:
            stats = await IngestRepository(session).report()
    finally:
        await engine.dispose()
    table = "\n".join(
        [
            "| Measure | Value |",
            "|---|---:|",
            f"| Documents | {stats['documents']:,} |",
            f"| Pages | {stats['pages']:,} |",
            f"| Text characters | {stats['characters']:,} |",
            f"| Estimated tokens (characters / 4) | {stats['characters'] // 4:,} |",
            f"| Recorded extraction tokens | {stats['tokens']:,} |",
            f"| Dead-letter items | {stats['dead_letter']:,} |",
        ]
    )
    generated = f"{START}\n{table}\n{END}"
    old = (
        REPORT.read_text(encoding="utf-8")
        if REPORT.exists()
        else "# Ingestion report\n"
    )
    if START in old and END in old:
        before, rest = old.split(START, 1)
        _, after = rest.split(END, 1)
        content = before.rstrip() + "\n\n" + generated + after
    else:
        content = old.rstrip() + "\n\n" + generated + "\n"
    REPORT.write_text(content, encoding="utf-8")
    print(
        f"documents={stats['documents']} pages={stats['pages']} "
        f"dead_letter={stats['dead_letter']} -> docs/INGEST_REPORT.md"
    )


if __name__ == "__main__":
    asyncio.run(main())
