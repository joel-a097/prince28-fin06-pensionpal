"""Offline tests for the corpus downloader; all HTTP is served by MockTransport."""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest

from pensionpal.ingest.fetch import (
    Manifest,
    Robots,
    Source,
    backoff_delay,
    fetch_all,
    file_stem,
    pick_ext,
    read_sources,
    retry_after_seconds,
    slug,
)


def run(coro):
    return asyncio.run(coro)


def client(handler):
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"User-Agent": "examate-student-bot/0.1 test"},
        follow_redirects=False,
    )


def no_sleep(_delay: float):
    async def sleeper(_seconds: float) -> None:
        return None

    return sleeper


def test_slug_is_safe_and_nonempty():
    assert slug("EPFO / Forms 13") == "epfo-forms-13"
    assert slug("東京") == "file"


def test_file_stem_is_stable_and_url_specific():
    first = file_stem("https://example.test/forms/Form13.pdf")
    assert first == file_stem("https://example.test/forms/Form13.pdf")
    assert first.startswith("form13-")
    assert first != file_stem("https://example.test/forms/Form19.pdf")


def test_pick_ext_prefers_known_url_suffix_then_content_type():
    assert pick_ext("https://x.test/a.pdf", "text/html") == ".pdf"
    assert pick_ext("https://x.test/download", "application/pdf; version=1") == ".pdf"
    assert pick_ext("https://x.test/download", "application/x-unknown") == ".bin"


def test_backoff_delay_is_bounded():
    assert 0 <= backoff_delay(4, base=2, cap=5) <= 5


def test_retry_after_seconds_value():
    assert retry_after_seconds("12") == 12
    assert retry_after_seconds(None) is None
    assert retry_after_seconds("not-a-date") is None


def test_retry_after_http_date():
    when = datetime.now(UTC) + timedelta(seconds=30)
    parsed = retry_after_seconds(format_datetime(when, usegmt=True))
    assert parsed is not None and 0 <= parsed <= 30


def test_read_sources_ignores_comments_deduplicates_and_keeps_quoted_commas(
    tmp_path: Path,
):
    path = tmp_path / "sources.csv"
    path.write_text(
        "# header note\nurl,source,licence,title\n"
        'https://x.test/a,epfo,"public, cite source",A\n'
        "https://x.test/a,epfo,ignored,duplicate\n",
        encoding="utf-8",
    )
    rows = read_sources(path)
    assert rows == [Source("https://x.test/a", "epfo", "public, cite source", "A")]


def test_read_sources_rejects_non_http_url(tmp_path: Path):
    path = tmp_path / "sources.csv"
    path.write_text("url,source,licence,title\nfile:///secret,epfo,public,test\n")
    with pytest.raises(ValueError, match=r"not an http\(s\) URL"):
        read_sources(path)


def test_read_sources_requires_source_and_licence(tmp_path: Path):
    path = tmp_path / "sources.csv"
    path.write_text("url,source,licence,title\nhttps://x.test/a,epfo,,test\n")
    with pytest.raises(ValueError, match="source and licence are required"):
        read_sources(path)


def test_manifest_tracks_only_complete_files_and_repairs_truncated_line(tmp_path: Path):
    root = tmp_path
    content = root / "data" / "raw" / "epfo" / "form.pdf"
    content.parent.mkdir(parents=True)
    content.write_bytes(b"whole")
    manifest_path = root / "data" / "manifest.jsonl"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "url": "https://x.test/form",
                "status": "downloaded",
                "path": "data/raw/epfo/form.pdf",
            }
        )
        + "\n{cut off",
        encoding="utf-8",
    )
    manifest = Manifest(manifest_path)
    assert manifest.done("https://x.test/form", root)
    assert manifest_path.read_text(encoding="utf-8").endswith("\n")
    assert not manifest.done("https://x.test/missing", root)


