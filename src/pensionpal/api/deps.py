"""FastAPI dependency functions shared across routes."""

import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pensionpal.db.ingest_jobs import IngestRepository
from pensionpal.db.llm_calls import LlmCallRepository
from pensionpal.db.repository import DocumentRepository
from pensionpal.llm.embeddings import GeminiEmbedder
from pensionpal.llm.gateway import LLMGateway
from pensionpal.services.retrieval import DocumentRetriever


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async with request.app.state.session_factory() as session:
        yield session


async def get_repo(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentRepository:
    return DocumentRepository(session)


async def get_gateway(request: Request) -> LLMGateway:
    return request.app.state.gateway


async def get_embedder(request: Request) -> GeminiEmbedder:
    return request.app.state.embedder


async def get_retriever(request: Request) -> DocumentRetriever:
    return request.app.state.retriever


async def get_usage_repo(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LlmCallRepository:
    return LlmCallRepository(session)


async def get_ingest_repo(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IngestRepository:
    return IngestRepository(session)


async def get_queue(request: Request):
    return request.app.state.ingest_queue


async def get_manifest(request: Request) -> list[dict]:
    path = Path(request.app.state.settings.manifest_file)
    if not path.exists():
        return []
    latest: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and isinstance(record.get("url"), str):
            latest[record["url"]] = record
    return list(latest.values())


async def require_admin(
    request: Request,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = request.app.state.settings.admin_token
    if not expected:
        raise HTTPException(
            status_code=403, detail="Set ADMIN_TOKEN to allow ingestion here."
        )
    if x_admin_token != expected:
        raise HTTPException(
            status_code=401, detail="Missing or wrong X-Admin-Token header."
        )


GatewayDep = Annotated[LLMGateway, Depends(get_gateway)]
EmbedderDep = Annotated[GeminiEmbedder, Depends(get_embedder)]
RetrieverDep = Annotated[DocumentRetriever, Depends(get_retriever)]
UsageDep = Annotated[LlmCallRepository, Depends(get_usage_repo)]
IngestRepoDep = Annotated[IngestRepository, Depends(get_ingest_repo)]
QueueDep = Annotated[object, Depends(get_queue)]
ManifestDep = Annotated[list[dict], Depends(get_manifest)]


async def check_db(request: Request) -> bool:
    """Return True if the database is reachable, False otherwise."""
    try:
        from sqlalchemy import text

        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False
