# Document-grounded chat

PensionPal chat embeds the user's question, retrieves nearby `document_chunks`
from Postgres using pgvector cosine distance, and sends those passages to the
existing LLM gateway as untrusted evidence. Answers include citation metadata;
the system prompt requires citations and tells the model not to invent facts.

The index uses 768-dimensional Gemini `gemini-embedding-001` vectors. New
documents are indexed after ingestion when `GEMINI_API_KEY` is configured.
Without that key, ingestion still stores the document and pages, but the
document is not available to retrieval until it is indexed.

## Production rollout

The migration is additive: it enables the `vector` extension and creates the
`document_chunks` table and cosine-search index. It does not alter existing
document or page rows.

1. Securely configure `DATABASE_URL` for the migration environment to point to
   Neon. Confirm that the database role can use the `vector` extension.
2. Apply the migration with `uv run poe migrate` before deploying the new API.
3. Configure `GEMINI_API_KEY` in the API and worker environments, then deploy.
4. Backfill existing corpus documents from a trusted environment that can
   connect to Neon: `uv run python scripts/index_documents.py`. Use
   `--limit N` to index a smaller batch first.
5. Verify the API health and ask a document-grounded question through `/v1/chat`.

The backfill is idempotent: unchanged documents reuse existing embeddings.
Keep database URLs and provider keys in private environment configuration;
never commit them or pass them as literal command-line arguments.
