import asyncio

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

    async def known_ids(self):
        return set()

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
            == 401
        )


def test_ingest_rejects_invalid_token():
    client, _, _ = make_client()
    with client:
        response = client.post(
            "/v1/ingest", json={}, headers={"X-Admin-Token": "wrong"}
        )
    assert response.status_code == 401


def test_worker_in_api_uses_configured_redis_url(monkeypatch):
    observed = {}

    class FakeEngine:
        async def dispose(self):
            pass

    class FakeResource:
        async def aclose(self):
            pass

    class FakeWorker:
        def __init__(self, **kwargs):
            observed.update(kwargs)

        async def async_run(self):
            await asyncio.Future()

    monkeypatch.setattr("pensionpal.api.main.make_engine", lambda _: FakeEngine())
    monkeypatch.setattr("pensionpal.api.main.make_sessionmaker", lambda _: object())
    monkeypatch.setattr("pensionpal.api.main.make_recorder", lambda _: object())
    monkeypatch.setattr(
        "pensionpal.api.main.build_gateway", lambda *_args, **_kwargs: FakeResource()
    )
    monkeypatch.setattr("arq.worker.Worker", FakeWorker)
    settings = Settings(
        app_env="ci",
        database_url="postgresql://localhost/unused",
        redis_url="redis://configured.example:6381/4",
        worker_in_api=True,
        _env_file=None,
    )

    with TestClient(create_app(settings)):
        pass

    assert observed["redis_settings"].host == "configured.example"
    assert observed["redis_settings"].port == 6381
    assert observed["redis_settings"].database == 4


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
