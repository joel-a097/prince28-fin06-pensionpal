# Local queue and worker drill (Windows PowerShell)

This drill uses only the local Docker Postgres database and Redis. It does not
send ingestion requests to Render or modify Neon. Do not use `docker compose
down -v`; that would remove the local database volume.

## Start the isolated services

From the repository root:

```powershell
uv sync --locked
$env:POSTGRES_HOST_PORT = "5434"
Set-Item Env:ADMIN_TOKEN (Read-Host -Prompt "Enter a disposable local admin token")
$env:WORKER_IN_API = "false"
$env:INGEST_CONCURRENCY = "1"
$env:INGEST_RPM = "12"
$env:INGEST_JOB_TIMEOUT = "600"
$env:INGEST_MAX_TRIES = "3"
$env:INGEST_EXTRACT_ENABLED = "false"
docker compose up -d db redis
docker compose run --build --rm migrate
```

Run PostgreSQL integration tests against the isolated Compose test database:

```powershell
$env:TEST_DATABASE_URL = "postgresql://app:app@localhost:5434/app_test"  # pragma: allowlist secret
uv run poe test-integration
```

The settings above are passed to the containerized API and worker. The token
is intentionally disposable; never use it in Render.

```powershell
docker compose up -d --build api worker
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health"
```

## Start the API and worker

The API and separate Linux ARQ worker are now running as Compose services.
Follow their logs in separate windows if desired:

```powershell
docker compose logs -f api
```

```powershell
docker compose logs -f worker
```

The Compose worker runs in Linux, so Windows host signal handling does not
affect this drill. For a host-run worker, if ARQ fails because of Windows
signal/event-loop handling, set `$env:WORKER_IN_API = "true"` and run
`uv run poe dev` instead of starting a separate worker.

## Queue and monitor jobs

In another PowerShell window:

```powershell
Set-Item Env:ADMIN_TOKEN (Read-Host -Prompt "Enter the same local admin token")
uv run python scripts/ingest.py --limit 10 --url http://127.0.0.1:8000
```

Queue twenty more records without waiting for completion:

```powershell
$api = "http://127.0.0.1:8000"
$headers = @{ "X-Admin-Token" = $env:ADMIN_TOKEN }
$job = Invoke-RestMethod -Method Post -Uri "$api/v1/ingest" -Headers $headers `
    -ContentType "application/json" -Body '{"limit":20}'
$jobId = $job.job_id
$job
```

Check its PostgreSQL-backed progress at any time:

```powershell
$progress = Invoke-RestMethod -Uri "$api/v1/ingest/$jobId"
$progress | Select-Object job_id, requested, queued, running, done, skipped, failed, pages
```

## Kill and recover the worker

Wait until the progress response shows at least one running item, then hard-kill
the local worker container:

```powershell
docker compose kill --signal SIGKILL worker
```

With the configured 600-second job timeout, allow 595 seconds for the running
item lease to expire. Then restart the worker:

```powershell
docker compose up -d worker
```

On startup it requeues unfinished items and marks items that exhausted their
attempt limit as failed.

Recheck the same job until no queued or running items remain:

```powershell
$progress = Invoke-RestMethod -Uri "$api/v1/ingest/$jobId"
$progress | Select-Object job_id, requested, queued, running, done, skipped, failed, pages
if (($progress.queued + $progress.running + $progress.done + $progress.skipped + $progress.failed) -ne $progress.requested) {
    throw "Some job items are not accounted for."
}
```

The completed, skipped, and failed counts together should equal `requested`.
Failures are visible in the dead-letter endpoint:

```powershell
Invoke-RestMethod -Uri "$api/v1/ingest/dead-letter" |
    ConvertTo-Json -Depth 6
```

Check stored document hashes in the isolated local database:

```powershell
docker compose exec db psql -U app -d app -c `
    "SELECT COUNT(*) AS documents, COUNT(DISTINCT sha256) AS unique_hashes FROM documents;"
```

## Refresh the report

The report command reads whichever database is selected by `DATABASE_URL`.
After local testing, remove the local override to use the private `.env`
connection configured for the report. The script only reads the database and
writes `docs/INGEST_REPORT.md`; it does not ingest records:

```powershell
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
uv run python scripts/ingest_report.py
```

Stop local containers without deleting their data:

```powershell
docker compose down
```
