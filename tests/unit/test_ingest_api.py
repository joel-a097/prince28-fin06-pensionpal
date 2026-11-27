from fastapi.testclient import TestClient

from pensionpal.api.deps import get_ingest_repo, get_manifest, get_queue
from pensionpal.api.main import create_app
from pensionpal.config import Settings


async def no_manifest():
    return []


class FakeIngestRepo:
    def __init__(self, empty=False):
        self.empty = empty
        self.created = []
        self.known = {"a" * 64} if empty else set()
        self.uploaded = []

    async def known_ids(self):
        return self.known

    async def save_local_document(self, record, parsed):
        self.uploaded.append((record, parsed))
        return {
            "status": "inserted",
            "document_id": "d" * 64,
            "pages": len(parsed.pages),
        }

    async def create(self, records):
        self.created = records
        return "job123", [1, 2][: len(records)]

    async def progress(self, job_id):
        if job_id != "job123":
            return None
        return {
            "job_id": job_id,
            "requested": 1,
            "queued": 1,
            "running": 0,
            "done": 0,
            "skipped": 0,
            "failed": 0,
            "pages": 0,
            "items": [],
        }

    async def dead_letter(self, limit=50):
        return [{"id": 3, "error": "failed"}]

    async def failed_records(self):
        return [
            {
                "url": "https://example.test/retry",
                "sha256": "c" * 64,
                "status": "downloaded",
            }
        ]


class FakeQueue:
    def __init__(self, fail=False):
        self.ids, self.fail = [], fail

    async def put(self, ids):
        if self.fail:
            raise OSError("redis unavailable")
        self.ids.extend(ids)


def make_client(*, token="secret", empty=False, redis_down=False):
    settings = Settings(
        app_env="ci",
        database_url="postgresql://localhost/unused",
        admin_token=token,
        _env_file=None,
    )
    app = create_app(settings)
    repo, queue = FakeIngestRepo(empty), FakeQueue(redis_down)
    app.dependency_overrides[get_ingest_repo] = lambda: repo
    app.dependency_overrides[get_queue] = lambda: queue
    app.dependency_overrides[get_manifest] = lambda: [
        {
            "url": "https://example.test/new",
            "path": "data/raw/new.pdf",
            "source": "epfo",
            "sha256": "a" * 64,
            "status": "downloaded",
        }
    ]
    return TestClient(app), repo, queue


def test_ingest_requires_token():
    client, _, _ = make_client()
    with client:
        assert client.post("/v1/ingest", json={"limit": 1}).status_code == 401


def test_ingest_is_disabled_without_configured_token():
    client, _, _ = make_client(token="")
    with client:
        assert (
            client.post(
                "/v1/ingest", json={}, headers={"X-Admin-Token": "anything"}
            ).status_code
            == 403
        )


def test_ingest_queues_and_returns_202():
    client, repo, queue = make_client()
    with client:
        response = client.post(
            "/v1/ingest", json={"limit": 1}, headers={"X-Admin-Token": "secret"}
        )
    assert response.status_code == 202
    assert response.json()["job_id"] == "job123"
    assert queue.ids == [1]
    assert len(repo.created) == 1


def test_ingest_nothing_to_do_returns_200():
    client, _, _ = make_client(empty=True)
    client.app.dependency_overrides[get_manifest] = no_manifest
    with client:
        response = client.post(
            "/v1/ingest", json={}, headers={"X-Admin-Token": "secret"}
        )
    assert response.status_code == 200
    assert response.json()["queued"] == 0


def test_retry_failed_records():
    client, repo, _ = make_client()
    with client:
        response = client.post(
            "/v1/ingest",
            json={"retry_failed": True},
            headers={"X-Admin-Token": "secret"},
        )
    assert response.status_code == 202
    assert repo.created[0]["url"].endswith("/retry")


def test_redis_failure_returns_503_and_leaves_durable_job():
    client, repo, _ = make_client(redis_down=True)
    with client:
        response = client.post(
            "/v1/ingest", json={"limit": 1}, headers={"X-Admin-Token": "secret"}
        )
    assert response.status_code == 503
    assert len(repo.created) == 1


def test_progress_and_missing_job():
    client, _, _ = make_client()
    with client:
        assert client.get("/v1/ingest/job123").status_code == 200
        assert client.get("/v1/ingest/missing").status_code == 404


def test_dead_letter_is_readable_without_admin_token():
    client, _, _ = make_client()
    with client:
        response = client.get("/v1/ingest/dead-letter")
    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_ingest_limit_validation():
    client, _, _ = make_client()
    with client:
        response = client.post(
            "/v1/ingest", json={"limit": 0}, headers={"X-Admin-Token": "secret"}
        )
    assert response.status_code == 422


def local_record(digest="a" * 64):
    return {
        "url": "https://example.test/circular.pdf",
        "source": "epfo",
        "licence": "Public document",
        "title": "Circular",
        "path": "data/raw/epfo/circular.pdf",
        "sha256": digest,
        "status": "downloaded",
    }


def test_local_plan_requires_admin_token():
    client, _, _ = make_client()
    with client:
        response = client.post(
            "/v1/ingest/local/plan", json={"records": [local_record()]}
        )
    assert response.status_code == 401


def test_local_plan_excludes_existing_hashes_before_local_processing():
    client, _, _ = make_client(empty=True)
    with client:
        response = client.post(
            "/v1/ingest/local/plan",
            json={"records": [local_record()], "limit": 5},
            headers={"X-Admin-Token": "secret"},
        )
    assert response.status_code == 200
    assert response.json() == {"count": 0, "records": []}


def test_local_document_upload_uses_production_page_store():
    client, repo, _ = make_client()
    payload = {
        "record": local_record("b" * 64),
        "parsed": {
            "parser": "pymupdf",
            "kind": "pdf",
            "title": "Circular",
            "pages": [
                {"page_no": 1, "text": "Circular text", "headings": [], "tables": 0}
            ],
        },
    }
    with client:
        response = client.post(
            "/v1/ingest/local/document",
            json=payload,
            headers={"X-Admin-Token": "secret"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "inserted"
    assert len(repo.uploaded) == 1
    assert repo.uploaded[0][1].pages[0].text == "Circular text"


def test_local_document_upload_rejects_paths_outside_raw_corpus():
    client, _, _ = make_client()
    payload = {
        "record": local_record("b" * 64) | {"path": "../../secrets.txt"},
        "parsed": {
            "parser": "pymupdf",
            "kind": "pdf",
            "pages": [{"page_no": 1, "text": "text"}],
        },
    }
    with client:
        response = client.post(
            "/v1/ingest/local/document",
            json=payload,
            headers={"X-Admin-Token": "secret"},
        )
    assert response.status_code == 422
