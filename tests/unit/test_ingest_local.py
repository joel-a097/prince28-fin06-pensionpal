import json

import httpx
import pytest

from scripts.ingest_local import (
    filter_manifest_records,
    read_manifest,
    request_plan_with_retry,
)


def test_read_manifest_uses_latest_status_per_url(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    records = [
        {
            "url": "https://example.test/a.pdf",
            "path": "data/raw/a.pdf",
            "sha256": "a" * 64,
            "status": "downloaded",
        },
        {
            "url": "https://example.test/a.pdf",
            "path": "data/raw/a.pdf",
            "sha256": "a" * 64,
            "status": "failed",
        },
        {
            "url": "https://example.test/b.pdf",
            "path": "data/raw/b.pdf",
            "sha256": "b" * 64,
            "status": "downloaded",
        },
    ]
    manifest.write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8"
    )

    result = read_manifest(manifest)

    assert [record["url"] for record in result] == ["https://example.test/b.pdf"]


def test_filter_manifest_records_accepts_windows_paths():
    record = {
        "path": "data/raw/epfo/circular.pdf",
        "url": "https://example.test/circular.pdf",
    }

    assert filter_manifest_records([record], [r"data\raw\epfo\circular.pdf"]) == [
        record
    ]


def test_filter_manifest_records_rejects_unknown_paths():
    with pytest.raises(ValueError, match="Manifest path"):
        filter_manifest_records([], ["data/raw/epfo/missing.pdf"])


@pytest.mark.asyncio
async def test_planning_request_retries_transient_server_errors(monkeypatch):
    calls = 0

    def respond(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"records": [{"path": "data/raw/a.pdf"}]})

    async def no_wait(_delay):
        pass

    monkeypatch.setattr("scripts.ingest_local.asyncio.sleep", no_wait)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        records = await request_plan_with_retry(
            client, "https://api.test/plan", {}, {}, 2
        )

    assert calls == 2
    assert records == [{"path": "data/raw/a.pdf"}]
