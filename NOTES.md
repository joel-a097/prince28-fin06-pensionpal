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

- Live URL: https://pensionpal.onrender.com
- CI run for pull request 1: https://github.com/joel-a097/prince28-fin06-pensionpal/actions/runs/44768134896
- First automatic deploy: https://github.com/joel-a097/prince28-fin06-pensionpal/actions/runs/45341277176
- PR #11 merged at 12:01:43 IST → “Smoke test passed” at 12:03:53 IST → lead time: 2 min 10 sec.

### Smoke test output from the automatic CD run

```text
ok   /health -> 200, version 79b1db4e2682e2f1db485f9c3c55d39df072ec80
ok   /ready -> 200 {'status': 'ready', 'checks': {'database': True}}
ok   /v1/documents?limit=1 -> 200
Smoke test passed
```

### Rollback drill

- Rolled back to `f40795df1bf0f30e9454a2d65d7868b95d5642e8`: started 12:04:47 IST, smoke passed 12:05:37 IST (50 sec). [Run](https://github.com/joel-a097/prince28-fin06-pensionpal/actions/runs/45341502171)
- Rolled forward to `79b1db4e2682e2f1db485f9c3c55d39df072ec80`: started 12:06:13 IST, smoke passed 12:07:00 IST (47 sec). [Run](https://github.com/joel-a097/prince28-fin06-pensionpal/actions/runs/45341678219)
- The rollback changed only the application image; no migrations were added after the older image. The existing database schema remained compatible, and the rollback workflow skipped migrations.

### Where the secrets live

- Neon string: GitHub Actions secret `DATABASE_URL` and Render environment; never in Git or the image.
- Render deploy hook: GitHub Actions secret `RENDER_DEPLOY_HOOK` only.
- Live URL: repository variable `LIVE_URL`.

### Monitoring

- `/health` and `/ready` both returned 200 after deployment; `/ready` reported the database connected.
- UptimeRobot five-minute monitoring and its monitor-specific badge key are still pending account access. Add its badge here after creating the monitor.
- A warm service avoids the roughly minute-long cold start on the first request after inactivity.

### Deployment verification

- [x] CI checks pass on the CI and CD pull requests.
- [x] Image published to GHCR and available to Render.
- [x] Main is the default branch and protected by required CI checks.
- [x] Render service is live; `/health` and `/ready` return 200.
- [x] Automatic CD deployed the merged SHA, migrated the database, and passed its smoke test.
- [x] Rollback and roll-forward completed successfully.
- [ ] UptimeRobot checks `/health` every five minutes; uptime badge added to README.
- [ ] `week-1` tag pushed after these notes are merged.
