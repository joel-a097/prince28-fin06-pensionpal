"""Exercise ingestion state against a migrated PostgreSQL database."""

import hashlib
from types import SimpleNamespace

import httpx
import pytest
from arq import Retry
from sqlalchemy import select

from pensionpal.db.models import Document, IngestItem, IngestJob
from pensionpal.db.session import make_engine, make_sessionmaker
from pensionpal.workers.ingest import ingest_document, process


def context(database_url):
    settings = SimpleNamespace(ingest_max_tries=3, ingest_job_timeout=60)
    engine = make_engine(SimpleNamespace(database_url=database_url))
    return engine, make_sessionmaker(engine), settings


async def queued_item(sessionmaker, path, *, via="http"):
    payload = path.read_bytes() if path.exists() else b"missing file"
    record = {
        "url": "https://example.test/document",
        "path": str(path),
        "source": "test",
        "licence": "test fixture",
        "title": path.name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "status": "downloaded",
        "via": via,
    }
    async with sessionmaker() as session:
        job = IngestJob(id=hashlib.md5(str(path).encode()).hexdigest(), requested=1)
        item = IngestItem(job=job, record=record)
        session.add(job)
        await session.flush()
        item_id = item.id
        await session.commit()
    return item_id, record


@pytest.mark.asyncio
async def test_worker_parses_and_persists_manifest_file(database_url, tmp_path):
    path = tmp_path / "notice.md"
    path.write_text(
        "# Test notice\n\nThis document explains a sample pension claim process."
    )
    engine, sessionmaker, settings = context(database_url)
    item_id, _ = await queued_item(sessionmaker, path)
    async with httpx.AsyncClient() as client:
        ctx = {
            "settings": settings,
            "sessionmaker": sessionmaker,
            "http": client,
            "extract": None,
        }
        result = await ingest_document(ctx, item_id)
    async with sessionmaker() as session:
        item = await session.get(IngestItem, item_id)
    assert result == "done"
    assert item.status == "done"
    assert item.attempts == 1
    assert item.pages >= 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_reprocessing_same_content_does_not_duplicate_document(
    database_url, tmp_path
):
    path = tmp_path / "same.md"
    path.write_text(
        "# Idempotent\n\nThis content should be stored once by its content hash."
    )
    engine, sessionmaker, settings = context(database_url)
    item_id, _ = await queued_item(sessionmaker, path)
    async with httpx.AsyncClient() as client:
        ctx = {
            "settings": settings,
            "sessionmaker": sessionmaker,
            "http": client,
            "extract": None,
        }
        first = await process(ctx, item_id)
        second = await process(ctx, item_id)
    async with sessionmaker() as session:
        docs = list(
            await session.scalars(
                select(Document).where(
                    Document.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
                )
            )
        )
    assert first[0] == "done"
    assert second[0] == "skipped"
    assert len(docs) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_missing_manual_file_becomes_dead_letter(database_url, tmp_path):
    path = tmp_path / "missing.pdf"
    engine, sessionmaker, settings = context(database_url)
    item_id, record = await queued_item(sessionmaker, path, via="manual")
    record["path"] = str(path)
    async with sessionmaker() as session:
        item = await session.get(IngestItem, item_id)
        item.record = record
        await session.commit()
    async with httpx.AsyncClient() as client:
        ctx = {
            "settings": settings,
            "sessionmaker": sessionmaker,
            "http": client,
            "extract": None,
        }
        result = await ingest_document(ctx, item_id)
    async with sessionmaker() as session:
        item = await session.get(IngestItem, item_id)
    assert result == "failed"
    assert "exists only on the laptop" in item.error
    await engine.dispose()


@pytest.mark.asyncio
async def test_transient_worker_error_is_rescheduled(
    database_url, tmp_path, monkeypatch
):
    path = tmp_path / "retry.md"
    path.write_text("payload")
    engine, sessionmaker, settings = context(database_url)
    item_id, _ = await queued_item(sessionmaker, path)

    async def fail_once(*_):
        raise OSError("temporary outage")

    monkeypatch.setattr("pensionpal.workers.ingest.process", fail_once)
    async with httpx.AsyncClient() as client:
        ctx = {
            "settings": settings,
            "sessionmaker": sessionmaker,
            "http": client,
            "extract": None,
        }
        with pytest.raises(Retry):
            await ingest_document(ctx, item_id)
    async with sessionmaker() as session:
        item = await session.get(IngestItem, item_id)
    assert item.status == "queued"
    assert item.attempts == 1
    assert "temporary outage" in item.error
    await engine.dispose()
