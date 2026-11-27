# Ingestion report

This report is generated from the database by `uv run python scripts/ingest_report.py`.

<!-- ingest-report:start -->
| Measure | Value |
|---|---:|
| Documents | 127 |
| Pages | 1,230 |
| Text characters | 2,100,057 |
| Estimated tokens (characters / 4) | 525,014 |
| Recorded extraction tokens | 232,842 |
| Dead-letter items | 28 |
<!-- ingest-report:end -->

## What I learnt

- PostgreSQL stores durable job/item state; Redis carries work notifications.
- The local worker recovered interrupted jobs without duplicating document hashes.
- The Render worker received HTTP 403 from the source; honor that restriction instead of routing around it.
- The corpus is 770 pages and 238,006 estimated tokens below the 2,000-page / 763,020-token capacity estimate.
