import httpx
import pytest

from pensionpal.workers.ingest import Pace, Permanent, get_file, plan


def record(name: str, digest: str = "a" * 64, **extra) -> dict:
    return {
        "url": f"https://example.test/{name}",
        "path": f"data/raw/{name}",
        "sha256": digest,
        "status": "downloaded",
        "source": "epfo",
        **extra,
    }


def test_plan_filters_source_and_deduplicates_hashes():
    records = [
        record("a"),
        record("b", "b" * 64),
        record("c", "c" * 64, source="other"),
    ]
    todo = plan(records, set(), source="epfo")
    assert [item["path"] for item in todo] == ["data/raw/a", "data/raw/b"]


def test_plan_applies_limit_after_filtering():
    records = [record(str(number), str(number) * 64) for number in range(1, 4)]
    assert len(plan(records, set(), limit=2)) == 2


@pytest.mark.asyncio
async def test_pace_waits_between_calls(monkeypatch):
    now = [0.0]
    waits = []

    async def sleep(delay):
        waits.append(delay)
        now[0] += delay

    monkeypatch.setattr("pensionpal.workers.ingest.asyncio.sleep", sleep)
    pace = Pace(12, clock=lambda: now[0])
    await pace.wait()
    await pace.wait()
    assert waits == [5.0]


@pytest.mark.asyncio
async def test_get_file_returns_local_manifest_file(tmp_path):
    path = tmp_path / "letter.pdf"
    path.write_bytes(b"pdf")
    async with httpx.AsyncClient() as client:
        actual = await get_file(
            {"path": str(path), "url": "https://unused.test"}, tmp_path, client
        )
    assert actual == path


@pytest.mark.asyncio
async def test_get_file_explains_missing_manual_file(tmp_path):
    async with httpx.AsyncClient() as client:
        with pytest.raises(Permanent, match="exists only on the laptop"):
            await get_file(
                {"path": "missing.pdf", "url": "https://unused.test", "via": "manual"},
                tmp_path,
                client,
            )
