# Engineering notes: PensionPal

## D07 - Parsing my corpus
- Files in the current source manifest: 110 downloaded; 53 parsed; 57 circular PDFs have no extractable text; 1,027 page rows in Postgres.
- Parsing coverage: 48% of downloaded files (53 / 110); all 100 new circular files were downloaded successfully.
### Failures by reason
| Reason | Files | What I did |
|---|---:|---|
| no_text_layer | 57 current circular PDFs; plus 1 historical failure cleared | The downloaded PDFs are image-only or otherwise textless to both current parsers; OCR is not configured. The original wage-ceiling failure was cleared with pypdf. |
- The one I fixed: `data/raw/epfo/wageceiling-f1b23c5c.pdf`, reason `no_text_layer`, fix: pypdf extracted its text and the retry cleared the failure row.
### What I saw when I read my parsed pages
- A page where the heading path is right (document, page, path): EPF Scheme 1952, page 2, `[EMPLOYEES' PROVIDENT FUNDS SCHEME, 1952, CHAPTER I Preliminary, 1. Short title and application.]`.
- Something that came out wrong (document, page, what): the contribution rates PDF contains a replacement glyph in "employers' contributions"; this PDF font encoding needs a cleaner source or targeted repair.
- A table: Markdown grid on EPF contribution rates, page 1; the six-column contribution table is readable as rows and columns.
### My parser choice
- For PDFs I use PyMuPDF because it retained heading structure and found 2 tables in the transfer FAQ (pypdf found 0); pypdf recovered text from the wage-ceiling file that PyMuPDF classified as scanned.
- A kind of document in my corpus that neither parser handles well: dense vector-heavy annual-report tables (table extraction was skipped for speed) and scanned PDFs without OCR.
### One thing that went wrong today, and how I fixed it
The Day 06 EPFO URLs had moved and returned 404. I refreshed the sources from EPFO's official pages and added 100 circular PDFs from its official circular index. The fetcher checked robots.txt and downloaded all 100 at one request at a time with a two-second host delay. Fifty-seven PDFs have no extractable text layer, so they remain in the dataset report but are not searchable in Postgres until OCR is configured.
### Parser comparison
<!-- parser-comparison:start -->
| File | Type | Parser A (chars/pages/headings/tables/sec) | Parser B (chars/pages/headings/tables/sec) | Verdict |
|---|---|---|---|---|
| `data/raw/epfo/annual-report-2023-24-88221eca.pdf` | .pdf | PyMuPDF: 475,516 / 259 / 2750 / 0 / 48.61s | pypdf: 458,516 / 259 / 0 / 0 / 54.10s | PyMuPDF: more structure and faster; dense tables remain a gap |
| `data/raw/epfo/citizencharter-5075ead5.pdf` | .pdf | PyMuPDF: 7,660 / 10 / 74 / 0 / 0.52s | pypdf: 7,321 / 10 / 0 / 0 / 0.66s | PyMuPDF: slightly more text, headings, and faster |
| `data/raw/epfo/employees-provident-funds-scheme-445662a2.html` | .html | trafilatura: 225,920 / 85 / 124 / 0 / 0.53s | plain tags: 229,102 / 1 / 0 / 0 / 0.19s | Trafilatura: keeps scheme structure and drops page chrome |
| `data/raw/epfo/contributionrate-80aa900e.pdf` | .pdf | PyMuPDF: 7,349 / 3 / 2 / 0 / 0.13s | pypdf: 7,311 / 3 / 1 / 0 / 0.83s | PyMuPDF: similar text with headings and much faster |
| `data/raw/epfo/eps-scheme-e4deea56.html` | .html | trafilatura: 77,317 / 33 / 7 / 0 / 0.77s | plain tags: 71,373 / 1 / 0 / 0 / 0.15s | Trafilatura: preserves pages and section headings |
| `data/raw/epfo/faq-transfer-claim-f1982656.pdf` | .pdf | PyMuPDF: 10,915 / 9 / 35 / 2 / 0.57s | pypdf: 12,798 / 9 / 0 / 0 / 0.55s | PyMuPDF: pypdf has more characters, but loses the tables and headings |
| `data/raw/epfo/faq-epfo-5e8668f6.html` | .html | trafilatura: 40,742 / 15 / 141 / 0 / 0.18s | plain tags: 41,748 / 1 / 0 / 0 / 0.05s | Trafilatura: small plain-text surplus is page chrome; structure is retained |
| `data/raw/epfo/edli-scheme-dc36e942.html` | .html | trafilatura: 30,305 / 11 / 0 / 0 / 0.12s | plain tags: 32,891 / 1 / 0 / 0 / 0.05s | Trafilatura: splits the scheme into pages; headings need tuning |
| `data/raw/epfo/interestrate-onpfaccumulationssince1952-37bf9df5.pdf` | .pdf | PyMuPDF: 5,666 / 3 / 9 / 0 / 0.10s | pypdf: 5,627 / 3 / 0 / 0 / 0.51s | PyMuPDF: similar text with useful headings and faster |
| `data/raw/epfo/wageceiling-f1b23c5c.pdf` | .pdf | PyMuPDF: 416 / 1 / 3 / 0 / 0.02s | pypdf: 404 / 1 / 0 / 0 / 0.03s | PyMuPDF default; pypdf fallback fixed its false scan detection |
<!-- parser-comparison:end -->
## D06 - Corpus collection
- Scope: primary EPFO materials for EPF/EPS/EDLI rules, member FAQs, transfer and claim forms, and claim guidance. The tracked source list is a 110-document starter sample; the 2,000-page full-corpus target remains a planning estimate.
- Acquisition: `uv run python scripts/fetch.py urls` checks `robots.txt`, uses a descriptive user agent, paces requests per host, limits concurrency, retries transient errors, streams into temporary files, hashes completed files, and resumes from `data/manifest.jsonl`.
- Provenance and reuse: each source row records its publisher, URL, title, and terms. No general open reuse licence was located for EPFO; keep raw files local, cite and link them, and do not redistribute full text. `data/raw/` is ignored by Git; provenance records are tracked.
- Live collection: the original 10 URLs returned 404 and remain as failed historical attempts. The refreshed official EPFO URLs all allow crawling and yielded 110 files (4 HTML pages, 106 PDFs, including 100 circulars); raw documents stay local and are ignored by Git.
- Validation: the offline downloader suite covers retry/backoff, robots policy, host pacing, atomic partial-file cleanup, manifest resume, and redirect checks. The refreshed source inventory and capacity estimate are in `DATASET.md` and `docs/CAPACITY.md`.
- Capacity model: `uv run python scripts/dataset_report.py` extracts PDF/text characters, estimates tokens as characters / 4, estimates 500-token chunks and 1,024-dimensional float32 vectors, and calculates embedding cost using the configurable price and exchange rate. These are planning estimates, not tokenizer or vendor quotes.
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
- UptimeRobot monitors `https://pensionpal.onrender.com/health` every five minutes; the README has its monitor-specific uptime badge.
- A warm service avoids the roughly minute-long cold start on the first request after inactivity.

