"""Compare both available parsers on the ten largest PDFs/HTML corpus files."""

from __future__ import annotations

import argparse
import html
import re
import time
from html.parser import HTMLParser
from pathlib import Path

from pensionpal.ingest.parse import (
    ParsedDoc,
    ParseError,
    finish,
    parse_file,
    parse_pdf_pypdf,
    split_pages,
)

ROOT = Path(__file__).resolve().parents[1]
NOTES = ROOT / "NOTES.md"
START = "<!-- parser-comparison:start -->"
END = "<!-- parser-comparison:end -->"


class PlainHTML(HTMLParser):
    """Deliberately simple tag stripper used as the HTML baseline."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, _attrs) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        if tag in {"p", "div", "tr", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def parse_html_plain(path: Path) -> ParsedDoc:
    parser = PlainHTML()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    text = html.unescape(re.sub(r"\s+", " ", " ".join(parser.parts))).strip()
    if len(text) < 40:
        raise ParseError("empty", "plain tag stripping found no content")
    return finish("plain-html", "html", path.stem, split_pages(text))


def measure(path: Path, parser_name: str, call) -> dict:
    started = time.perf_counter()
    try:
        doc = call(path)
        text = "\n".join(page.text for page in doc.pages)
        result = {
            "chars": len(text),
            "pages": len(doc.pages),
            "headings": len(re.findall(r"(?m)^#{1,6} ", text)),
            "tables": sum(page.tables for page in doc.pages),
            "error": "",
        }
    except ParseError as exc:
        result = {
            "chars": 0,
            "pages": 0,
            "headings": 0,
            "tables": 0,
            "error": exc.reason,
        }
    result["seconds"] = time.perf_counter() - started
    result["parser"] = parser_name
    return result


def compare(path: Path) -> tuple[dict, dict]:
    if path.suffix.lower() == ".pdf":
        return (
            measure(path, "PyMuPDF", lambda p: parse_file(p, "pymupdf")),
            measure(path, "pypdf", parse_pdf_pypdf),
        )
    return (
        measure(path, "trafilatura", parse_file),
        measure(path, "plain tags", parse_html_plain),
    )


def render(paths: list[Path]) -> str:
    lines = [
        "| File | Type | Parser A (chars/pages/headings/tables/sec) | Parser B (chars/pages/headings/tables/sec) | Verdict |",
        "|---|---|---|---|---|",
    ]
    for path in paths:
        first, second = compare(path)

        def fmt(row: dict) -> str:
            if row["error"]:
                return f"{row['parser']}: {row['error']} ({row['seconds']:.2f}s)"
            return (
                f"{row['parser']}: {row['chars']:,} / {row['pages']} / "
                f"{row['headings']} / {row['tables']} / {row['seconds']:.2f}s"
            )

        lines.append(
            f"| `{path.relative_to(ROOT).as_posix()}` | {path.suffix.lower()} | "
            f"{fmt(first)} | {fmt(second)} | Review text and choose |"
        )
    return "\n".join(lines)


def replace_table(content: str) -> None:
    text = NOTES.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise ValueError("NOTES.md is missing parser comparison markers")
    before, rest = text.split(START, 1)
    _, after = rest.split(END, 1)
    NOTES.write_text(
        before + START + "\n" + content + "\n" + END + after, encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    if args.paths:
        paths = [path.resolve() for path in args.paths]
    else:
        paths = sorted(
            (
                path
                for path in (ROOT / "data" / "raw").rglob("*")
                if path.is_file() and path.suffix.lower() in {".pdf", ".html", ".htm"}
            ),
            key=lambda path: path.stat().st_size,
            reverse=True,
        )[:10]
    if any(ROOT not in path.parents for path in paths):
        parser.error("all comparison files must be inside this repository")
    replace_table(render(paths))
    print(f"compared {len(paths)} files -> table written to NOTES.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
