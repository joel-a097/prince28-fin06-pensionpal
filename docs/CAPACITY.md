# Corpus capacity estimate

Planning assumptions and measured corpus size are generated from the local provenance manifest.

<!-- generated:start -->
## Measured sample and full-corpus estimate

No successful source downloads are available to calibrate estimates.

Observed files: 0. Observed pages: 0. Planned corpus target: 1,000 pages.

Token count, chunk count, embedding cost, and vector storage are unavailable until a non-empty sample has been collected.

The measured corpus report records blocked sources and their provenance. Rerun the downloader where EPFO robots.txt and source documents are reachable, then regenerate this report.
<!-- generated:end -->

## Planning notes

- **Sample:** the initial source set is listed in `data/sources.csv` and covers EPFO scheme rules, member FAQs, forms, and claim guidance. The current environment could not retrieve EPFO robots.txt, so the sample has no downloaded files yet.
- The initial target is 1,000 pages; this is a planning assumption, not a complete EPFO inventory.
- **Expansion:** add older circulars, the citizen charter, and related member guidance only after checking each host's robots.txt and recording its reuse terms.
- **Text and storage:** the report measures extracted characters, estimates tokens as characters / 4, then estimates 500-token chunks and 1,024-dimensional float32 vector bytes. It excludes text, metadata, indexes, and database overhead.
- **Embedding estimate:** after measuring a sample, estimate at USD 0.20 per million tokens and USD/INR 95 by default. These are configurable planning inputs, not vendor pricing guidance.
- Estimated token count uses extracted characters divided by four. It is not tokenizer output.
- Embedding cost uses a configurable price and USD/INR conversion; it is an estimate, not a quote.
- Vector storage assumes float32 and excludes text, metadata, indexes, and database overhead.
- When the measured sample is empty, token, chunk, cost, and vector estimates are marked unavailable; collect an accessible sample before extrapolating.
