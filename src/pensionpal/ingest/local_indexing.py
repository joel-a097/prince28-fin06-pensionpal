"""Idempotently build and persist chunks for the local embedding model."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pensionpal.config import Settings
from pensionpal.db.models import Document, LocalDocumentChunk, Page
from pensionpal.ingest.chunk import TextChunk, chunk_pages
from pensionpal.llm.local_embeddings import LocalFastEmbedder

logger = logging.getLogger("pensionpal.local_indexing")
LOCAL_INDEX_VERSION = "local-chunk-v1"


class LocalIndexContentChanged(RuntimeError):
    """The source pages changed while local embeddings were generated."""


def _format_embedding_text(title: str, page_no: int, section: str, text: str) -> str:
    return (
        f"title: {title or 'none'}\npage: {page_no}\nsection: {section}\ntext: {text}"
    )


def _fit_embedding_renderer(
    title: str,
    page_no: int,
    headings: list[str],
    *,
    token_count: Callable[[str], int],
    token_limit: int,
) -> Callable[[str], str]:
    render_title = title or "none"
    section = " > ".join(headings) or "none"
    reserve = min(16, token_limit // 4)
    metadata_limit = max(1, token_limit - reserve)

    def render(text: str) -> str:
        return _format_embedding_text(render_title, page_no, section, text)

    while token_count(render("x")) > metadata_limit:
        if render_title != "none" and (
            section == "none" or len(render_title) >= len(section)
        ):
            render_title = render_title[: len(render_title) // 2].strip() or "none"
        elif section != "none":
            section = section[: len(section) // 2].strip() or "none"
        elif render_title != "none":
            render_title = render_title[: len(render_title) // 2].strip() or "none"
        elif token_count("text: x") <= metadata_limit:
            return lambda text: f"text: {text}"
        else:
            return lambda text: text
    return render


def _split_at_boundary(text: str) -> tuple[str, str]:
    midpoint = len(text) // 2
    before = text.rfind(" ", 1, midpoint + 1)
    after = text.find(" ", midpoint)
    if before > 0 and (after < 0 or midpoint - before <= after - midpoint):
        boundary = before
    elif after > 0:
        boundary = after
    else:
        boundary = midpoint
    left, right = text[:boundary].strip(), text[boundary:].strip()
    if not left or not right:
        boundary = midpoint
        left, right = text[:boundary].strip(), text[boundary:].strip()
    return left, right


def _token_limited_texts(
    text: str,
    *,
    render: Callable[[str], str],
    token_count: Callable[[str], int],
    token_limit: int,
) -> list[str]:
    if token_limit < 1:
        raise ValueError("token_limit must be positive")
    pending = [text]
    chunks: list[str] = []
    while pending:
        current = pending.pop()
        if token_count(render(current)) <= token_limit:
            chunks.append(current)
            continue
        if len(current) < 2:
            raise ValueError("A local embedding input cannot fit the token limit")
        left, right = _split_at_boundary(current)
        pending.extend((right, left))
    return chunks


def _prepare_chunks(
    title: str,
    pages: list[Page],
    settings: Settings,
    embedder: LocalFastEmbedder,
) -> tuple[list[TextChunk], list[str], str]:
    base_chunks = chunk_pages(
        pages,
        max_chars=settings.chunk_max_chars,
        overlap_chars=settings.chunk_overlap_chars,
    )
    chunks: list[TextChunk] = []
    embedding_texts: list[str] = []
    for base in base_chunks:
        render = _fit_embedding_renderer(
            title,
            base.page_no,
            base.headings,
            token_count=embedder.token_count,
            token_limit=settings.local_embedding_token_limit,
        )
        texts = _token_limited_texts(
            base.text,
            render=render,
            token_count=embedder.token_count,
            token_limit=settings.local_embedding_token_limit,
        )
        for text in texts:
            identity = "\n".join([str(base.page_no), *base.headings, text]).encode(
                "utf-8"
            )
            chunks.append(
                TextChunk(
                    chunk_index=len(chunks),
                    page_no=base.page_no,
                    text=text,
                    headings=list(base.headings),
                    content_hash=hashlib.sha256(identity).hexdigest(),
                )
            )
            embedding_texts.append(render(text))
    signature = hashlib.sha256(
        "\n".join(
            [
                LOCAL_INDEX_VERSION,
                embedder.model,
                *[
                    hashlib.sha256(text.encode("utf-8")).hexdigest()
                    for text in embedding_texts
                ],
            ]
        ).encode("utf-8")
    ).hexdigest()
    return chunks, embedding_texts, signature


async def index_local_document(
    sessions: async_sessionmaker[AsyncSession],
    embedder: LocalFastEmbedder,
    external_id: str,
    settings: Settings,
) -> tuple[int, bool]:
    """Index locally without reading or changing the existing Gemini chunk table."""
    async with sessions() as session:
        document = await session.scalar(
            select(Document).where(Document.external_id == external_id)
        )
        if document is None:
            raise LookupError(f"document {external_id!r} does not exist")
        title = document.title
        pages = list(
            await session.scalars(
                select(Page)
                .where(Page.document_id == document.id)
                .order_by(Page.page_no)
            )
        )
        existing = list(
            await session.scalars(
                select(LocalDocumentChunk)
                .where(LocalDocumentChunk.document_id == document.id)
                .order_by(LocalDocumentChunk.chunk_index)
            )
        )

    chunks, embedding_texts, signature = await asyncio.to_thread(
        _prepare_chunks, title, pages, settings, embedder
    )
    if not chunks:
        raise ValueError(f"document {external_id!r} has no embeddable text")

    if len(existing) == len(chunks) and all(
        old.chunk_index == chunk.chunk_index
        and old.embedding_model == embedder.model
        and old.content_hash
        == hashlib.sha256(
            embedding_texts[chunk.chunk_index].encode("utf-8")
        ).hexdigest()
        for old, chunk in zip(existing, chunks, strict=True)
    ):
        return len(chunks), False

    old_by_index = {chunk.chunk_index: chunk for chunk in existing}
    vectors: dict[int, list[float]] = {}
    pending: list[int] = []
    for chunk in chunks:
        old = old_by_index.get(chunk.chunk_index)
        content_hash = hashlib.sha256(
            embedding_texts[chunk.chunk_index].encode("utf-8")
        ).hexdigest()
        if (
            old is not None
            and old.content_hash == content_hash
            and old.embedding_model == embedder.model
        ):
            vectors[chunk.chunk_index] = old.embedding
        else:
            pending.append(chunk.chunk_index)

    generated = await embedder.embed_documents(
        [embedding_texts[index] for index in pending]
    )
    vectors.update(zip(pending, generated, strict=True))

    async with sessions() as session:
        current = await session.scalar(
            select(Document).where(Document.external_id == external_id)
        )
        if current is None:
            raise LookupError(f"document {external_id!r} does not exist")
        current_pages = list(
            await session.scalars(
                select(Page)
                .where(Page.document_id == current.id)
                .order_by(Page.page_no)
            )
        )
        _, _, current_signature = await asyncio.to_thread(
            _prepare_chunks, current.title, current_pages, settings, embedder
        )
        if current_signature != signature:
            raise LocalIndexContentChanged(
                f"document {external_id!r} changed during local embedding"
            )

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
        _, _, current_signature = await asyncio.to_thread(
            _prepare_chunks, document.title, current_pages, settings, embedder
        )
        if current_signature != signature:
            raise LocalIndexContentChanged(
                f"document {external_id!r} changed during local embedding"
            )
        await session.execute(
            delete(LocalDocumentChunk).where(
                LocalDocumentChunk.document_id == document.id
            )
        )
        session.add_all(
            [
                LocalDocumentChunk(
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

    logger.info(
        "locally indexed document %s: %s chunk(s), %s new embedding(s)",
        external_id,
        len(chunks),
        len(pending),
    )
    return len(chunks), True


async def index_all_local_documents(
    sessions: async_sessionmaker[AsyncSession],
    embedder: LocalFastEmbedder,
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

    counts = {"indexed": 0, "unchanged": 0, "failed": 0, "chunks": 0}
    for position, external_id in enumerate(external_ids, start=1):
        try:
            chunks, changed = await index_local_document(
                sessions, embedder, external_id, settings
            )
        except Exception:
            counts["failed"] += 1
            logger.exception(
                "local indexing failed for document %s (%s/%s)",
                external_id,
                position,
                len(external_ids),
            )
        else:
            counts["chunks"] += chunks
            counts["indexed" if changed else "unchanged"] += 1
        logger.info(
            "local indexing progress %s/%s: indexed=%s unchanged=%s failed=%s",
            position,
            len(external_ids),
            counts["indexed"],
            counts["unchanged"],
            counts["failed"],
        )
    return counts
