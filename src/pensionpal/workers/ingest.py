"""One ARQ task processes one manifest document, safely across retries."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import tempfile
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import httpx
from arq import Retry
from sqlalchemy import and_, func, or_, select, update

from pensionpal.db.models import Document, IngestItem
from pensionpal.ingest.fetch import RETRYABLE, HostGate, Robots, Source, fetch_one
from pensionpal.ingest.local_indexing import index_local_document
from pensionpal.ingest.parse import (
    ParseError,
    parse_file,
    parse_pdf_ocr,
    parse_pdf_pypdf,
)
from pensionpal.ingest.store import lock_document_keys, save_failure, save_parsed
from pensionpal.llm.extract import document_text, extract, save

logger = logging.getLogger("pensionpal.worker")
GITHUB_BLOB = re.compile(r"^https://github\.com/([^/]+/[^/]+)/blob/[^/]+/(.+)$")


class Permanent(Exception):
    """An error that will not be fixed by retrying the same input."""


def plan(
    records: list[dict], done_ids: set[str], *, source: str = "", limit: int = 0
) -> list[dict]:
    """Select downloaded, not-yet-known records and deduplicate by content hash."""
    todo, seen = [], set(done_ids)
    for record in records:
        if record.get("status") != "downloaded" or (
            source and record.get("source") != source
        ):
            continue
        digest = record.get("sha256")
        if not digest or digest in seen:
            continue
        seen.add(digest)
        todo.append(record)
    return todo[:limit] if limit else todo


class Pace:
    """Throttle model work within one worker process."""

    def __init__(
        self, per_minute: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if per_minute <= 0:
            raise ValueError("per_minute must be positive")
        self._gap, self._clock, self._next = 60 / per_minute, clock, 0.0

    async def wait(self) -> None:
        now = self._clock()
        delay = max(0.0, self._next - now)
        self._next = max(now, self._next) + self._gap
        if delay:
            await asyncio.sleep(delay)


class PacedGateway:
    """Apply the worker rate limit to every provider attempt, including repairs."""

    def __init__(self, gateway, pace: Pace) -> None:
        self.gateway, self.pace = gateway, pace

    async def generate(self, *args, **kwargs):
        await self.pace.wait()
        return await self.gateway.generate(*args, **kwargs)


async def get_file(record: dict, folder: Path, client: httpx.AsyncClient) -> Path:
    """Use local corpus files when present; otherwise fetch them politely."""
    path = Path(record["path"])
    if path.is_file():
        return path
    if record.get("via") == "manual":
        raise Permanent(
            "downloaded by hand: this file exists only on the laptop that has it"
        )
    url = record["url"]
    match = GITHUB_BLOB.match(url)
    if record.get("via", "").startswith("git:") and match:
        commit = (
            record.get("commit")
            or match.group(0).split("/blob/", 1)[1].split("/", 1)[0]
        )
        url = f"https://raw.githubusercontent.com/{match[1]}/{commit}/{match[2]}"
    source = Source(
        url, record.get("source", "unknown"), record.get("licence") or "unknown"
    )
    result = await fetch_one(
        client,
        source,
        root=folder,
        raw_dir=folder / "raw",
        robots=Robots(client),
        gate=HostGate(0.5, asyncio.sleep),
        slots=asyncio.Semaphore(1),
        max_attempts=2,
        sleep=asyncio.sleep,
    )
    if result.get("status") == "downloaded":
        return folder / result["path"]
    problem = f"download {result.get('status')}: {result.get('error', '')}"
    if result.get("status") == "blocked" or result.get("http_status") not in {
        None,
        *RETRYABLE,
    }:
        raise Permanent(problem)
    raise RuntimeError(problem)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_document(path: Path):
    """Use the normal parser, then text-only PDF extraction, then English OCR."""
    try:
        return parse_file(path)
    except ParseError as primary:
        if path.suffix.lower() != ".pdf" or primary.reason != "no_text_layer":
            raise
    try:
        return parse_pdf_pypdf(path)
    except ParseError as fallback:
        if fallback.reason != "no_text_layer":
            raise
        return parse_pdf_ocr(path, "eng")


async def process(ctx: dict, item_id: int) -> tuple[str, int]:
    """Fetch, parse, save, and extract without holding DB transactions over I/O."""
    async with ctx["sessionmaker"]() as session:
        item = await session.get(IngestItem, item_id)
        if item is None:
            raise Permanent(f"ingest item {item_id} disappeared")
        record = dict(item.record)

    with tempfile.TemporaryDirectory() as temp:
        path = await get_file(record, Path(temp), ctx["http"])
        digest = await asyncio.to_thread(sha256_of, path)
        async with ctx["sessionmaker"]() as session:
            existing = await session.scalar(
                select(Document).where(Document.sha256 == digest)
            )
            if existing is not None:
                doc_id, title = existing.id, existing.title
                pages = int(existing.metadata_.get("pages", 0))
                note = existing.metadata_.get("extract") or {}
                status = "skipped"
            else:
                status = "done"
        if existing is None:
            try:
                parsed = await asyncio.to_thread(parse_document, path)
            except ParseError as error:
                async with ctx["sessionmaker"]() as session, session.begin():
                    await save_failure(
                        session,
                        path=record["path"],
                        sha256=digest,
                        source_url=record.get("url"),
                        error=error,
                    )
                raise Permanent(f"parse: {error.reason}") from error
            async with ctx["sessionmaker"]() as session, session.begin():
                await lock_document_keys(session, f"sha:{digest}")
                current = await session.scalar(
                    select(Document).where(Document.sha256 == digest).with_for_update()
                )
                if current is None:
                    await save_parsed(
                        session,
                        path=record["path"],
                        sha256=digest,
                        source_url=record.get("final_url") or record.get("url"),
                        licence=record.get("licence"),
                        source_title=record.get("title"),
                        parsed=parsed,
                    )
                else:
                    status = "skipped"
        async with ctx["sessionmaker"]() as session:
            document = await session.scalar(
                select(Document).where(Document.sha256 == digest)
            )
            if document is None:
                raise RuntimeError("saved document could not be read back")
            doc_id, title = document.id, document.title
            document_external_id = document.external_id
            pages = int(document.metadata_.get("pages", 0))
            note = document.metadata_.get("extract") or {}

    embedder = ctx.get("embedder")
    if embedder is not None and embedder.configured:
        await index_local_document(
            ctx["sessionmaker"],
            embedder,
            document_external_id,
            ctx["settings"],
        )
    elif embedder is not None:
        logger.warning(
            "document %s saved without local retrieval indexing",
            document_external_id,
        )

    task = ctx.get("extract")
    if task and note.get("prompt") != task["version"]:
        async with ctx["sessionmaker"]() as session:
            document = await session.get(Document, doc_id)
            text = await document_text(session, document, task["chars"])
        if not text.strip():
            raise Permanent("extract: document has no parsed page text")
        result = await extract(
            ctx["paced_gateway"],
            task["schema"],
            task["prompt"],
            task["version"],
            title,
            text,
        )
        async with ctx["sessionmaker"]() as session:
            document = await session.get(Document, doc_id)
            await save(session, document, result, task["version"])
        if result.record is None:
            raise Permanent(f"extract: {result.errors[-1][:200]}")
        status = "done"
    return status, pages


async def ingest_document(ctx: dict, item_id: int) -> str:
    """Persist state transitions before and after processing; retry transient errors."""
    settings = ctx["settings"]
    async with ctx["sessionmaker"]() as session:
        stale_before = func.now() - timedelta(
            seconds=max(1, settings.ingest_job_timeout - 5)
        )
        claim = await session.execute(
            update(IngestItem)
            .where(
                IngestItem.id == item_id,
                or_(
                    IngestItem.status == "queued",
                    and_(
                        IngestItem.status == "running",
                        IngestItem.updated_at < stale_before,
                    ),
                ),
                IngestItem.attempts < settings.ingest_max_tries,
            )
            .values(
                status="running",
                attempts=IngestItem.attempts + 1,
                updated_at=func.now(),
            )
            .returning(IngestItem.attempts)
        )
        attempt = claim.scalar_one_or_none()
        if attempt is None:
            failed = await session.execute(
                update(IngestItem)
                .where(
                    IngestItem.id == item_id,
                    IngestItem.status == "running",
                    IngestItem.attempts >= settings.ingest_max_tries,
                    IngestItem.updated_at < stale_before,
                )
                .values(
                    status="failed",
                    error="gave up after repeated worker crashes",
                    updated_at=func.now(),
                )
            )
            if failed.rowcount:
                await session.commit()
                return "failed"
            await session.rollback()
            return "ignored"
        await session.commit()

    try:
        status, pages = await process(ctx, item_id)
    except Permanent as error:
        status, pages, detail = "failed", 0, str(error)[:500]
    except Exception as error:  # provider, network, and unexpected transient errors
        detail = f"{type(error).__name__}: {error}"[:500]
        status, pages = "failed", 0
        if attempt < settings.ingest_max_tries:
            async with ctx["sessionmaker"]() as session:
                item = await session.get(IngestItem, item_id)
                item.status, item.error = "queued", f"try {attempt} failed: {detail}"
                await session.commit()
            logger.warning("item %s will be retried: %s", item_id, detail)
            raise Retry(defer=attempt * 30) from error
        detail = f"gave up after {attempt} tries: {detail}"
    else:
        detail = ""

    async with ctx["sessionmaker"]() as session:
        item = await session.get(IngestItem, item_id)
        item.status, item.pages, item.error = status, pages, detail
        await session.commit()
    logger.info("item %s %s", item_id, status)
    return status
