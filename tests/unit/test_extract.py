import json

import pytest
from pydantic import ValidationError

from pensionpal.llm.doc_meta import DocMeta
from pensionpal.llm.extract import explain, extract, parse_json
from pensionpal.llm.gateway import FakeLLM, LLMGateway


def valid_record(**changes):
    record = {
        "doc_kind": "rule",
        "year": 1952,
        "language": "en",
        "summary": "The document explains rules for provident fund membership.",
        "topics": ["EPF", "membership"],
        "schemes": ["EPF Scheme"],
        "forms": [],
        "section_refs": ["Paragraph 1"],
    }
    return {**record, **changes}


def test_doc_meta_is_a_strict_contract():
    assert DocMeta.model_validate(valid_record()).doc_kind == "rule"
    with pytest.raises(ValidationError):
        DocMeta.model_validate(valid_record(extra_field="unexpected"))
    with pytest.raises(ValidationError):
        DocMeta.model_validate(valid_record(doc_kind="made_up"))


def test_parse_json_accepts_fences_but_requires_object():
    assert parse_json('```json\n{"ok": true}\n```') == {"ok": True}
    with pytest.raises(ValueError):
        parse_json("no json here")
    with pytest.raises(ValueError):
        parse_json('["not", "object"]')


def test_extraction_prompt_describes_all_fields():
    from pathlib import Path

    prompt = (Path(__file__).resolve().parents[2] / "prompts/extract_v1.md").read_text(
        encoding="utf-8"
    )
    for name in DocMeta.model_fields:
        assert name in prompt


@pytest.mark.asyncio
async def test_extract_validates_and_returns_record():
    provider = FakeLLM(script=[json.dumps(valid_record())])
    result = await extract(
        LLMGateway([provider]), DocMeta, "prompt", "extract_v1", "title", "text"
    )
    assert result.record is not None and result.attempts == 1


@pytest.mark.asyncio
async def test_extract_retries_rejected_json_with_reason():
    provider = FakeLLM(script=['{"unknown": 1}', json.dumps(valid_record())])
    result = await extract(
        LLMGateway([provider]), DocMeta, "prompt", "extract_v1", "title", "text"
    )
    assert result.record is not None and result.attempts == 2
    assert result.errors and "Extra inputs" in result.errors[0]


@pytest.mark.asyncio
async def test_extract_returns_none_after_attempt_limit():
    provider = FakeLLM(script=["bad", "bad"])
    result = await extract(
        LLMGateway([provider]),
        DocMeta,
        "prompt",
        "extract_v1",
        "title",
        "text",
        max_attempts=2,
    )
    assert result.record is None and result.attempts == 2


def test_reserved_parser_metadata_names_are_defined():
    from pensionpal.llm.extract import RESERVED

    assert "source" in RESERVED and "extract" in RESERVED


def test_validation_errors_are_compact():
    with pytest.raises(ValidationError) as error:
        DocMeta.model_validate({})
    assert explain(error.value)
