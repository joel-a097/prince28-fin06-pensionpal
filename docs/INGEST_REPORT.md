# Ingestion report

This report is generated from the database by `uv run python scripts/ingest_report.py`.

<!-- ingest-report:start -->
| Measure | Value |
|---|---:|
| Documents | 116 |
| Pages | 1,155 |
| Text characters | 1,790,387 |
| Estimated tokens (characters / 4) | 447,596 |
| Recorded extraction tokens | 232,842 |
| Dead-letter items | 21 |
<!-- ingest-report:end -->

## What I learnt

- Add your observation about the work queue.
- Add your observation about retrying interrupted work.
- Compare the measured pages and tokens with `docs/CAPACITY.md`.
