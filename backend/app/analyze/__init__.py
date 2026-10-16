"""Analysis package with structured output enforcement for Terms of Service."""

from backend.app.analyze.analyzer import (
    DEFAULT_ANALYSIS_MODEL,
    analyze_document,
    completion_with_backoff,
    is_transient_error,
)
from backend.app.analyze.lens import build_rubric_prompt, load_lens
from backend.app.analyze.prompt import build_analysis_prompt, format_document_for_prompt
from backend.app.analyze.schemas import AnalysisOutput, Finding

__all__ = [
    "DEFAULT_ANALYSIS_MODEL",
    "Finding",
    "AnalysisOutput",
    "load_lens",
    "build_rubric_prompt",
    "build_analysis_prompt",
    "format_document_for_prompt",
    "analyze_document",
    "completion_with_backoff",
    "is_transient_error",
]
