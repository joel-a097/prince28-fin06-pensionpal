"""Polite, resumable downloads for the PensionPal source corpus.

The fetcher checks robots.txt before requesting each host, limits concurrency,
paces requests per host, retries transient failures, and records completed files
in an append-only JSONL manifest. A file is only published after its temporary
``.part`` file is complete.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import random
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from protego import Protego

CONTACT = "https://github.com/joel-a097/prince28-fin06-pensionpal"
ROBOTS_TOKEN = "examate-student-bot"
USER_AGENT = f"{ROBOTS_TOKEN}/0.1 (student project; +{CONTACT})"

RETRYABLE = {408, 425, 429, 500, 502, 503, 504}
MAX_WAIT = 120.0
MAX_BYTES = 200 * 1024 * 1024
ATTEMPT_TIMEOUT = 300.0
MAX_REDIRECTS = 10
KNOWN_EXT = {
    ".pdf",
    ".html",
    ".htm",
    ".json",
    ".txt",
    ".md",
    ".mdx",
    ".rst",
    ".adoc",
    ".csv",
    ".xml",
    ".yaml",
    ".yml",
    ".zip",
    ".docx",
    ".xlsx",
    ".xls",
}
EXT_BY_TYPE = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "application/json": ".json",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "application/zip": ".zip",
    "application/yaml": ".yaml",
}

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class Source:
    url: str
    source: str
    licence: str
    title: str = ""


class DownloadError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def slug(text: str, limit: int = 60) -> str:
    """Return a portable path component containing only lowercase ASCII."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit] or "file"


def file_stem(url: str) -> str:
    """Stable readable file name with a URL-derived suffix to avoid collisions."""
    parts = urlsplit(url)
    last = unquote(parts.path.rstrip("/").rsplit("/", 1)[-1]) or parts.netloc
    name = last.rsplit(".", 1)[0] if "." in last else last
    suffix = hashlib.sha256(url.encode()).hexdigest()[:8]
    return f"{slug(name)}-{suffix}"


def pick_ext(url: str, content_type: str) -> str:
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix in KNOWN_EXT:
        return suffix
    media_type = content_type.split(";")[0].strip().lower()
    return EXT_BY_TYPE.get(media_type, ".bin")


def backoff_delay(attempt: int, *, base: float = 1.0, cap: float = 60.0) -> float:
    """Exponential backoff with full jitter."""
    return random.uniform(0, min(cap, base * 2**attempt))


def retry_after_seconds(value: str | None) -> float | None:
    """Parse Retry-After as either seconds or an HTTP date."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def read_sources(path: Path) -> list[Source]:
    """Read URL sources; comments and blank lines are ignored."""
    sources: list[Source] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        lines = (
            line
            for line in handle
            if line.strip() and not line.lstrip().startswith("#")
        )
        for number, row in enumerate(csv.DictReader(lines), start=1):
            url = (row.get("url") or "").strip()
            source = (row.get("source") or "").strip()
            licence = (row.get("licence") or "").strip()
            if (
                urlsplit(url).scheme not in {"http", "https"}
                or not urlsplit(url).netloc
            ):
                raise ValueError(f"sources row {number}: not an http(s) URL: {url!r}")
            if not source or not licence:
                raise ValueError(
                    f"sources row {number}: source and licence are required: {url}"
                )
            if url not in seen:
                seen.add(url)
                sources.append(
                    Source(url, source, licence, (row.get("title") or "").strip())
                )
    return sources


class Manifest:
    """Append-only provenance log; the last valid record for a URL is current."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.records: dict[str, dict] = {}
        if not path.exists():
            return
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and isinstance(record.get("url"), str):
                self.records[record["url"]] = record
        if text and not text.endswith("\n"):
            with path.open("a", encoding="utf-8") as handle:
                handle.write("\n")

    def done(self, url: str, root: Path) -> bool:
        record = self.records.get(url)
        return bool(
            record
            and record.get("status") == "downloaded"
            and isinstance(record.get("path"), str)
            and (root / record["path"]).is_file()
        )

    def add(self, record: dict) -> None:
        self.records[record["url"]] = record
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


