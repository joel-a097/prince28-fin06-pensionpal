import asyncio
import json

import httpx
import pytest

from pensionpal.llm.embeddings import EMBEDDING_DIMENSIONS, GeminiEmbedder


def response_vector():
    return [1.0, *([0.0] * (EMBEDDING_DIMENSIONS - 1))]


@pytest.mark.asyncio
async def test_gemini_embeddings_batch_as_documents_and_queries():
    requests = []

    def respond(request):
        body = json.loads(request.read())
        requests.append((body, request.headers["x-goog-api-key"]))
        count = len(body["requests"])
        return httpx.Response(
            200,
            json={"embeddings": [{"values": response_vector()} for _ in range(count)]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    embedder = GeminiEmbedder("not-a-real-key", batch_size=2, client=client)
    try:
        vectors = await embedder.embed_documents(["first", "second", "third"])
        query = await embedder.embed_query("question")
    finally:
        await embedder.aclose()
        await client.aclose()

    assert len(vectors) == 3
    assert all(len(vector) == EMBEDDING_DIMENSIONS for vector in vectors)
    assert len(requests) == 3
    assert requests[0][1] == "not-a-real-key"
    assert requests[0][0]["requests"][0]["taskType"] == "RETRIEVAL_DOCUMENT"
    assert requests[0][0]["requests"][0]["outputDimensionality"] == 768
    assert requests[2][0]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
    assert query[0] == 1


@pytest.mark.asyncio
async def test_gemini_embedding_retries_transient_status(monkeypatch):
    calls = 0

    def respond(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"embeddings": [{"values": response_vector()}]})

    async def no_wait(_delay):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    embedder = GeminiEmbedder("not-a-real-key", client=client)
    try:
        vector = await embedder.embed_query("question")
    finally:
        await embedder.aclose()
        await client.aclose()

    assert calls == 2
    assert len(vector) == EMBEDDING_DIMENSIONS