### Deployment verification

- [x] CI checks pass on the CI and CD pull requests.
- [x] Image published to GHCR and available to Render.
- [x] Main is the default branch and protected by required CI checks.
- [x] Render service is live; `/health` and `/ready` return 200.
- [x] Automatic CD deployed the merged SHA, migrated the database, and passed its smoke test.
- [x] Rollback and roll-forward completed successfully.
- [x] UptimeRobot checks `/health` every five minutes; uptime badge added to README.
- [x] `week-1` tag pushed for the live Week 1 release.


## D08 - LLM gateway

- Implementation: Gemini is first; Groq is fallback. The OpenAI-compatible HTTP adapter has timeouts, retry/backoff for retryable errors, a per-provider circuit breaker, streaming support, token accounting, and list-price cost estimates in INR. The prompt lives at `prompts/chat_system_v1.md`.
- API: `POST /v1/chat` streams SSE by default (`{"stream": false}` returns JSON); `GET /v1/usage` reports daily calls, errors, fallbacks, tokens, and cost. Provider attempts are written independently to `llm_calls`, including failed attempts with zero tokens/cost.
- Database: migration `9108ccd83de1_add_llm_calls` was applied to the configured Neon database; `alembic current` reported `9108ccd83de1 (head)`.
- Local verification: `pytest tests/unit` -> 91 passed; Ruff check and format checks pass. The local integration test was not run because the Docker engine is unavailable.
- Real-provider and live checks are pending: neither `GEMINI_API_KEY` nor `GROQ_API_KEY` is configured in this workspace. No provider request, cost, timing, model-answer quality, fallback drill, or Render deployment is claimed. Add the keys directly to local `.env` and Render's private environment settings; never paste them into chat or commit them. Then run `uv run python scripts/llm_ping.py`, start the app, and capture laptop/live timings and the English/Tamil token comparison before completing the interview notes below.

