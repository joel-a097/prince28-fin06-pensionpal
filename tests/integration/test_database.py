import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from pensionpal.api.main import create_app
from pensionpal.config import Settings
from pensionpal.db.models import Document
from pensionpal.db.repository import DocumentRepository
from pensionpal.db.session import make_engine, make_sessionmaker

ROWS = [
    {
        "id": "INT-001",
        "title": "Alpha",
        "kind": "circular",
        "year": 2024,
        "tags": ["a", "b"],
    },
    {
        "id": "INT-002",
        "title": "Beta",
        "kind": "guideline",
        "year": 2025,
        "tags": ["b"],
    },
    {"id": "INT-003", "title": "Gamma", "kind": "circular", "year": 2025, "tags": []},
]


@pytest.fixture
def settings(database_url):
    return Settings(app_env="ci", database_url=database_url, _env_file=None)


@pytest.fixture
async def seeded(settings):
    """Fresh rows for each test: delete, insert, and hand back the settings."""
    import hashlib

    engine = make_engine(settings)
    async with make_sessionmaker(engine)() as session, session.begin():
        await session.execute(text("DELETE FROM documents"))
        for r in ROWS:
            meta = {k: v for k, v in r.items() if k not in ("id", "title")}
            sha = hashlib.sha256(r["id"].encode()).hexdigest()
            session.add(
                Document(
                    external_id=r["id"],
                    title=r["title"],
                    sha256=sha,
                    metadata_=meta,
                )
            )
    await engine.dispose()
    return settings


async def test_migrations_created_the_tables(settings):
    engine = make_engine(settings)
    async with engine.connect() as conn:
        tables = set(
            await conn.scalars(
                text(
                    "SELECT table_name FROM information_schema.tables"
                    " WHERE table_schema='public'"
                )
            )
        )
        version = await conn.scalar(text("SELECT version_num FROM alembic_version"))
    await engine.dispose()
    assert {"documents", "pages", "llm_calls", "alembic_version"} <= tables
    assert version


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"kind": "circular"}, ["INT-001", "INT-003"]),
        ({"year": "2025"}, ["INT-002", "INT-003"]),
        ({"tags": "b"}, ["INT-001", "INT-002"]),
        ({"kind": "circular", "year": "2025"}, ["INT-003"]),
    ],
)
async def test_repository_filters(seeded, filters, expected):
    engine = make_engine(seeded)
    async with make_sessionmaker(engine)() as session:
        total, items = await DocumentRepository(session).list(
            q=None, filters=filters, limit=10, offset=0
        )
    await engine.dispose()
    assert [i["id"] for i in items] == expected
    assert total == len(expected)


def test_api_against_real_database(seeded):
    with TestClient(create_app(seeded)) as client:
        assert client.get("/ready").json()["checks"]["database"] is True
        assert client.get("/v1/documents/INT-002").json()["title"] == "Beta"
        assert client.get("/v1/documents", params={"q": "gamm"}).json()["total"] == 1


def test_loader_is_idempotent(database_url, tmp_path):
    data = tmp_path / "records.json"
    data.write_text(
        json.dumps([{"id": "L1", "x": 1}, {"id": "L2", "x": 2}]), encoding="utf-8"
    )
    env = {
        **os.environ,
        "APP_ENV": "ci",
        "DATABASE_URL": database_url,
        "DATA_FILE": str(data),
    }

    def run() -> str:
        cmd = [sys.executable, "scripts/load_db.py"]
        return subprocess.run(
            cmd, env=env, check=True, capture_output=True, text=True
        ).stdout

    assert "inserted=2" in run()
    assert "inserted=0 updated=0 unchanged=2" in run()
