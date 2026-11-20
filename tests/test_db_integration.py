"""Integration tests — skipped unless TEST_DATABASE_URL is set.

Set in a real environment:
  $env:TEST_DATABASE_URL = "postgresql://...your neon string..."
  uv run pytest tests/test_db_integration.py -v
"""

import os

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TEST_DB = os.getenv("TEST_DATABASE_URL")
skip_if_no_db = pytest.mark.skipif(
    not TEST_DB,
    reason="TEST_DATABASE_URL not set – skipping integration tests",
)


@pytest_asyncio.fixture
async def engine():
    if not TEST_DB:
        pytest.skip("TEST_DATABASE_URL not set")
    from pensionpal.config import Settings
    from pensionpal.db.session import make_engine

    settings = Settings(
        app_env="ci",
        database_url=TEST_DB,
        _env_file=None,
    )
    eng = make_engine(settings)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    from pensionpal.db.session import make_sessionmaker

    factory = make_sessionmaker(engine)
    async with factory() as s:
        yield s


@skip_if_no_db
@pytest.mark.asyncio
async def test_db_connection(engine):
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar() == 1


@skip_if_no_db
@pytest.mark.asyncio
async def test_documents_table_exists(session: AsyncSession):
    result = await session.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'documents'"
        )
    )
    assert result.scalar() == 1


@skip_if_no_db
@pytest.mark.asyncio
async def test_loader_inserted_records(session: AsyncSession):
    from sqlalchemy import func, select

    from pensionpal.db.models import Document

    total = await session.scalar(select(func.count()).select_from(Document))
    assert total >= 20