### Measurements to record after real provider calls

- Laptop first response: first words ___ s; total ___ s; input/output tokens ___ / ___; estimated cost Rs ___
- Live awake request: first words ___ s
- "Hi" / English sentence / Tamil sentence input tokens: ___ / ___ / ___
- PF balance question response and one verified mistake: pending real call
- Broken-primary drill: fallback provider ___; circuit opened after request ___; half-open retry ___
- `/v1/usage`: calls ___; errors ___; fallbacks ___; total estimated cost Rs ___

## D09 · Versioned prompts and structured document metadata

- Added `classify_v1` through `classify_v4`, a labeled 20-question PensionPal test set, and `scripts/compare_prompts.py` with a prompt-and-question response cache and Neon usage recording.
- Prompt comparison table (written by `scripts/compare_prompts.py`):

<!-- prompt-comparison:start -->
| Prompt | Accuracy | Input tokens |
|---|---:|---:|
| classify_v1 | 18/20 (90%) | 836 |
| classify_v2 | 19/20 (95%) | 3016 |
| classify_v3 | 20/20 (100%) | 5556 |
| classify_v4 | 20/20 (100%) | 6416 |
<!-- prompt-comparison:end -->
- Measured with Gemini 3.5 Flash Lite because the configured Gemini 3.8 Flash returned HTTP 503 and Gemini 3.5 Flash timed out. v3 and v4 each scored 20/20; v3 used 5,556 input tokens versus v4's 6,416, so v3 is the more efficient prompt on this small test set. The first 60-call pass was not usage-logged; the refreshed 80-call pass was logged to Neon.
- v4 adds a clear rule for live EPFO office hours after v2 mislabeled that kind of question off-topic. v3 and v4 both scored 20/20 on the 20-question set.
- Added `DocMeta` for document kind, year, language, summary, topics, scheme names, form references, and section references. Extracted values merge into the existing JSONB metadata column, which `/v1/documents` already filters.
- Added `scripts/extract_metadata.py` with schema validation, up to three repair attempts, per-document saves, prompt-version idempotency, and `--retry-failed`. No migration is required.
- Re-ran `scripts/compare_prompts.py` with Gemini 3.5 Flash Lite; it reproduced the cached scores above with 0 new provider calls.
- OCR processed all 57 previously textless circular PDFs with local Tesseract 5.5.3. All 110 manifest documents are now parsed, including all 100 circulars. The parser runs OCR outside database transactions, treats whitespace-only pages as empty, and resumes per file.
- `extract_v1` metadata is valid for all 110 parsed documents, including all 100 circulars. The extractor now takes the first three nonblank pages, so blank cover pages do not block extraction. Neon recorded 119 Gemini 3.5 Flash Lite calls, 0 provider errors, 220,005 input tokens, 12,837 output tokens, and estimated cost Rs 9.318924.
- Live `/v1/documents?parser=ocr-eng&limit=1` returned 200 and 57 matching OCR-parsed records. The deployed D09 service reported commit `edfdc36b226e3f6cbe48db0ae3083707c118bf40`; the OCR robustness fixes are in this follow-up change.
- Local verification: `uv run poe test` -> 111 passed; Ruff check and format checks pass.

