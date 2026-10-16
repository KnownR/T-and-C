"""Citation verification package for grounding legal findings in document clauses."""

from backend.app.verify.normalizer import normalize_text
from backend.app.verify.verifier import (
    VerificationResult,
    VerificationStatus,
    verify_finding,
    verify_findings,
)

__all__ = [
    "normalize_text",
    "VerificationResult",
    "VerificationStatus",
    "verify_finding",
    "verify_findings",
]