class Robots:
    """Fetch robots.txt once per origin and apply RFC 9309 user-agent rules."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._rules: dict[str, Protego | None] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def _load(self, origin: str) -> Protego | None:
        try:
            response = await self._client.get(
                f"{origin}/robots.txt", follow_redirects=True
            )
        except httpx.HTTPError:
            return None
        if response.status_code == 429 or response.status_code >= 500:
            return None
        if response.status_code >= 400:
            return Protego.parse("")
        return Protego.parse(response.text)

    async def check(self, url: str) -> tuple[bool, float]:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        lock = self._locks.setdefault(origin, asyncio.Lock())
        async with lock:
            if origin not in self._rules:
                self._rules[origin] = await self._load(origin)
        rules = self._rules[origin]
        if rules is None:
            return False, 0.0
        return (
            rules.can_fetch(url, ROBOTS_TOKEN),
            float(rules.crawl_delay(ROBOTS_TOKEN) or 0.0),
        )


class HostGate:
    """Keep at least ``delay`` seconds between requests to each host."""

    def __init__(self, delay: float, sleep: Sleep) -> None:
        self._delay = delay
        self._sleep = sleep
        self._next_ok: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, host: str, crawl_delay: float = 0.0) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            pause = self._next_ok.get(host, 0.0) - time.monotonic()
            if pause > 0:
                await self._sleep(pause)
            self._next_ok[host] = time.monotonic() + max(self._delay, crawl_delay)


def make_client(max_concurrency: int = 4) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        timeout=httpx.Timeout(30.0, connect=10.0),
        limits=httpx.Limits(max_connections=max_concurrency),
        follow_redirects=False,
    )


async def _download(
    client: httpx.AsyncClient,
    src: Source,
    *,
    root: Path,
    raw_dir: Path,
    robots: Robots,
    gate: HostGate,
) -> dict:
    """Follow redirects only after checking robots.txt for each destination."""
    current = src.url
    for redirect_count in range(MAX_REDIRECTS + 1):
        allowed, crawl_delay = await robots.check(current)
        if not allowed:
            raise DownloadError(f"robots.txt disallows {current}")
        host = urlsplit(current).netloc
        await gate.wait(host, crawl_delay)
        response = await client.send(client.build_request("GET", current), stream=True)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            await response.aclose()
            if not location:
                raise DownloadError(
                    "redirect without Location header", code=response.status_code
                )
            if redirect_count >= MAX_REDIRECTS:
                raise DownloadError("too many redirects", code=response.status_code)
            current = urljoin(current, location)
            if urlsplit(current).scheme not in {"http", "https"}:
                raise DownloadError("redirect to a non-http(s) URL")
            continue

        try:
            if response.status_code != 200:
                raise DownloadError(
                    f"HTTP {response.status_code}",
                    code=response.status_code,
                    retry_after=retry_after_seconds(
                        response.headers.get("Retry-After")
                    ),
                )
            content_type = response.headers.get("Content-Type", "")
            name = file_stem(src.url) + pick_ext(src.url, content_type)
            target = raw_dir / slug(src.source) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_name(target.name + ".part")
            digest, size = hashlib.sha256(), 0
            try:
                with part.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise DownloadError(f"larger than {MAX_BYTES // 2**20} MB")
                        digest.update(chunk)
                        handle.write(chunk)
                part.replace(target)
            finally:
                part.unlink(missing_ok=True)
        finally:
            await response.aclose()
        return {
            "path": target.relative_to(root).as_posix(),
            "bytes": size,
            "sha256": digest.hexdigest(),
            "content_type": content_type.split(";")[0].strip(),
            "http_status": 200,
            "final_url": current,
        }
    raise DownloadError("too many redirects")


async def fetch_one(
    client: httpx.AsyncClient,
    src: Source,
    *,
    root: Path,
    raw_dir: Path,
    robots: Robots,
    gate: HostGate,
    slots: asyncio.Semaphore,
    max_attempts: int,
    sleep: Sleep,
) -> dict:
    """Download one source with bounded retries; return a manifest record."""
    record = {
        "url": src.url,
        "source": src.source,
        "licence": src.licence,
        "title": src.title,
        "via": "http",
    }
    allowed, _ = await robots.check(src.url)
    if not allowed:
        return record | {
            "status": "blocked",
            "error": "robots.txt",
            "fetched_at": now_iso(),
        }
    error, code, attempt = "", None, 0
    for attempt in range(1, max_attempts + 1):
        wait = backoff_delay(attempt - 1)
        async with slots:
            try:
                async with asyncio.timeout(ATTEMPT_TIMEOUT):
                    fields = await _download(
                        client,
                        src,
                        root=root,
                        raw_dir=raw_dir,
                        robots=robots,
                        gate=gate,
                    )
                return (
                    record
                    | fields
                    | {
                        "status": "downloaded",
                        "attempts": attempt,
                        "fetched_at": now_iso(),
                    }
                )
            except DownloadError as exc:
                error, code = str(exc), exc.code
                if error.startswith("robots.txt disallows"):
                    return record | {
                        "status": "blocked",
                        "error": "robots.txt",
                        "fetched_at": now_iso(),
                    }
                if code not in RETRYABLE:
                    break
                if exc.retry_after is not None:
                    if exc.retry_after > MAX_WAIT:
                        error = (
                            f"{error}: asked to wait {exc.retry_after:.0f} s, run later"
                        )
                        break
                    wait = max(wait, exc.retry_after)
            except (httpx.TransportError, TimeoutError) as exc:
                error, code = type(exc).__name__, None
            except httpx.HTTPError as exc:
                error, code = type(exc).__name__, None
                break
        if attempt < max_attempts:
            await sleep(min(wait, MAX_WAIT))
    return record | {
        "status": "failed",
        "http_status": code,
        "error": error,
        "attempts": attempt,
        "fetched_at": now_iso(),
    }


async def fetch_all(
    sources: list[Source],
    *,
    root: Path = Path("."),
    max_concurrency: int = 4,
    per_host_delay: float = 0.5,
    max_attempts: int = 4,
    client: httpx.AsyncClient | None = None,
    sleep: Sleep = asyncio.sleep,
    on_result: Callable[[dict], None] | None = None,
) -> dict[str, int]:
    """Fetch incomplete sources and append each completed result immediately."""
    if max_concurrency < 1 or max_attempts < 1 or per_host_delay < 0:
        raise ValueError(
            "concurrency and attempts must be positive; delay cannot be negative"
        )
    root = root.resolve()
    raw_dir = root / "data" / "raw"
    manifest = Manifest(root / "data" / "manifest.jsonl")
    todo = [source for source in sources if not manifest.done(source.url, root)]
    counts = {
        "downloaded": 0,
        "skipped": len(sources) - len(todo),
        "blocked": 0,
        "failed": 0,
    }
    own_client = client is None
    active_client = client or make_client(max_concurrency)
    robots = Robots(active_client)
    gate = HostGate(per_host_delay, sleep)
    slots = asyncio.Semaphore(max_concurrency)
    tasks: list[asyncio.Task] = []
    try:
        tasks = [
            asyncio.create_task(
                fetch_one(
                    active_client,
                    source,
                    root=root,
                    raw_dir=raw_dir,
                    robots=robots,
                    gate=gate,
                    slots=slots,
                    max_attempts=max_attempts,
                    sleep=sleep,
                )
            )
            for source in todo
        ]
        for finished in asyncio.as_completed(tasks):
            record = await finished
            counts[record["status"]] += 1
            previous = manifest.records.get(record["url"], {})
            same_problem = (previous.get("status"), previous.get("error")) == (
                record["status"],
                record.get("error"),
            )
            if record["status"] == "downloaded" or not same_problem:
                manifest.add(record)
            if on_result:
                on_result(record)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if own_client:
            await active_client.aclose()
    return counts