## D10 · Queue and worker

- Added ARQ/Redis ingestion, Postgres job and item state, authenticated queueing endpoints, worker recovery, OCR fallback for scans, and a database-backed report.
- Neon migration `c40b3d9a2f11` is applied. Local Redis ran in Docker; the API and ARQ worker used the same Neon database.
- First 10-item batch: 10 queued; finished in 14 s with 1 done, 9 skipped, 0 failed; 21 pages. The skipped items already had parsed content from the earlier attempt. Local metadata extraction was disabled because the configured Gemini credential returned `INVALID_AUTH_KEY`.
- Local pace: about 1.4 s per item for this batch (INGEST_RPM=12, INGEST_CONCURRENCY=2; model calls disabled locally).

### Kill test

- Queued 20. At the hard worker kill: queued 12, running 2, done 5, failed 1.
- After recovery: done 15 + skipped 1 + failed 4 = 20; no items remained queued or running.
- Corpus documents after the run: 116; distinct external IDs: 116.
- The interrupted work returned over about 6 minutes in this debugging run. The first replacement worker was stopped while OCR was still active; the final recovery needed a longer local timeout and startup recovery for stale `running` rows.
- No row was duplicated: the worker atomically claims items, and PostgreSQL advisory locks serialize the final content-hash check and save.

### Dead-letter list

| Stage | Items in the 20-item kill-test job | What I did |
|---|---:|---|
| Parse (`ocr_unavailable`) | 3 | Kept the source and reason in the item dead-letter record; these scans failed Tesseract OCR locally. |
| Gave up after worker timeout | 1 | Recorded after three worker starts; this PDF exceeded the local OCR time limit. |

### Live ingestion

- PR #24 added D10 to `main`; PR #27 fixed the worker's missing downloader User-Agent and is deployed at `1168313eef39195f932413747cf74e0384c22419`. CI/CD succeeded, the D10 migration is applied, and `/health` returned 200 with the deployed SHA.
- Render Redis Key Value is provisioned in Singapore. `REDIS_URL`, `WORKER_IN_API`, and `ADMIN_TOKEN` are configured; OCR job timeout is 600 seconds and worker concurrency is 1. `/v1/usage` returned 200 with 213 calls, 11 errors, 0 fallbacks, 236,351 input tokens, 13,095 output tokens, and Rs 9.846057 estimated cost at the time checked.
- An unauthenticated, valid `POST /v1/ingest` returned 401. A Render-authenticated batch queued five items, but Render received HTTP 403 from EPFO for all five, including after the User-Agent fix; the same downloader fetched all five locally with HTTP 200. This indicates an egress/IP restriction at the EPFO edge.
- All five existing PDFs were then processed through the authenticated local API and ARQ worker against the shared Neon database, with extraction disabled. Four finished in the first job; the 38-page `SS_Result.pdf` finished in a single-worker retry in 364 seconds with a 600-second timeout. Neon again contains 116 documents and 1,188 pages; historical failed attempts remain in the dead-letter count of 25.
- Render's live source fetch is still blocked by upstream HTTP 403. The queue, local-file processing, OCR, database writes, and deployed API have all been exercised successfully; obtaining Render egress access to EPFO would require a change outside this repository.

### Week 2 against Monday's estimate

- `docs/CAPACITY.md` target: 2,000 pages and 763,020 estimated tokens. The original run's report showed 1,188 pages and 510,964 estimated tokens.
- Difference at the time of the original run: 812 pages and 252,056 estimated tokens below the full-target estimate. That run had 116 documents; the target is an estimate, not a corpus-completion count.

### One thing that went wrong today, and how I fixed it

