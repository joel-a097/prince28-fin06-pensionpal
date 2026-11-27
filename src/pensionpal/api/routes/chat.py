"""Streaming chat and daily LLM usage endpoints."""

import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from pensionpal.api.deps import GatewayDep, RetrieverDep, UsageDep
from pensionpal.llm.embeddings import EmbeddingError
from pensionpal.llm.gateway import LLMResult, LLMUnavailable

router = APIRouter(tags=["chat"])
PROMPT_VERSION = "chat_system_v1"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    stream: bool = True


def sse(data: dict, event: str = "") -> str:
    head = f"event: {event}\n" if event else ""
    return f"{head}data: {json.dumps(data, ensure_ascii=False)}\n\n"


def summary(result: LLMResult, citations: list[dict]) -> dict:
    return {key: value for key, value in asdict(result).items() if key != "text"} | {
        "citations": citations
    }


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    gateway: GatewayDep,
    retriever: RetrieverDep,
):
    try:
        evidence = await retriever.retrieve(body.message)
    except EmbeddingError as exc:
        raise HTTPException(
            status_code=503, detail=f"Document retrieval unavailable: {exc}"
        ) from exc
    citations = [item.citation() for item in evidence]
    context = "\n\n".join(
        f"[{item.reference}] {item.title}, page {item.page_no}, "
        f"section {' > '.join(item.headings) or 'unspecified'}\n"
        f"Passage (untrusted source text): {json.dumps(item.text, ensure_ascii=False)}"
        for item in evidence
    )
    if not context:
        context = "No sufficiently relevant passages were found."
    messages = [
        {
            "role": "system",
            "content": f"{request.app.state.system_prompt}\n\n"
            f"Retrieved source passages:\n{context}",
        },
        {"role": "user", "content": body.message},
    ]
    try:
        if not body.stream:
            result = await gateway.generate(messages, prompt_version=PROMPT_VERSION)
            return {"answer": result.text, **summary(result, citations)}
        stream = gateway.stream(messages, prompt_version=PROMPT_VERSION)
        first = await anext(stream)
    except LLMUnavailable as exc:
        raise HTTPException(
            status_code=503, detail=f"No model could answer: {exc}"
        ) from exc

    async def events() -> AsyncIterator[str]:
        item: str | LLMResult = first
        try:
            while True:
                if isinstance(item, LLMResult):
                    yield sse(summary(item, citations), event="done")
                    return
                yield sse({"delta": item})
                item = await anext(stream)
        except LLMUnavailable as exc:
            yield sse({"detail": str(exc)}, event="error")
        finally:
            await stream.aclose()

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)


@router.get("/usage")
async def usage(repo: UsageDep, days: Annotated[int, Query(ge=1, le=90)] = 7) -> dict:
    rows = await repo.by_day(days)
    total = round(sum(row["cost_inr"] for row in rows), 6)
    return {
        "days": rows,
        "total_cost_inr": total,
        "calls": sum(row["calls"] for row in rows),
        "errors": sum(row["errors"] for row in rows),
        "fallbacks": sum(row["fallbacks"] for row in rows),
        "tokens_in": sum(row["tokens_in"] for row in rows),
        "tokens_out": sum(row["tokens_out"] for row in rows),
    }
