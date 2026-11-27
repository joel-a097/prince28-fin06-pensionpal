"""Parse downloaded source files into documents/pages and dead-letter failures."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from pathlib import Path

from pensionpal.config import get_settings
from pensionpal.db.session import make_engine, make_sessionmaker
from pensionpal.ingest.parse import (
    ParsedDoc,
    ParseError,
    parse_file,
    parse_pdf_ocr,
    parse_pdf_pypdf,
)
from pensionpal.ingest.store import (
    already_parsed,
    content_hash,
    has_failure,
    save_failure,
    save_parsed,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifest.jsonl"


def source_files() -> list[dict]:
    if not MANIFEST.exists():
        return []
    latest: dict[str, dict] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("url"):
            latest[record["url"]] = record
    return [
        record
        for record in latest.values()
        if record.get("status") == "downloaded" and record.get("path")
    ]


def parse_source(path: Path, ocr: str | None = None) -> ParsedDoc:
    """Try the layout parser first, then text-only extraction, then optional OCR."""
    try:
        return parse_file(path)
    except ParseError as primary:
        if path.suffix.lower() != ".pdf" or primary.reason != "no_text_layer":
            raise
        try:
            return parse_pdf_pypdf(path)
        except ParseError as fallback:
            if ocr:
                return parse_pdf_ocr(path, ocr)
            if fallback.reason == "no_text_layer":
                raise fallback from primary
            raise


async def process(args: argparse.Namespace) -> int:
    records = source_files()
    if args.limit is not None:
        records = records[: args.limit]
    counts = Counter()
    reasons: Counter[str] = Counter()
    started = time.monotonic()
    engine = make_engine(get_settings())
    sessions = make_sessionmaker(engine)
    raw_root = (ROOT / "data" / "raw").resolve()
    try:
        for number, record in enumerate(records, start=1):
            relative = Path(record["path"])
            path = (ROOT / relative).resolve()
            if raw_root not in path.parents:
                raise ValueError(f"manifest path escapes data/raw: {relative}")
            rel = relative.as_posix()
            if path.is_file():
                digest = content_hash(path)
            else:
                digest = record.get("sha256") or "0" * 64
            skip = False
            async with sessions() as session, session.begin():
                source_title = record.get("title")
                if path.is_file() and await already_parsed(
                    session, rel, digest, source_title
                ):
                    counts["already_parsed"] += 1
                    skip = True
                elif not args.retry_failed and await has_failure(session, rel):
                    counts["failed_before"] += 1
                    skip = True
            if skip:
                continue

            # Parsing and OCR can take minutes for large scans. Keep that work
            # outside a database transaction so Neon does not time it out.
            try:
                if not path.is_file():
                    raise ParseError("missing_file", "manifest path is not present")
                parsed = parse_source(path, args.ocr)
            except ParseError as error:
                async with sessions() as session, session.begin():
                    attempts = await save_failure(
                        session,
                        path=rel,
                        sha256=digest,
                        source_url=record.get("final_url") or record["url"],
                        error=error,
                    )
                counts["failed"] += 1
                reasons[error.reason] += 1
                print(
                    f"failed {error.reason:<16} {rel} attempts={attempts}",
                    flush=True,
                )
                continue

            async with sessions() as session, session.begin():
                action, page_count = await save_parsed(
                    session,
                    path=rel,
                    sha256=digest,
                    source_url=record.get("final_url") or record["url"],
                    licence=record.get("licence"),
                    source_title=source_title,
                    parsed=parsed,
                )
                counts[action] += 1
                counts["pages"] += page_count
                print(f"parsed {action:<8} {rel} pages={page_count}", flush=True)
            if number % 50 == 0:
                print(f"progress {number}/{len(records)}", flush=True)
    finally:
        await engine.dispose()
    print(
        f"files={len(records)} parsed={counts['inserted'] + counts['updated']} "
        f"already_parsed={counts['already_parsed']} failed_before={counts['failed_before']} "
        f"failed={counts['failed']} pages={counts['pages']} "
        f"seconds={time.monotonic() - started:.1f}"
    )
    if reasons:
        print(
            "failure reasons: "
            + ", ".join(f"{k}={v}" for k, v in sorted(reasons.items()))
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--ocr", metavar="LANGUAGE")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    try:
        return asyncio.run(process(args))
    except KeyboardInterrupt:
        print(
            "Stopped. Each finished file has its own committed transaction; rerun to resume."
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
