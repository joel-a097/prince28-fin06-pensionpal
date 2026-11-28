"""Vector retrieval of grounded document passages for chat."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pensionpal.db.models import Document, DocumentChunk, LocalDocumentChunk
from pensionpal.llm.embeddings import GeminiEmbedder
from pensionpal.llm.local_embeddings import LocalFastEmbedder


@dataclass(frozen=True)
class Evidence:
    reference: str
    document_id: str
    title: str
    source_url: str | None
    page_no: int
    headings: list[str]
    text: str
    distance: float

    def citation(self) -> dict[str, str | int | list[str] | None]:
        return {
            "reference": self.reference,
            "document_id": self.document_id,
            "title": self.title,
            "source_url": self.source_url,
            "page_no": self.page_no,
            "headings": self.headings,
        }


class DocumentRetriever:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        embedder: GeminiEmbedder,
        *,
        limit: int = 5,
        max_distance: float = 0.65,
    ) -> None:
        self.sessions = sessions
        self.embedder = embedder
        self.limit = limit
        self.max_distance = max_distance

    async def retrieve(self, question: str) -> list[Evidence]:
        query_vector = await self.embedder.embed_query(question)
        distance = DocumentChunk.embedding.cosine_distance(query_vector)
        statement = (
            select(DocumentChunk, Document, distance.label("distance"))
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(distance <= self.max_distance)
            .order_by(distance)
            .limit(self.limit)
        )
        async with self.sessions() as session:
            rows = (await session.execute(statement)).all()
        return [
            Evidence(
                reference=f"D{index}",
                document_id=document.external_id,
                title=document.title,
                source_url=document.source_url,
                page_no=chunk.page_no,
                headings=list(chunk.headings or []),
                text=chunk.text,
                distance=float(distance_value),
            )
            for index, (chunk, document, distance_value) in enumerate(rows, 1)
        ]


class LocalDocumentRetriever:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        embedder: LocalFastEmbedder,
        *,
        limit: int = 5,
        max_distance: float = 0.65,
    ) -> None:
        self.sessions = sessions
        self.embedder = embedder
        self.limit = limit
        self.max_distance = max_distance

    async def retrieve(self, question: str) -> list[Evidence]:
        query_vector = await self.embedder.embed_query(question)
        distance = LocalDocumentChunk.embedding.cosine_distance(query_vector)
        statement = (
            select(LocalDocumentChunk, Document, distance.label("distance"))
            .join(Document, Document.id == LocalDocumentChunk.document_id)
            .where(distance <= self.max_distance)
            .order_by(distance)
            .limit(self.limit)
        )
        async with self.sessions() as session:
            rows = (await session.execute(statement)).all()
        return [
            Evidence(
                reference=f"D{index}",
                document_id=document.external_id,
                title=document.title,
                source_url=document.source_url,
                page_no=chunk.page_no,
                headings=list(chunk.headings or []),
                text=chunk.text,
                distance=float(distance_value),
            )
            for index, (chunk, document, distance_value) in enumerate(rows, 1)
        ]