The first recovery left stale `running` items waiting because startup only put `queued` items back in Redis. Startup now atomically expires stale worker leases, requeues retryable items, and dead-letters items at the attempt limit. A separate local OCR run showed that scanned files can exceed a 60-second lease, so the local drill used a five-minute timeout.

### What I learnt

- Postgres is the durable record of each item's state; Redis only carries the work notification.
- A worker restart must reclaim stale `running` rows as well as restore queued rows.
- OCR duration varies substantially by PDF, so the worker lease must exceed the largest expected parse time.

## Final Day 10 verification (2026-11-27)

- `uv run poe test`: 144 passed. `uv run poe lint`: Ruff checks and formatting passed. `uv lock --check` and `git diff --check` passed.
- The PostgreSQL integration suite passed against the isolated Compose database on host port 5434: 20 passed. An invocation without `TEST_DATABASE_URL` initially hit an unrelated listener on port 5433 and failed authentication; it did not alter the test database.
- Local 10-item job `a1ebea39eb0f441b9219b4e3813d726a`: 10 done, 0 failed, 429 pages. The local 20-item hard-kill/recovery job `86432134ca2540ea8652c79cdbaf408d`: 18 done + 2 skipped + 0 failed; no queued/running items remained; 99 pages.
- The isolated local database had 50 documents and 50 distinct SHA-256 hashes after both jobs. Its containers were stopped without deleting the data volume.
- Read-only Neon inspection showed revision `f31a9d8c0b27` and the existing ingestion/document/page tables. No production migration was run.
- An approved five-record request to current Render queued three records; job `d69f5939754c449dbe8563e31145a619` ended with 3 failures, 0 processed pages. The source returned HTTP 403 after one attempt per record; no source restriction was bypassed.
- The report was regenerated from Neon after that job: 127 documents, 1,230 pages, 2,100,057 text characters, 525,014 estimated tokens, and 28 dead letters.

### Release-branch verification

- On `feat/day-10-queue`, `uv sync --locked`, `uv lock --check`, and `uv run poe lint` passed. With `APP_ENV=ci`, `uv run poe test` passed 127 unit tests and `TEST_DATABASE_URL` pointed at the isolated Docker Postgres, `uv run poe test-integration` passed 16 tests.
- Docker built the API and worker images. A separate local Compose database applied migrations through `c40b3d9a2f11` and seeded 20 local records; the API returned healthy, the worker started, and an unauthenticated ingestion request returned 401.
- The prior isolated kill/recovery drill completed 20 items with 18 done, 2 idempotent skips, and 0 failed; stored documents had unique content hashes. See the detailed job IDs in the final verification entry above.
- Neon was inspected read-only and already contains the Day 10 tables at revision `f31a9d8c0b27`; no production migration was applied.
- The approved Render test job `d69f5939754c449dbe8563e31145a619` recorded three HTTP 403 source failures and no processed pages. The report reflects current Neon totals; the upstream source restriction remains unresolved.

### Neon revision reconciliation

- The first CD attempt for `b28fa98f7f093ab0bd1729748ee609ecbcd5dce5` stopped in Alembic before DDL because the deployed database revision `f31a9d8c0b27` was not present in the checked-in migration graph. Render deployment and smoke testing were skipped.
- Read-only Neon checks confirmed revision `f31a9d8c0b27` and that both `document_chunks` and `document_chunks_local` already exist. The matching additive migration (`a4d73e6192f0` -> `f31a9d8c0b27`) is restored in the migration graph; `alembic upgrade head` should therefore be a no-op on this Neon revision and will not alter existing documents, pages, or embeddings.
- On the main-based candidate, `uv run poe test` passed 140 tests; `uv run poe test-integration` passed 19 tests; lint and the API/worker Docker build passed. The local integration test exposed a timezone boundary in LLM usage rollups; the date window now uses UTC, matching stored timestamps.
- The migration-reconciliation branch has 140 passing unit tests, 19 passing integration tests, and clean lint/format checks. No production migration has been applied by this task.
