"""Database operations for durable ingestion jobs and dead letters."""

from collections import Counter
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pensionpal.db.models import (
    Document,
    IngestItem,
    IngestJob,
    LlmCall,
    Page,
    ParseFailure,
)
from pensionpal.ingest.parse import ParsedDoc
from pensionpal.ingest.store import external_id, lock_document_keys, save_parsed


class IngestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def known_ids(self) -> set[str]:
        ids = set(await self.session.scalars(select(Document.sha256)))
        queued = await self.session.scalars(
            select(IngestItem.record["sha256"].astext).where(
                IngestItem.status.in_(["queued", "running"])
            )
        )
        return ids | {value for value in queued if value}

    async def create(self, records: list[dict]) -> tuple[str, list[int]]:
        job_id = uuid4().hex
        job = IngestJob(id=job_id, requested=len(records))
        self.session.add(job)
        await self.session.flush()
        items = [IngestItem(job_id=job_id, record=record) for record in records]
        self.session.add_all(items)
        await self.session.flush()
        item_ids = [item.id for item in items]
        await self.session.commit()
        return job_id, item_ids

    async def save_local_document(
        self, record: dict, parsed: ParsedDoc
    ) -> dict[str, str | int]:
        """Save locally parsed pages, skipping existing paths and content hashes."""
        path = record["path"]
        digest = record["sha256"]
        identity = external_id(path)
        async with self.session.begin():
            # Serialize identical API uploads so a client retry cannot race itself.
            await lock_document_keys(self.session, f"path:{identity}", f"sha:{digest}")

            existing_path = await self.session.scalar(
                select(Document)
                .where(Document.external_id == identity)
                .with_for_update()
            )
            if existing_path is not None:
                if existing_path.sha256 != digest:
                    return {
                        "status": "conflict",
                        "document_id": existing_path.external_id,
                        "pages": 0,
                    }
                page_count = await self.session.scalar(
                    select(func.count(Page.id)).where(
                        Page.document_id == existing_path.id
                    )
                )
                if page_count:
                    return {
                        "status": "skipped_duplicate",
                        "document_id": existing_path.external_id,
                        "pages": int(page_count),
                    }

            existing_hash = await self.session.scalar(
                select(Document).where(Document.sha256 == digest).limit(1)
            )
            if existing_hash is not None and existing_hash.external_id != identity:
                duplicate_pages = await self.session.scalar(
                    select(func.count(Page.id)).where(
                        Page.document_id == existing_hash.id
                    )
                )
                return {
                    "status": "skipped_duplicate",
                    "document_id": existing_hash.external_id,
                    "pages": int(duplicate_pages or 0),
                }

            action, page_count = await save_parsed(
                self.session,
                path=path,
                sha256=digest,
                source_url=record.get("final_url") or record["url"],
                licence=record.get("licence"),
                source_title=record.get("title"),
                parsed=parsed,
            )
            return {
                "status": "inserted" if action == "inserted" else "repaired",
                "document_id": identity,
                "pages": page_count,
            }

    async def progress(self, job_id: str) -> dict | None:
        job = await self.session.get(IngestJob, job_id)
        if job is None:
            return None
        rows = list(
            await self.session.scalars(
                select(IngestItem)
                .where(IngestItem.job_id == job_id)
                .order_by(IngestItem.id)
            )
        )
        counts = Counter(item.status for item in rows)
        return {
            "job_id": job.id,
            "requested": job.requested,
            "queued": counts["queued"],
            "running": counts["running"],
            "done": counts["done"],
            "skipped": counts["skipped"],
            "failed": counts["failed"],
            "pages": sum(item.pages for item in rows),
            "items": [
                {
                    "id": item.id,
                    "path": item.record.get("path", ""),
                    "status": item.status,
                    "attempts": item.attempts,
                    "error": item.error,
                    "pages": item.pages,
                }
                for item in rows
            ],
        }

    async def dead_letter(self, limit: int = 50) -> list[dict]:
        rows = await self.session.scalars(
            select(IngestItem)
            .where(IngestItem.status == "failed")
            .order_by(IngestItem.updated_at.desc())
            .limit(limit)
        )
        return [
            {
                "id": item.id,
                "job_id": item.job_id,
                "path": item.record.get("path", ""),
                "url": item.record.get("url", ""),
                "attempts": item.attempts,
                "error": item.error,
            }
            for item in rows
        ]

    async def failed_records(self) -> list[dict]:
        rows = await self.session.scalars(
            select(IngestItem)
            .where(IngestItem.status == "failed")
            .order_by(IngestItem.id)
        )
        return [item.record for item in rows]

    async def report(self) -> dict:
        docs = (
            await self.session.scalar(select(func.count()).select_from(Document)) or 0
        )
        pages = await self.session.scalar(select(func.count()).select_from(Page)) or 0
        chars = (
            await self.session.scalar(
                select(func.coalesce(func.sum(func.length(Page.text)), 0))
            )
            or 0
        )
        tokens = (
            await self.session.scalar(
                select(
                    func.coalesce(func.sum(LlmCall.tokens_in + LlmCall.tokens_out), 0)
                ).where(LlmCall.purpose == "extract")
            )
            or 0
        )
        dead = (
            await self.session.scalar(
                select(func.count())
                .select_from(IngestItem)
                .where(IngestItem.status == "failed")
            )
            or 0
        )
        failures = (
            await self.session.scalar(select(func.count()).select_from(ParseFailure))
            or 0
        )
        return {
            "documents": docs,
            "pages": pages,
            "characters": chars,
            "tokens": tokens,
            "dead_letter": dead + failures,
        }

    async def queued_ids(self) -> list[int]:
        return list(
            await self.session.scalars(
                select(IngestItem.id)
                .where(IngestItem.status == "queued")
                .order_by(IngestItem.id)
            )
        )
