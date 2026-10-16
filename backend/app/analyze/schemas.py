"""Pydantic schemas for structured legal analysis output."""

from typing import Literal
from pydantic import BaseModel, Field, field_validator

UnfairTosCategory = Literal[
    "arbitration",
    "unilateral_change",
    "content_removal",
    "jurisdiction",
    "choice_of_law",
    "limitation_of_liability",
    "unilateral_termination",
    "contract_by_using",
]

SeverityLevel = Literal["red", "yellow", "info"]


class Finding(BaseModel):
    """Pydantic schema representing a single proposed unfair clause finding.

    Required fields: {category, severity, title, explanation, clause_id, quote}
    """

    category: UnfairTosCategory = Field(
        ...,
        description="The unfair clause category ID from the UNFAIR-ToS rubric.",
    )
    severity: SeverityLevel = Field(
        ...,
        description="Risk severity level: red (critical/unfair), yellow (caution), info (informational).",
    )
    title: str = Field(
        ...,
        min_length=1,
        description="Concise descriptive title of the unfair clause finding.",
    )
    explanation: str = Field(
        ...,
        min_length=1,
        description="Plain-English explanation of why the clause is unfair to the consumer.",
    )
    clause_id: str = Field(
        ...,
        min_length=1,
        description="The exact clause identifier (e.g. C-1, C-4) cited from the document.",
    )
    quote: str = Field(
        ...,
        min_length=1,
        description="Exact verbatim substring quote extracted directly from the cited clause.",
    )

    @field_validator("title", "explanation", "clause_id", "quote")
    @classmethod
    def validate_non_empty_stripped(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field cannot be empty or purely whitespace.")
        return v.strip()


class AnalysisOutput(BaseModel):
    """Container for findings returned by the model or parser."""

    findings: list[Finding] = Field(
        default_factory=list,
        description="List of proposed unfair clause findings identified in the document.",
    )