def test_manifest_add_appends_jsonl(tmp_path: Path):
    manifest = Manifest(tmp_path / "data" / "manifest.jsonl")
    record = {"url": "https://x.test/a", "status": "blocked"}
    manifest.add(record)
    assert json.loads(manifest.path.read_text(encoding="utf-8")) == record


def test_robots_allows_empty_policy_and_caches_per_origin():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(404)

    async def scenario():
        async with client(handler) as http:
            robots = Robots(http)
            assert await robots.check("https://x.test/a") == (True, 0.0)
            assert await robots.check("https://x.test/b") == (True, 0.0)

    run(scenario())
    assert calls == ["https://x.test/robots.txt"]


def test_robots_disallows_matching_path():
    def handler(request):
        return httpx.Response(
            200, text="User-agent: examate-student-bot\nDisallow: /private\n"
        )

    async def scenario():
        async with client(handler) as http:
            robots = Robots(http)
            assert await robots.check("https://x.test/private/file") == (False, 0.0)
            assert (await robots.check("https://x.test/public/file"))[0]

    run(scenario())


def test_robots_treats_server_error_as_disallowed():
    def handler(_request):
        return httpx.Response(503)

    async def scenario():
        async with client(handler) as http:
            assert await Robots(http).check("https://x.test/a") == (False, 0.0)

    run(scenario())


def test_fetch_downloads_and_records_hash(tmp_path: Path):
    payload = b"public EPFO document"

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:\n")
        return httpx.Response(
            200, content=payload, headers={"Content-Type": "application/pdf"}
        )

    async def scenario():
        async with client(handler) as http:
            return await fetch_all(
                [Source("https://x.test/form", "epfo", "public document")],
                root=tmp_path,
                per_host_delay=0,
                client=http,
                sleep=no_sleep(0),
            )

    counts = run(scenario())
    assert counts == {"downloaded": 1, "skipped": 0, "blocked": 0, "failed": 0}
    manifest = Manifest(tmp_path / "data" / "manifest.jsonl")
    record = manifest.records["https://x.test/form"]
    assert record["status"] == "downloaded"
    assert record["sha256"]
    assert (tmp_path / record["path"]).read_bytes() == payload


def test_fetch_second_run_skips_existing_complete_file(tmp_path: Path):
    counts_seen = 0

    def handler(request):
        nonlocal counts_seen
        counts_seen += 1
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:\n")
        return httpx.Response(200, content=b"pdf")

    async def scenario():
        src = [Source("https://x.test/form", "epfo", "public")]
        async with client(handler) as http:
            first = await fetch_all(src, root=tmp_path, per_host_delay=0, client=http)
            second = await fetch_all(src, root=tmp_path, per_host_delay=0, client=http)
        return first, second

    first, second = run(scenario())
    assert first["downloaded"] == 1
    assert second["skipped"] == 1
    assert counts_seen == 2  # robots.txt and one document GET; no second-run requests


def test_cancel_during_retry_can_resume(tmp_path: Path):
    waiting_to_retry = asyncio.Event()
    attempts = 0

    def handler(request):
        nonlocal attempts
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:\n")
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=b"resumed document")

    async def paused_sleep(_seconds: float) -> None:
        waiting_to_retry.set()
        await asyncio.Event().wait()

    async def scenario():
        src = [Source("https://x.test/file.pdf", "epfo", "public")]
        async with client(handler) as http:
            task = asyncio.create_task(
                fetch_all(
                    src,
                    root=tmp_path,
                    per_host_delay=0,
                    client=http,
                    sleep=paused_sleep,
                )
            )
            await asyncio.wait_for(waiting_to_retry.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            return await fetch_all(src, root=tmp_path, per_host_delay=0, client=http)

    result = run(scenario())
    assert result["downloaded"] == 1
    assert not list((tmp_path / "data" / "raw").rglob("*.part"))
    manifest = Manifest(tmp_path / "data" / "manifest.jsonl")
    assert manifest.records["https://x.test/file.pdf"]["status"] == "downloaded"


def test_fetch_does_not_retry_permanent_404(tmp_path: Path):
    seen = 0

    def handler(request):
        nonlocal seen
        seen += 1
        return httpx.Response(404)

    async def scenario():
        async with client(handler) as http:
            return await fetch_all(
                [Source("https://x.test/missing", "epfo", "public")],
                root=tmp_path,
                per_host_delay=0,
                client=http,
                sleep=no_sleep(0),
            )

    result = run(scenario())
    assert result["failed"] == 1
    assert seen == 2  # one robots check and one GET


def test_fetch_retries_429_and_obeys_retry_after(tmp_path: Path):
    calls = 0
    sleeps = []

    def handler(request):
        nonlocal calls
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, content=b"ok")

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def scenario():
        async with client(handler) as http:
            return await fetch_all(
                [Source("https://x.test/a", "epfo", "public")],
                root=tmp_path,
                per_host_delay=0,
                client=http,
                sleep=record_sleep,
            )

    result = run(scenario())
    assert result["downloaded"] == 1
    assert calls == 2
    assert sleeps and sleeps[0] >= 2


