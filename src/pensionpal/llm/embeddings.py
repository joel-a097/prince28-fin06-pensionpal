"""Gemini text embeddings for document and query retrieval."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence

import httpx

EMBEDDING_DIMENSIONS = 768
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class EmbeddingError(RuntimeError):
    """Embedding generation failed or returned an invalid response."""


class GeminiEmbedder:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = "gemini-embedding-001",
        batch_size: int = 32,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.api_key = api_key
        self.model = model
        self.batch_size = batch_size
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=10)
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed(texts, "RETRIEVAL_DOCUMENT")

    async def embed_query(self, text: str) -> list[float]:
        embeddings = await self._embed([text], "RETRIEVAL_QUERY")
        return embeddings[0]

    async def _embed(self, texts: Sequence[str], task_type: str) -> list[list[float]]:
        if not self.api_key:
            raise EmbeddingError("GEMINI_API_KEY is required for document retrieval")
        if any(not text.strip() for text in texts):
            raise ValueError("embedding input cannot be empty")

        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            embeddings.extend(await self._embed_batch(batch, task_type))
        return embeddings

    async def _embed_batch(
        self, texts: Sequence[str], task_type: str
    ) -> list[list[float]]:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:batchEmbedContents"
        )
        body = {
            "requests": [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": text}]},
                    "taskType": task_type,
                    "outputDimensionality": EMBEDDING_DIMENSIONS,
                }
                for text in texts
            ]
        }
        for attempt in range(1, 5):
            try:
                response = await self._client.post(
                    url,
                    headers={"x-goog-api-key": self.api_key},
                    json=body,
                )
            except httpx.RequestError as error:
                if attempt == 4:
                    raise EmbeddingError(
                        f"Gemini embedding request failed ({type(error).__name__})"
                    ) from error
                await asyncio.sleep(min(2 ** (attempt - 1), 8))
                continue

            if response.status_code in RETRYABLE_STATUS and attempt < 4:
                await asyncio.sleep(min(2 ** (attempt - 1), 8))
                continue
            if response.is_error:
                detail = response.text[:300].replace("\n", " ")
                raise EmbeddingError(
                    f"Gemini embedding API returned HTTP "
                    f"{response.status_code}: {detail}"
                )
            try:
                vectors = response.json()["embeddings"]
                if len(vectors) != len(texts):
                    raise ValueError("embedding count does not match request count")
                return [self._normalize(item["values"]) for item in vectors]
            except (KeyError, TypeError, ValueError) as error:
                raise EmbeddingError(
                    f"Gemini returned an invalid embedding response: {error}"
                ) from error
        raise EmbeddingError("Gemini embedding retries exhausted")

    @staticmethod
    def _normalize(values: list[float]) -> list[float]:
        if len(values) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"expected {EMBEDDING_DIMENSIONS} dimensions, got {len(values)}"
            )
        vector = [float(value) for value in values]
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("embedding contains a non-finite value")
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            raise ValueError("embedding vector has zero magnitude")
        return [value / norm for value in vector]
