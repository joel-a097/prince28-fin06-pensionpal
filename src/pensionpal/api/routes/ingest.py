"""HTTP API for queueing ingestion and checking durable job status."""

from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from redis.exceptions import RedisError

from pensionpal.api.deps import (
    EmbedderDep,
    IngestRepoDep,
    ManifestDep,
    QueueDep,
    require_admin,
)
from pensionpal.ingest.local_indexing import (
    LocalIndexContentChanged,
    index_local_document,
)
from pensionpal.ingest.parse import ParsedDoc, ParsedPage
from pensionpal.llm.embeddings import EmbeddingError
from pensionpal.workers.ingest import plan

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=2000)
    source: str = Field(default="", max_length=100)
    retry_failed: bool = False


class LocalManifestRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    url: AnyHttpUrl
    source: str = Field(min_length=1, max_length=100)
    licence: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=2000)
    path: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["downloaded"]
    final_url: AnyHttpUrl | None = None

    @field_validator("path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            "\\" in value
            or path.is_absolute()
            or ".." in path.parts
            or path.parts[:2] != ("data", "raw")
            or len(path.parts) < 3
        ):
            raise ValueError("path must be inside data/raw")
        return path.as_posix()


class LocalPlanRequest(BaseModel):
    records: list[LocalManifestRecord] = Field(max_length=2000)
    limit: int = Field(default=20, ge=1, le=2000)
    source: str = Field(default="", max_length=100)


class ParsedPagePayload(BaseModel):
    page_no: int = Field(ge=1)
    text: str = Field(max_length=500_000)
    headings: list[str] = Field(default_factory=list, max_length=100)
    tables: int = Field(default=0, ge=0)


class ParsedDocumentPayload(BaseModel):
    parser: str = Field(min_length=1, max_length=80)
    kind: Literal["pdf", "html", "text", "data"]
    title: str = Field(default="", max_length=2000)
    pages: list[ParsedPagePayload] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_pages(self):
        if [page.page_no for page in self.pages] != list(range(1, len(self.pages) + 1)):
            raise ValueError("pages must be numbered consecutively from 1")
        total_chars = sum(
            len(page.text) + sum(len(heading) for heading in page.headings)
            for page in self.pages
        )
        if total_chars > 5_000_000:
            raise ValueError("parsed document exceeds the 5 MB text limit")
        return self


class LocalDocumentUpload(BaseModel):
    record: LocalManifestRecord
    parsed: ParsedDocumentPayload


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


@router.post("/local/plan", dependencies=[Depends(require_admin)])
async def local_plan(body: LocalPlanRequest, repo: IngestRepoDep) -> dict[str, Any]:
    """Return unprocessed manifest records for the local fetch/parse worker."""
    records = plan(
        [record.model_dump(mode="json") for record in body.records],
        await repo.known_ids(),
        source=body.source,
        limit=body.limit,
    )
    return {"count": len(records), "records": records}


@router.post("/local/document", dependencies=[Depends(require_admin)])
async def upload_local_document(
    body: LocalDocumentUpload,
    request: Request,
    repo: IngestRepoDep,
    embedder: EmbedderDep,
) -> dict[str, str | int]:
    """Persist locally parsed pages using the production document/page tables."""
    record = body.record.model_dump(mode="json")
    parsed = ParsedDoc(
        parser=body.parsed.parser,
        kind=body.parsed.kind,
        title=body.parsed.title,
        pages=[
            ParsedPage(
                page_no=page.page_no,
                text=page.text,
                headings=page.headings,
                tables=page.tables,
            )
            for page in body.parsed.pages
        ],
    )
    result = await repo.save_local_document(record, parsed)
    if result["status"] == "conflict":
        raise HTTPException(
            status_code=409,
            detail="This manifest path already exists with different content.",
        )
    if embedder.configured:
        try:
            chunks, _ = await index_local_document(
                request.app.state.session_factory,
                embedder,
                str(result["document_id"]),
                request.app.state.settings,
            )
        except (EmbeddingError, LocalIndexContentChanged) as error:
            raise HTTPException(
                status_code=503, detail="Document indexing failed; retry the upload."
            ) from error
        result = result | {"index_status": "ready", "chunks": chunks}
    else:
        result = result | {"index_status": "pending", "chunks": 0}
    return result


@router.get("/dead-letter", dependencies=[Depends(require_admin)])
async def dead_letter(
    repo: IngestRepoDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> dict:
    items = await repo.dead_letter(limit=limit)
    return {"count": len(items), "items": items}


@router.get("/{job_id}", dependencies=[Depends(require_admin)])
async def progress(job_id: str, repo: IngestRepoDep) -> dict:
    found = await repo.progress(job_id)
    if found is None:
        raise HTTPException(
            status_code=404, detail=f"No ingest job with id {job_id!r}."
        )
    return found
