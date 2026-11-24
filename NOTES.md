# Engineering notes: PensionPal

## D03 · PostgreSQL

### Migrations (upgrade, downgrade, upgrade)

```text
INFO  [alembic.runtime.migration] Running downgrade 5f1275c9ff24 -> dc4f9b756223, add gin index on metadata

dc4f9b756223

INFO  [alembic.runtime.migration] Running upgrade dc4f9b756223 -> 5f1275c9ff24, add gin index on metadata

dc4f9b756223 -> 5f1275c9ff24 (head), add gin index on metadata
<base> -> dc4f9b756223, create documents and pages
```

### The loader is idempotent

```text
run 1: records=20 inserted=20 updated=0 unchanged=0
run 2: records=20 inserted=0 updated=0 unchanged=20
run 3 (after editing one record): records=20 inserted=0 updated=1 unchanged=19
```

### EXPLAIN for ?doc_type=FAQ

```text
-- 1) What the planner chooses on its own:
Seq Scan on documents  (cost=0.00..11.00 rows=1 width=36) (actual time=0.022..0.022 rows=0.00 loops=1)
  Filter: (metadata @> '{"doc_type": "FAQ"}'::jsonb)
  Rows Removed by Filter: 20
  Buffers: shared hit=2
Planning:
  Buffers: shared hit=149
Planning Time: 0.413 ms
Execution Time: 0.045 ms

-- 2) Seq scan switched off, to prove the index can be used:
Bitmap Heap Scan on documents  (cost=12.81..16.82 rows=1 width=36) (actual time=0.108..0.109 rows=0.00 loops=1)
  Recheck Cond: (metadata @> '{"doc_type": "FAQ"}'::jsonb)
  Buffers: shared hit=3
  ->  Bitmap Index Scan on ix_documents_metadata_gin  (cost=0.00..12.81 rows=1 width=0) (actual time=0.027..0.028 rows=0.00 loops=1)
        Index Cond: (metadata @> '{"doc_type": "FAQ"}'::jsonb)
        Index Searches: 1
        Buffers: shared hit=3
Planning:
  Buffers: shared hit=1
Planning Time: 0.089 ms
Execution Time: 0.146 ms
```

**Why did the planner choose a Seq Scan on my table? (2 lines, your own words)**

With only 20 rows the entire table fits in 2 shared buffer pages, so reading everything in one pass costs less than the overhead of an index lookup.

**When would it switch to the GIN index? (1 line)**

The planner uses the Bitmap Index Scan on ix_documents_metadata_gin once the table is large enough that filtering first is cheaper than a full scan.

## D04 · Docker, Compose and tests

### The image

```text
IMAGE            ID             DISK USAGE   CONTENT SIZE
pensionpal:dev   4c65767d4001        211MB             0B

uid=999(app) gid=999(app) groups=999(app)
```

- Size: 211 MB (target: under 400 MB) ✅
- First build: \~90 s. After changing one line of code: \~1.3 s.
- Which step said CACHED, and why? The `uv sync --locked --no-install-project` step was cached because `pyproject.toml` and `uv.lock` had not changed — only source code changed, so the dependency layer was reused.

### The stack

```text
NAME                   IMAGE                    STATUS
pensionpal-api-1       pensionpal-api           Up (healthy)   0.0.0.0:8000->8000/tcp
pensionpal-db-1        pgvector/pgvector:pg17   Up (healthy)   0.0.0.0:5433->5432/tcp
pensionpal-migrate-1   pensionpal-migrate       Exited (0)
pensionpal-redis-1     redis:7-alpine           Up (healthy)   0.0.0.0:6379->6379/tcp

First up:  records=20 inserted=20 updated=0 unchanged=0
After down + up: records=20 inserted=0 updated=0 unchanged=20
```

### Breaking the database on purpose

```text
db stopped:  /health → {"status":"healthy","application":"PensionPal"}
db stopped:  /ready  → {"status":"unavailable","checks":{"database":false}}
db started:  /ready  → {"status":"ready","checks":{"database":true}}
```

**Why should a load balancer stop sending traffic here but not restart the app? (2 lines)**

The app itself is healthy; only the database connection is gone. Restarting the app would not fix a database outage, and would cause unnecessary downtime for requests that do not touch the database.

### Tests and coverage

```text
uv run poe test              → 16 passed, 1 warning in 0.62s
uv run poe test-integration  → 7 passed, 1 warning in 4.66s
coverage TOTAL, unit only    → 76%  (16 passed, 7 skipped)
coverage TOTAL, with integration tests → 88%  (23 passed)
```

**Two files or lines my coverage report says are never run, and whether they matter: (2 lines)**

`pensionpal/core/logging_config.py` — the `RequestIDFilter` path for missing request_id is not exercised by unit tests; it matters only in production logging, not for correctness.

`migrations/env.py` — the offline migration path is never run in tests; it only matters when generating SQL scripts without a live database.

## D05 · CI/CD and going live

Deployment automation is prepared in `.github/workflows/ci.yml` and `.github/workflows/cd.yml`. The CI workflow checks lint, tests against Postgres, and builds a SHA-tagged image. CD migrates the database, asks Render to deploy that image, and smoke-tests `/health`, `/ready`, and `/v1/documents`.

### Pending live deployment tasks

The following require account setup and are intentionally left for the live deployment session:

- Live URL: pending Render service creation
- CI run for pull request 1: pending GitHub Actions run
- First automatic deploy: pending Render deployment configuration
- Uptime monitor and public live/uptime badges: pending live URL and monitor
- Rollback drill and lead times: pending successful deployment

### Deployment configuration

The CD workflow uses the following GitHub Actions settings:

- `DATABASE_URL` — protected Actions setting.
- `RENDER_DEPLOY_HOOK` — protected Actions setting.
- `LIVE_URL` — repository variable.

Configure the Neon connection string in the Render service environment.

Keep all actual credentials outside the Git repository and container image.### Deployment verification

Pending completion:

- [ ] CI checks pass on the CI pull request.
- [ ] CI checks pass on the CD pull request.
- [ ] Docker image is published to GHCR.
- [ ] GHCR package visibility is public.
- [ ] Main branch protection is enabled.
- [ ] Render service is deployed successfully.
- [ ] `/health` returns a successful response.
- [ ] `/ready` returns a successful response.
- [ ] Automatic CD deployment succeeds.
- [ ] Smoke tests pass.
- [ ] UptimeRobot monitors `/health` every five minutes.
- [ ] README contains live and uptime badges.
- [ ] Rollback drill is completed.
- [ ] `week-1` release tag is pushed.

### Deployment and rollback timings

- Initial deployment time: pending measurement.
- Rollback deployment time: pending measurement.
- Latest image redeployment time: pending measurement.

### Rollback drill

1. Select an older SHA-tagged Docker image.
2. Deploy the older image to Render.
3. Run smoke tests against `/health` and `/ready`.
4. Confirm the older deployment works.
5. Redeploy the newest SHA-tagged image.
6. Run smoke tests again.
7. Record deployment and rollback timings here.