def test_fetch_cleans_part_file_when_download_exceeds_limit(
    tmp_path: Path, monkeypatch
):
    import pensionpal.ingest.fetch as fetch_module

    monkeypatch.setattr(fetch_module, "MAX_BYTES", 2)

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=b"too big")

    async def scenario():
        async with client(handler) as http:
            return await fetch_all(
                [Source("https://x.test/a", "epfo", "public")],
                root=tmp_path,
                per_host_delay=0,
                max_attempts=1,
                client=http,
                sleep=no_sleep(0),
            )

    result = run(scenario())
    assert result["failed"] == 1
    assert not list((tmp_path / "data" / "raw").rglob("*.part"))


def test_fetch_checks_redirect_destination_robots_before_get(tmp_path: Path):
    requested = []

    def handler(request):
        requested.append(str(request.url))
        if request.url.host == "a.test" and request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == "a.test":
            return httpx.Response(302, headers={"Location": "https://b.test/file"})
        if request.url.host == "b.test" and request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return httpx.Response(200, content=b"should not be requested")

    async def scenario():
        async with client(handler) as http:
            return await fetch_all(
                [Source("https://a.test/start", "epfo", "public")],
                root=tmp_path,
                per_host_delay=0,
                max_attempts=1,
                client=http,
                sleep=no_sleep(0),
            )

    result = run(scenario())
    assert result["blocked"] == 1
    assert "https://b.test/file" not in requested


def test_host_gate_waits_when_same_host_is_not_ready():
    from pensionpal.ingest.fetch import HostGate

    slept = []

    async def clock_sleep(seconds):
        slept.append(seconds)

    async def scenario():
        gate = HostGate(2.0, clock_sleep)
        gate._next_ok["x.test"] = time.monotonic() + 1.0
        await gate.wait("x.test")

    run(scenario())
    assert slept and slept[0] > 0


def test_fetch_all_validates_limits(tmp_path: Path):
    async def scenario():
        return await fetch_all([], root=tmp_path, max_concurrency=0)

    with pytest.raises(ValueError, match="positive"):
        run(scenario())


def test_robots_crawl_delay_is_returned():
    def handler(_request):
        return httpx.Response(
            200,
            text="User-agent: examate-student-bot\nCrawl-delay: 1.5\nDisallow: /no\n",
        )

    async def scenario():
        async with client(handler) as http:
            return await Robots(http).check("https://x.test/yes")

    allowed, delay = run(scenario())
    assert allowed
    assert delay == 1.5


def test_retries_transport_error(tmp_path: Path):
    calls = 0

    def handler(request):
        nonlocal calls
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("temporary", request=request)
        return httpx.Response(200, content=b"ok")

    async def scenario():
        async with client(handler) as http:
            return await fetch_all(
                [Source("https://x.test/a", "epfo", "public")],
                root=tmp_path,
                per_host_delay=0,
                client=http,
                sleep=no_sleep(0),
            )

    assert run(scenario())["downloaded"] == 1
    assert calls == 2
