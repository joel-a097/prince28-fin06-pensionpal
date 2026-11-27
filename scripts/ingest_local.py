"""Fetch and parse manifest documents locally, then store pages through the API."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from pensionpal.config import get_settings
from pensionpal.ingest.fetch import RETRYABLE, make_client
from pensionpal.ingest.parse import ParseError
from pensionpal.workers.ingest import Permanent, get_file, parse_document, sha256_of

logger = logging.getLogger("pensionpal.local_ingest")


def read_manifest(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"Manifest not found: {path}")
    latest: dict[str, dict] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Ignoring invalid manifest JSON on line %s", line_number)
            continue
        if isinstance(record, dict) and isinstance(record.get("url"), str):
            latest[record["url"]] = record
    return [
        record
        for record in latest.values()
        if record.get("status") == "downloaded"
        and record.get("path")
        and record.get("sha256")
    ]


def configure_tesseract() -> None:
    if sys.platform != "win32":
        return
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return
    tesseract_dir = Path(local_app_data) / "Programs" / "Tesseract-OCR"
    if (tesseract_dir / "tesseract.exe").is_file():
        os.environ["PATH"] = f"{tesseract_dir}{os.pathsep}{os.environ.get('PATH', '')}"


def endpoint(root: str, path: str) -> str:
    return urljoin(root.rstrip("/") + "/", path.lstrip("/"))


async def upload_with_retry(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    payload: dict,
    attempts: int,
) -> dict:
    for attempt in range(1, attempts + 1):
        try:
            response = await client.post(url, json=payload, headers=headers)
        except httpx.RequestError as error:
            if attempt == attempts:
                raise RuntimeError(
                    f"API request failed after {attempts} attempts ({type(error).__name__})"
                ) from error
            delay = min(30, 2 ** (attempt - 1))
            logger.warning("API unavailable; retrying upload in %ss", delay)
            await asyncio.sleep(delay)
            continue

        if response.status_code in RETRYABLE and attempt < attempts:
            delay = min(30, 2 ** (attempt - 1))
            logger.warning(
                "API returned HTTP %s; retrying upload in %ss",
                response.status_code,
                delay,
            )
            await asyncio.sleep(delay)
            continue
        if response.is_error:
            detail = response.text[:300].replace("\n", " ")
            raise RuntimeError(f"API returned HTTP {response.status_code}: {detail}")
        return response.json()
    raise RuntimeError("Upload retries exhausted")


async def ingest_record(
    record: dict,
    *,
    fetch_client: httpx.AsyncClient,
    api_client: httpx.AsyncClient,
    api_url: str,
    headers: dict[str, str],
    upload_attempts: int,
) -> dict:
    with tempfile.TemporaryDirectory(prefix="pensionpal-ingest-") as temporary:
        path = await get_file(record, Path(temporary), fetch_client)
        digest = await asyncio.to_thread(sha256_of, path)
        expected = record.get("sha256")
        if expected and digest != expected:
            raise ValueError("downloaded file SHA-256 does not match the manifest")
        parsed = await asyncio.to_thread(parse_document, path)

    payload = {
        "record": record | {"sha256": digest},
        "parsed": {
            "parser": parsed.parser,
            "kind": parsed.kind,
            "title": parsed.title,
            "pages": [
                {
                    "page_no": page.page_no,
                    "text": page.text,
                    "headings": page.headings,
                    "tables": page.tables,
                }
                for page in parsed.pages
            ],
        },
    }
    return await upload_with_retry(
        api_client,
        api_url,
        headers,
        payload,
        upload_attempts,
    )


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.admin_token:
        raise SystemExit("Set ADMIN_TOKEN in .env; the value is never printed.")
    records = read_manifest(Path(args.manifest))
    headers = {"X-Admin-Token": settings.admin_token}
    root = args.url.rstrip("/")
    parsed_root = urlsplit(root)
    if parsed_root.scheme != "https" and not (
        parsed_root.scheme == "http"
        and parsed_root.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise SystemExit(
            "Use HTTPS for remote API URLs; HTTP is allowed only on localhost."
        )
    api_timeout = httpx.Timeout(120, connect=15)
    failures = 0
    inserted = skipped = 0
    started = time.monotonic()

    async with httpx.AsyncClient(timeout=api_timeout) as api_client:
        response = await api_client.post(
            endpoint(root, "v1/ingest/local/plan"),
            json={"records": records, "limit": args.limit, "source": args.source},
            headers=headers,
        )
        if response.is_error:
            detail = response.text[:300].replace("\n", " ")
            raise SystemExit(
                f"Planning API returned HTTP {response.status_code}: {detail}"
            )
        selected = response.json().get("records", [])
        logger.info(
            "Production plan selected %s unprocessed document(s)", len(selected)
        )
        if not selected:
            logger.info(
                "Nothing to do; already stored documents were not downloaded or parsed"
            )
            return 0

        async with make_client(max_concurrency=1) as fetch_client:
            for index, record in enumerate(selected, 1):
                path = record.get("path", "(unknown path)")
                logger.info("[%s/%s] processing %s", index, len(selected), path)
                try:
                    result = await ingest_record(
                        record,
                        fetch_client=fetch_client,
                        api_client=api_client,
                        api_url=endpoint(root, "v1/ingest/local/document"),
                        headers=headers,
                        upload_attempts=args.upload_attempts,
                    )
                    status = result.get("status", "stored")
                    inserted += status in {"inserted", "repaired"}
                    skipped += status == "skipped_duplicate"
                    logger.info(
                        "[%s/%s] %s: %s (id=%s, %s pages)",
                        index,
                        len(selected),
                        status,
                        path,
                        result.get("document_id", "unknown"),
                        result.get("pages", 0),
                    )
                except (
                    Permanent,
                    ParseError,
                    ValueError,
                    RuntimeError,
                    httpx.HTTPError,
                ) as error:
                    failures += 1
                    logger.error(
                        "[%s/%s] failed %s: %s", index, len(selected), path, error
                    )

    logger.info(
        "Finished in %.1fs: inserted=%s duplicate_skipped=%s failed=%s",
        time.monotonic() - started,
        inserted,
        skipped,
        failures,
    )
    if failures:
        logger.info(
            "Rerun the same command to retry failures; stored documents are excluded by the API plan"
        )
    return int(failures > 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.getenv("PENSIONPAL_API_URL", "https://pensionpal.onrender.com"),
    )
    parser.add_argument("--manifest", default=str(get_settings().manifest_file))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--source", default="")
    parser.add_argument("--upload-attempts", type=int, default=3)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    if args.upload_attempts < 1:
        parser.error("--upload-attempts must be positive")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    configure_tesseract()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        logger.warning("Interrupted; rerunning safely skips documents already stored")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
