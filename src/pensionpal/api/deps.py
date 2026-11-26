"""FastAPI dependency functions shared across routes."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pensionpal.db.llm_calls import LlmCallRepository
from pensionpal.db.repository import DocumentRepository
from pensionpal.llm.gateway import LLMGateway


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async with request.app.state.session_factory() as session:
        yield session


async def get_repo(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentRepository:
    return DocumentRepository(session)


async def get_gateway(request: Request) -> LLMGateway:
    return request.app.state.gateway


async def get_usage_repo(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LlmCallRepository:
    return LlmCallRepository(session)


GatewayDep = Annotated[LLMGateway, Depends(get_gateway)]
UsageDep = Annotated[LlmCallRepository, Depends(get_usage_repo)]


async def check_db(request: Request) -> bool:
    """Return True if the database is reachable, False otherwise."""
    try:
        from sqlalchemy import text

        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False
