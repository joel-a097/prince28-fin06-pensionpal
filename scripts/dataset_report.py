"""Measure downloaded source files and estimate the future PensionPal corpus."""

from __future__ import annotations

import argparse
import html
import json
import math
import re
from collections import defaultdict
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifest.jsonl"
DATASET = ROOT / "DATASET.md"
CAPACITY = ROOT / "docs" / "CAPACITY.md"
START = "EPF/EPS/EDLI rules, member FAQs, transfer and claim forms, and claim guidance"
FULL = "Add the older EPFO circular archive, citizen charter, and related member guidance; 1,000 pages is an initial planning estimate, not a measured inventory."


def text_from_html(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style)\b.*?>.*?</\1>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def measure(path: Path, content_type: str) -> dict:
    suffix = path.suffix.lower()
    chars = 0
    pages = 0
    low_text = False
    if suffix == ".pdf" or content_type == "application/pdf":
        try:
            reader = PdfReader(path, strict=False)
            pages = len(reader.pages)
            lengths = [
                len((page.extract_text() or "").strip()) for page in reader.pages
            ]
            chars = sum(lengths)
            low_text = (
                pages > 0 and sum(length < 50 for length in lengths) / pages > 0.5
            )
        except Exception:  # noqa: BLE001 - damaged and encrypted PDFs still count as files
            low_text = True
    else:
        try:
            raw = path.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            raw = ""
        text = text_from_html(raw) if suffix in {".html", ".htm"} else raw
        chars = len(text)
        pages = int(bool(text.strip()))
    return {
        "pages": pages,
        "chars": chars,
        "tokens": math.ceil(chars / 4),
        "low_text": low_text,
    }


def read_manifest() -> list[dict]:
    if not MANIFEST.exists():
        return []
    records = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("url"):
            records[row["url"]] = row
    return list(records.values())


def load_files() -> list[dict]:
    measured = []
    for record in read_manifest():
        if record.get("status") != "downloaded" or not record.get("path"):
            continue
        path = ROOT / record["path"]
        if not path.is_file():
            continue
        stats = measure(path, record.get("content_type", ""))
        measured.append(
            record
            | stats
            | {
                "file": path.name,
                "bytes": path.stat().st_size,
                "path": path.relative_to(ROOT).as_posix(),
            }
        )
    return measured


