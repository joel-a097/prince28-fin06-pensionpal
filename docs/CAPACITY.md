# Corpus capacity estimate

Planning assumptions and measured corpus size are generated from the local provenance manifest.

<!-- generated:start -->
## Measured sample and full-corpus estimate

| Measure | Observed sample | Full target estimate |
|---|---:|---:|
| Files | 10 | scales by pages |
| Pages / text files | 289 | 1000 |
| Text tokens (characters / 4) | 218,950 | 757,613 |
| Tokens per page | 758 | based on measured sample |
| Chunks at 500 tokens | 438 | 1,516 |
| Embedding estimate at $0.2/million tokens | n/a | INR 14.39 (USD/INR 95) |
| Raw float32 vectors at 1024 dimensions | n/a | 5.92 MiB |

Full target input: **1,000 pages**. Token count is an estimate from extracted characters, not tokenizer output. Vector storage excludes database indexes, row metadata, and text chunks.

Embedding estimate formula: 757,613 tokens / 1,000,000 x $0.2 x INR 95/USD. Vector estimate: 1,516 chunks x 1024 dimensions x 4 bytes.
<!-- generated:end -->

## Planning notes

- **Sample:** `data/sources.csv` lists 10 current official EPFO sources (6 PDFs and 4 HTML pages) covering scheme rules, member FAQs, rates, forms, and claim guidance. EPFO robots.txt allows crawling; the older Day 06 file paths returned 404 and were replaced.
- The initial target is 1,000 pages; this is a planning assumption, not a complete EPFO inventory.
- The source report counts 285 PDF pages and 4 HTML documents; Postgres stores 429 pages after splitting the HTML into chunks.
- **Expansion:** add older circulars, the citizen charter, and related member guidance only after checking each host's robots.txt and recording its reuse terms.
- **Text and storage:** the report measures extracted characters, estimates tokens as characters / 4, then estimates 500-token chunks and 1,024-dimensional float32 vector bytes. It excludes text, metadata, indexes, and database overhead.
- **Embedding estimate:** after measuring a sample, estimate at USD 0.20 per million tokens and USD/INR 95 by default. These are configurable planning inputs, not vendor pricing guidance.
- Estimated token count uses extracted characters divided by four. It is not tokenizer output.
- Embedding cost uses a configurable price and USD/INR conversion; it is an estimate, not a quote.
- Vector storage assumes float32 and excludes text, metadata, indexes, and database overhead.
