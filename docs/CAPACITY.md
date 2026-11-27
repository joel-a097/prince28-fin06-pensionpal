# Corpus capacity estimate

Planning assumptions and measured corpus size are generated from the local provenance manifest.

<!-- generated:start -->
## Measured sample and full-corpus estimate

| Measure | Observed sample | Full target estimate |
|---|---:|---:|
| Files | 110 | scales by pages |
| Pages / text files | 1099 | 2000 |
| Text tokens (characters / 4) | 419,279 | 763,020 |
| Tokens per page | 382 | based on measured sample |
| Chunks at 500 tokens | 839 | 1,527 |
| Embedding estimate at $0.2/million tokens | n/a | INR 14.50 (USD/INR 95) |
| Raw float32 vectors at 768 dimensions | n/a | 4.47 MiB |

Full target input: **2,000 pages**. Token count is an estimate from extracted characters, not tokenizer output. Vector storage excludes database indexes, row metadata, and text chunks.

Embedding estimate formula: 763,020 tokens / 1,000,000 x $0.2 x INR 95/USD. Vector estimate: 1,527 chunks x 768 dimensions x 4 bytes.
<!-- generated:end -->

## Planning notes

- **Sample:** `data/sources.csv` lists 110 official EPFO sources: the original 10 scheme, FAQ, and guidance documents plus 100 recent circular PDFs from the official circular index. EPFO robots.txt allows crawling; the older Day 06 file paths returned 404 and were replaced.
- The planning target is 2,000 pages, above the measured 1,099-page starter corpus; it is not a complete EPFO inventory.
- The source report counts 1,095 PDF pages and 4 HTML documents. Postgres currently stores 1,027 parsed page rows; 57 downloaded circular PDFs have no extractable text and remain unindexed.
- **Expansion:** the initial 100 circulars are from EPFO's current public index; expand to older circulars and related member guidance after checking each host's robots.txt and recording reuse terms.
- **Text and storage:** the report measures extracted characters, estimates tokens as characters / 4, then estimates 500-token chunks and 768-dimensional float32 vector bytes. It excludes text, metadata, indexes, and database overhead.
- **Embedding estimate:** after measuring a sample, estimate at USD 0.20 per million tokens and USD/INR 95 by default. These are configurable planning inputs, not vendor pricing guidance.
- Estimated token count uses extracted characters divided by four. It is not tokenizer output.
- Embedding cost uses a configurable price and USD/INR conversion; it is an estimate, not a quote.
- Vector storage assumes float32 and excludes text, metadata, indexes, and database overhead.
