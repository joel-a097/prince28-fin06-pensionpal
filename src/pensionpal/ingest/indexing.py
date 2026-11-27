"""Idempotently build and persist retrieval chunks for a parsed document."""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pensionpal.config import Settings
from pensionpal.db.models import Document, DocumentChunk, Page
from pensionpal.ingest.chunk import TextChunk, chunk_pages
from pensionpal.llm.embeddings import GeminiEmbedder

logger = logging.getLogger("pensionpal.indexing")
INDEX_VERSION = "chunk-v1"


class IndexContentChanged(RuntimeError):
    """The document changed while its embeddings were being generated."""


def _embedding_text(title: str, chunk: TextChunk) -> str:
    section = " > ".join(chunk.headings) or "none"
    return (
        f"title: {title or 'none'}\n"
        f"page: {chunk.page_no}\n"
        f"section: {section}\n"
        f"text: {chunk.text}"
    )


def _prepare_chunks(
    title: str, pages: list[Page], settings: Settings
) -> tuple[list[TextChunk], list[str], str]:
    chunks = chunk_pages(
        pages,
        max_chars=settings.chunk_max_chars,
        overlap_chars=settings.chunk_overlap_chars,
    )
    embedding_texts = [_embedding_text(title, chunk) for chunk in chunks]
    signature = hashlib.sha256(
        "\n".join(
            [
                INDEX_VERSION,
                *[
                    hashlib.sha256(text.encode("utf-8")).hexdigest()
                    for text in embedding_texts
                ],
            ]
        ).encode("utf-8")
    ).hexdigest()
    return chunks, embedding_texts, signature


async def index_document(
    sessions: async_sessionmaker[AsyncSession],
    embedder: GeminiEmbedder,
    external_id: str,
    settings: Settings,
) -> tuple[int, bool]:
    """Index a document; unchanged chunks reuse vectors without another API call."""
    async with sessions() as session:
        document = await session.scalar(
            select(Document).where(Document.external_id == external_id)
        )
        if document is None:
            raise LookupError(f"document {external_id!r} does not exist")
        pages = list(
            await session.scalars(
                select(Page)
                .where(Page.document_id == document.id)
                .order_by(Page.page_no)
            )
        )
        chunks, embedding_texts, signature = _prepare_chunks(
            document.title, pages, settings
        )
        existing = list(
            await session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document.id)
                .order_by(DocumentChunk.chunk_index)
            )
        )
        index_state = (document.metadata_ or {}).get("rag_index", {})
        if (
            index_state.get("version") == INDEX_VERSION
            and index_state.get("model") == embedder.model
            and index_state.get("content_hash") == signature
            and len(existing) == len(chunks)
        ):
            return len(chunks), False

        old_by_index = {chunk.chunk_index: chunk for chunk in existing}
        vectors: dict[int, list[float]] = {}
        pending: list[int] = []
        for chunk in chunks:
            old = old_by_index.get(chunk.chunk_index)
            text_hash = hashlib.sha256(
                embedding_texts[chunk.chunk_index].encode("utf-8")
            ).hexdigest()
            if (
                old is not None
                and old.content_hash == text_hash
                and old.embedding_model == embedder.model
            ):
                vectors[chunk.chunk_index] = old.embedding
            else:
                pending.append(chunk.chunk_index)

    generated = await embedder.embed_documents(
        [embedding_texts[index] for index in pending]
    )
    vectors.update(zip(pending, generated, strict=True))

    async with sessions() as session, session.begin():
        document = await session.scalar(
            select(Document)
            .where(Document.external_id == external_id)
            .with_for_update()
        )
        if document is None:
            raise LookupError(f"document {external_id!r} does not exist")
        current_pages = list(
            await session.scalars(
                select(Page)
                .where(Page.document_id == document.id)
                .order_by(Page.page_no)
            )
        )
        _, _, current_signature = _prepare_chunks(
            document.title, current_pages, settings
        )
        if current_signature != signature:
            raise IndexContentChanged(
                f"document {external_id!r} changed during embedding"
            )
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document.id)
        )
        session.add_all(
            [
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=chunk.chunk_index,
                    page_no=chunk.page_no,
                    text=chunk.text,
                    headings=chunk.headings,
                    content_hash=hashlib.sha256(
                        embedding_texts[chunk.chunk_index].encode("utf-8")
                    ).hexdigest(),
                    embedding_model=embedder.model,
                    embedding=vectors[chunk.chunk_index],
                )
                for chunk in chunks
            ]
        )
        document.metadata_ = {
            **(document.metadata_ or {}),
            "rag_index": {
                "version": INDEX_VERSION,
                "model": embedder.model,
                "content_hash": signature,
                "chunks": len(chunks),
            },
        }
    logger.info(
        "indexed document %s: %s chunk(s), %s new embedding(s)",
        external_id,
        len(chunks),
        len(pending),
    )
    return len(chunks), True


async def index_all_documents(
    sessions: async_sessionmaker[AsyncSession],
    embedder: GeminiEmbedder,
    settings: Settings,
    *,
    limit: int = 0,
) -> dict[str, int]:
    async with sessions() as session:
        statement = (
            select(Document.external_id)
            .where(Document.doc_type == "corpus")
            .order_by(Document.id)
        )
        if limit:
            statement = statement.limit(limit)
        external_ids = list(await session.scalars(statement))

    counts = {"indexed": 0, "unchanged": 0, "chunks": 0}
    for external_id in external_ids:
        chunks, changed = await index_document(
            sessions, embedder, external_id, settings
        )
        counts["chunks"] += chunks
        counts["indexed" if changed else "unchanged"] += 1
    return counts
