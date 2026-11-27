"""Queue a batch through PensionPal's HTTP API and watch its progress."""

import argparse
import os
import time
from urllib.parse import urljoin

import httpx

from pensionpal.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--source", default="")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    token = get_settings().admin_token or os.getenv("ADMIN_TOKEN", "")
    if not token:
        raise SystemExit("Set ADMIN_TOKEN in .env before starting an ingestion.")
    root = args.url.rstrip("/")
    body = {
        "limit": args.limit,
        "source": args.source,
        "retry_failed": args.retry_failed,
    }
    with httpx.Client(timeout=30) as client:
        response = client.post(
            urljoin(root + "/", "v1/ingest"),
            json=body,
            headers={"X-Admin-Token": token},
        )
        if response.status_code != 202:
            print(f"HTTP {response.status_code}: {response.text}")
        response.raise_for_status()
        data = response.json()
        job_id = data.get("job_id")
        if not job_id:
            return 0
        print(f"HTTP {response.status_code}: job {job_id}, {data['queued']} queued")
        status_url = urljoin(root + "/", data.get("status_url", f"v1/ingest/{job_id}"))
        started = time.monotonic()
        while True:
            result = client.get(status_url).json()
            done = result["done"] + result["skipped"] + result["failed"]
            state = "finished" if done == result["requested"] else "working"
            print(
                f"{state:8} queued={result['queued']} running={result['running']} "
                f"done={result['done']} skipped={result['skipped']} "
                f"failed={result['failed']} pages={result['pages']} "
                f"{time.monotonic() - started:.0f}s",
                flush=True,
            )
            if state == "finished":
                for item in result["items"]:
                    if item["status"] == "failed":
                        print(
                            f"FAILED   {item['path']} ({item['attempts']} tries) {item['error']}"
                        )
                return int(result["failed"] > 0)
            time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
