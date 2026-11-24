"""Persist parser results in Postgres, keeping one transaction per source file."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pensionpal.db.models import Document, Page, ParseFailure
from pensionpal.ingest.parse import ParsedDoc, ParseError


def content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def external_id(path: str) -> str:
    return hashlib.sha256(path.replace("\\", "/").encode("utf-8")).hexdigest()


async def already_parsed(
    session: AsyncSession, path: str, sha256: str, source_title: str | None = None
) -> bool:
    row = await session.scalar(
        select(Document).where(Document.external_id == external_id(path))
    )
    return bool(
        row
        and row.sha256 == sha256
        and (source_title is None or row.title == source_title)
    )


async def has_failure(session: AsyncSession, path: str) -> bool:
    return (
        await session.scalar(select(ParseFailure.id).where(ParseFailure.path == path))
        is not None
    )


async def save_parsed(
    session: AsyncSession,
    *,
    path: str,
    sha256: str,
    source_url: str | None,
    licence: str | None,
    source_title: str | None,
    parsed: ParsedDoc,
) -> tuple[str, int]:
    """Insert or replace a parsed document and its pages; clear any old failure."""
    doc_id = external_id(path)
    document = await session.scalar(
        select(Document).where(Document.external_id == doc_id)
    )
    action = "inserted" if document is None else "updated"
    values = {
        "title": source_title or parsed.title or Path(path).stem,
        "source_url": source_url,
        "licence": (licence or "")[:200] or None,
        "doc_type": "corpus",
        "sha256": sha256,
        "metadata_": {
            "kind": parsed.kind,
            "parser": parsed.parser,
            "parsed_title": parsed.title,
            "pages": len(parsed.pages),
            "tables": sum(page.tables for page in parsed.pages),
            "path": path,
        },
    }
    if document is None:
        document = Document(external_id=doc_id, **values)
        session.add(document)
        await session.flush()
    else:
        await session.execute(delete(Page).where(Page.document_id == document.id))
        for key, value in values.items():
            setattr(document, key, value)
        await session.flush()
    session.add_all(
        [
            Page(
                document_id=document.id,
                page_no=page.page_no,
                text=page.text,
                headings=page.headings,
            )
            for page in parsed.pages
        ]
    )
    failure = await session.scalar(
        select(ParseFailure).where(ParseFailure.path == path)
    )
    if failure is not None:
        await session.delete(failure)
    await session.flush()
    return action, len(parsed.pages)


async def save_failure(
    session: AsyncSession,
    *,
    path: str,
    sha256: str,
    source_url: str | None,
    error: ParseError,
) -> int:
    """Upsert a dead-letter row and increase attempts on each explicit retry."""
    failure = await session.scalar(
        select(ParseFailure).where(ParseFailure.path == path)
    )
    if failure is None:
        failure = ParseFailure(
            path=path,
            sha256=sha256,
            source_url=source_url,
            reason=error.reason[:40],
            detail=error.detail,
            attempts=1,
        )
        session.add(failure)
        attempts = 1
    else:
        failure.sha256 = sha256
        failure.source_url = source_url
        failure.reason = error.reason[:40]
        failure.detail = error.detail
        failure.attempts = (failure.attempts or 1) + 1
        attempts = failure.attempts
    await session.flush()
    return attempts
