"""Extract, validate, and persist structured metadata for parsed documents."""

import asyncio
import json
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pensionpal.core.logging_config import request_id_var
from pensionpal.db.models import Document, Page
from pensionpal.llm.gateway import LLMGateway, LLMUnavailable

RESERVED = {"source", "path", "parser", "pages", "tables", "chars", "extract"}
PARSED_DOC_TYPE = "corpus"


def parse_json(reply: str) -> dict:
    start, end = reply.find("{"), reply.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("the reply contains no JSON object")
    value = json.loads(reply[start : end + 1])
    if not isinstance(value, dict):
        raise TypeError("the JSON is not an object")
    return value


def explain(error: Exception) -> str:
    if isinstance(error, ValidationError):
        return "; ".join(
            f"{'.'.join(map(str, issue['loc'])) or 'object'}: {issue['msg']}"
            for issue in error.errors()[:6]
        )
    return str(error)


@dataclass
class Extraction:
    record: BaseModel | None
    attempts: int = 0
    errors: list[str] = field(default_factory=list)
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_inr: float = 0.0


async def extract(
    gateway: LLMGateway,
    schema: type[BaseModel],
    prompt: str,
    version: str,
    title: str,
    text: str,
    *,
    max_attempts: int = 3,
    native_schema: bool = False,
) -> Extraction:
    json_schema = schema.model_json_schema()
    messages = [
        {
            "role": "system",
            "content": f"{prompt}\n\nMatch this JSON schema exactly:\n{json.dumps(json_schema)}",
        },
        {"role": "user", "content": f"Title: {title}\n<document>\n{text}\n</document>"},
    ]
    options: dict = {"temperature": 0}
    if native_schema:
        options["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": json_schema},
        }
    out = Extraction(record=None)
    for attempt in range(1, max_attempts + 1):
        result = await gateway.generate(
            messages, purpose="extract", prompt_version=version, **options
        )
        out.attempts, out.model = attempt, result.model
        out.tokens_in += result.tokens_in
        out.tokens_out += result.tokens_out
        out.cost_inr += result.cost_inr
        try:
            out.record = schema.model_validate(parse_json(result.text))
            return out
        except (ValueError, ValidationError) as error:
            out.errors.append(explain(error))
            messages.extend(
                [
                    {"role": "assistant", "content": result.text},
                    {
                        "role": "user",
                        "content": f"Rejected: {out.errors[-1]}. Return corrected JSON only.",
                    },
                ]
            )
    return out


async def pending(
    session: AsyncSession, version: str, *, limit: int = 0, retry_failed: bool = False
) -> list[Document]:
    extract_meta = Document.metadata_["extract"]
    not_done = extract_meta["prompt"].astext.is_distinct_from(version)
    failed = extract_meta["error"].astext.is_not(None)
    stmt = select(Document).where(Document.doc_type == PARSED_DOC_TYPE)
    stmt = stmt.where(or_(not_done, failed) if retry_failed else not_done).order_by(
        Document.id
    )
    return list(await session.scalars(stmt.limit(limit) if limit else stmt))


async def document_text(
    session: AsyncSession, document: Document, chars: int = 6000
) -> str:
    stmt = (
        select(Page.text)
        .where(Page.document_id == document.id)
        .where(func.trim(Page.text) != "")
        .order_by(Page.page_no)
        .limit(3)
    )
    return "\n\n".join(await session.scalars(stmt))[:chars]


async def save(
    session: AsyncSession, document: Document, result: Extraction, version: str
) -> None:
    note = {"prompt": version, "model": result.model, "attempts": result.attempts}
    fields = {}
    if result.record is None:
        note["error"] = (result.errors[-1] if result.errors else "no valid response")[
            :300
        ]
    else:
        fields = result.record.model_dump(mode="json")
    document.metadata_ = {**document.metadata_, **fields, "extract": note}
    await session.commit()


async def run(
    sessionmaker: async_sessionmaker,
    gateway: LLMGateway,
    schema: type[BaseModel],
    prompt: str,
    version: str,
    *,
    limit: int = 0,
    rpm: float = 12,
    chars: int = 6000,
    retry_failed: bool = False,
    native: bool = False,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    echo: Callable[[str], None] = print,
) -> Counter:
    clash = RESERVED & set(schema.model_fields)
    if clash:
        raise ValueError(f"reserved metadata field names: {sorted(clash)}")
    if rpm <= 0:
        raise ValueError("rpm must be positive")
    counts: Counter = Counter()
    async with sessionmaker() as session:
        todo = await pending(session, version, limit=limit, retry_failed=retry_failed)
        counts["pending"] = len(todo)
        for number, document in enumerate(todo, 1):
            text = await document_text(session, document, chars)
            label = f"{document.external_id}  {document.title[:50]}"
            request_token = request_id_var.set(f"extract-{document.external_id}"[:64])
            try:
                if not text.strip():
                    result = Extraction(
                        record=None, errors=["document has no parsed page text"]
                    )
                else:
                    for retry in range(2):
                        try:
                            result = await extract(
                                gateway,
                                schema,
                                prompt,
                                version,
                                document.title,
                                text,
                                native_schema=native,
                            )
                            break
                        except LLMUnavailable as error:
                            if retry:
                                echo(
                                    f"stopped: no model can answer ({str(error)[:160]})"
                                )
                                counts["stopped"] = 1
                                return counts
                            echo(
                                "no model can answer; waiting 60 seconds before resuming"
                            )
                            await sleep(60)
                await save(session, document, result, version)
            finally:
                request_id_var.reset(request_token)
            counts["tokens_in"] += result.tokens_in
            counts["tokens_out"] += result.tokens_out
            counts["micro_inr"] += round(result.cost_inr * 1_000_000)
            if result.record is None:
                counts["failed"] += 1
                echo(f"FAILED   {label}  {result.errors[-1]}")
            else:
                counts["ok"] += 1
                if result.attempts > 1:
                    counts["repaired"] += 1
                    echo(f"repaired {label} after: {result.errors[0]}")
            if number % 10 == 0:
                echo(f"... {number} of {len(todo)} documents")
            if number < len(todo):
                await sleep(60 / rpm)
    return counts
