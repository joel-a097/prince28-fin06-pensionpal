# Local ingestion to production

Use `scripts/ingest_local.py` when Render cannot fetch a source URL. The script reads the local manifest, asks the production API for records whose SHA-256 is not already stored or queued, downloads and parses those files on this machine, and posts parsed pages over HTTPS. The API writes them through the existing `documents` and `pages` tables. It does not connect to Neon directly and does not use Redis.

## One-time setup

1. Install Python 3.11+ and `uv` if they are not installed.
2. In PowerShell, install `uv` if needed, then the locked project dependencies:

   ```powershell
   if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
       winget install --id=astral-sh.uv -e
   }
   uv sync --locked
   ```

3. If `.env` does not exist, copy the example and set `ADMIN_TOKEN` to the existing production Render token using a local editor. Keep `.env` private; do not paste the token into chat or commit it.

   ```powershell
   if (-not (Test-Path .env)) { Copy-Item .env.example .env }
   notepad .env
   ```

4. Install Tesseract OCR with English language data if scanned PDFs need OCR. Confirm the executable is on `PATH`:

   ```powershell
   tesseract --version
   ```

The local uploader uses the existing `ADMIN_TOKEN` from `.env`. It does not need a Neon `DATABASE_URL`, provider API keys, local Redis, or an API key passed on the command line.

## Run and verify

Set the API URL and queue a small EPFO batch:

```powershell
$env:PENSIONPAL_API_URL = "https://pensionpal.onrender.com"
uv run python scripts/ingest_local.py --source epfo --limit 5
```

The command prints an outcome for each item: inserted, duplicate skipped, or failed. Successful outcomes include a document ID and page count. To verify a document through the production API, paste one printed ID into `$documentId`:

```powershell
$documentId = "PASTE_PRINTED_DOCUMENT_ID"
$document = Invoke-RestMethod -Uri "https://pensionpal.onrender.com/v1/documents/$documentId"
$document | Select-Object title, doc_type, parser, pages, path
```

The production plan excludes hashes already stored in Neon or currently queued/running, so completed files are neither downloaded nor parsed. Failed files remain eligible and can be retried by rerunning the command; uploads are idempotent if the API saved a document but the client lost the response.

The uploader uses the project's polite downloader, including its User-Agent and robots.txt checks. A local HTTP 403 is reported as a failure; the script does not use a proxy or alternate route to bypass source restrictions.

To confirm that a processed document is excluded without processing any other document, use its path from the previous API response or query `/v1/documents/{id}`:

```powershell
$documentId = "PASTE_PRINTED_DOCUMENT_ID"
$document = Invoke-RestMethod -Uri "https://pensionpal.onrender.com/v1/documents/$documentId"
uv run python scripts/ingest_local.py --source epfo --path $document.path --dry-run
```

An empty production plan means its content hash is already stored or queued. A non-empty plan lists eligible paths only; dry-run never downloads, parses, or uploads them. The upload endpoint independently returns `skipped_duplicate` for an already stored path or content hash.
