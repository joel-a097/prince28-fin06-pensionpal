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
