"""Document listing, detail, and stats endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse

from pensionpal.api.deps import get_repo
from pensionpal.db.repository import FILTER_KEY, DocumentRepository

router = APIRouter(prefix="/v1")

_RESERVED = {"q", "limit", "offset", "sort"}


@router.get("/documents")
async def list_documents(
    request: Request,
    repo: Annotated[DocumentRepository, Depends(get_repo)],
    q: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    # Collect any extra query params as metadata filters
    filters: dict[str, str] = {}
    for key, value in request.query_params.items():
        if key in _RESERVED:
            continue
        if not FILTER_KEY.match(key):
            return JSONResponse(
                status_code=400,
                content={
                    "type": "about:blank",
                    "title": "Bad Request",
                    "status": 400,
                    "detail": f"Invalid filter key: '{key}'. "
                    "Keys must be lowercase letters, digits, or underscores.",
                },
            )
        filters[key] = value

    total, records = await repo.list(q=q, filters=filters, limit=limit, offset=offset)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "filters": filters,
        "results": records,
    }


@router.get("/documents/{record_id}")
async def get_document(
    repo: Annotated[DocumentRepository, Depends(get_repo)],
    record_id: str = Path(min_length=5, max_length=64),
) -> dict[str, Any]:
    record = await repo.get(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="EPFO document not found")
    return record


@router.get("/stats")
async def get_stats(
    repo: Annotated[DocumentRepository, Depends(get_repo)],
) -> dict[str, Any]:
    total, records = await repo.list(q=None, filters={}, limit=1000, offset=0)
    type_counts: dict[str, int] = {}
    for rec in records:
        dt = rec.get("doc_type", "unknown")
        type_counts[dt] = type_counts.get(dt, 0) + 1
    return {"total": total, "by_doc_type": type_counts}
