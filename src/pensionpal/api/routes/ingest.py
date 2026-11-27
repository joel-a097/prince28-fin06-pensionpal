"""HTTP API for queueing ingestion and checking durable job status."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from pensionpal.api.deps import IngestRepoDep, ManifestDep, QueueDep, require_admin
from pensionpal.workers.ingest import plan

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=2000)
    source: str = Field(default="", max_length=100)
    retry_failed: bool = False


@router.post("", status_code=202, dependencies=[Depends(require_admin)])
async def start(
    body: IngestRequest,
    response: Response,
    repo: IngestRepoDep,
    queue: QueueDep,
    manifest: ManifestDep,
) -> dict:
    if body.retry_failed:
        records = (await repo.failed_records())[: body.limit]
    else:
        records = plan(
            manifest, await repo.known_ids(), source=body.source, limit=body.limit
        )
    if not records:
        response.status_code = 200
        return {
            "job_id": None,
            "queued": 0,
            "detail": "Nothing to do: all of it is ingested.",
        }
    job_id, item_ids = await repo.create(records)
    try:
        await queue.put(item_ids)
    except (RedisError, OSError, ConnectionError) as error:
        raise HTTPException(
            status_code=503, detail="The job queue (Redis) cannot be reached."
        ) from error
    return {
        "job_id": job_id,
        "queued": len(item_ids),
        "status_url": f"/v1/ingest/{job_id}",
    }


@router.get("/dead-letter")
async def dead_letter(
    repo: IngestRepoDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> dict:
    items = await repo.dead_letter(limit=limit)
    return {"count": len(items), "items": items}


@router.get("/{job_id}")
async def progress(job_id: str, repo: IngestRepoDep) -> dict:
    found = await repo.progress(job_id)
    if found is None:
        raise HTTPException(
            status_code=404, detail=f"No ingest job with id {job_id!r}."
        )
    return found
