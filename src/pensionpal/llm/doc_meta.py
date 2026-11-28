"""Validated per-document metadata for PensionPal's EPF and pension corpus."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Short = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
Values = Annotated[list[Short], Field(default_factory=list, max_length=8)]
Kind = Literal[
    "guideline",
    "rule",
    "notice",
    "list",
    "report",
    "faq",
    "form",
    "tutorial",
    "reference",
    "other",
]


class DocMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_type: Kind
    number: str | None = Field(default=None, max_length=80)
    date: str | None = Field(default=None, max_length=80)
    topic: Annotated[list[Short], Field(min_length=1, max_length=6)]
    condition: Values
    form: Values
    effective_from: str | None = Field(default=None, max_length=80)

    @field_validator("topic", "condition", "form")
    @classmethod
    def _tidy_values(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(topic.lower() for topic in value))
