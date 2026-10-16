"""Citation verifier engine with 4-stage pipeline: exact -> fuzzy -> re-anchor -> reject."""

import uuid
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from backend.app.analyze.schemas import Finding
from backend.app.db import ClauseRecord, FindingRecord
from backend.app.verify.normalizer import normalize_text

VerificationStatus = Literal["verified", "verified_fuzzy", "reanchored", "rejected"]


class VerificationResult(BaseModel):
    """Result of verifying a single finding's citation against document clauses."""

    status: VerificationStatus
    clause_id: str
    original_clause_id: str
    match_score: Optional[float] = None
    details: str = ""


def verify_finding(
    finding: Union[Finding, FindingRecord, dict[str, Any]],
    clauses_by_id: dict[str, ClauseRecord],
    all_clauses: Optional[list[ClauseRecord]] = None,
) -> VerificationResult:
    """Run the 4-stage verification pipeline on a single finding.

    Pipeline:
    1. Validate inputs: if quote is empty or cited clause_id does not exist in document -> reject (do not crash).
    2. Normalize quote and cited clause text (collapse whitespace, unify quotes/dashes, lowercase).
    3. Stage 1 (exact): If normalized quote is an exact substring of cited clause -> verified (100.0).
    4. Stage 2 (fuzzy): If rapidfuzz partial_ratio >= 90 vs cited clause -> verified_fuzzy (score).
    5. Stage 3 (re-anchor): Search all other clauses in document:
       - Exact substring in another clause -> reanchored (100.0).
       - Fuzzy partial_ratio >= 90 in another clause -> reanchored (best score).
    6. Stage 4 (reject): Else -> rejected.
    """
    if all_clauses is None:
        all_clauses = list(clauses_by_id.values())

    # Extract fields from object or dict
    if isinstance(finding, dict):
        cited_clause_id = finding.get("clause_id", "")
        quote = finding.get("quote", "")
    else:
        cited_clause_id = getattr(finding, "clause_id", "")
        quote = getattr(finding, "quote", "")

    if not quote or not quote.strip():
        return VerificationResult(
            status="rejected",
            clause_id=cited_clause_id,
            original_clause_id=cited_clause_id,
            match_score=0.0,
            details="Rejected: quote is empty or whitespace.",
        )

    # Rule: quote attached to a nonexistent clause_id must reject (not crash)
    if cited_clause_id not in clauses_by_id:
        return VerificationResult(
            status="rejected",
            clause_id=cited_clause_id,
            original_clause_id=cited_clause_id,
            match_score=0.0,
            details=f"Rejected: cited clause '{cited_clause_id}' does not exist in document.",
        )

    cited_clause = clauses_by_id[cited_clause_id]
    norm_quote = normalize_text(quote)
    norm_cited_clause = normalize_text(cited_clause.text)

    # Stage 1: Exact substring in cited clause (normalized)
    if norm_quote in norm_cited_clause:
        return VerificationResult(
            status="verified",
            clause_id=cited_clause_id,
            original_clause_id=cited_clause_id,
            match_score=100.0,
            details="Exact substring match in cited clause (normalized).",
        )

    # Stage 2: Fuzzy match >= 90% against cited clause
    cited_score = fuzz.partial_ratio(norm_quote, norm_cited_clause)
    if cited_score >= 90.0:
        return VerificationResult(
            status="verified_fuzzy",
            clause_id=cited_clause_id,
            original_clause_id=cited_clause_id,
            match_score=round(float(cited_score), 2),
            details=f"Fuzzy match in cited clause with partial_ratio {cited_score:.1f}% >= 90%.",
        )

    # Stage 3: Re-anchor across all other clauses
    # 3a. First check for exact substring in other clauses
    for other in all_clauses:
        if other.id == cited_clause_id:
            continue
        norm_other = normalize_text(other.text)
        if norm_quote in norm_other:
            return VerificationResult(
                status="reanchored",
                clause_id=other.id,
                original_clause_id=cited_clause_id,
                match_score=100.0,
                details=f"Re-anchored from {cited_clause_id} to {other.id} (exact substring match).",
            )

    # 3b. Next check for fuzzy match >= 90% in other clauses (pick highest score)
    best_other: Optional[ClauseRecord] = None
    best_other_score = 0.0
    for other in all_clauses:
        if other.id == cited_clause_id:
            continue
        norm_other = normalize_text(other.text)
        score = fuzz.partial_ratio(norm_quote, norm_other)
        if score > best_other_score:
            best_other_score = score
            best_other = other

    if best_other is not None and best_other_score >= 90.0:
        return VerificationResult(
            status="reanchored",
            clause_id=best_other.id,
            original_clause_id=cited_clause_id,
            match_score=round(float(best_other_score), 2),
            details=f"Re-anchored from {cited_clause_id} to {best_other.id} (fuzzy match {best_other_score:.1f}% >= 90%).",
        )

    # Stage 4: Rejection
    return VerificationResult(
        status="rejected",
        clause_id=cited_clause_id,
        original_clause_id=cited_clause_id,
        match_score=round(float(cited_score), 2),
        details=f"Rejected: quote not grounded in cited clause ({cited_score:.1f}% < 90%) or any other clause.",
    )


def verify_findings(
    findings: list[Union[Finding, FindingRecord]],
    clauses: list[ClauseRecord],
    document_id: str,
    analysis_run_id: Optional[str] = None,
) -> tuple[list[FindingRecord], int, int, float]:
    """Run verification pipeline on a batch of findings.

    Returns:
        tuple of:
        - verified_records: list of FindingRecord items that passed (status != 'rejected')
        - verified_count: count of passed findings
        - rejected_count: count of rejected findings
        - grounding_rate: verified_count / proposed_count (float)
    """
    clauses_by_id = {c.id: c for c in clauses}
    verified_records: list[FindingRecord] = []
    proposed_count = len(findings)
    verified_count = 0
    rejected_count = 0

    for f in findings:
        res = verify_finding(f, clauses_by_id, all_clauses=clauses)

        if res.status == "rejected":
            rejected_count += 1
            # Rejected findings are NEVER stored as findings in SQLite or returned to UI
            continue

        verified_count += 1
        finding_id = getattr(f, "id", None) or f"f_{uuid.uuid4().hex[:12]}"

        record = FindingRecord(
            id=finding_id,
            document_id=document_id,
            analysis_run_id=analysis_run_id,
            category=f.category,
            severity=f.severity,
            title=f.title,
            explanation=f.explanation,
            clause_id=res.clause_id,  # Updated if reanchored
            quote=f.quote,
            verification_status=res.status,
            verification_details=res.details,
            match_score=res.match_score,
        )
        verified_records.append(record)

    grounding_rate = (verified_count / proposed_count) if proposed_count > 0 else 0.0
    grounding_rate = round(grounding_rate, 4)

    return verified_records, verified_count, rejected_count, grounding_rate
