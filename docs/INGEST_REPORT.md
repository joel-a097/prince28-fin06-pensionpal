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
| Dead-letter items | 25 |
<!-- ingest-report:end -->

## What I learnt

- Neon keeps the durable job and item state; Redis carries queue notifications. A local worker can process already-downloaded corpus files when the hosted worker cannot reach the source.
- OCR time varies sharply by PDF size: the 38-page scan took 364 seconds on one local worker, so the worker timeout must exceed that measured case.
- The corpus has 1,188 pages and 510,964 estimated tokens, 812 pages and 252,056 tokens below the 2,000-page and 763,020-token capacity estimate.
