"""Poll the live API until it serves the expected version and real data."""

import argparse
import json
import time
import urllib.error
import urllib.request


def get_json(url: str) -> tuple[int, dict]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.status, json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "url", help="Base URL, for example https://pensionpal.onrender.com"
    )
    parser.add_argument(
        "--expect-version", help="Wait until /health reports this Git SHA"
    )
    parser.add_argument("--attempts", type=int, default=60)
    parser.add_argument("--interval", type=float, default=10)
    args = parser.parse_args()
    base = args.url.rstrip("/")

    for attempt in range(args.attempts):
        try:
            status, health = get_json(f"{base}/health")
            version = health.get("version")
            print(f"ok   /health -> {status}, version {version}")
            if status != 200 or health.get("status") != "ok":
                raise RuntimeError(f"unhealthy response: {health}")
            if args.expect_version and version != args.expect_version:
                raise RuntimeError(
                    f"waiting for {args.expect_version}; live version is {version}"
                )

            status, ready = get_json(f"{base}/ready")
            print(f"ok   /ready -> {status} {ready}")
            if status != 200 or ready.get("checks", {}).get("database") is not True:
                raise RuntimeError(f"not ready: {ready}")

            status, documents = get_json(f"{base}/v1/documents?limit=1")
            print(f"ok   /v1/documents?limit=1 -> {status}")
            if status != 200 or not isinstance(documents.get("results"), list):
                raise RuntimeError(f"document endpoint failed: {documents}")
            print("Smoke test passed")
            return 0
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            RuntimeError,
        ) as exc:
            print(f"waiting ({attempt + 1}/{args.attempts}): {exc}")
            if attempt + 1 < args.attempts:
                time.sleep(args.interval)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
