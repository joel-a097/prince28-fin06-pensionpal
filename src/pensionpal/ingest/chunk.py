"""Split parsed pages into stable, citation-preserving retrieval chunks."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


class PageText(Protocol):
    page_no: int
    text: str
    headings: list[str]


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    page_no: int
    text: str
    headings: list[str]
    content_hash: str


def _windows(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    if max_chars < 1 or overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError(
            "max_chars must be positive and overlap smaller than max_chars"
        )
    text = text.strip()
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + max_chars // 2, end)
            if boundary > start:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(start + 1, end - overlap_chars)
        while start < len(text) and text[start].isspace():
            start += 1
    return chunks


def chunk_pages(
    pages: Iterable[PageText], *, max_chars: int = 2000, overlap_chars: int = 200
) -> list[TextChunk]:
    """Keep chunks within one parsed page so each result has a precise citation."""
    chunks: list[TextChunk] = []
    for page in pages:
        for text in _windows(page.text, max_chars, overlap_chars):
            identity = "\n".join([str(page.page_no), *page.headings, text]).encode(
                "utf-8"
            )
            chunks.append(
                TextChunk(
                    chunk_index=len(chunks),
                    page_no=page.page_no,
                    text=text,
                    headings=list(page.headings),
                    content_hash=hashlib.sha256(identity).hexdigest(),
                )
            )
    return chunks