def generated_dataset(rows: list[dict]) -> str:
    total_pages = sum(row["pages"] for row in rows)
    total_bytes = sum(row["bytes"] for row in rows)
    total_tokens = sum(row["tokens"] for row in rows)
    by_source = defaultdict(lambda: {"files": 0, "pages": 0, "bytes": 0})
    for row in rows:
        group = by_source[row.get("source", "unknown")]
        group["files"] += 1
        group["pages"] += row["pages"]
        group["bytes"] += row["bytes"]
    lines = [
        "## Measured corpus",
        "",
        f"Collected files: **{len(rows)}** | pages / text files: **{total_pages}** | disk size: **{total_bytes / 2**20:.2f} MiB** | estimated text: **{total_tokens:,} tokens** (characters / 4).",
        "",
        "### Files and provenance",
        "",
        "| File | Source | Pages | Characters | Est. tokens | Size MiB | Terms recorded | Original URL |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        title = row.get("title") or row["file"]
        licence = row.get("licence", "")
        url = row.get("final_url") or row["url"]
        warning = " (low extractable text; may be scanned)" if row["low_text"] else ""
        lines.append(
            f"| {title}{warning} | {row.get('source', '')} | {row['pages']} | {row['chars']:,} | {row['tokens']:,} | {row['bytes'] / 2**20:.2f} | {licence} | [{url}]({url}) |"
        )
    lines.extend(
        [
            "",
            "### Totals by publisher",
            "",
            "| Source | Files | Pages | Size MiB |",
            "|---|---:|---:|---:|",
        ]
    )
    for source, stats in sorted(by_source.items()):
        lines.append(
            f"| {source} | {stats['files']} | {stats['pages']} | {stats['bytes'] / 2**20:.2f} |"
        )
    lines.extend(["", "### Download status", "", "| Status | Files |", "|---|---:|"])
    statuses = defaultdict(int)
    for row in read_manifest():
        statuses[row.get("status", "unknown")] += 1
    for status, count in sorted(statuses.items()):
        lines.append(f"| {status} | {count} |")
    return "\n".join(lines)


def generated_capacity(
    rows: list[dict],
    *,
    full_pages: int | None,
    full_files: int | None,
    embed_usd: float,
    dims: int,
    chunk_tokens: int,
    usd_inr: float,
) -> str:
    pages = sum(row["pages"] for row in rows)
    files = len(rows)
    tokens = sum(row["tokens"] for row in rows)
    tokens_per_page = tokens / pages if pages else 0
    tokens_per_file = tokens / files if files else 0
    if not pages and full_pages is not None:
        return "\n".join(
            [
                "## Measured sample and full-corpus estimate",
                "",
                "No successful source downloads are available to calibrate estimates.",
                "",
                f"Observed files: {files}. Observed pages: {pages}. Planned corpus target: {full_pages:,} pages.",
                "",
                "Token count, chunk count, embedding cost, and vector storage are unavailable until a non-empty sample has been collected.",
                "",
                "The measured corpus report records blocked sources and their provenance. Rerun the downloader where EPFO robots.txt and source documents are reachable, then regenerate this report.",
            ]
        )
    target_tokens = (
        math.ceil(tokens_per_page * full_pages)
        if full_pages is not None
        else math.ceil(tokens_per_file * (full_files or files))
    )
    chunks = math.ceil(target_tokens / chunk_tokens) if target_tokens else 0
    embed_cost_inr = target_tokens / 1_000_000 * embed_usd * usd_inr
    vector_mib = chunks * dims * 4 / 2**20
    assumption = (
        f"{full_pages:,} pages"
        if full_pages is not None
        else f"{full_files or files:,} files"
    )
    return "\n".join(
        [
            "## Measured sample and full-corpus estimate",
            "",
            "| Measure | Observed sample | Full target estimate |",
            "|---|---:|---:|",
            f"| Files | {files} | {full_files or 'scales by pages'} |",
            f"| Pages / text files | {pages} | {full_pages or 'scales by files'} |",
            f"| Text tokens (characters / 4) | {tokens:,} | {target_tokens:,} |",
            f"| Tokens per page | {tokens_per_page:,.0f} | based on measured sample |",
            f"| Chunks at {chunk_tokens:,} tokens | {math.ceil(tokens / chunk_tokens) if tokens else 0:,} | {chunks:,} |",
            f"| Embedding estimate at ${embed_usd:g}/million tokens | n/a | INR {embed_cost_inr:,.2f} (USD/INR {usd_inr:g}) |",
            f"| Raw float32 vectors at {dims} dimensions | — | {vector_mib:,.2f} MiB |",
            "",
            f"Full target input: **{assumption}**. Token count is an estimate from extracted characters, not tokenizer output. Vector storage excludes database indexes, row metadata, and text chunks.",
            "",
            f"Embedding estimate formula: {target_tokens:,} tokens / 1,000,000 x ${embed_usd:g} x INR {usd_inr:g}/USD. Vector estimate: {chunks:,} chunks x {dims} dimensions x 4 bytes.",
        ]
    )


def replace_generated(path: Path, content: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if "<!-- generated:start -->" not in text:
        raise ValueError(f"{path.relative_to(ROOT)} needs generated:start/end markers")
    before, remainder = text.split("<!-- generated:start -->", 1)
    _, after = remainder.split("<!-- generated:end -->", 1)
    path.write_text(
        before
        + "<!-- generated:start -->\n"
        + content
        + "\n<!-- generated:end -->"
        + after,
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    size = parser.add_mutually_exclusive_group()
    size.add_argument("--full-pages", type=int, default=1000)
    size.add_argument("--full-files", type=int)
    parser.add_argument("--embed-usd", type=float, default=0.20)
    parser.add_argument("--dims", type=int, default=1024)
    parser.add_argument("--chunk-tokens", type=int, default=500)
    parser.add_argument("--usd-inr", type=float, default=95.0)
    args = parser.parse_args()
    if (
        args.dims < 1
        or args.chunk_tokens < 1
        or args.embed_usd < 0
        or args.usd_inr <= 0
    ):
        parser.error("dimensions/chunk size must be positive and prices non-negative")
    rows = load_files()
    replace_generated(DATASET, generated_dataset(rows))
    replace_generated(
        CAPACITY,
        generated_capacity(
            rows,
            full_pages=args.full_pages,
            full_files=args.full_files,
            embed_usd=args.embed_usd,
            dims=args.dims,
            chunk_tokens=args.chunk_tokens,
            usd_inr=args.usd_inr,
        ),
    )
    print(
        f"files={len(rows)} pages={sum(row['pages'] for row in rows)} "
        f"-> wrote DATASET.md and docs/CAPACITY.md"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
