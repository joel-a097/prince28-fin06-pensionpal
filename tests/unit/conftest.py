import pytest
from fastapi.testclient import TestClient

from pensionpal.api.deps import check_db, get_gateway, get_repo, get_retriever
from pensionpal.api.main import create_app
from pensionpal.config import Settings
from pensionpal.llm.gateway import FakeLLM, LLMGateway

# Tiny fake records: unit tests never touch a real database or your data file.
SAMPLE = [
    {"id": "001", "title": "Alpha guideline", "year": 2023, "kind": "guideline"},
    {"id": "002", "title": "Beta circular", "year": 2024, "kind": "circular"},
    {"id": "003", "title": "Gamma notice", "year": 2025, "kind": "circular"},
]


class FakeRepo:
    """Behaves like DocumentRepository, but keeps rows in a Python list."""

    def __init__(self, rows):
        self.rows = rows

    async def list(self, *, q, filters, limit, offset):
        rows = [
            r
            for r in self.rows
            if (not q or q.lower() in str(r).lower())
            and all(str(r.get(k)) == v for k, v in filters.items())
        ]
        return len(rows), rows[offset : offset + limit]

    async def get(self, external_id):
        return next((r for r in self.rows if r["id"] == external_id), None)


class FakeRetriever:
    def __init__(self, evidence=None):
        self.evidence = evidence or []

    async def retrieve(self, question):
        return self.evidence


@pytest.fixture
def settings():
    # _env_file=None: ignore your local .env so tests behave the same everywhere
    return Settings(
        app_env="ci",
        database_url="postgresql://localhost:5432/unused",
        _env_file=None,
    )


@pytest.fixture
def db_state():
    return {"up": True}


@pytest.fixture
def client(settings, db_state):
    app = create_app(settings)
    app.dependency_overrides[get_repo] = lambda: FakeRepo(SAMPLE)
    app.dependency_overrides[check_db] = lambda: db_state["up"]
    app.dependency_overrides[get_gateway] = lambda: LLMGateway(
        [FakeLLM("gemini", "test-model")]
    )
    app.dependency_overrides[get_retriever] = lambda: FakeRetriever()
    with TestClient(app) as c:
        yield c
