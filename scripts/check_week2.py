"""Week 2 self-check for PensionPal.

Standard library only. It reads files and runs the local unit suite; it never
migrates a database, starts a deployment, creates a job, or changes project files.
Pass an optional live base URL to check read-only and authentication endpoints.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path.cwd()
OK, BAD = "  ok ", "  x  "
results: list[tuple[str, bool]] = []


def exists(path: str) -> bool:
    return (ROOT / path).exists()


def text(path: str) -> str:
    try:
        return (ROOT / path).read_text(encoding="utf-8")
    except OSError:
        return ""


def check(day: str, label: str, passed: bool, hint: str = "") -> None:
    print(
        f"{OK if passed else BAD}{label}"
        + (f"\n       -> {hint}" if not passed and hint else "")
    )
    results.append((day, passed))


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, capture_output=True, text=True, cwd=ROOT)


def migrations_contain(*names: str) -> bool:
    return all(
        name
        in "\n".join(
            text(f"migrations/versions/{path.name}")
            for path in (ROOT / "migrations/versions").glob("*.py")
        )
        for name in names
    )


def request(method: str, url: str, body: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return 0, str(error)


def main() -> int:
    live = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else None
    if not exists("pyproject.toml"):
        print("Run this from your project folder (where pyproject.toml is).")
        return 2

    print("\nD06 - Document collection")
    for path in [
        "src/pensionpal/ingest/fetch.py",
        "scripts/fetch.py",
        "DATASET.md",
        "docs/CAPACITY.md",
        "data/manifest.jsonl",
    ]:
        check("D06", path, exists(path), "missing")
    fetch = text("src/pensionpal/ingest/fetch.py")
    check(
        "D06",
        "async downloader and bounded concurrency",
        "async def fetch_all" in fetch and "asyncio.Semaphore" in fetch,
    )
    check(
        "D06",
        "retry backoff and robots.txt",
        "backoff_delay" in fetch and "can_fetch" in fetch,
    )
    check(
        "D06",
        "manifest resume and .gitignore raw data",
        exists("data/manifest.jsonl") and "data/raw/" in text(".gitignore"),
    )

    print("\nD07 - Document parsing")
    for path in [
        "src/pensionpal/ingest/parse.py",
        "src/pensionpal/ingest/store.py",
        "scripts/parse_corpus.py",
        "NOTES.md",
    ]:
        check("D07", path, exists(path), "missing")
    check(
        "D07",
        "PyMuPDF >=1.26,<2",
        "pymupdf>=1.26,<2" in text("pyproject.toml").replace('"', "'").replace(" ", ""),
    )
    check(
        "D07",
        "pages, parse_failures migrations",
        migrations_contain(
            "create_table('pages'", "create_table('parse_failures'", "headings"
        ),
    )
    notes = text("NOTES.md")
    check("D07", "NOTES parser comparison", "<!-- parser-comparison:start -->" in notes)

    print("\nD08 - LLM gateway")
    for path in [
        "src/pensionpal/llm/gateway.py",
        "src/pensionpal/api/routes/chat.py",
        "prompts/chat_system_v1.md",
        ".env.example",
        "Dockerfile",
    ]:
        check("D08", path, exists(path), "missing")
    gateway = text("src/pensionpal/llm/gateway.py")
    check(
        "D08",
        "generate(), stream(), fallback and breaker",
        "async def generate(" in gateway
        and "async def stream(" in gateway
        and "CircuitBreaker" in gateway,
    )
    check("D08", "llm_calls migration", migrations_contain("llm_calls"))
    check(
        "D08",
        "uncertainty wording",
        "I am not sure" in text("prompts/chat_system_v1.md"),
    )
    env = text(".env.example")
    check(
        "D08",
        "empty provider key entries",
        re.search(r"(?m)^GEMINI_API_KEY=$", env) is not None
        and re.search(r"(?m)^GROQ_API_KEY=$", env) is not None,
    )
    check(
        "D08",
        "Dockerfile includes prompts",
        "COPY --chown=app:app prompts ./prompts" in text("Dockerfile"),
    )

    print("\nD09 - Prompts and structured extraction")
    classify = [
        name
        for name in [f"prompts/classify_v{i}.md" for i in range(1, 10)]
        if exists(name)
    ]
    check(
        "D09",
        "at least 3 classify prompt versions",
        len(classify) >= 3,
        f"{len(classify)} found",
    )
    testset = text("eval/prompt_testset.jsonl").splitlines()
    rows, valid = [], True
    for line in testset:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            valid = (
                valid
                and row.get("label") in {"docs", "personal", "off_topic"}
                and "TODO" not in row.get("question", "")
            )
            rows.append(row)
        except json.JSONDecodeError:
            valid = False
    check("D09", "20 completed labelled test questions", len(rows) >= 20 and valid)
    for path in [
        "src/pensionpal/llm/extract.py",
        "src/pensionpal/llm/doc_meta.py",
        "scripts/compare_prompts.py",
        "prompts/extract_v1.md",
    ]:
        check("D09", path, exists(path), "missing")
    doc_meta = text("src/pensionpal/llm/doc_meta.py")
    required_fields = [
        "doc_type",
        "number",
        "date",
        "topic",
        "condition",
        "form",
        "effective_from",
    ]
    check(
        "D09",
        "required Pydantic metadata fields",
        all(re.search(rf"(?m)^\s*{field}:?", doc_meta) for field in required_fields),
    )
    check(
        "D09", "prompt comparison recorded", "<!-- prompt-comparison:start -->" in notes
    )

    print("\nD10 - Queue and worker")
    for path in [
        "src/pensionpal/workers/ingest.py",
        "src/pensionpal/api/routes/ingest.py",
        "scripts/ingest.py",
        "scripts/ingest_report.py",
        "docs/INGEST_REPORT.md",
        "docker-compose.yml",
    ]:
        check("D10", path, exists(path), "missing")
    check(
        "D10",
        "ingest_jobs and ingest_items migration",
        migrations_contain("ingest_jobs", "ingest_items"),
    )
    compose = text("docker-compose.yml")
    check(
        "D10", "worker service and Redis", "worker:" in compose and "redis:" in compose
    )
    ingest_route = text("src/pensionpal/api/routes/ingest.py")
    check(
        "D10",
        "queue, progress and dead-letter routes",
        '@router.post("",' in ingest_route
        and '@router.get("/dead-letter"' in ingest_route
        and '@router.get("/{job_id}"' in ingest_route,
    )

    print("\nUnit tests")
    tests = run(["uv", "run", "pytest", "tests/unit"])
    check(
        "UNIT",
        f"unit tests pass ({tests.returncode})",
        tests.returncode == 0,
        (tests.stdout + tests.stderr)[-1000:],
    )

    if live:
        print(f"\nLive - {live}")
        status, _body = request("GET", f"{live}/health")
        check("LIVE", "/health returns 200", status == 200)
        status, _body = request("GET", f"{live}/v1/documents")
        check("LIVE", "/v1/documents returns 200", status == 200)
        status, _body = request("GET", f"{live}/v1/usage")
        check("LIVE", "/v1/usage returns 200", status == 200)
        status, _body = request("POST", f"{live}/v1/ingest")
        check("LIVE", "unauthenticated ingest returns 401", status == 401)
        status, _body = request("GET", f"{live}/v1/ingest/dead-letter")
        check("LIVE", "dead-letter endpoint exists (200 or 401)", status in {200, 401})
        status, _body = request("POST", f"{live}/v1/chat", {"message": ""})
        check(
            "LIVE",
            "chat route exists (validation response, no model call)",
            status in {422, 200, 503},
        )

    total, passed = len(results), sum(ok for _, ok in results)
    print(f"\n{passed} of {total} checks passed.")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
