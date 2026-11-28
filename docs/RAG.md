# Document-grounded chat

Chat embeds each question with the local FastEmbed model, retrieves nearby
`document_chunks_local` rows from Postgres using pgvector cosine distance, and
sends those passages to the existing LLM gateway as untrusted evidence. Answers
include citation metadata; the system prompt requires citations and tells the
model not to invent facts. Gemini and Groq remain chat-generation providers;
neither is used for document embeddings in this index.

The local index uses 384-dimensional
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` vectors. FastEmbed
runs it locally and does not require an embedding API key. The existing
768-dimensional Gemini vectors in `document_chunks` are a separate vector
space; they are not changed or queried by the local retriever. The new
`document_chunks_local` table is additive.

## Production rollout

The code deploy requires the additive migration and a full local-model backfill
before switching chat retrieval. Index every corpus document into the local
table, including documents that already have Gemini vectors: vectors from
different models cannot be searched together. The backfill does not modify
`documents`, `pages`, or `document_chunks`.

1. Install locked dependencies with `uv sync --locked`.
2. Ensure the private local `.env` has `DATABASE_URL` pointing to Neon. Do not
   print it or pass it as a command-line argument.
3. Apply the additive migration with `uv run poe migrate`.
4. Run `uv run python scripts/index_documents_local.py`. Use `--limit N` for a
   small initial batch. The script reports progress, continues past
   document-level failures, and exits nonzero if any document failed.
5. Rerun the same command after resolving failures. Completed documents are
   detected by model/content hashes and are skipped; retries do not duplicate
   chunks or re-embed unchanged content.
6. Confirm `document_chunks_local` covers all corpus documents, then deploy the
   API and worker. The Docker image downloads the model during the build so the
   first production request does not need to fetch it.
7. Run the backfill once more after deployment to cover documents ingested
   during the rollout, then test `/v1/chat` with a document-grounded question.

The earlier Gemini backfill script remains available for the legacy index, but
it is not needed for local retrieval. Keep database URLs and provider keys in
private environment configuration; never commit them or pass them as literal
command-line arguments.
