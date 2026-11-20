"""16 unit tests — no database, no network. FakeRepo is wired in via conftest."""

from fastapi.testclient import TestClient

from pensionpal.api.deps import check_db, get_repo
from pensionpal.api.main import create_app
from pensionpal.config import Settings

SAMPLE = [
    {"id": "001", "title": "Alpha guideline", "year": 2023, "kind": "guideline"},
    {"id": "002", "title": "Beta circular", "year": 2024, "kind": "circular"},
    {"id": "003", "title": "Gamma notice", "year": 2025, "kind": "circular"},
]

LONG_ID_SAMPLE = [
    {"id": "EPFO-001", "title": "Transfer Form", "kind": "faq"},
]


class FakeRepo:
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


def _make_settings():
    return Settings(
        app_env="ci",
        database_url="postgresql://localhost:5432/unused",
        _env_file=None,
    )


def _make_client(rows=None, db_up=True):
    rows = rows if rows is not None else SAMPLE
    app = create_app(_make_settings())
    app.dependency_overrides[get_repo] = lambda: FakeRepo(rows)
    app.dependency_overrides[check_db] = lambda: db_up
    return TestClient(app)


# ---------------------------------------------------------------------------
# Health / readiness
# ---------------------------------------------------------------------------


def test_health_returns_200(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy", "application": "PensionPal"}


def test_ready_returns_200_when_db_up(client):
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["checks"]["database"] is True


def test_ready_returns_503_when_db_down():
    with _make_client(db_up=False) as c:
        r = c.get("/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["database"] is False


def test_request_id_header_present(client):
    r = client.get("/health")
    assert "X-Request-ID" in r.headers
    assert r.headers["X-Request-ID"] != ""


# ---------------------------------------------------------------------------
# Document listing
# ---------------------------------------------------------------------------


def test_list_returns_all_records(client):
    r = client.get("/v1/documents")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["results"]) == 3


def test_list_respects_limit(client):
    r = client.get("/v1/documents?limit=2")
    assert r.status_code == 200
    assert len(r.json()["results"]) == 2


def test_list_respects_offset(client):
    r = client.get("/v1/documents?offset=2")
    assert r.status_code == 200
    assert len(r.json()["results"]) == 1


def test_list_filters_by_kind(client):
    r = client.get("/v1/documents?kind=circular")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert all(rec["kind"] == "circular" for rec in body["results"])


def test_list_filter_echoed_in_response(client):
    r = client.get("/v1/documents?kind=guideline")
    assert r.status_code == 200
    assert r.json()["filters"] == {"kind": "guideline"}


def test_list_unknown_filter_returns_empty(client):
    r = client.get("/v1/documents?kind=nonexistent")
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_list_bad_filter_key_returns_400(client):
    r = client.get("/v1/documents?Bad-Name=1")
    assert r.status_code == 400
    assert r.json()["status"] == 400


def test_list_q_search(client):
    r = client.get("/v1/documents?q=Alpha")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["results"][0]["title"] == "Alpha guideline"


# ---------------------------------------------------------------------------
# Document detail
# ---------------------------------------------------------------------------


def test_get_document_id_too_short_returns_422(client):
    # Path min_length=5; "AB" is too short → 422
    r = client.get("/v1/documents/AB")
    assert r.status_code == 422
    body = r.json()
    assert body["status"] == 422


def test_get_document_found():
    with _make_client(rows=LONG_ID_SAMPLE) as c:
        r = c.get("/v1/documents/EPFO-001")
    assert r.status_code == 200
    assert r.json()["id"] == "EPFO-001"


def test_get_document_not_found_is_404(client):
    r = client.get("/v1/documents/EPFO-MISSING")
    assert r.status_code == 404
    body = r.json()
    assert body["status"] == 404
    assert body["title"] == "Not Found"


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def test_stats_returns_total(client):
    r = client.get("/v1/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert "by_doc_type" in body
