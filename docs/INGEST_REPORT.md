# Ingestion report

This report is generated from the database by `uv run python scripts/ingest_report.py`.

<!-- ingest-report:start -->
| Measure | Value |
|---|---:|
| Documents | 116 |
| Pages | 1,188 |
| Text characters | 2,043,857 |
| Estimated tokens (characters / 4) | 510,964 |
| Recorded extraction tokens | 232,842 |
| Dead-letter items | 18 |
<!-- ingest-report:end -->

## What I learnt

- Add your observation about the work queue.
- Add your observation about retrying interrupted work.
- Compare the measured pages and tokens with `docs/CAPACITY.md`.
