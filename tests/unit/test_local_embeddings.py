import math

import pytest

from pensionpal.llm.embeddings import EmbeddingError
from pensionpal.llm.local_embeddings import (
    LOCAL_EMBEDDING_DIMENSIONS,
    LocalFastEmbedder,
)


class FakeModel:
    def passage_embed(self, texts):
        vector = [3.0, 4.0, *([0.0] * (LOCAL_EMBEDDING_DIMENSIONS - 2))]
        return iter([vector for _ in texts])

    def query_embed(self, texts):
        vector = [3.0, 4.0, *([0.0] * (LOCAL_EMBEDDING_DIMENSIONS - 2))]
        return iter([vector for _ in texts])

    def token_count(self, text):
        return len(text.split())


@pytest.mark.asyncio
async def test_local_embedder_normalizes_passage_and_query_vectors(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "pensionpal.llm.local_embeddings.TextEmbedding",
        lambda **_: FakeModel(),
    )
    embedder = LocalFastEmbedder(model="local-test", cache_dir=tmp_path)

    passage = (await embedder.embed_documents(["passage text"]))[0]
    query = await embedder.embed_query("query text")

    assert len(passage) == len(query) == LOCAL_EMBEDDING_DIMENSIONS
    assert math.sqrt(sum(value * value for value in passage)) == pytest.approx(1.0)
    assert math.sqrt(sum(value * value for value in query)) == pytest.approx(1.0)
    assert embedder.token_count("one two three") == 3


@pytest.mark.asyncio
async def test_local_embedder_rejects_invalid_vector_dimensions(monkeypatch, tmp_path):
    class InvalidModel(FakeModel):
        def passage_embed(self, texts):
            return iter([[1.0, 0.0] for _ in texts])

    monkeypatch.setattr(
        "pensionpal.llm.local_embeddings.TextEmbedding",
        lambda **_: InvalidModel(),
    )
    embedder = LocalFastEmbedder(model="local-test", cache_dir=tmp_path)

    with pytest.raises(EmbeddingError) as error:
        await embedder.embed_documents(["passage text"])
    assert "expected 384 dimensions" in str(error.value.__cause__)
