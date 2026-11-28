"""Local multilingual text embeddings backed by FastEmbed and ONNX Runtime."""

from __future__ import annotations

import asyncio
import math
import threading
from collections.abc import Sequence
from pathlib import Path

from fastembed import TextEmbedding

from pensionpal.llm.embeddings import EmbeddingError

LOCAL_EMBEDDING_DIMENSIONS = 384


class LocalFastEmbedder:
    def __init__(
        self,
        *,
        model: str,
        cache_dir: Path,
        threads: int = 2,
    ) -> None:
        if threads < 1:
            raise ValueError("threads must be positive")
        self.model = model
        self.cache_dir = cache_dir
        self.threads = threads
        self._model: TextEmbedding | None = None
        self._model_lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return True

    def _get_model(self) -> TextEmbedding:
        with self._model_lock:
            if self._model is None:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                self._model = TextEmbedding(
                    model_name=self.model,
                    cache_dir=str(self.cache_dir),
                    threads=self.threads,
                )
            return self._model

    def token_count(self, text: str) -> int:
        try:
            return self._get_model().token_count(text)
        except (OSError, RuntimeError, ValueError) as error:
            raise EmbeddingError(
                f"Local tokenizer failed ({type(error).__name__})"
            ) from error

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if any(not text.strip() for text in texts):
            raise ValueError("embedding input cannot be empty")
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_passages, list(texts))

    async def embed_query(self, text: str) -> list[float]:
        if not text.strip():
            raise ValueError("embedding input cannot be empty")
        vectors = await asyncio.to_thread(self._embed_queries, [text])
        return vectors[0]

    def _embed_passages(self, texts: list[str]) -> list[list[float]]:
        try:
            vectors = self._get_model().passage_embed(texts)
            return [self._normalize(vector) for vector in vectors]
        except (OSError, RuntimeError, ValueError) as error:
            raise EmbeddingError(
                f"Local passage embedding failed ({type(error).__name__})"
            ) from error

    def _embed_queries(self, texts: list[str]) -> list[list[float]]:
        try:
            vectors = self._get_model().query_embed(texts)
            return [self._normalize(vector) for vector in vectors]
        except (OSError, RuntimeError, ValueError) as error:
            raise EmbeddingError(
                f"Local query embedding failed ({type(error).__name__})"
            ) from error

    @staticmethod
    def _normalize(values: Sequence[float]) -> list[float]:
        vector = [float(value) for value in values]
        if len(vector) != LOCAL_EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"expected {LOCAL_EMBEDDING_DIMENSIONS} dimensions, got {len(vector)}"
            )
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("embedding contains a non-finite value")
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            raise ValueError("embedding vector has zero magnitude")
        return [value / norm for value in vector]

    async def aclose(self) -> None:
        await asyncio.to_thread(self._release_model)

    def _release_model(self) -> None:
        with self._model_lock:
            self._model = None
